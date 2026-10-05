#!/home/stock_trading_bot/.venv/bin/python
# -*- coding: utf-8 -*-
"""
Daily Travel Article Telegram Dispatcher & State Tracker
Dispatches 10 distinct, non-duplicated city travel articles daily across 7,000-article pool.
"""

import os
import sys
import json
import time
import html
import argparse
from datetime import datetime, timezone

# Ensure project root is in sys.path
WORKSPACE_ROOT = os.path.dirname(os.path.abspath(__file__))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from common.env_loader import EnvLoader, TelegramNotifier
from core.media.image_searcher import ImageSearcher
from core.generation.travel_article_generator import TravelArticleGenerator
from common.logger_setup import get_domain_logger

logger = get_domain_logger("travel_pipeline")

STATE_FILE = os.path.join(WORKSPACE_ROOT, "data", "travel_pool_state.json")
CITIES_FILE = os.path.join(WORKSPACE_ROOT, "data", "world_cities_1000.json")
ARCHIVE_DIR = os.path.join(WORKSPACE_ROOT, "data", "archive", "travel_articles")

def load_json(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(filepath, data):
    temp_path = filepath + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(temp_path, filepath)

def get_next_jobs(state, cities, count=10):
    """
    Select the next batch of distinct cities for today's dispatch.
    Ensures 0% city duplication within the batch.
    """
    total_cities = len(cities)
    current_theme_idx = state.get("current_theme_index", 0)
    start_rank = state.get("next_city_rank", 1)
    
    jobs = []
    curr_rank = start_rank
    curr_theme_idx = current_theme_idx
    
    for _ in range(count):
        if curr_rank > total_cities:
            curr_rank = 1
            curr_theme_idx = (curr_theme_idx + 1) % len(state["themes"])
            
        city_item = cities[curr_rank - 1]
        theme_item = state["themes"][curr_theme_idx]
        
        jobs.append({
            "city": city_item,
            "theme": theme_item,
            "rank": curr_rank,
            "theme_idx": curr_theme_idx
        })
        curr_rank += 1
        
    return jobs

def format_telegram_messages(article_data, img_info):
    """
    Format metadata card (Message 1) and full body (Message 2).
    """
    img_url = img_info.get("url", "")
    img_credit = img_info.get("credit", "Unsplash/Pexels")
    img_str = f"\n<b>■ 대표 이미지:</b> <a href='{img_url}'>View High-Res Photo</a> ({html.escape(img_credit)})" if img_url else ""
    
    meta_msg = (
        f"🌍 <b>[Global Travel Guide #{article_data.get('city_rank', 'N/A')}]</b>\n\n"
        f"<b>■ 목적지:</b> {html.escape(article_data['city'])}\n"
        f"<b>■ 테마:</b> {html.escape(article_data['theme_name'])}\n"
        f"<b>■ 기사 제목:</b>\n<b>{html.escape(article_data['title'])}</b>\n\n"
        f"<b>■ 기사 요약:</b>\n{html.escape(article_data['summary'])}\n\n"
        f"<b>■ 본문 분량:</b> {article_data['word_count']} words (저널리즘 3단 구성)\n"
        f"<b>■ 검증 장소/명소:</b> {len(article_data.get('verified_entities', []))}개 실존 명소 확인\n"
        f"<b>■ SEO 태그:</b> <code>{html.escape(article_data['seo_tags'])}</code>{img_str}\n\n"
        f"✅ <b>사실 검증:</b> {article_data['fact_check_status']} ({article_data['fact_check_method']})"
    )
    
    body_content = article_data["content"]
    escaped_content = html.escape(body_content)
    body_msg = f"<pre><code>{escaped_content}</code></pre>"
    
    return meta_msg, body_msg

def main():
    parser = argparse.ArgumentParser(description="Daily Travel Articles Pipeline")
    parser.add_argument("--count", type=int, default=10, help="Number of articles to dispatch today (default 10)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate generation and check without sending Telegram or saving state")
    parser.add_argument("--status", action="store_true", help="Print current progress of the 7,000-article pool")
    parser.add_argument("--now", action="store_true", help="Execute immediately without safety prompt")
    args = parser.parse_args()

    env = EnvLoader.load_env()
    state = load_json(STATE_FILE)
    cities = load_json(CITIES_FILE)
    
    os.makedirs(ARCHIVE_DIR, exist_ok=True)

    if args.status:
        completed = state.get("completed_articles_count", 0)
        total = state.get("total_pool_size", 7000)
        pct = (completed / total) * 100 if total > 0 else 0
        print("=" * 60)
        print("📊 [전세계 1,000개 도시 X 7대 테마 여행 기사 풀 진행 현황]")
        print("=" * 60)
        print(f"- 전체 목표 풀: {total:,}개 기사")
        print(f"- 현재 완료 수: {completed:,}개 ({pct:.2f}%)")
        print(f"- 남은 기사 수: {total - completed:,}개")
        print(f"- 현재 진행 사이클: Cycle {state.get('current_cycle', 1)} / 7")
        print(f"- 현재 테마: {state.get('current_theme_code')} ({state['themes'][state.get('current_theme_index', 0)]['name']})")
        print(f"- 다음 차례 도시 순번: Rank #{state.get('next_city_rank', 1)} ({cities[state.get('next_city_rank', 1)-1]['city_en']})")
        print(f"- 최근 가동 일시: {state.get('last_run_timestamp') or '없음'}")
        print("=" * 60)
        return

    print(f"\n🚀 [Daily Travel Articles Pipeline] Starting dispatch for {args.count} cities...")
    if args.dry_run:
        print("⚠️ [DRY-RUN MODE ACTIVATED]: No Telegram messages will be sent, state file will not be updated.\n")

    notifier = TelegramNotifier(env)
    searcher = ImageSearcher(env)
    generator = TravelArticleGenerator(env)

    jobs = get_next_jobs(state, cities, count=args.count)
    print(f"📋 오늘 선정된 {len(jobs)}개 도시 (중복 0%):")
    for i, job in enumerate(jobs, 1):
        print(f"  {i}. [Rank #{job['rank']}] {job['city']['city_en']} ({job['city']['country_ko']}) - Theme: {job['theme']['code']}")
    print("-" * 60)

    success_count = 0
    today_records = []

    for idx, job in enumerate(jobs, 1):
        city_item = job["city"]
        theme_item = job["theme"]
        city_en = city_item["city_en"]
        theme_code = theme_item["code"]
        
        print(f"\n▶ [{idx}/{len(jobs)}] 기사 집필 시작: {city_en} ({city_item['country_en']}) | 테마: {theme_item['name']}")
        try:
            article_data = generator.generate_travel_article(city_item, theme_code)
            article_data["city_rank"] = job["rank"]
            print(f"  ✓ 기사 집필 완료: \"{article_data['title']}\" ({article_data['word_count']} words)")
            
            search_query = article_data.get("search_keyword") or f"{city_en} landmark view"
            print(f"  ✓ 고화질 대표 썸네일 검색 중... (검색어: '{search_query}')")
            img_info = searcher.search_image(search_query, site_domain="general")
            article_data["image"] = img_info
            print(f"    - 매핑 이미지: {img_info.get('url')} ({img_info.get('credit')})")
            
            if not args.dry_run:
                meta_msg, body_msg = format_telegram_messages(article_data, img_info)
                
                print("  ✓ [텔레그램 1/2] 메타데이터 요약 카드 발송 중...")
                notifier.send_notification(meta_msg)
                time.sleep(1.5)
                
                print("  ✓ [텔레그램 2/2] HTML 본문 전문 발송 중...")
                if len(body_msg) > 3800:
                    chunks = [body_msg[i:i+3800] for i in range(0, len(body_msg), 3800)]
                    for chunk in chunks:
                        notifier.send_notification(chunk)
                        time.sleep(1.0)
                else:
                    notifier.send_notification(body_msg)
                    
                print("  ✓ 텔레그램 발송 성공!")
            else:
                print("  [Dry-Run] 텔레그램 발송 스킵.")

            now_iso = datetime.now(timezone.utc).isoformat()
            article_data["published_at"] = now_iso
            article_data["status"] = "dry_run" if args.dry_run else "published_to_telegram"
            
            today_str = datetime.now().strftime("%Y-%m-%d")
            city_slug = city_en.lower().replace(" ", "_").replace("'", "")
            filename = f"{today_str}_{job['rank']:04d}_{city_slug}_{theme_code}.json"
            archive_path = os.path.join(ARCHIVE_DIR, filename)
            
            if not args.dry_run:
                save_json(archive_path, article_data)
                print(f"  ✓ 아카이브 저장 완료: {archive_path}")
            
            success_count += 1
            today_records.append({
                "rank": job["rank"],
                "city": city_en,
                "country": city_item["country_en"],
                "theme": theme_code,
                "title": article_data["title"],
                "word_count": article_data["word_count"],
                "timestamp": now_iso
            })

            if idx < len(jobs):
                time.sleep(3.0)

        except Exception as e:
            print(f"  ❌ [{city_en}] 기사 생성/송출 중 오류 발생: {e}")
            logger.error(f"Error processing {city_en}: {e}", exc_info=True)

    print("\n" + "=" * 60)
    print(f"🎉 [작업 완료 보고] 총 {len(jobs)}개 중 {success_count}개 기사 처리 성공!")
    print("=" * 60)

    if not args.dry_run and success_count > 0:
        last_job = jobs[success_count - 1]
        next_rank = last_job["rank"] + 1
        curr_theme_idx = last_job["theme_idx"]
        
        if next_rank > len(cities):
            next_rank = 1
            curr_theme_idx = (curr_theme_idx + 1) % len(state["themes"])
            state["current_cycle"] = state.get("current_cycle", 1) + 1
            
        state["next_city_rank"] = next_rank
        state["current_theme_index"] = curr_theme_idx
        state["current_theme_code"] = state["themes"][curr_theme_idx]["code"]
        state["completed_articles_count"] = state.get("completed_articles_count", 0) + success_count
        state["last_run_timestamp"] = datetime.now(timezone.utc).isoformat()
        
        if "history" not in state:
            state["history"] = []
        state["history"].append({
            "run_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "dispatched_count": success_count,
            "dispatched_cities": [r["city"] for r in today_records]
        })
        state["history"] = state["history"][-50:]
        
        save_json(STATE_FILE, state)
        print(f"💾 진행 상태 갱신 완료: 총 완료 누계 {state['completed_articles_count']}개, 다음 순번 City #{next_rank}")

if __name__ == "__main__":
    main()
