import os
import sys
import json
import time
from datetime import datetime, timedelta, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 컴포넌트 임포트
from common.env_loader import EnvLoader, TelegramNotifier
from core.media.cost_tracker import CostTracker

def parse_iso_datetime(dt_str):
    if not dt_str:
        return None
    # 2026-08-22T15:56:01.123456 형식이나 Z, +09:00 형태의 오프셋 보정
    dt_str_clean = dt_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(dt_str_clean)
    except Exception:
        return None

def main():
    env = EnvLoader.load_env()
    notifier = TelegramNotifier(env)
    sites = EnvLoader.get_sites_config(env)
    
    # 인자 파싱
    mode = None
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        
    if mode == "--morning":
        # 아침 9시 출근 메시지 송출
        notifier.send_notification("출근했습니다.")
        time.sleep(1)
        # 하루를 시작하는 활기찬 응원 메시지 추가 송출
        notifier.send_notification("오늘 하루도 힘차게 시작해봐요! 14개 매체의 성공적인 송출을 적극 응원합니다! 🚀🔥")
        print("Morning notification successfully sent.")
        
    elif mode == "--evening":
        # 저녁 6시 통계 보고서 및 퇴근 메시지 송출
        print("Gathering evening publication reports...")
        
        # 현재 시간 기준 (UTC)
        now_utc = datetime.now(timezone.utc)
        start_time_utc = now_utc - timedelta(hours=18) # 지난 18시간 동안의 통계 수집 (동부 당일 00:00 ~ 18:00)
        
        # history archiver 경로 설정
        pub_dir = "data/archive/publication"
        
        # 어제와 오늘 일자(KST 기준)에 해당하는 아카이브 파일 로드
        timezone_kst = timezone(timedelta(hours=9))
        today_kst = now_utc.astimezone(timezone_kst).strftime("%Y-%m-%d")
        yesterday_kst = (now_utc.astimezone(timezone_kst) - timedelta(days=1)).strftime("%Y-%m-%d")
        
        files_to_check = []
        for d_str in [yesterday_kst, today_kst]:
            f_path = os.path.join(pub_dir, f"{d_str}.json")
            if os.path.exists(f_path):
                files_to_check.append(f_path)
                
        # 14개 사이트 도메인별 통계 맵 구성
        domain_status = {site["domain_key"]: {"success": [], "failed": []} for site in sites}
        
        for f_path in files_to_check:
            try:
                with open(f_path, "r", encoding="utf-8") as f:
                    pub_data_dict = json.load(f)
                    for pub_key, pub_item in pub_data_dict.items():
                        published_at_str = pub_item.get("published_at")
                        dt_pub = parse_iso_datetime(published_at_str)
                        if dt_pub:
                            # timezone-aware로 변환하여 범위 검사
                            if dt_pub.tzinfo is None:
                                dt_pub = dt_pub.replace(tzinfo=timezone.utc)
                            else:
                                dt_pub = dt_pub.astimezone(timezone.utc)
                                
                            if start_time_utc <= dt_pub <= now_utc:
                                site_id = pub_item.get("site_id")
                                status = pub_item.get("status")
                                if site_id in domain_status:
                                    if status == "published":
                                        domain_status[site_id]["success"].append(pub_item)
                                    elif status == "publish_failed":
                                        domain_status[site_id]["failed"].append(pub_item)
            except Exception as e:
                print(f"Failed to process archive {f_path}: {e}")
                
        # 보고서 빌드
        total_success_count = 0
        total_failed_count = 0
        unsent_media_count = 0
        
        detail_lines = []
        for idx, site in enumerate(sites, 1):
            domain = site["domain_key"]
            status_info = domain_status.get(domain, {"success": [], "failed": []})
            
            success_list = status_info["success"]
            failed_list = status_info["failed"]
            
            if not success_list and not failed_list:
                detail_lines.append(f"{idx}. {domain}: ⚠️ 미송출 (RSS 시드 없음 또는 가이드라인 차단)")
                unsent_media_count += 1
            else:
                success_tailored = sum(1 for item in success_list if item.get("mode", "tailored") == "tailored")
                success_trend = sum(1 for item in success_list if item.get("mode") == "trend")
                failed_tailored = sum(1 for item in failed_list if item.get("mode", "tailored") == "tailored")
                failed_trend = sum(1 for item in failed_list if item.get("mode") == "trend")
                
                total_success_count += len(success_list)
                total_failed_count += len(failed_list)
                
                detail_lines.append(f"{idx}. {domain}:")
                detail_lines.append(f"  • 송출 성공: {len(success_list)}건 (tailored: {success_tailored}, trend: {success_trend})")
                for item in success_list:
                    art_id = item.get("article_id", "Draft-OK")
                    pub_url = item.get("published_url")
                    url_str = f" (<a href='{pub_url}'>Link</a>)" if pub_url else ""
                    detail_lines.append(f"    - ✅ ID: {art_id}{url_str}")
                    
                if failed_list:
                    detail_lines.append(f"  • 송출 실패: {len(failed_list)}건 (tailored: {failed_tailored}, trend: {failed_trend})")
                    for item in failed_list:
                        err_msg = item.get("error", "Unknown CMS error")
                        detail_lines.append(f"    - ❌ 사유: {err_msg}")
                
        cost_tracker = CostTracker()
        cost_report = cost_tracker.format_telegram_report()
        
        total_msg = f"""<b>[일일 기사 송출 현황 보고서]</b>
• 집계 기준: 미국 동부시간 당일 (09:00 ~ 18:00)

• 총 성공 송출: {total_success_count}건 / {len(sites)}개 매체
• 실패 매체: {total_failed_count}건
• 미송출 매체: {unsent_media_count}건

{cost_report}

<b>[매체별 상세 리포트]</b>
""" + "\n".join(detail_lines)

        # 1. 보고서 텔레그램 송출
        notifier.send_notification(total_msg)
        print("Evening stats report successfully sent.")
        
        # 2. 퇴근 메시지 송출
        time.sleep(1)
        notifier.send_notification("퇴근하겠습니다. 뿅")
        print("Evening sign-off notification successfully sent.")
        
    else:
        print("Usage: python3 telegram_notifier_cron.py [--morning | --evening]")

if __name__ == "__main__":
    main()
