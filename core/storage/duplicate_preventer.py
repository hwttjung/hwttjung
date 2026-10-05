import os
import re
import json
import difflib
import contextlib
import fcntl
from datetime import datetime, timedelta, timezone

# 도메인별 비활성/유령 카테고리 슬러그 리스트
INACTIVE_CATEGORIES = {
    "scienceworldreport": ["trending-news", "video"],
    "latinoshealth": ["trending-news", "video"],
    "autoworldnews": ["trending-news", "galleries", "autoworldbuzz"],
    "youthhealthmag": [
        "trending", "myths-facts", "resources", 
        "Lentertainment", "Lsports", "Lgame", "Ltech", "Lscience", "Llife-gossip",
        "Tenterainment", "Tsports", "Tgame", "Ttech", "Tscience", "Slife-gossip",
        "best_deals", "product", "offer", "misc", "teengirl", "teenboy",
        "cardioWorkouts", "bodyWork", "yoga-pilates", "recipes", "healthyFood",
        "headlines", "Tlife", "skin-anti-aging", "hair-makeup", "fashionTips",
        "healthyHabits", "preventive", "mentalHealth"
    ],
    "boomsbeat": ["trending-news", "best_companies", "product_reviews"],
    "sportsworldreport": ["trending-news", "brazil-world-cup-2014", "hidden", "videos"],
    "newseveryday": ["social-trends"],
    "celebeat": ["photos", "video"],
    "franchiseherald": ["trending-news"],
    "mobilenapps": ["trending-news"],
    "parentherald": ["trending-news"],
    "jobsnhire": []
}

class DuplicatePreventer:
    def __init__(self, history_path="data/published_history.json", threshold=0.7):
        self.history_path = history_path
        self.lock_path = history_path + ".lock"
        self.threshold = threshold
        self._ensure_history_exists()
        
    import contextlib
    @contextlib.contextmanager
    def _lock(self):
        import fcntl
        os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)
        with open(self.lock_path, "w") as lock_f:
            fcntl.flock(lock_f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_f, fcntl.LOCK_UN)

    def _ensure_history_exists(self):
        os.makedirs(os.path.dirname(self.history_path), exist_ok=True)
        with self._lock():
            if not os.path.exists(self.history_path):
                with open(self.history_path, "w", encoding="utf-8") as f:
                    json.dump({}, f)
                
    def _normalize_image_url(self, url):
        if not url:
            return ""
        return url.split("?")[0].strip().lower()

    def _is_within_168_hours(self, timestamp_str):
        if not timestamp_str:
            return False
        from datetime import datetime, timezone
        try:
            clean_ts = timestamp_str.strip()
            if clean_ts.endswith("Z"):
                # if there is already an offset like +00:00 before Z, slice it off
                if "+" in clean_ts or "-" in clean_ts[10:]:
                    clean_ts = clean_ts[:-1]
                else:
                    clean_ts = clean_ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_ts)
            now = datetime.now(timezone.utc)
            diff = now - dt
            return diff.total_seconds() <= 168 * 3600
        except Exception:
            return False

    def _load_history(self):
        try:
            with open(self.history_path, "r", encoding="utf-8") as f:
                raw_history = json.load(f)
            standardized = {}
            for site_domain, items in raw_history.items():
                standardized[site_domain] = []
                for item in items:
                    if isinstance(item, str):
                        standardized[site_domain].append({
                            "title": item.strip(),
                            "category": None,
                            "date": None,
                            "image_url": None,
                            "timestamp": None,
                            "rss_link": None
                        })
                    elif isinstance(item, dict):
                        standardized[site_domain].append({
                            "title": item.get("title", "").strip(),
                            "category": item.get("category"),
                            "date": item.get("date"),
                            "image_url": item.get("image_url"),
                            "timestamp": item.get("timestamp"),
                            "rss_link": item.get("rss_link")
                        })
            return standardized
        except Exception:
            return {}
            
    def _save_history(self, history):
        try:
            with open(self.history_path, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            from common.logger_setup import get_domain_logger
            logger = get_domain_logger("general")
            logger.warning(f"Failed to save duplicate preventer history: {e}")
            
    def is_duplicate(self, title, site_domain):
        with self._lock():
            history = self._load_history()
        site_history = history.get(site_domain, [])
        
        # Clean and normalize new title
        new_clean = re.sub(r"\s+", " ", title.lower().strip())
        new_clean = new_clean.replace("’", "'").replace("`", "'")
        
        import difflib
        for past_item in site_history:
            # 168시간 이내에 발행된 기사만 중복 검사
            if not self._is_within_168_hours(past_item.get("timestamp")):
                continue
                
            past_title = past_item.get("title", "")
            past_clean = re.sub(r"\s+", " ", past_title.lower().strip())
            past_clean = past_clean.replace("’", "'").replace("`", "'")
            
            # 1. Exact match
            if new_clean == past_clean:
                return True
                
            # 2. SequenceMatcher similarity ratio
            similarity = difflib.SequenceMatcher(None, new_clean, past_clean).ratio()
            if similarity >= self.threshold:
                from common.logger_setup import get_domain_logger
                logger = get_domain_logger(site_domain)
                logger.info(f"[Duplicate Detected] New title similarity is {round(similarity * 100, 1)}% with past article: '{past_title}'")
                return True
                
        return False

    def get_allowed_categories(self, site_domain, available_categories):
        """
        카테고리 제약 조건을 검증하여 허용 가능한 카테고리 목록만 필터링하여 반환합니다.
        0. 비활성/유령 카테고리는 송출 대상에서 영구 제외합니다.
        1. 같은 카테고리는 연속으로 2번 발생해서는 안 됩니다.
        2. 하루 KST 기준 송출되는 기사는 같은 카테고리의 기사가 3개 이상이 되면 안 됩니다. (최대 2개)
        """
        with self._lock():
            history = self._load_history()
        site_history = history.get(site_domain, [])
        
        from datetime import datetime, timedelta, timezone
        kst = timezone(timedelta(hours=9))
        today_kst = datetime.now(kst).strftime("%Y-%m-%d")
        
        # 1. 직전 발행된 기사의 카테고리 조회
        last_category = None
        if site_history:
            last_category = site_history[-1].get("category")
            
        # 2. 오늘 날짜의 카테고리별 누적 카운트 계산
        today_counts = {}
        for item in site_history:
            if item.get("date") == today_kst and item.get("category"):
                cat = item["category"]
                today_counts[cat] = today_counts.get(cat, 0) + 1
                
        from common.logger_setup import get_domain_logger
        logger = get_domain_logger(site_domain)
        
        allowed = []
        for cat_info in available_categories:
            slug = cat_info["slug"]
            
            # 규칙 0: 비활성/유령 카테고리 블랙리스트 필터링
            inactive_slugs = INACTIVE_CATEGORIES.get(site_domain, [])
            if slug in inactive_slugs:
                logger.info(f"[Category Restrict] Category '{slug}' is blocked due to inactive status.")
                continue
                
            # 규칙 1: 같은 카테고리 연속 발행 차단
            if last_category and slug == last_category:
                logger.info(f"[Category Restrict] Category '{slug}' is blocked due to consecutive restriction.")
                continue
                
            # 규칙 2: 하루 최대 2개까지만 허용 (3개 이상 방지)
            if today_counts.get(slug, 0) >= 2:
                logger.info(f"[Category Restrict] Category '{slug}' is blocked due to daily limit (already published {today_counts[slug]} times today KST).")
                continue
                
            allowed.append(cat_info)
            
        # 모든 카테고리가 차단된 최악의 경우, 안전장치로 전체 카테고리 반환
        if not allowed:
            logger.warning("[Warning] All categories were restricted. Falling back to all available categories for safety.")
            return available_categories
            
        return allowed

    def get_stochastically_weighted_category(self, site_domain, available_categories):
        """
        최근 7일(168시간) 카테고리별 발행 이력을 집계하여,
        발행 빈도가 적은 카테고리에 높은 가중치를 부여하는 확률적(Stochastic) 추첨을 수행합니다.
        """
        allowed = self.get_allowed_categories(site_domain, available_categories)
        if not allowed:
            return None
            
        with self._lock():
            history = self._load_history()
        site_history = history.get(site_domain, [])
        
        # 최근 168시간(7일) 내 카테고리별 누적 빈도 집계
        recent_counts = {}
        for item in site_history:
            if self._is_within_168_hours(item.get("timestamp")) and item.get("category"):
                cat = item["category"]
                recent_counts[cat] = recent_counts.get(cat, 0) + 1
                
        # 각 카테고리별 역가중치: 1 / (count + 1)
        weights = []
        for cat_info in allowed:
            slug = cat_info["slug"]
            cnt = recent_counts.get(slug, 0)
            weights.append(1.0 / (cnt + 1))
            
        import random
        chosen = random.choices(allowed, weights=weights, k=1)[0]
        
        from common.logger_setup import get_domain_logger
        logger = get_domain_logger(site_domain)
        cnt_chosen = recent_counts.get(chosen['slug'], 0)
        logger.info(f"[{site_domain}] [Stochastic Selector] Selected primary category '{chosen['slug']}' (7-day count: {cnt_chosen}, Weight: {round(1.0 / (cnt_chosen + 1), 3)}).")
        return chosen

    def sort_categories_by_stochastic_priority(self, site_domain, categories):
        """
        최근 7일 발행 빈도가 적은 카테고리를 프롬프트 앞쪽에 우선 배치하여 LLM 선택 다양성을 극대화합니다.
        동점일 경우 무작위 셔플을 통해 매번 새로운 순서를 보장합니다.
        """
        with self._lock():
            history = self._load_history()
        site_history = history.get(site_domain, [])
        
        recent_counts = {}
        for item in site_history:
            if self._is_within_168_hours(item.get("timestamp")) and item.get("category"):
                cat = item["category"]
                recent_counts[cat] = recent_counts.get(cat, 0) + 1
                
        import random
        cats_copy = list(categories)
        random.shuffle(cats_copy) # 동점 시 완전 무작위성 부여
        cats_copy.sort(key=lambda c: recent_counts.get(c.get("slug"), 0))
        return cats_copy
        
    def get_recent_image_urls(self, site_domain):
        """
        최근 168시간(7일) 이내에 해당 사이트에 송출된 이미지 URL(정규화됨) 목록을 구합니다.
        """
        with self._lock():
            history = self._load_history()
        site_history = history.get(site_domain, [])
        
        recent_urls = set()
        for item in site_history:
            if self._is_within_168_hours(item.get("timestamp")) and item.get("image_url"):
                normalized = self._normalize_image_url(item["image_url"])
                if normalized:
                    recent_urls.add(normalized)
        return recent_urls

    def get_recent_rss_links(self, site_domain):
        """
        최근 168시간(7일) 이내에 사용된 RSS 기사 원본 링크(rss_link) 목록을 구합니다.
        """
        with self._lock():
            history = self._load_history()
        site_history = history.get(site_domain, [])
        
        recent_links = set()
        for item in site_history:
            if self._is_within_168_hours(item.get("timestamp")) and item.get("rss_link"):
                recent_links.add(item["rss_link"].strip())
        return recent_links

    def get_globally_restricted_rss_links(self, max_allowed_sites=2):
        """
        최근 168시간(7일) 이내에 전체 사이트 중 max_allowed_sites 개수 이상의 사이트에서
        이미 사용된 RSS 기사 원본 링크(rss_link) 목록을 구합니다.
        이를 통해 동일 뉴스가 3개 이상의 사이트에 겹쳐 송출되는 것을 방지합니다.
        """
        with self._lock():
            history = self._load_history()
            
        link_site_count = {}
        for site_domain, items in history.items():
            for item in items:
                if self._is_within_168_hours(item.get("timestamp")) and item.get("rss_link"):
                    link = item["rss_link"].strip()
                    if link:
                        if link not in link_site_count:
                            link_site_count[link] = set()
                        link_site_count[link].add(site_domain)
                        
        restricted_links = set()
        for link, sites in link_site_count.items():
            if len(sites) >= max_allowed_sites:
                restricted_links.add(link)
        return restricted_links

    def add_to_history(self, title, site_domain, category=None, image_url=None, rss_link=None, max_keep=100):
        with self._lock():
            history = self._load_history()
            if site_domain not in history:
                history[site_domain] = []
                
            from datetime import datetime, timedelta, timezone
            kst = timezone(timedelta(hours=9))
            today_kst = datetime.now(kst).strftime("%Y-%m-%d")
            now_utc_str = datetime.now(timezone.utc).isoformat() + "Z"
            
            new_entry = {
                "title": title.strip(),
                "category": category,
                "date": today_kst,
                "image_url": image_url,
                "timestamp": now_utc_str,
                "rss_link": rss_link
            }
            
            history[site_domain].append(new_entry)
            
            # Keep only the last N articles to prevent file bloating
            if len(history[site_domain]) > max_keep:
                history[site_domain] = history[site_domain][-max_keep:]
                
            self._save_history(history)


# ==============================================================================
# 2. AI 기사 생성 모듈 (ArticleGenerator)
# ==============================================================================
