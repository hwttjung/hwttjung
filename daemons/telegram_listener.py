import os
import sys
import json
import time
import socket
import urllib.request
import urllib.parse
import ssl

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from common.env_loader import EnvLoader
from common.logger_setup import get_domain_logger

# 글로벌 소켓 타임아웃 설정 (TCP/SSL 레벨의 무한 블로킹 방지)
socket.setdefaulttimeout(40)

logger = get_domain_logger("general")

def load_status_dict():
    status_file = "config/status.json"
    if os.path.exists(status_file):
        try:
            with open(status_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[Listener] Error reading status file: {e}")
    return {"STOP_PUBLISHING": False, "TELEGRAM_COPY_MODE": False}

def get_publishing_status():
    data = load_status_dict()
    return data.get("STOP_PUBLISHING", False)

check_stop_publishing = get_publishing_status

def get_copy_mode_status():
    data = load_status_dict()
    return data.get("TELEGRAM_COPY_MODE", False)

def update_status_key(key, val):
    status_file = "config/status.json"
    os.makedirs(os.path.dirname(status_file), exist_ok=True)
    try:
        data = load_status_dict()
        data[key] = val
        with open(status_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.info(f"[Listener] Status updated in status.json: {key} = {val}")
        return True
    except Exception as e:
        logger.error(f"[Listener] Error writing status file: {e}")
        return False

def send_reply(api_token, chat_id, text):
    url = f"https://api.telegram.org/bot{api_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as res:
            res.read()
    except Exception as e:
        logger.error(f"[Listener] Failed to send reply to Telegram: {e}")

def main():
    logger.info("==================================================")
    logger.info(" Starting Telegram Remote Control Listener")
    logger.info("==================================================")
    
    env = EnvLoader.load_env()
    api_token = env.get("TELEGRAM_API")
    target_user_id_str = env.get("TELEGRAM_USER_ID")
    
    if not api_token or not target_user_id_str:
        logger.error("[Listener] TELEGRAM_API or TELEGRAM_USER_ID is missing in .env. Exiting.")
        sys.exit(1)
        
    try:
        target_user_id = int(target_user_id_str.strip())
    except ValueError:
        logger.error(f"[Listener] Invalid TELEGRAM_USER_ID format: '{target_user_id_str}'. Exiting.")
        sys.exit(1)
        
    offset = 0
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    logger.info(f"[Listener] Authenticated target Admin ID: {target_user_id}")
    logger.info("[Listener] Listening for commands...")
    
    loop_count = 0
    while True:
        loop_count += 1
        # 100회(약 50분)마다 생존 하트비트 로그 기록
        if loop_count % 100 == 1:
            logger.info(f"[Listener Heartbeat] Actively listening for Telegram commands (Offset: {offset})...")

        # Long polling with getUpdates API (Connection: close로 소켓 재사용 누수 및 프리징 방지)
        url = f"https://api.telegram.org/bot{api_token}/getUpdates?offset={offset}&timeout=30"
        
        try:
            req = urllib.request.Request(url, headers={"Connection": "close", "User-Agent": "Telegram-Listener/1.0"}, method="GET")
            with urllib.request.urlopen(req, context=ctx, timeout=35) as res:
                response_data = json.loads(res.read().decode("utf-8"))
                
            if not response_data.get("ok"):
                logger.error(f"[Listener] getUpdates API returned ok=False: {response_data}")
                time.sleep(5)
                continue
                
            updates = response_data.get("result", [])
            for update in updates:
                update_id = update.get("update_id")
                offset = update_id + 1  # Acknowledge this update
                
                message = update.get("message")
                if not message:
                    continue
                    
                sender = message.get("from", {})
                sender_id = sender.get("id")
                
                # Security Check: Only process messages from the authorized user
                if sender_id != target_user_id:
                    logger.warning(f"[Listener Security Warning] Unauthorized message from ID {sender_id} (Username: {sender.get('username')}) ignored.")
                    continue
                    
                chat_id = message.get("chat", {}).get("id")
                text = message.get("text", "").strip()
                
                if not text:
                    continue
                
                logger.info(f"[Listener Received] Command: '{text}' from User ID: {sender_id}")
                
                # Command Routing
                if text == "/stop":
                    success = update_status_key("STOP_PUBLISHING", True)
                    if success:
                        reply = "🛑 <b>[기사 송출 중지]</b>\n기사 수집, 생성 및 송출 파이프라인이 <b>전역 중지(STOP)</b> 상태로 설정되었습니다."
                    else:
                        reply = "⚠️ <b>[오류]</b>\n상태 파일 변경에 실패했습니다. 로그를 확인하세요."
                    send_reply(api_token, chat_id, reply)
                    
                elif text == "/start":
                    success = update_status_key("STOP_PUBLISHING", False)
                    if success:
                        reply = "🟢 <b>[기사 송출 활성화]</b>\n기사 수집, 생성 및 송출 파이프라인이 다시 <b>활성화(START)</b> 되었습니다."
                    else:
                        reply = "⚠️ <b>[오류]</b>\n상태 파일 변경에 실패했습니다. 로그를 확인하세요."
                    send_reply(api_token, chat_id, reply)
                    
                elif text == "/copymode on":
                    success = update_status_key("TELEGRAM_COPY_MODE", True)
                    if success:
                        reply = "🟢 <b>[텔레그램 복사 모드 활성화]</b>\n수동 복사 모드가 켜졌습니다. 모든 기사는 API 송출을 스킵하고 텔레그램으로 상세 본문을 발송합니다."
                    else:
                        reply = "⚠️ <b>[오류]</b>\n상태 파일 변경에 실패했습니다. 로그를 확인하세요."
                    send_reply(api_token, chat_id, reply)
                    
                elif text == "/copymode off":
                    success = update_status_key("TELEGRAM_COPY_MODE", False)
                    if success:
                        reply = "🛑 <b>[텔레그램 복사 모드 비활성화]</b>\n일반 API 송출 모드로 복구되었습니다."
                    else:
                        reply = "⚠️ <b>[오류]</b>\n상태 파일 변경에 실패했습니다. 로그를 확인하세요."
                    send_reply(api_token, chat_id, reply)
                    
                elif text == "/status":
                    is_stopped = get_publishing_status()
                    is_copy_mode = get_copy_mode_status()
                    status_str = "🛑 중지됨 (STOP)" if is_stopped else "🟢 활성화됨 (RUNNING)"
                    copy_mode_str = "🟢 활성화 (ON)" if is_copy_mode else "🛑 비활성화 (OFF)"
                    reply = (
                        f"ℹ️ <b>[현재 시스템 제어 상태]</b>\n"
                        f"• 송출 상태: <b>{status_str}</b>\n"
                        f"• 텔레그램 복사 모드: <b>{copy_mode_str}</b>\n"
                        f"(상태 파일: <code>config/status.json</code>)"
                    )
                    send_reply(api_token, chat_id, reply)
                    
                else:
                    reply = (
                        "❓ <b>[명령어 가이드]</b>\n"
                        "아래의 명령어만 사용 가능합니다:\n\n"
                        "• /stop : 기사 송출 전역 중지 (STOP_PUBLISHING=true)\n"
                        "• /start : 기사 송출 재개 및 활성화 (STOP_PUBLISHING=false)\n"
                        "• /copymode on : 텔레그램 복사 모드 활성화 (API 송출 스킵 및 텔레그램 상세 발송)\n"
                        "• /copymode off : 텔레그램 복사 모드 비활성화 (일반 API 송출)\n"
                        "• /status : 현재 제어 상태 조회"
                    )
                    send_reply(api_token, chat_id, reply)
                    
        except urllib.error.URLError as e:
            logger.warning(f"[Listener Warning] Network error during update polling: {e}. Resetting context and retrying in 5s...")
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            time.sleep(5)
        except Exception as e:
            logger.error(f"[Listener Error] Unexpected exception in loop: {e}. Resetting context and retrying in 5s...")
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            time.sleep(5)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("[Listener] Terminated by KeyboardInterrupt.")
        sys.exit(0)
