import os
import sys
import json
import shutil
import html
from datetime import datetime

sys.path.append("/home/stock_trading_bot")

from common.env_loader import EnvLoader, TelegramNotifier
from core.publishing.article_publisher import ArticlePublisher
from common.logger_setup import get_domain_logger

logger = get_domain_logger("general")

def main():
    logger.info("==================================================")
    logger.info(" Starting Re-publishing of Unused/Failed Articles")
    logger.info("==================================================")
    
    env = EnvLoader.load_env()
    
    # 1. Check if STOP_PUBLISHING is active
    stop_publishing = env.get("STOP_PUBLISHING", "False").strip().lower() in ("true", "1", "yes")
    status_file = "config/status.json"
    if os.path.exists(status_file):
        try:
            with open(status_file, "r", encoding="utf-8") as sf:
                status_data = json.load(sf)
                if status_data.get("STOP_PUBLISHING") is True:
                    stop_publishing = True
        except Exception as e:
            logger.warning(f"[Re-publisher] Failed to read status file: {e}")
            
    if stop_publishing:
        logger.warning("[Re-publisher] STOP_PUBLISHING is active. Exiting.")
        sys.exit(0)
        
    unused_dir = "data/local_articles/unused"
    used_dir = "data/local_articles/used"
    os.makedirs(used_dir, exist_ok=True)
    
    if not os.path.exists(unused_dir):
        logger.error(f"[Re-publisher] Unused directory not found: {unused_dir}")
        sys.exit(1)
        
    files = [f for f in os.listdir(unused_dir) if f.endswith(".json")]
    if not files:
        logger.info("[Re-publisher] No unused articles to re-publish.")
        sys.exit(0)
        
    # Sort files by filename (which usually starts with domain or contains timestamp)
    files.sort()
    
    publisher = ArticlePublisher()
    notifier = TelegramNotifier(env)
    
    logger.info(f"[Re-publisher] Found {len(files)} unused articles to process.")
    
    success_count = 0
    fail_count = 0
    
    for filename in files:
        filepath = os.path.join(unused_dir, filename)
        logger.info(f"\n[Processing File] {filename}")
        
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            domain_key = data.get("site")
            generated_article = data.get("generated")
            image_url = data.get("image_url")
            image_credit = data.get("image_credit", "")
            
            if not domain_key or not generated_article:
                logger.warning(f"  [Skip] Invalid JSON structure in {filename}. Missing 'site' or 'generated'.")
                continue
                
            # Prepare image data object expected by publisher
            img_data = {
                "url": image_url,
                "credit": image_credit
            }
            
            # Extract source RSS link if available
            rss_link = generated_article.get("source_rss_link") or data.get("url")
            
            logger.info(f"  Domain: {domain_key}")
            logger.info(f"  Title: '{generated_article.get('title')}'")
            logger.info(f"  Category: '{generated_article.get('selected_category')}'")
            
            # Call Ingest API
            pub_response, err = publisher.publish_to_ingest_api(
                domain_key, generated_article, img_data, rss_link=rss_link
            )
            
            if err is None and pub_response:
                # Response matching
                a_id = pub_response.get("a_id") or pub_response.get("article_id")
                cms_url = pub_response.get("cms_url") or pub_response.get("url")
                
                logger.info(f"   [Re-publish SUCCESS] Admin/CMS registered successfully! ID: {a_id}")
                logger.info(f"   [Re-publish SUCCESS] URL: {cms_url}")
                
                # Move file to used/
                dest_path = os.path.join(used_dir, filename)
                shutil.move(filepath, dest_path)
                logger.info(f"   [File Moved] Moved {filename} to {dest_path}")
                
                # Send Telegram Success Notification
                pub_title = generated_article.get("title", "")
                pub_category = generated_article.get("selected_category", "")
                pub_summary = generated_article.get("summary", "")
                pub_tags = generated_article.get("seo_tags", "")
                
                # 1. Metadata Message
                meta_msg = (
                    f"<b>[로컬 기사 CMS 재송출 완료]</b>\n\n"
                    f"<b>■ 사이트명</b>\n"
                    f"<pre>{domain_key}</pre>\n\n\n"
                    f"<b>■ Title</b>\n"
                    f"<pre>{pub_title}</pre>\n\n\n"
                    f"<b>■ CMS URL</b>\n"
                    f"<pre>{cms_url}</pre>\n\n\n"
                    f"<b>■ Summary</b>\n"
                    f"<pre>{pub_summary}</pre>\n\n\n"
                    f"<b>■ 카테고리 (Category)</b>\n"
                    f"<pre>{pub_category}</pre>\n\n\n"
                    f"<b>■ 태그 (SEO Tags)</b>\n"
                    f"<pre>{pub_tags}</pre>"
                )
                notifier.send_notification(meta_msg)
                

                success_count += 1
            else:
                logger.error(f"   [Re-publish FAILED] Error: {err}")
                
                # Send Telegram Failure Notification
                pub_title = generated_article.get("title", "N/A")
                pub_category = generated_article.get("selected_category", "N/A")
                tg_msg = (
                    f"<b>[재송출 실패]</b>\n"
                    f"• 사이트명: {domain_key}\n"
                    f"• 기사명: {pub_title}\n"
                    f"• 카테고리: {pub_category}\n"
                    f"• 에러: <code>{err}</code>"
                )
                notifier.send_notification(tg_msg)
                
                fail_count += 1
                
        except Exception as file_err:
            logger.error(f"  [Error] Failed to process {filename}: {file_err}")
            fail_count += 1
            
    logger.info("\n==================================================")
    logger.info(f" Re-publishing Finished. Success: {success_count}, Fail: {fail_count}")
    logger.info("==================================================")

def update_cron_with_random_time():
    import random
    import subprocess
    
    # 미국 서머타임(EDT) 기준 09:00~18:00 = UTC 13:00~22:00
    # UTC 13시부터 22시 사이의 랜덤 시간(hour), 0분~59분 사이의 랜덤 분(minute)
    rand_hour = random.randint(13, 22)
    rand_minute = random.randint(0, 59)
    
    try:
        res = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        lines = res.stdout.splitlines()
        
        new_lines = []
        target_pattern = "publish_failed_unused_articles.py"
        found = False
        
        for line in lines:
            if target_pattern in line:
                # 새로운 랜덤 시간대 스케줄로 치환
                new_line = f"{rand_minute} {rand_hour} * * * cd /home/stock_trading_bot && /usr/bin/python3 publish_failed_unused_articles.py >> logs/republish_cron.log 2>&1"
                new_lines.append(new_line)
                found = True
            else:
                new_lines.append(line)
                
        if not found:
            new_line = f"{rand_minute} {rand_hour} * * * cd /home/stock_trading_bot && /usr/bin/python3 publish_failed_unused_articles.py >> logs/republish_cron.log 2>&1"
            new_lines.append(new_line)
            
        cron_content = "\n".join(new_lines) + "\n"
        subprocess.run(["crontab", "-"], input=cron_content, text=True)
        logger.info(f"[Cron-Scheduler] publish_failed_unused_articles.py 다음 예약 완료: UTC {rand_hour:02d}:{rand_minute:02d} (동부 EDT {rand_hour-4:02d}:{rand_minute:02d})")
    except Exception as e:
        logger.warning(f"[Cron-Scheduler] 크론탭 랜덤 갱신 실패: {e}")

if __name__ == "__main__":
    main()
    # 파이프라인 가동 완료 후 다음 날을 위한 동적 크론 시간 갱신 수행
    update_cron_with_random_time()
