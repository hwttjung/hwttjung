import os
import re
import ssl
import urllib.request
import urllib.parse
from .logger_setup import get_domain_logger

logger = get_domain_logger("general")

class EnvLoader:
    @staticmethod
    def load_env(env_path=".env"):
        if not os.path.exists(env_path):
            if os.path.exists("config/.env"):
                env_path = "config/.env"
            else:
                logger.warning(f"[Warning] {env_path} file not found.")
                return {}
        
        env_vars = {}
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                match = re.match(r"^([^=]+)=(.*)$", line)
                if match:
                    key = match.group(1).strip()
                    val = match.group(2).strip()
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    env_vars[key] = val
                    os.environ[key] = val
        return env_vars

    @staticmethod
    def get_sites_config(env):
        sites = []
        for i in range(1, 9):
            url_key = f"ARTICLES_API_BASE_URL_{i}"
            key_key = f"ARTICLES_API_KEY_{i}"
            url = env.get(url_key)
            api_key = env.get(key_key)
            if url and api_key:
                domain = "unknown"
                match = re.search(r"https?://admin\.([^/]+)", url)
                if match:
                    domain = match.group(1).split(".")[0]
                sites.append({
                    "index": i,
                    "domain_key": domain,
                    "url": url,
                    "api_key": api_key
                })
        # 로컬 기사 작성 전용(송출 제외) 사이트 강제 주입 목록
        local_only_configs = [
            {"index": 9, "domain_key": "jobsnhire", "url": "https://admin.jobsnhire.com/api/v1/", "api_key": "local-key-jobsnhire"},
            {"index": 10, "domain_key": "franchiseherald", "url": "https://admin.franchiseherald.com/api/v1/", "api_key": "local-key-franchiseherald"},
            {"index": 11, "domain_key": "mobilenapps", "url": "https://admin.mobilenapps.com/api/v1/", "api_key": "local-key-mobilenapps"},
            {"index": 12, "domain_key": "parentherald", "url": "https://admin.parentherald.com/api/v1/", "api_key": "local-key-parentherald"},
            {"index": 13, "domain_key": "booksnreview", "url": "https://admin.booksnreview.com/api/v1/", "api_key": "local-key-booksnreview"},
            {"index": 14, "domain_key": "foodworldnews", "url": "https://admin.foodworldnews.com/api/v1/", "api_key": "local-key-foodworldnews"}
        ]
        sites.extend(local_only_configs)
        return sites


class TelegramNotifier:
    def __init__(self, env):
        self.api_token = env.get("TELEGRAM_API")
        self.chat_id = env.get("TELEGRAM_USER_ID")
        
    def send_notification(self, message):
        if not self.api_token or not self.chat_id:
            logger.warning("[Warning] Telegram notification skipped: API token or chat ID is missing in .env.")
            return False
            
        # 4000자 초과 시 텔레그램 API 전송 실패를 방지하기 위해 강제 슬라이싱 및 경고 로그
        if len(message) > 4000:
            logger.warning(f"[Warning] Telegram message too long ({len(message)} chars), clipping to 4000 chars.")
            message = message[:4000] + "\n... (clipped due to Telegram length limit)"
            
        url = f"https://api.telegram.org/bot{self.api_token}/sendMessage"
        
        # Ensure correct formatting for username or id
        chat_id_param = self.chat_id.strip()
        if not chat_id_param.startswith("@") and not chat_id_param.isdigit() and "-" not in chat_id_param:
            chat_id_param = f"@{chat_id_param}"
            
        payload = {
            "chat_id": chat_id_param,
            "text": message,
            "parse_mode": "HTML"
        }
        
        req = urllib.request.Request(
            url,
            data=urllib.parse.urlencode(payload).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST"
        )
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=10) as res:
                return True
        except Exception as e:
            logger.warning(f"[Warning] Failed to send Telegram notification: {e}")
            return False
