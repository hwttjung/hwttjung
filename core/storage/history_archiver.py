import os
import re
import json
import hashlib
import contextlib
import fcntl
from datetime import datetime, timedelta, timezone

class HistoryArchiver:
    def __init__(self, archive_dir="data/archive", retention_days=90):
        self.archive_dir = archive_dir
        self.content_dir = os.path.join(archive_dir, "content")
        self.pub_dir = os.path.join(archive_dir, "publication")
        self.lock_path = os.path.join(archive_dir, "archive.lock")
        self.retention_days = retention_days
        self.timezone_kst = timezone(timedelta(hours=9)) # Asia/Seoul KST
        self._ensure_dirs_exist()
        
    @contextlib.contextmanager
    def _lock(self):
        os.makedirs(self.archive_dir, exist_ok=True)
        import time
        max_retries = 10
        retry_delay = 0.2
        
        with open(self.lock_path, "w") as lock_f:
            locked = False
            for attempt in range(max_retries):
                try:
                    fcntl.flock(lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                    break
                except (BlockingIOError, OSError):
                    time.sleep(retry_delay)
                    
            if not locked:
                from common.logger_setup import get_domain_logger
                logger = get_domain_logger("general")
                logger.error(f"[HistoryArchiver] Failed to acquire lock on {self.lock_path} within timeout.")
                raise TimeoutError(f"Archive write lock timeout after {max_retries * retry_delay}s")
                
            try:
                yield
            finally:
                fcntl.flock(lock_f, fcntl.LOCK_UN)
                
    def _ensure_dirs_exist(self):
        os.makedirs(self.content_dir, exist_ok=True)
        os.makedirs(self.pub_dir, exist_ok=True)

    def _get_kst_now(self):
        return datetime.now(self.timezone_kst)

    def _normalize_string(self, text):
        if not text:
            return ""
        # 불필요한 앞뒤 공백 제거, 연속된 공백 하나로 치환, 줄바꿈 정리
        normalized = re.sub(r"\s+", " ", text.strip())
        return normalized

    def make_article_hash(self, content_html):
        """
        완성된 기사 본문을 정규화한 후 SHA-256 해시를 생성합니다.
        """
        normalized = self._normalize_string(content_html)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def generate_article_id(self):
        """
        기존 ID가 없을 경우 YYYYMMDD-6자리순번 형태로 생성합니다.
        """
        now_str = self._get_kst_now().strftime("%Y%m%d")
        import random
        random_seq = f"{random.randint(1, 999999):06d}"
        return f"{now_str}_{random_seq}"

    def save_content(self, content_data):
        """
        Content 데이터를 날짜별 JSON 파일에 원자적으로 저장합니다.
        """
        article_id = content_data.get("article_id")
        if not article_id:
            article_id = self.generate_article_id()
            content_data["article_id"] = article_id

        # 계보 정보 기본값 안전 기입
        if "story_id" not in content_data:
            content_data["story_id"] = None
        if "parent_article_id" not in content_data:
            content_data["parent_article_id"] = None
        if "article_type" not in content_data:
            content_data["article_type"] = None

        # 날짜 구하기 (created_at 기준 또는 오늘 날짜 KST)
        created_at_str = content_data.get("created_at")
        if created_at_str:
            try:
                dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                date_str = dt.astimezone(self.timezone_kst).strftime("%Y-%m-%d")
            except Exception:
                date_str = self._get_kst_now().strftime("%Y-%m-%d")
        else:
            date_str = self._get_kst_now().strftime("%Y-%m-%d")
            content_data["created_at"] = self._get_kst_now().isoformat()

        # TTL 만료 시각(90일 후) 설정
        if "expires_at" not in content_data:
            dt = datetime.fromisoformat(content_data["created_at"].replace("Z", "+00:00"))
            expires_dt = dt + timedelta(days=self.retention_days)
            content_data["expires_at"] = expires_dt.isoformat()

        file_path = os.path.join(self.content_dir, f"{date_str}.json")
        tmp_path = file_path + ".tmp"

        with self._lock():
            existing_data = {}
            if os.path.exists(file_path):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        existing_data = json.load(f)
                except Exception as e:
                    # 파일 손상 시 삭제 금지 및 경고 로깅 후 예외 전파 (기존 데이터 보호)
                    from common.logger_setup import get_domain_logger
                    logger = get_domain_logger("general")
                    logger.error(f"[HistoryArchiver] Content JSON parse error in {file_path}: {e}")
                    raise ValueError(f"Factual Enforcer: Content JSON parse failed: {e}")

            existing_data[article_id] = content_data

            # 원자적 쓰기 (Atomic write)
            with open(tmp_path, "w", encoding="utf-8") as tf:
                json.dump(existing_data, tf, indent=2, ensure_ascii=False)

            # JSON 파싱 유효성 검증
            with open(tmp_path, "r", encoding="utf-8") as tf:
                json.load(tf)

            os.replace(tmp_path, file_path)
        return article_id

    def save_publication(self, pub_data):
        """
        Publication 데이터를 날짜별 JSON 파일에 원자적으로 저장합니다.
        """
        article_id = pub_data.get("article_id")
        site_id = pub_data.get("site_id")
        if not article_id or not site_id:
            return False

        published_at_str = pub_data.get("published_at")
        if published_at_str:
            try:
                dt = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
                date_str = dt.astimezone(self.timezone_kst).strftime("%Y-%m-%d")
            except Exception:
                date_str = self._get_kst_now().strftime("%Y-%m-%d")
        else:
            date_str = self._get_kst_now().strftime("%Y-%m-%d")
            pub_data["published_at"] = self._get_kst_now().isoformat()

        if "expires_at" not in pub_data:
            dt = datetime.fromisoformat(pub_data["published_at"].replace("Z", "+00:00"))
            expires_dt = dt + timedelta(days=self.retention_days)
            pub_data["expires_at"] = expires_dt.isoformat()

        file_path = os.path.join(self.pub_dir, f"{date_str}.json")
        tmp_path = file_path + ".tmp"

        pub_key = f"{article_id}#{site_id}"

        with self._lock():
            existing_data = {}
            if os.path.exists(file_path):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        existing_data = json.load(f)
                except Exception as e:
                    from common.logger_setup import get_domain_logger
                    logger = get_domain_logger("general")
                    logger.error(f"[HistoryArchiver] Publication JSON parse error in {file_path}: {e}")
                    raise ValueError(f"Factual Enforcer: Publication JSON parse failed: {e}")

            existing_data[pub_key] = pub_data

            with open(tmp_path, "w", encoding="utf-8") as tf:
                json.dump(existing_data, tf, indent=2, ensure_ascii=False)

            with open(tmp_path, "r", encoding="utf-8") as tf:
                json.load(tf)

            os.replace(tmp_path, file_path)
        return True

    def load_active_contents(self):
        """
        최근 90일 내의 모든 유효한 Content 리스트를 로드합니다.
        """
        contents = []
        if not os.path.exists(self.content_dir):
            return contents

        with self._lock():
            files = sorted([f for f in os.listdir(self.content_dir) if f.endswith(".json")], reverse=True)
            for fname in files:
                try:
                    file_date = datetime.strptime(fname.split(".json")[0], "%Y-%m-%d")
                    age = (datetime.now() - file_date).days
                    if age > self.retention_days:
                        continue
                except ValueError:
                    continue

                fpath = os.path.join(self.content_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        contents.extend(data.values())
                except Exception:
                    continue
        return contents

    def check_content_duplication(self, new_headline, new_content_html, new_seed_url, new_image_url=None):
        """
        중복 검사 4단계 수행:
        1차: article_hash 중복 검사
        2차: seed_url 중복 검사
        3차: headline 동일 검사
        4차: image_url 동일 검사 (경고 로깅)
        """
        active_contents = self.load_active_contents()
        
        new_hash = self.make_article_hash(new_content_html)
        new_norm_headline = self._normalize_string(new_headline).lower()
        new_norm_image = new_image_url.strip().lower() if new_image_url else ""

        for past in active_contents:
            # 1차: article_hash
            if past.get("article_hash") == new_hash:
                return True, f"1차 중복: 동일한 본문 해시 감지 ({new_hash})"

            # 2차: seed_url (중복 검토 신호로만 사용하고 자동 REJECT에서 제외)
            if new_seed_url and past.get("seed_url") == new_seed_url:
                from common.logger_setup import get_domain_logger
                logger = get_domain_logger("general")
                logger.info(f"[HistoryArchiver] [Review Signal] Seed URL overlap detected: {new_seed_url}")

            # 3차: headline
            past_norm_headline = self._normalize_string(past.get("headline", "")).lower()
            if past_norm_headline == new_norm_headline:
                return True, f"3차 중복: 동일한 헤드라인 감지 ('{past.get('headline')}')"

            # 4차: image_url
            if new_norm_image and past.get("image_url"):
                past_norm_image = past.get("image_url", "").strip().lower()
                if past_norm_image == new_norm_image:
                    # 이미지 중복만으로는 기사 전체 중복 확정하지 않고 경고 로깅
                    from common.logger_setup import get_domain_logger
                    logger = get_domain_logger("general")
                    logger.info(f"[HistoryArchiver] Image URL match detected: {new_image_url}")

        return False, "중복되지 않음"

    def clean_expired_archives(self):
        """
        90일 보관 기간을 초과한 content 및 publication 날짜별 JSON 파일들을 삭제합니다.
        """
        from common.logger_setup import get_domain_logger
        logger = get_domain_logger("general")
        now = self._get_kst_now()

        for directory in [self.content_dir, self.pub_dir]:
            if not os.path.exists(directory):
                continue
            
            with self._lock():
                for fname in os.listdir(directory):
                    # 파일명 형식 검증 (YYYY-MM-DD.json)
                    if not re.match(r"^\d{4}-\d{2}-\d{2}\.json$", fname):
                        continue
                    
                    file_date_str = fname.split(".json")[0]
                    try:
                        file_date = datetime.strptime(file_date_str, "%Y-%m-%d")
                        # 90일 경과 체크
                        delta = now - file_date.replace(tzinfo=self.timezone_kst)
                        if delta.days >= self.retention_days:
                            fpath = os.path.join(directory, fname)
                            
                            # 삭제 로그 작성
                            logger.info(f"[HistoryArchiver-TTL] Deleting expired archive file: {fpath} (Age: {delta.days} days)")
                            os.remove(fpath)
                    except Exception as e:
                        logger.error(f"[HistoryArchiver-TTL] Error cleaning up file {fname}: {e}")
