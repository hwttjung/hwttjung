# External Articles API — v1

기사 및 카테고리를 외부 시스템에서 등록/조회하기 위한 API 명세.

- **Base URL (per site)**: `https://admin.<site-domain>/api/v1/`
  - 예: `https://admin.boomsbeat.com/api/v1/`
- **Protocol**: HTTPS only
- **Content-Type**: `application/json` (썸네일 파일 업로드 시 `multipart/form-data`)

---

## 1. 인증 & 접근 제어

세 층을 모두 통과해야 요청이 처리됩니다.

### 1.1 IP allowlist

각 사이트는 요청 발신 IP를 CIDR 목록으로 허용합니다. 등록되지 않은 IP는 `403 ip_not_allowed`.

**클라이언트가 사전 제공할 정보**: 요청을 보낼 서버의 고정 public IP 목록.

### 1.2 API Key

- 헤더: `X-API-Key: <site-specific-key>`
- 사이트별로 다른 키 발급. 노출 시 즉시 폐기 후 재발급.
- 실패 시 `401 invalid_api_key`.

### 1.3 Rate limit

- 기본: **분당 30 요청 / 사이트 / 키**
- 초과 시 `429 rate_limit_exceeded`
- 필요 시 사이트별 상향 조정 가능 (사전 요청).

---

## 2. Endpoints

### 2.1 `POST /api/v1/articles.php` — 기사 등록

**Request Headers**

| Header | 필수 | 값 |
|---|---|---|
| `X-API-Key` | ✅ | 사이트별 발급 키 |
| `Content-Type` | ✅ | `application/json` 또는 `multipart/form-data` |

**Request Body (JSON)**

```json
{
  "title": "기사 제목",
  "content": "<p>본문 HTML</p>",
  "summary": "짧은 요약 (옵션, 미제공 시 본문 앞 150자 자동 생성)",
  "categories": ["tech", "tech-mobile"],
  "typology": "news",
  "regdate": "2026-08-05T10:30:00+09:00",
  "thumbnail_url": "https://external.example.com/original.jpg"
}
```

**Request Body (multipart/form-data)** — 썸네일 파일 업로드 시

동일 필드에 추가로:

- `thumbnail` — 파일 (jpeg/png/gif/webp, 최대 10MB)

`categories`는 반복 파라미터로 전달: `categories[]=tech&categories[]=tech-mobile`

**필드 상세**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `title` | string | ✅ | 기사 제목 |
| `content` | string (HTML) | ✅ | 본문. `<script>`, `<iframe>`, `on*` 속성은 서버에서 제거됨 |
| `categories` | array of slug string | ✅ | 최소 1개. `GET /api/v1/categories.json`의 `slug`값 |
| `summary` | string | | 요약. 미지정 시 본문 첫 150자 |
| `typology` | string | | 기사 유형 slug (`news`, `slideshow`, `featured`, `sponsored`, `review`, `evergreen`, `affiliate`). 미지정 시 `news` |
| `regdate` | ISO 8601 | | 게시 예정 시각. 미지정 시 서버 현재 시각 |
| `thumbnail_url` | string (URL) | | 썸네일 원본 URL (기록용). 파일 업로드와 별개 |
| `thumbnail` (multipart only) | file | | 대표 이미지 파일 |

**본문 내 인라인 이미지**

- 본문 HTML의 `<img src="https://...">`는 **서버가 저장하지 않고 그대로 유지**됩니다.
- 클라이언트는 이미지가 계속 접근 가능한 URL을 사용해야 합니다.
- 이미지 자체 저장이 필요하면 별도 요청 후 지원 계획.

**Response — 성공 (201 Created)**

```json
{
  "article_id": 12345,
  "image_id": 67890,
  "site": "boomsbeat",
  "status": "draft",
  "url": "/articles/12345/20260805/gisa-jemog.htm",
  "categories": [
    {"id": 2, "slug": "tech"},
    {"id": 15, "slug": "tech-mobile"}
  ]
}
```

- `status`는 항상 `draft`. 편집자가 admin에서 검토 후 publish.

**Response — 에러**

| HTTP | body.error | 설명 |
|---|---|---|
| 400 | `invalid_json` | JSON 파싱 실패 |
| 400 | `title_and_content_required` | 필수 필드 누락 |
| 400 | `categories_required` | `categories`가 비었거나 배열 아님 |
| 400 | `unknown_category` | slug가 존재하지 않거나 숨김 처리됨. body에 `unknown: ["bad-slug"]` 포함 |
| 400 | `unknown_typology` | typology slug 무효 |
| 400 | `unsupported_image_type` | 썸네일 mime 지원 안 됨 (`detected`에 실제 mime) |
| 400 | `thumbnail_too_large` | 10MB 초과 |
| 400 | `invalid_regdate` | ISO 8601 파싱 실패 |
| 401 | `invalid_api_key` | 키 누락/불일치 |
| 403 | `ip_not_allowed` | 허용 IP 아님 |
| 404 | `api_not_enabled_for_site` | 해당 사이트 API 미설정 |
| 405 | `method_not_allowed` | GET 등 비허용 메소드 |
| 415 | `unsupported_content_type` | JSON/multipart 아님 |
| 429 | `rate_limit_exceeded` | 분당 한도 초과 |
| 500 | `db_insert_failed`, `thumbnail_save_failed`, `site_bootstrap_failed` | 서버 문제. 재시도 가능 |

---

### 2.2 `GET /api/v1/categories.json` — 카테고리 목록

**Request Headers**

| Header | 필수 | 값 |
|---|---|---|
| `X-API-Key` | ✅ | 사이트별 발급 키 |

**Response — 성공 (200)**

```json
{
  "site": "boomsbeat",
  "updated_at": "2026-08-05T10:00:00Z",
  "categories": [
    {"id": 1, "slug": "news",        "title": "News",       "parent": null, "order": 1},
    {"id": 2, "slug": "tech",        "title": "Technology", "parent": null, "order": 2},
    {"id": 15,"slug": "tech-mobile", "title": "Mobile",     "parent": 2,    "order": 1}
  ]
}
```

- 숨김 처리된(`ca_hide=1`) 카테고리는 제외
- `parent: null`은 최상위
- `Cache-Control: max-age=3600` (1시간). 클라이언트는 캐시 후 재사용 권장.
- `ETag` 지원. 조건부 GET (`If-None-Match`) 사용 시 변경 없으면 `304 Not Modified`.

**에러 응답**: `401`, `403`, `404`, `429` (Articles API와 동일)

---

## 3. 클라이언트 구현 권장 사항

- **재시도**: `5xx` 및 `429`는 지수 백오프로 재시도 (`Retry-After` 헤더 존중).
- **Idempotency**: 서버는 중복 감지를 하지 않음. 클라이언트는 성공 응답을 받기 전 재시도 시 중복 등록 가능성 인지.
- **카테고리 캐싱**: `categories.json` 시작 시 1회 로드 + ETag 재확인. 매 요청마다 fetch 금지.
- **HTML sanitization**: 서버에서도 제거하지만 클라이언트도 신뢰할 수 있는 원본만 전송.
- **문자 인코딩**: UTF-8.

---

## 4. Curl 예시

```bash
# 카테고리 목록
curl -sSf \
  -H 'X-API-Key: <SITE_KEY>' \
  https://admin.boomsbeat.com/api/v1/categories.json

# 기사 등록 (JSON)
curl -sSf -X POST \
  -H 'X-API-Key: <SITE_KEY>' \
  -H 'Content-Type: application/json' \
  --data '{
    "title": "테스트 기사",
    "content": "<p>본문입니다.</p>",
    "categories": ["tech"],
    "thumbnail_url": "https://cdn.example.com/img/1.jpg"
  }' \
  https://admin.boomsbeat.com/api/v1/articles.php

# 기사 등록 (썸네일 파일 첨부)
curl -sSf -X POST \
  -H 'X-API-Key: <SITE_KEY>' \
  -F 'title=테스트 기사' \
  -F 'content=<p>본문입니다.</p>' \
  -F 'categories[]=tech' \
  -F 'categories[]=tech-mobile' \
  -F 'thumbnail=@/path/to/image.jpg' \
  https://admin.boomsbeat.com/api/v1/articles.php
```

---

## 5. 온보딩 절차

외부 팀이 시작하기 위해 필요한 것:

1. 대상 사이트 확정 (예: boomsbeat)
2. 요청 발신 IP 알림 → allowlist 등록
3. API Key 발급 (secure channel로 전달)
4. `categories.json`으로 카테고리 slug 확인 후 매핑
5. Staging(있다면) 먼저 테스트 → 프로덕션

---

**버전**: v1
**최종 업데이트**: 2026-08-05
