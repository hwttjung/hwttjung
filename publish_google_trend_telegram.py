#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Trends RSS 기반 실시간 영어 기사(600단어 이하, 팩트체크 완료) 텔레그램 송출 오케스트레이터
- 소스: https://trends.google.co.kr/trending/rss?geo=US
- 일일 3건 선별 및 텔레그램 직송
- Gemini Google Search Grounding 기반 팩트체크 검증
"""

import os
import sys
import re
import json
import time
import html
import argparse
from datetime import datetime, timezone, timedelta

# 기본 컴포넌트 임포트
from common.env_loader import EnvLoader, TelegramNotifier
from core.generation.article_generator import ArticleGenerator
from core.media.image_searcher import ImageSearcher
from core.generation.fact_checker import verify_article_facts
from core.ingestion.trend_analyzer import fetch_google_trends_detailed, fetch_trend_news_body
from common.logger_setup import get_domain_logger

logger = get_domain_logger("google_trend_telegram")

ARCHIVE_DIR = "data/archive/google_trends"

def is_stop_publishing_active(env):
    """STOP_GOOGLE_TREND 전용 긴급 중단 플래그 검사 (14개 사이트용 STOP_PUBLISHING과 독립)"""
    if env.get("STOP_GOOGLE_TREND", "False").strip().lower() in ("true", "1", "yes"):
        return True
    status_file = "config/status.json"
    if os.path.exists(status_file):
        try:
            with open(status_file, "r", encoding="utf-8") as sf:
                data = json.load(sf)
                if data.get("STOP_GOOGLE_TREND") is True:
                    return True
        except Exception as e:
            logger.warning(f"[Warning] Failed to read status file: {e}")
    return False

def get_used_trend_queries(days=7):
    """최근 N일간 이미 송출된 트렌드 검색어 목록 반환"""
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    used_queries = set()
    now = datetime.now(timezone.utc)
    
    for fname in os.listdir(ARCHIVE_DIR):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(ARCHIVE_DIR, fname)
        try:
            # 파일명 형식: YYYY-MM-DD.json
            date_str = fname.replace(".json", "")
            fdate = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if (now - fdate).days <= days:
                with open(fpath, "r", encoding="utf-8") as f:
                    day_data = json.load(f)
                    for item in day_data:
                        q = item.get("trend_query", "").strip().lower()
                        if q:
                            used_queries.add(q)
        except Exception as e:
            logger.warning(f"Error reading archive file {fname}: {e}")
            
    return used_queries

def save_trend_archive(record):
    """송출 완료된 기사 기록을 아카이브에 영구 저장"""
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    today_str = datetime.now().strftime("%Y-%m-%d")
    archive_file = os.path.join(ARCHIVE_DIR, f"{today_str}.json")
    
    existing = []
    if os.path.exists(archive_file):
        try:
            with open(archive_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = []
            
    existing.append(record)
    with open(archive_file, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved trend article record to {archive_file}")

def send_telegram_article(notifier, trend_item, generated_article, img_info=None):
    """
    텔레그램 창으로 1) 메타데이터 카드, 2) 본문 내용을 안전하게 분할 송출합니다.
    """
    query = trend_item.get("query", "")
    traffic = trend_item.get("traffic", "N/A")
    title = generated_article.get("title", "")
    summary = generated_article.get("summary", "")
    category = generated_article.get("category", "General")
    seo_tags = generated_article.get("seo_tags", "")
    word_count = generated_article.get("word_count", 0)
    raw_content = generated_article.get("content", "")
    
    # 1. 원천 뉴스 출처 정보 구성
    source_links = []
    for n in trend_item.get("news_items", [])[:2]:
        s_title = html.escape(n.get("title", ""))
        s_src = html.escape(n.get("source", "News"))
        s_url = n.get("url", "")
        if s_url:
            source_links.append(f"• <a href='{s_url}'>{s_src}</a>: {s_title}")
        else:
            source_links.append(f"• {s_src}: {s_title}")
    source_str = "\n".join(source_links) if source_links else "• Google Trends Live Anchor"
    
    # 이미지 링크 정보
    img_url = img_info.get("url", "") if img_info else ""
    img_credit = img_info.get("photographer", "") if img_info else ""
    img_str = f"\n<b>■ 대표 이미지:</b> <a href='{img_url}'>View Image</a> (Photo by {html.escape(img_credit)})" if img_url else ""
    
    # [메시지 1] 메타데이터 요약 카드
    meta_msg = (
        f"🔥 <b>[실시간 구글 트렌드 영어 뉴스]</b>\n\n"
        f"<b>■ 트렌드 검색어:</b> <code>{html.escape(query)}</code> (트래픽: {traffic})\n"
        f"<b>■ 카테고리:</b> {html.escape(category)}\n"
        f"<b>■ 기사 제목:</b>\n<b>{html.escape(title)}</b>\n\n"
        f"<b>■ 기사 요약:</b>\n{html.escape(summary)}\n\n"
        f"<b>■ 본문 분량:</b> {word_count} words (600단어 이하 규격 준수)\n"
        f"<b>■ SEO 태그:</b> <code>{html.escape(seo_tags)}</code>{img_str}\n\n"
        f"<b>■ 관련 팩트 출처:</b>\n{source_str}\n\n"
        f"✅ <b>사실 검증:</b> Gemini Search Grounding 팩트체크 완료"
    )
    
    success_meta = notifier.send_notification(meta_msg)
    time.sleep(1.5) # 메시지 전송 간격 안전 딜레이
    
    # [메시지 2] 본문 전문 송출 (HTML pre/code 포맷팅)
    escaped_content = html.escape(raw_content)
    chunk_size = 3800
    chunks = [escaped_content[i:i+chunk_size] for i in range(0, len(escaped_content), chunk_size)]
    
    success_content = True
    for idx, chunk in enumerate(chunks):
        part_info = f" (Part {idx+1}/{len(chunks)})" if len(chunks) > 1 else ""
        content_msg = (
            f"📰 <b>[기사 본문 - {html.escape(query)}]{part_info}</b>\n\n"
            f"<pre><code>{chunk}</code></pre>"
        )
        s = notifier.send_notification(content_msg)
        if not s:
            success_content = False
        time.sleep(1.2)
        
    return success_meta and success_content

def process_single_trend(trend_item, env, generator, notifier, image_searcher, dry_run=False):
    """
    단일 트렌드에 대해 팩트 수집 → 600단어 이하 기사 생성 → 팩트체크 → 텔레그램 송출을 수행합니다.
    """
    query = trend_item.get("query", "")
    traffic = trend_item.get("traffic", "N/A")
    news_items = trend_item.get("news_items", [])
    
    logger.info(f"\n{'='*60}\n▶ [트렌드 처리 시작] 검색어: '{query}' (트래픽: {traffic})\n{'='*60}")
    
    # 1. 관련 뉴스 헤드라인 및 본문 팩트 크롤링
    news_headlines = []
    crawled_texts = []
    
    for n in news_items[:3]:
        n_title = n.get("title", "")
        n_src = n.get("source", "")
        n_url = n.get("url", "")
        n_snippet = n.get("snippet", "")
        
        news_headlines.append(f"- [{n_src}] {n_title} {f'({n_snippet})' if n_snippet else ''}")
        if n_url and len(crawled_texts) < 2:
            body = fetch_trend_news_body(n_url, timeout=8)
            if body:
                crawled_texts.append(f"[Source: {n_src} / {n_title}]\n{body}")
                
    news_context = "\n".join(news_headlines)
    raw_fact_text = "\n\n".join(crawled_texts) if crawled_texts else "General news reports confirm widespread real-time discussion and public interest in this topic."
    
    # 2. 기사 생성 및 팩트체크 루프 (최대 3회 재시도)
    max_retries = 3
    final_article = None
    
    for attempt in range(1, max_retries + 1):
        logger.info(f"[{query}] 기사 생성 시도 ({attempt}/{max_retries})...")
        try:
            article_data = generator.generate_concise_trend_article(
                trend_keyword=query,
                traffic_val=traffic,
                news_context=news_context,
                raw_fact_text=raw_fact_text
            )
            
            word_count = article_data.get("word_count", 0)
            logger.info(f"[{query}] 기사 생성 완료 (단어 수: {word_count}단어)")
            
            # 단어 수 초과 검사 (600단어 이하)
            if word_count > 600:
                logger.warning(f"[{query}] 단어 수 초과 ({word_count} > 600단어). 재시도합니다.")
                continue
                
            # 3. 팩트체크 검증 (Gemini Google Search Grounding)
            logger.info(f"[{query}] Gemini Search Grounding 기반 팩트체크 검증 수행 중...")
            combined_source = f"Trend Query: {query} (Traffic: {traffic})\n\nNews Headlines:\n{news_context}\n\nFacts:\n{raw_fact_text}"
            
            api_key = env.get("GEMINI_API_KEY")
            is_valid = verify_article_facts(
                api_key=api_key,
                source_text=combined_source,
                generated_content=article_data.get("content", ""),
                target_site_domain="GoogleTrends",
                trend_report={"seed_keyword": query, "traffic": traffic}
            )
            
            if is_valid:
                logger.info(f"[{query}] ✅ 팩트체크 검증 완벽 통과!")
                final_article = article_data
                break
            else:
                logger.warning(f"[{query}] ⚠️ 팩트체크 불합격 (왜곡 또는 출처 미흡). 재시도 중...")
                time.sleep(2)
        except Exception as e:
            logger.error(f"[{query}] 기사 생성/검증 중 오류: {e}")
            time.sleep(2)
            
    if not final_article:
        logger.error(f"[{query}] {max_retries}회 시도 후에도 기사 생성/팩트체크에 실패했습니다.")
        return False
        
    # 4. 대표 이미지 검색
    search_kw = final_article.get("search_keyword") or query
    img_info = None
    try:
        img_info = image_searcher.search_image(search_kw)
    except Exception as img_err:
        logger.warning(f"[{query}] 이미지 검색 실패: {img_err}")
        
    # 5. 텔레그램 송출 또는 Dry-run
    if dry_run:
        logger.info(f"[{query}] [DRY-RUN] 텔레그램 전송 생략 (제목: {final_article.get('title')}, 단어수: {final_article.get('word_count')})")
        return True
        
    logger.info(f"[{query}] 텔레그램 창으로 기사 송출 중...")
    published_ok = send_telegram_article(notifier, trend_item, final_article, img_info)
    
    if published_ok:
        logger.info(f"[{query}] 🎉 텔레그램 송출 성공!")
        # 아카이브 저장
        record = {
            "trend_query": query,
            "traffic": traffic,
            "title": final_article.get("title"),
            "category": final_article.get("category"),
            "word_count": final_article.get("word_count"),
            "seo_tags": final_article.get("seo_tags"),
            "published_at": datetime.now(timezone.utc).isoformat(),
            "status": "published"
        }
        save_trend_archive(record)
        return True
    else:
        logger.error(f"[{query}] 텔레그램 송출 실패")
        return False

def run_pipeline(target_count=3, dry_run=False):
    """
    구글 트렌드 RSS 기반 일일 트렌드 영어 기사 송출 파이프라인
    """
    env = EnvLoader.load_env()
    
    # 긴급 차단 플래그 검사
    if is_stop_publishing_active(env):
        logger.warning("[STOP_PUBLISHING] 긴급 차단 플래그가 활성화되어 있어 파이프라인을 종료합니다.")
        return
        
    notifier = TelegramNotifier(env)
    generator = ArticleGenerator(env)
    image_searcher = ImageSearcher(env)
    
    logger.info("==================================================")
    logger.info(f" 실시간 구글 트렌드 영어 뉴스 송출 시작 (목표: {target_count}건)")
    logger.info("==================================================")
    
    # 1. 구글 트렌드 피드 수집
    trends = fetch_google_trends_detailed(geo="US", max_items=20)
    if not trends:
        logger.error("구글 트렌드 RSS 피드 수집 실패. 파이프라인을 중단합니다.")
        return
        
    # 2. 최근 7일 중복 트렌드 필터링
    used_queries = get_used_trend_queries(days=7)
    logger.info(f"최근 7일간 사용된 트렌드 검색어 ({len(used_queries)}개 로드 완료)")
    
    selected_trends = []
    for t in trends:
        q_lower = t["query"].strip().lower()
        if q_lower not in used_queries:
            selected_trends.append(t)
            if len(selected_trends) >= target_count:
                break
        else:
            logger.info(f"중복 트렌드 스킵: '{t['query']}'")
            
    if not selected_trends:
        logger.warning("가용한 신규 트렌드 항목이 없습니다. (모두 최근 사용됨)")
        return
        
    logger.info(f"선별된 신규 트렌드 ({len(selected_trends)}건): {[t['query'] for t in selected_trends]}")
    
    success_count = 0
    for idx, trend_item in enumerate(selected_trends, 1):
        # 송출 도중 STOP_PUBLISHING 감지
        if is_stop_publishing_active(env):
            logger.warning("[STOP_PUBLISHING] 실행 중단 신호 감지됨. 즉시 중단합니다.")
            break
            
        ok = process_single_trend(trend_item, env, generator, notifier, image_searcher, dry_run=dry_run)
        if ok:
            success_count += 1
            
        if idx < len(selected_trends):
            time.sleep(3) # 다음 기사 처리 전 짧은 휴식
            
    logger.info(f"\n[완료] 총 {len(selected_trends)}개 중 {success_count}건 송출 완료.")
    
    if not dry_run and success_count > 0:
        # 일일 송출 완료 요약 알림
        summary_msg = (
            f"🏁 <b>[구글 트렌드 실시간 뉴스 송출 완료]</b>\n"
            f"• 금일 총 송출: <b>{success_count}건</b>\n"
            f"• 송출 대상 검색어: {', '.join([t['query'] for t in selected_trends[:success_count]])}\n"
            f"• 규격: 600단어 이하 영문 심층 기사 / 팩트체크 검증 완료"
        )
        notifier.send_notification(summary_msg)

def main():
    parser = argparse.ArgumentParser(description="실시간 구글 트렌드 600단어 이하 팩트체크 영어 기사 텔레그램 송출기")
    parser.add_argument("--count", type=int, default=3, help="송출할 기사 개수 (기본 3개)")
    parser.add_argument("--now", action="store_true", help="즉시 3개 기사 송출")
    parser.add_argument("--dry-run", action="store_true", help="텔레그램 전송 없이 생성 및 팩트체크만 테스트")
    args = parser.parse_args()
    
    target_count = args.count if not args.now else 3
    run_pipeline(target_count=target_count, dry_run=args.dry_run)

if __name__ == "__main__":
    main()
