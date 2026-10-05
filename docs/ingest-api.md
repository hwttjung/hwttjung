# Article Ingest API

HTTP API for filing articles into our CMS from an external system.

Articles arrive **queued**, not live. An editor reviews each one in the CMS and
publishes it. Nothing you POST appears on the public site by itself.

---

## 1. Base URL

One host per site. The host decides which site the article lands in — there is
no `site` parameter, so you cannot post to the wrong site by mistake.

| Site | Base URL |
|---|---|
| Jobs & Hire | `https://api.jobsnhire.com` |
| Food World News | `https://api.foodworldnews.com` |
| Parent Herald | `https://api.parentherald.com` |
| Books & Review | `https://api.booksnreview.com` |
| Franchise Herald | `https://api.franchiseherald.com` |
| Mobile & Apps | `https://api.mobilenapps.com` |

Any other host returns `404`.

## 2. Authentication

HTTP Basic on every request, over HTTPS. The same credential works on all five
hosts. It is supplied separately — never commit it to your repository.

```
Authorization: Basic base64(user:password)
```

Missing or wrong credentials return `401`.

---

## 3. Look up ids first

Reporter, category and source ids are **per site** — id `5` on Books & Review is
not id `5` on Parent Herald. Fetch them once per site and cache them; they
change rarely. Ids are never created for you, so an id we do not recognise is
rejected rather than silently guessed.

```
GET /ingest/reporters
GET /ingest/categories
GET /ingest/sources
```

```bash
curl -u "$USER:$PASS" https://api.booksnreview.com/ingest/categories
```

```json
{
  "categories": [
    { "id": "5",  "name": "Books",             "parent_id": "0", "ancestry": "-5-"    },
    { "id": "11", "name": "Biography / Memoir", "parent_id": "2", "ancestry": "-2-11-" }
  ]
}
```

`parent_id` is `0` for a top-level category. `reporters` and `sources` return
`{"reporters":[{"id","name"}]}` and `{"sources":[{"id","name"}]}`.

---

## 4. Create an article

```
POST /ingest/article
Content-Type: application/json
```

### Fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `headline` | string | **yes** | max 255 chars |
| `body` | string | **yes** | HTML, max 400,000 bytes. See *Body HTML* below |
| `reporter_id` | int | **yes** | from `GET /ingest/reporters` |
| `category_id` | int | **yes** | from `GET /ingest/categories` |
| `source_id` | int | no | from `GET /ingest/sources` |
| `classification` | string | no | `news` (default), `evergreen`, `affiliate`, `sponsored` |
| `summary` | string | no | max 500 chars. Defaults to the first 300 chars of the body text |
| `short_headline` | string | no | defaults to `headline` |
| `social_headline` | string | no | defaults to `headline` |
| `keywords` | string or array | no | `"a,b"` or `["a","b"]`, max 500 chars |
| `written_time` | string | no | any format `strtotime()` accepts. Defaults to now |
| `source_url` | string | no | link back to the original, max 500 chars |
| `external_id` | string | no | **strongly recommended** — see *Retrying safely* |
| `images` | array | no | see *Images* |

### Example

```bash
curl -u "$USER:$PASS" \
     -H "Content-Type: application/json" \
     -X POST https://api.booksnreview.com/ingest/article \
     -d '{
  "headline": "Five debut novels worth your weekend",
  "summary": "A short standfirst that appears in listings.",
  "body": "<p>First paragraph.</p><p>Second <strong>paragraph</strong>.</p>",
  "classification": "news",
  "reporter_id": 48,
  "category_id": 5,
  "source_id": 1,
  "keywords": "books,fiction,debut",
  "external_id": "cms-2026-08-05-00412",
  "source_url": "https://example.com/original-article",
  "images": [
    {
      "url": "https://example.com/cover.jpg",
      "name": "Cover of the book",
      "caption": "The debut novel, out this week.",
      "credit": "Example Publishing"
    }
  ]
}'
```

### Response — `201 Created`

```json
{
  "a_id": 60031,
  "status": "queued",
  "images_attached": 1,
  "images_failed": 0,
  "cms_url": "https://cms.booksnreview.com/adm/article/edit?a_id=60031",
  "note": ""
}
```

Store `a_id` — it is the CMS article id. `cms_url` opens it in the editor.

---

## 5. Images

Send public image URLs; we download and store them ourselves. The first image
becomes the lead image, and each one is also placed into the article body.

**An article cannot be published without at least one image.** If you send none,
the article is still created, and `note` says an editor has to add one. Sending a
usable image is the difference between an article an editor can publish in one
click and one they have to go find a picture for.

Rules:

- `http` or `https` only, on port 80 or 443
- the host must resolve to a public address — private, loopback and
  link-local addresses are rejected
- max 10 images per article
- the URL must be fetchable **without** authentication, cookies or a special
  `User-Agent`. Some hosts (Wikimedia, for one) reject default agents — if we
  cannot fetch it, that image is skipped

A rejected URL fails the whole request with `400`. A URL that passes validation
but cannot be downloaded is skipped, and counted in `images_failed`; the article
is still created.

`name`, `caption` and `credit` are optional per image.

---

## 6. Body HTML

Send clean article HTML. We keep this tag set:

```
p br h2 h3 h4 strong b em i u ul ol li a blockquote
figure figcaption img iframe table thead tbody tr th td
```

Everything else is removed. `<script>`, `<style>` and `<noscript>` are removed
along with their contents. Event-handler attributes (`onclick=`, `onmouseover=`,
…) and `javascript:` / `data:` URLs are stripped — a normal `href="https://…"`
is kept.

Do not send full-page HTML (`<html>`, `<head>`, navigation, ads). Send the
article body only.

---

## 7. Retrying safely

Set `external_id` to your own stable id for the article. If you POST the same
`external_id` twice we do not create a duplicate — you get `409` with the `a_id`
of the article we already have:

```json
{
  "error": "external_id already ingested",
  "a_id": 60031,
  "cms_url": "https://cms.booksnreview.com/adm/article/edit?a_id=60031"
}
```

Treat that `409` as success on a retry.

Without an `external_id` there is still a fallback guard: an identical headline
posted within 3 minutes is rejected with `409`. It is a safety net, not a
substitute — use `external_id`.

`external_id` is scoped per site, so the same id may be posted to each of the
five sites.

---

## 8. Responses

| Code | Meaning |
|---|---|
| `201` | Created. Body contains `a_id` |
| `400` | Bad request — missing/invalid field, unknown id, rejected image URL. `error` says which |
| `401` | Missing or wrong credentials |
| `404` | Wrong host, or the endpoint is not enabled for this site |
| `409` | Duplicate — see *Retrying safely* |
| `503` | Endpoint is not configured on this host. Contact us |

Errors are JSON: `{"error": "reporter_id 999999 does not exist on this site - see GET /ingest/reporters"}`

Always check the status code. A `201` means stored, not published.

---

## 9. What happens next

1. You POST → article is created with status **queued**
2. It appears in the CMS under **Queued**
3. An editor reviews, adjusts and publishes it
4. Only then is it on the public site

There is no API call to publish, and no API call to update or delete an article
after it is created. Corrections go through the editor. If you need to withdraw
something you have already sent, tell the editorial contact for that site — do
not re-POST with a changed `external_id`, that just creates a second copy.

---

## 10. Practical notes

- Rate: no hard limit, but keep it to a few requests per second. Image
  downloads make a request take a few seconds.
- `written_time` sets the article's byline date. Leave it out for "now".
- Empty `body` or `headline` is a `400` — send real content, not placeholders.
- Test with one article per site before running a batch, and check the
  `cms_url` in a browser.


<?php
// Ingest API config - api.\<domain>/ingest (brg\api\controllers\Ingest).
//
// BASIC is the HTTP Basic credential the external system sends, as
// "user:password". One credential is shared by every pleroma site that has the
// /ingest stub in its api docroot; drop a copy of this file into
// sites/\<domain>/all/application/config/ to give one site its own.
//
// To move the value out of the repo later, replace the literal with a read of
// a mounted file the way elastic.php does - the controller only reads
// $this->config['BASIC'] and does not care where it came from:
//   'BASIC' => (static function(){ $p='/etc/secrets/api_ingest';
//               if(is_readable($p)){ $v=trim(@file_get_contents($p)); if($v!=='') return $v; }
//               return $_ENV['API_INGEST_BASIC'] ?? ''; })(),
$config =
 [
  'BASIC' => 'ingest:924486070132097c5c90ffb7720000b1e3b08fa01fe2d73b',
 ];
?>