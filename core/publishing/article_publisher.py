import os
import json
import time
import urllib.request
import urllib.parse
import urllib.error
import ssl
import requests
import random

# 6개 Ingest API 매체별 고정 필터링 기자명
FIXED_REPORTERS = {
    "jobsnhire": ["Ed Stoddard", "John O'Donnell"],
    "franchiseherald": ["Cindy Wallace", "Adelyn Torralba"],
    "booksnreview": ["Keifer Jones", "Ana Albiad"],
    "mobilenapps": ["Charleston Lim", "Jose Enrico"],
    "parentherald": ["Will Veale", "Belle Smith"],
    "foodworldnews": ["Allison Walker", "Lauren DeThomasis"]
}

# 도메인별 오타/불일치 카테고리 슬러그 자동 번역 사전
CATEGORY_TRANSLATION_MAP = {
    "youthhealthmag": {
        "teenhealth": "teenHeath"
    }
}

class ArticlePublisher:
    def __init__(self, categories_cache_path="data/categories_cache.json"):
        self.categories_cache = self._load_categories_cache(categories_cache_path)
        
    def _load_categories_cache(self, path):
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"sites": {}}

    def get_categories_for_site(self, domain_key):
        return self.categories_cache.get("sites", {}).get(domain_key, [])

    def _download_image(self, url, site_domain=None):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ua = "GlobalNewsDeskBot/1.0 (contact@stocktradingbot.com; Mozilla/5.0)"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua})
            with urllib.request.urlopen(req, context=ctx, timeout=15) as res:
                data = res.read()
                
            # [이중 방어 가드레일] 950KB 초과 시 위키미디어 썸네일 다운스케일 재시도 (413 차단 방지)
            if len(data) > 950 * 1024 and "wikimedia.org" in url:
                from common.logger_setup import get_domain_logger
                logger = get_domain_logger(site_domain)
                logger.warning(
                    f"[{site_domain}] 다운로드된 이미지 크기({len(data)} bytes)가 950KB를 초과하여 1024px로 다운스케일 재시도합니다: {url}"
                )
                import re
                downscaled_url = re.sub(r'/\d+px-', '/1024px-', url)
                if downscaled_url != url:
                    try:
                        req_down = urllib.request.Request(downscaled_url, headers={"User-Agent": ua})
                        with urllib.request.urlopen(req_down, context=ctx, timeout=15) as res_down:
                            down_data = res_down.read()
                            if len(down_data) < len(data):
                                logger.info(f"[{site_domain}] 1024px 다운스케일 성공: {len(down_data)} bytes")
                                return down_data
                    except Exception as de:
                        logger.warning(f"[{site_domain}] 1024px 다운스케일 실패({de}), 기존 데이터 유지")
                        
            return data
        except Exception as e:
            from common.logger_setup import get_domain_logger
            logger = get_domain_logger(site_domain)
            logger.warning(f"Failed to download image from {url}: {e}")
            return None

    def _clean_text(self, text):
        if not text:
            return ""
        # Replace normal single quote with smart single quote to prevent backslash escapes on PHP backend
        return text.replace("'", "’")

    def _encode_multipart_formdata(self, fields, files):
        boundary = f"----WebKitFormBoundary{int(time.time()):x}"
        body = bytearray()
        
        # 1. Add general form fields
        for key, value in fields.items():
            if isinstance(value, list):
                for item in value:
                    body.extend(f"--{boundary}\r\n".encode("utf-8"))
                    body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
                    body.extend(f"{item}\r\n".encode("utf-8"))
            else:
                body.extend(f"--{boundary}\r\n".encode("utf-8"))
                body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
                body.extend(f"{value}\r\n".encode("utf-8"))
                
        # 2. Add file fields
        for key, file_info in files.items():
            filename, file_data, content_type = file_info
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'.encode("utf-8"))
            body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
            body.extend(file_data)
            body.extend(b"\r\n")
            
        # 3. Final boundary
        body.extend(f"--{boundary}--\r\n".encode("utf-8"))
        
        content_type = f"multipart/form-data; boundary={boundary}"
        return bytes(body), content_type

    def _is_stop_publishing_active(self):
        stop_publishing = os.environ.get("STOP_PUBLISHING", "False").strip().lower() in ("true", "1", "yes")
        status_file = "config/status.json"
        if os.path.exists(status_file):
            try:
                with open(status_file, "r", encoding="utf-8") as sf:
                    status_data = json.load(sf)
                    if status_data.get("STOP_PUBLISHING") is True:
                        stop_publishing = True
            except Exception:
                pass
        return stop_publishing

    def publish(self, site_config, article_data, img_data):
        domain_key = site_config.get("domain_key", "unknown")
        
        # [최후 방어선 Kill Switch] STOP_PUBLISHING 상태 시 CMS 송출 원천 차단
        if self._is_stop_publishing_active():
            from common.logger_setup import get_domain_logger
            logger = get_domain_logger(domain_key)
            logger.warning(f"[{domain_key}] [Stop Publishing Kill Switch] Blocked publication to CMS. STOP_PUBLISHING is active.")
            return None, "Blocked: STOP_PUBLISHING is active"

        import hashlib
        import time
        art_id = article_data.get("article_id", "")
        art_hash = article_data.get("article_hash", "")
        idempotency_key = hashlib.sha256(f"{domain_key}#{art_id}#{art_hash}".encode('utf-8')).hexdigest()

        # 1. API Endpoint and URL check
        base_url = site_config["url"]
        if not base_url.endswith("/"):
            base_url += "/"
        target_url = f"{base_url}articles.php"
        
        # 2. Extract image URL and credit
        img_url = img_data.get("url") if img_data else None
        img_credit = img_data.get("credit", "") if img_data else ""
        
        # 3. Try to download the representative image file
        img_bytes = self._download_image(img_url, domain_key) if img_url else None
        
        # 3-1. Resolve category_id from cache
        category_id = None
        selected_cat = article_data["selected_category"]
        translation = CATEGORY_TRANSLATION_MAP.get(domain_key, {})
        if selected_cat.lower() in translation:
            selected_cat = translation[selected_cat.lower()]
            
        try:
            import json
            cache_file = "data/categories_cache.json"
            if os.path.exists(cache_file):
                with open(cache_file, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
                site_cats = cache_data.get("sites", {}).get(domain_key, [])
                for cat in site_cats:
                    if cat.get("slug") == selected_cat:
                        category_id = int(cat["id"])
                        break
        except Exception as e:
            from common.logger_setup import get_domain_logger
            logger = get_domain_logger(domain_key)
            logger.warning(f"[{domain_key}] Failed to resolve category_id from cache: {e}")

        clean_title = self._clean_text(article_data["title"])
        formatted_caption = f"({img_credit})" if img_credit else ""

        # 4. Prepare fields and files for multipart/form-data with clean text (quotes fix)
        fields = {
            "title": clean_title,
            "content": self._clean_text(article_data["content"]),
            "summary": self._clean_text(article_data.get("summary", "")),
            "categories[]": [selected_cat], # match repetitive param categories[]
            "thumbnail_url": img_url,
            "seo_tags": self._clean_text(article_data.get("seo_tags", "")),
            "idempotency_key": idempotency_key,
            # [이미지 메타데이터 명시 매핑 - 제목: 기사제목, 내용: ({credit}), 출처: credit]
            "im_title": clean_title,
            "image_title": clean_title,
            "thumbnail_title": clean_title,
            "im_content": formatted_caption,
            "image_caption": formatted_caption,
            "thumbnail_caption": formatted_caption,
            "caption": formatted_caption,
            "im_credit": img_credit,
            "image_credit": img_credit,
            "thumbnail_credit": img_credit,
            "credit": img_credit
        }
        if category_id is not None:
            fields["category_id"] = category_id
        
        from common.logger_setup import get_domain_logger
        logger = get_domain_logger(domain_key)
        
        files = {}
        if img_bytes:
            content_type = "image/jpeg"
            ext = ".jpg"
            if img_url:
                if ".png" in img_url.lower():
                    content_type = "image/png"
                    ext = ".png"
                elif ".gif" in img_url.lower():
                    content_type = "image/gif"
                    ext = ".gif"
                elif ".webp" in img_url.lower():
                    content_type = "image/webp"
                    ext = ".webp"
                
            import re
            safe_title = re.sub(r'[^a-zA-Z0-9가-힣]', '_', article_data.get("title", "thumbnail"))[:50].strip('_')
            if not safe_title:
                safe_title = "thumbnail"
            files["thumbnail"] = (f"{safe_title}{ext}", img_bytes, content_type)
            logger.info(f"[Upload 준비] Image downloaded successfully ({len(img_bytes)} bytes) as {content_type}.")
        else:
            logger.warning("[Warning] No thumbnail file to upload. Sending without image file.")

        # 5. Encode payload
        body_bytes, content_type_header = self._encode_multipart_formdata(fields, files)
        
        headers = {
            "Content-Type": content_type_header,
            "X-API-Key": site_config["api_key"],
            "X-Idempotency-Key": idempotency_key
        }
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        # 6. HTTP Request with Max 3 Retries (5xx and timeout only)
        max_retries = 3
        last_error = None
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Publishing article (attempt {attempt + 1}/{max_retries}) via multipart/form-data to 어드민 [{domain_key}]...")
                req = urllib.request.Request(
                    target_url, 
                    data=body_bytes, 
                    headers=headers,
                    method="POST"
                )
                with urllib.request.urlopen(req, context=ctx, timeout=20) as response:
                    body = response.read().decode("utf-8")
                    res_data = json.loads(body)
                    return res_data, None
            except urllib.error.HTTPError as e:
                status_code = e.code
                if status_code >= 500:
                    last_error = f"HTTP {status_code} ({e.reason})"
                    time.sleep(1)
                    continue
                else:
                    try:
                        error_body = e.read().decode('utf-8')
                        error_json = json.loads(error_body)
                        error_msg = error_json.get("error", "unknown_api_error")
                    except:
                        error_msg = e.reason
                    return None, f"HTTP {status_code} ({error_msg})"
            except Exception as e:
                last_error = str(e)
                time.sleep(1)
                continue
                
        return None, f"Failed after {max_retries} retries. Last error: {last_error}"

    def _fetch_ingest_ids(self, base_url, headers, selected_category_slug, domain_key):
        from common.logger_setup import get_domain_logger
        logger = get_domain_logger(domain_key)
        reporter_id = None
        try:
            res = requests.get(f"{base_url}/ingest/reporters", headers=headers, verify=False, timeout=10)
            if res.status_code == 200:
                data = res.json()
                reporters = data.get("reporters", [])
                
                # 도메인에 매핑된 고정 기자 리스트 확보 (대소문자 제거 정규화 대조)
                allowed_names = FIXED_REPORTERS.get(domain_key, [])
                allowed_names_lower = [name.strip().lower() for name in allowed_names]
                
                matched_reporter_ids = []
                for rep in reporters:
                    rep_name = rep.get("name", "").strip().lower()
                    if rep_name in allowed_names_lower:
                        matched_reporter_ids.append(int(rep["id"]))
                        
                if matched_reporter_ids:
                    reporter_id = random.choice(matched_reporter_ids)
                else:
                    # API 수량/목록 누락 대비 고정 fallback ID 채택
                    FALLBACK_REPORTER_IDS = {
                        "jobsnhire": 12,
                        "franchiseherald": 13,
                        "mobilenapps": 15,
                        "parentherald": 16,
                        "booksnreview": 14,
                        "foodworldnews": random.choice([100575, 100578])
                    }
                    fallback_id = FALLBACK_REPORTER_IDS.get(domain_key)
                    if fallback_id:
                        reporter_id = fallback_id
                        logger.info(f"[{domain_key}] [Author Lookup Failed] API missed target authors. Switched to fallback reporter ID: {reporter_id}")
                    else:
                        logger.warning(f"[{domain_key}] [Author Lookup Failed] No matching reporter and no fallback ID. Setting reporter_id to None.")
                        reporter_id = None
        except Exception as e:
            logger.warning(f"[{domain_key}] Failed to fetch ingest reporters: {e}")
            reporter_id = None
            
        if not reporter_id:
            reporter_id = None

        category_id = None
        try:
            res = requests.get(f"{base_url}/ingest/categories", headers=headers, verify=False, timeout=10)
            if res.status_code == 200:
                data = res.json()
                categories = data.get("categories", [])
                
                # 번역 보정 맵 적용
                selected_slug = selected_category_slug
                translation = CATEGORY_TRANSLATION_MAP.get(domain_key, {})
                if selected_slug.lower() in translation:
                    selected_slug = translation[selected_slug.lower()]
                
                local_categories = self.get_categories_for_site(domain_key)
                target_name = None
                for c in local_categories:
                    if c.get("slug") == selected_slug:
                        target_name = c.get("name")
                        break
                
                if not target_name:
                    target_name = selected_slug.replace("-", " ")
                
                norm_target = target_name.lower().replace(" ", "").replace("&", "")
                
                for cat in categories:
                    norm_cat_name = cat["name"].lower().replace(" ", "").replace("&", "")
                    if norm_target == norm_cat_name:
                        category_id = int(cat["id"])
                        break
                        
                if not category_id:
                    for cat in categories:
                        norm_cat_slug = cat["name"].lower().replace(" ", "-").replace("/", "-")
                        if selected_slug.lower() == norm_cat_slug:
                            category_id = int(cat["id"])
                            break
                            
                if not category_id:
                    for cat in categories:
                        if norm_target in cat["name"].lower():
                            category_id = int(cat["id"])
                            break
                            
                if not category_id and categories:
                    category_id = int(categories[0]["id"])
        except Exception as e:
            from common.logger_setup import get_domain_logger
            logger = get_domain_logger(domain_key)
            logger.warning(f"[{domain_key}] Failed to fetch ingest categories: {e}")
            
        if not category_id:
            category_id = 1

        source_id = None
        try:
            res = requests.get(f"{base_url}/ingest/sources", headers=headers, verify=False, timeout=10)
            if res.status_code == 200:
                data = res.json()
                sources = data.get("sources", [])
                if sources:
                    site_names = {
                        "jobsnhire": "jobs & hire",
                        "foodworldnews": "food world news",
                        "parentherald": "parent herald",
                        "booksnreview": "books & review",
                        "franchiseherald": "franchise herald",
                        "mobilenapps": "mobile & apps"
                    }
                    expected_name = site_names.get(domain_key, "").lower()
                    
                    for src in sources:
                        if src.get("name", "").strip().lower() == expected_name:
                            source_id = int(src["id"])
                            break
                            
                    if not source_id:
                        source_id = int(sources[0]["id"])
        except Exception as e:
            pass

        return reporter_id, category_id, source_id

    def publish_to_ingest_api(self, domain_key, article_data, img_data, rss_link=None):
        # [최후 방어선 Kill Switch] STOP_PUBLISHING 상태 시 Ingest API 송출 원천 차단
        if self._is_stop_publishing_active():
            from common.logger_setup import get_domain_logger
            logger = get_domain_logger(domain_key)
            logger.warning(f"[{domain_key}] [Stop Publishing Kill Switch] Blocked publication to Ingest API. STOP_PUBLISHING is active.")
            return None, "Blocked: STOP_PUBLISHING is active"

        import hashlib
        import time
        art_id = article_data.get("article_id", "")
        art_hash = article_data.get("article_hash", "")
        idempotency_key = hashlib.sha256(f"{domain_key}#{art_id}#{art_hash}".encode('utf-8')).hexdigest()

        base_url = INGEST_API_HOSTS.get(domain_key)
        if not base_url:
            return None, f"Unsupported Ingest API domain: {domain_key}"
            
        import base64
        basic_auth_val = os.environ.get("API_INGEST_BASIC", "ingest:924486070132097c5c90ffb7720000b1e3b08fa01fe2d73b")
        encoded_auth = base64.b64encode(basic_auth_val.encode('utf-8')).decode('utf-8')
        headers = {
            "Authorization": f"Basic {encoded_auth}",
            "Content-Type": "application/json",
            "User-Agent": "AI-Article-Publisher/1.0",
            "X-Idempotency-Key": idempotency_key
        }
        
        # 1. Fetch IDs
        reporter_id, category_id, source_id = self._fetch_ingest_ids(
            base_url, headers, article_data["selected_category"], domain_key
        )
        
        # 기자 매칭 조회 실패 시 WAIT 처리
        if reporter_id is None:
            from common.logger_setup import get_domain_logger
            logger = get_domain_logger(domain_key)
            logger.warning(f"[{domain_key}] [WAIT / SKIP] Author ID is invalid or mapping lookup failed. Skipping API call.")
            return {"status": "waiting", "reason": "Author mapping lookup failed"}, "Author mapping lookup failed"
        
        # 2. Build images array
        img_url = img_data.get("url") if img_data else None
        img_credit = img_data.get("credit", "") if img_data else ""
        title_clean = self._clean_text(article_data["title"])
        
        images = []
        if img_url:
            formatted_caption = f"({img_credit})" if img_credit else ""
            images.append({
                "url": img_url,
                "name": title_clean[:100],
                "caption": formatted_caption[:200],
                "credit": img_credit
            })
            
        # 3. Build payload (use title hash as unique external_id fallback to prevent duplicates)
        external_id = f"cms-{domain_key}-{abs(hash(title_clean))}"
        
        payload = {
            "headline": title_clean[:255],
            "body": self._clean_text(article_data["content"]),
            "reporter_id": reporter_id,
            "category_id": category_id,
            "classification": "news",
            "idempotency_key": idempotency_key
        }
        
        if source_id:
            payload["source_id"] = source_id
        if article_data.get("summary"):
            payload["summary"] = self._clean_text(article_data["summary"])[:500]
        if article_data.get("seo_tags"):
            payload["keywords"] = self._clean_text(article_data["seo_tags"])[:500]
        if rss_link:
            payload["source_url"] = rss_link[:500]
        if external_id:
            payload["external_id"] = external_id
        if images:
            payload["images"] = images
            
        target_url = f"{base_url}/ingest/article"
        
        from common.logger_setup import get_domain_logger
        logger = get_domain_logger(domain_key)
        
        max_retries = 3
        last_error = None
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Publishing article (attempt {attempt + 1}/{max_retries}) via Ingest API JSON to [{domain_key}] ({target_url})...")
                response = requests.post(target_url, json=payload, headers=headers, verify=False, timeout=20)
                if response.status_code in (200, 201):
                    return response.json(), None
                else:
                    status_code = response.status_code
                    if status_code >= 500:
                        last_error = f"HTTP {status_code} ({response.text})"
                        time.sleep(1)
                        continue
                    try:
                        error_json = response.json()
                        a_id = error_json.get("a_id")
                        cms_url = error_json.get("cms_url")
                        if status_code == 409 and a_id:
                            logger.info(f"Ingest API returned 409 duplicate check, treating as success: a_id {a_id}")
                            return {
                                "a_id": a_id,
                                "status": "queued",
                                "cms_url": cms_url
                            }, None
                        error_msg = error_json.get("error", "unknown_api_error")
                    except:
                        error_msg = response.text or "HTTP Error"
                    return None, f"HTTP {status_code} ({error_msg})"
            except Exception as e:
                last_error = str(e)
                time.sleep(1)
                continue
                
        return None, f"Failed after {max_retries} retries. Last error: {last_error}"

# Ingest API 호스트 맵핑 정보 (사용자 피드백 수용: mobilenapps.com 적용)
INGEST_API_HOSTS = {
    "jobsnhire": "https://api.jobsnhire.com",
    "foodworldnews": "https://api.foodworldnews.com",
    "parentherald": "https://api.parentherald.com",
    "booksnreview": "https://api.booksnreview.com",
    "franchiseherald": "https://api.franchiseherald.com",
    "mobilenapps": "https://api.mobilenapps.com"
}



# ==============================================================================
# 5. 오케스트레이션 및 파이프라인 (Main Orchestrator)
# ==============================================================================
