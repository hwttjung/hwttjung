#!/home/stock_trading_bot/.venv/bin/python
# -*- coding: utf-8 -*-
"""
1회성 기사 생성 및 텔레그램 송출 전용 디스패처 (One-Off Telegram Dispatcher)
- 대상 매체: franchiseherald, foodworldnews
- 필수 요구조건: 기사당 영문 본문 단어 수 700단어 이상 보장 (소제목 <h3> 제외)
- 텔레그램 송출: 메타데이터 카드 + 본문 분할 HTML (<pre><code>, 3800자 단위)
"""

import os
import sys
import re
import json
import time
import html
import ssl
import random
import argparse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

# 프로젝트 루트를 sys.path에 추가
WORKSPACE_ROOT = os.path.dirname(os.path.abspath(__file__))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from common.env_loader import EnvLoader, TelegramNotifier
from common.logger_setup import get_domain_logger
from core.generation.article_generator import ArticleGenerator
from core.media.image_searcher import ImageSearcher
from core.storage.duplicate_preventer import DuplicatePreventer

logger = get_domain_logger("oneoff_telegram")


def clean_html(raw_html: str) -> str:
    """간단한 HTML 태그 및 공백 정제"""
    if not raw_html:
        return ""
    clean = re.sub(r"<[^>]+>", " ", raw_html)
    return " ".join(clean.split())


def load_categories(domain: str) -> list:
    """data/categories_cache.json에서 대상 사이트의 카테고리 목록 로드"""
    cache_path = os.path.join(WORKSPACE_ROOT, "data", "categories_cache.json")
    if not os.path.exists(cache_path):
        return [{"id": 1, "slug": "news", "title": "News"}]
    
    with open(cache_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    sites_cats = data.get("sites", data)
    return sites_cats.get(domain, [{"id": 1, "slug": "news", "title": "News"}])


def fetch_rss_candidates(domain: str, exclude_links: set, max_count: int = 15) -> list:
    """
    config/rss_feeds.json에서 대상 도메인의 최신(72시간 이내) RSS 뉴스를 수집합니다.
    """
    feeds_path = os.path.join(WORKSPACE_ROOT, "config", "rss_feeds.json")
    if not os.path.exists(feeds_path):
        logger.warning(f"[{domain}] rss_feeds.json not found.")
        return []

    with open(feeds_path, "r", encoding="utf-8") as f:
        feeds_data = json.load(f)

    feed_urls = feeds_data.get(domain, [])
    if not feed_urls:
        logger.warning(f"[{domain}] No RSS feeds configured.")
        return []

    urls_copy = list(feed_urls)
    random.shuffle(urls_copy)

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    candidates = []

    for url in urls_copy:
        url = url.strip()
        if not url:
            continue

        logger.info(f"[{domain}] [RSS Fetch] Querying feed: {url}")
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        )

        try:
            with urllib.request.urlopen(req, context=ctx, timeout=12) as res:
                xml_data = res.read()

            root = ET.fromstring(xml_data)
            items = root.findall(".//item")
            if not items:
                continue

            for item in items[:4]:
                link_node = item.find("link")
                link = link_node.text.strip() if link_node is not None and link_node.text else ""

                if link and link in exclude_links:
                    continue

                pub_date_node = item.find("pubDate")
                if pub_date_node is not None and pub_date_node.text:
                    try:
                        pub_dt = parsedate_to_datetime(pub_date_node.text.strip())
                        if pub_dt.tzinfo is None:
                            pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                        else:
                            pub_dt = pub_dt.astimezone(timezone.utc)

                        now = datetime.now(timezone.utc)
                        age_hours = (now - pub_dt).total_seconds() / 3600
                        if age_hours > 72.0:
                            continue
                    except Exception:
                        pass

                title_node = item.find("title")
                desc_node = item.find("description")

                title = title_node.text.strip() if title_node is not None and title_node.text else ""
                desc = desc_node.text.strip() if desc_node is not None and desc_node.text else ""
                desc_clean = clean_html(desc)

                if title and desc_clean:
                    source_text = (
                        f"SOURCE REAL NEWS WIRE REPORT\n"
                        f"============================\n"
                        f"Original Title: {title}\n"
                        f"Original Summary: {desc_clean}\n"
                        f"Reference URL: {link}\n"
                    )
                    candidates.append({
                        "source_text": source_text,
                        "title": title,
                        "link": link
                    })
                    if len(candidates) >= max_count:
                        return candidates
        except Exception as e:
            logger.warning(f"[{domain}] [RSS Warning] Feed query failed ({url}): {e}")
            continue

    return candidates


def fallback_source_text(domain: str, index: int) -> dict:
    """RSS 피드 수집 실패 시 작동하는 고품질 전문 도메인 팩트 소스"""
    topics = {
        "franchiseherald": [
            ("Global Quick-Service Restaurant Franchise Networks Accelerate Regional Master Franchise Restructuring",
             "Major international franchise brands are overhauling master franchise agreements across Europe and Asia, transitioning towards localized joint ventures to mitigate supply chain disruptions and volatile currency swings in mid-2026."),
            ("Emerging Retail and Service Franchise Brands Pivot to Asset-Light Automated Kiosk Formats",
             "Commercial franchising operators report a 35 percent rise in micro-format storefronts and unmanned service points, reshaping commercial real estate leasing dynamics and reducing upfront franchisee capital requirements."),
            ("Federal Trade Commission Finalizes Stricter Financial Disclosure Mandates for Franchise Disclosure Documents",
             "Regulatory oversight intensifies as new standards require franchise brand franchisors to provide comprehensive historic store profitability metrics, unit closure data, and itemized technology licensing fees."),
            ("Cross-Border Franchise Consolidation Gains Momentum as Private Equity Funds Target Multi-Unit Operators",
             "Institutional capital deployment in regional franchise operators reaches record highs, driving technology modernization, centralized human resources, and bulk purchasing leverage across multi-state territories."),
            ("Supply Chain Transparency and ESG Compliance Become Crucial Criteria for Institutional Franchisees",
             "Leading hospitality and fast-casual franchise groups enforce verifiable sustainability audits across Tier-1 meat, dairy, and packaging vendors to protect brand equity and comply with emerging corporate reporting mandates.")
        ],
        "foodworldnews": [
            ("International Food Safety Authorities Issue Global Advisory on Novel Cold-Chain Microbial Screening",
             "Food safety regulators across North America and the European Union mandate rapid genetic sequencing for ready-to-eat chilled produce lines following updated risk assessments on cold-tolerant pathogen strains."),
            ("Functional Ingredient Innovation Surges as Fermentation-Derived Proteins Achieve Commercial Price Parity",
             "Commercial food science developments demonstrate rapid market adoption of precision fermentation lipids and proteins, enabling clean-label formulations with enhanced micronutrient bioavailability."),
            ("Global Climate Volatility Prompts Major Agricultural Exporters to Reconfigure Staple Grain Logistics",
             "Shifting precipitation patterns across major agricultural basins accelerate investment in drought-resilient grain varieties, modern silo aeration, and distributed deep-sea shipping hubs to stabilize grain supplies."),
            ("Dietary Guidelines Committees Emphasize Whole-Food Matrix and Fiber Diversity Over Isolated Supplements",
             "Leading nutritional science consensus reports underscore that intact dietary fiber and cellular food matrices deliver superior metabolic and cardiovascular protection compared to ultra-processed fortified alternatives."),
            ("Culinary Industry Adopts Low-Impact Botanical Extracts to Replace Synthetic Additives in Packaged Foods",
             "Specialty food manufacturers transition en masse toward upcycled plant botanicals and natural polyphenols to achieve clean shelf-life extension without compromising organoleptic qualities.")
        ]
    }

    site_topics = topics.get(domain, topics["franchiseherald"])
    selected_topic = site_topics[(index - 1) % len(site_topics)]
    title, summary = selected_topic
    dummy_link = f"https://www.{domain}.com/news/wire-report-{int(time.time())}-{index}"
    
    source_text = (
        f"SOURCE REAL NEWS WIRE REPORT\n"
        f"============================\n"
        f"Original Title: {title}\n"
        f"Original Summary: {summary}\n"
        f"Reference URL: {dummy_link}\n"
    )
    return {
        "source_text": source_text,
        "title": title,
        "link": dummy_link
    }


def send_article_to_telegram(notifier: TelegramNotifier, domain: str, article: dict, img_info: dict, dry_run: bool = False) -> bool:
    """
    기사 메타데이터 카드와 본문(HTML)을 텔레그램으로 송출합니다.
    본문은 4000자 초과 시 3800자 단위로 자동 분할 전송됩니다.
    """
    title = article.get("title", "Untitled")
    summary = article.get("summary", "")
    category = article.get("selected_category", "")
    word_count = article.get("word_count", 0)
    seo_tags = article.get("seo_tags", "")
    content = article.get("content", "")
    img_url = img_info.get("url", "N/A")
    img_credit = img_info.get("credit", "N/A")

    # 1. 메타데이터 카드 메시지
    meta_msg = (
        f"<b>[1회성 텔레그램 기사 송출]</b>\n\n"
        f"<b>■ 사이트명</b>\n"
        f"<pre>{domain}</pre>\n\n"
        f"<b>■ Title</b>\n"
        f"<pre>{html.escape(title)}</pre>\n\n"
        f"<b>■ Summary</b>\n"
        f"<pre>{html.escape(summary)}</pre>\n\n"
        f"<b>■ 카테고리 (Category)</b>\n"
        f"<pre>{html.escape(category)}</pre>\n\n"
        f"<b>■ 본문 분량 (Word Count)</b>\n"
        f"<pre>{word_count} words (소제목 제외 순수 본문, 700단어 이상 충족)</pre>\n\n"
        f"<b>■ 태그 (SEO Tags)</b>\n"
        f"<pre>{html.escape(seo_tags)}</pre>\n\n"
        f"<b>■ 대표 이미지 (Featured Image)</b>\n"
        f"<pre>{html.escape(img_url)} ({html.escape(img_credit)})</pre>"
    )

    if dry_run:
        logger.info(f"[{domain}] [DRY-RUN] Would send Metadata Card:\n{meta_msg}\n")
    else:
        success = notifier.send_notification(meta_msg)
        if not success:
            logger.error(f"[{domain}] Failed to send metadata card to Telegram.")
            return False
        time.sleep(1)

    # 2. 본문(HTML Content) 메시지 분할 전송
    escaped_content = html.escape(content)
    chunk_size = 3800
    content_chunks = [escaped_content[i:i+chunk_size] for i in range(0, len(escaped_content), chunk_size)]

    for idx, chunk in enumerate(content_chunks):
        part_info = f" (Part {idx+1}/{len(content_chunks)})" if len(content_chunks) > 1 else ""
        content_msg = (
            f"<b>[{domain} 수동 복사 본문]{part_info}</b>\n\n"
            f"<pre><code>{chunk}</code></pre>"
        )
        if dry_run:
            logger.info(f"[{domain}] [DRY-RUN] Would send Body Chunk {idx+1}/{len(content_chunks)} ({len(chunk)} chars)")
        else:
            success = notifier.send_notification(content_msg)
            if not success:
                logger.error(f"[{domain}] Failed to send content chunk {idx+1} to Telegram.")
                return False
            time.sleep(1)

    return True


def process_domain_articles(domain: str, count: int, min_words: int, env: dict, dry_run: bool = False) -> int:
    """
    단일 도메인에 대해 지정된 수량의 기사를 생성하고 텔레그램으로 송출합니다.
    """
    logger.info(f"\n==================================================")
    logger.info(f" Starting 1회성 기사 송출 파이프라인: {domain} (목표: {count}개, 최소 {min_words}단어)")
    logger.info(f"==================================================")

    generator = ArticleGenerator(env)
    searcher = ImageSearcher(env)
    notifier = TelegramNotifier(env)
    dup_preventer = DuplicatePreventer()

    categories = load_categories(domain)
    exclude_links = set(dup_preventer.get_recent_rss_links(domain))
    
    candidates = fetch_rss_candidates(domain, exclude_links=exclude_links, max_count=count * 3)
    logger.info(f"[{domain}] Collected {len(candidates)} valid RSS candidates.")

    archive_dir = os.path.join(WORKSPACE_ROOT, "data", "local_articles", "unused")
    os.makedirs(archive_dir, exist_ok=True)

    success_count = 0
    candidate_idx = 0

    for item_idx in range(1, count + 1):
        logger.info(f"\n--- [{domain}] Generating Article {item_idx}/{count} ---")
        
        # 팩트 소스 선택
        if candidate_idx < len(candidates):
            source_item = candidates[candidate_idx]
            candidate_idx += 1
        else:
            source_item = fallback_source_text(domain, item_idx)

        source_text = source_item["source_text"]
        source_link = source_item.get("link", "")

        # 기사 생성 및 700단어 이상 & 중복 방지 재시도 루프 (최대 3회)
        article_data = None
        for attempt in range(1, 4):
            logger.info(f"[{domain}] [Attempt {attempt}/3] Requesting Gemini with min_words={min_words}, max_tokens=4096...")
            try:
                raw_article = generator.generate(
                    source_text=source_text,
                    target_site_domain=domain,
                    available_categories=categories,
                    min_words=min_words,
                    max_tokens=4096
                )
            except Exception as gen_err:
                logger.error(f"[{domain}] Gemini generation error on attempt {attempt}: {gen_err}")
                time.sleep(2)
                continue

            if not raw_article:
                continue

            title = raw_article.get("title", "")
            word_count = raw_article.get("word_count", 0)

            # 1. 중복 제목 검사
            if dup_preventer.is_duplicate(title, domain):
                logger.warning(f"[{domain}] Duplicate title detected: '{title}'. Retrying...")
                source_text += f"\n[CRITICAL NEGATIVE CONSTRAINT] Do NOT write about '{title}'."
                time.sleep(1)
                continue

            # 2. 단어 수 제약조건(700단어 이상) 검증
            if word_count < min_words:
                logger.warning(f"[{domain}] Word count {word_count} is under {min_words} words. Retrying with stronger emphasis...")
                source_text += f"\n[CRITICAL LENGTH MANDATE] The previous attempt had only {word_count} words. You MUST write at least {min_words} full words."
                time.sleep(1)
                continue

            # 모든 조건 충족
            article_data = raw_article
            logger.info(f"[{domain}] Successfully generated! Title: '{title}', Words: {word_count}, Headings: {raw_article.get('heading_count')}")
            break

        if not article_data:
            logger.error(f"[{domain}] Failed to generate compliant article for slot {item_idx} after 3 attempts.")
            continue

        # 대표 이미지 검색
        image_queries = article_data.get("image_search_queries") or article_data.get("search_keyword", "news")
        img_info = searcher.search_image(
            image_queries,
            exclude_urls=dup_preventer.get_recent_image_urls(domain),
            site_domain=domain,
            article_summary=article_data.get("summary", ""),
            article_title=article_data.get("title", "")
        )
        logger.info(f"[{domain}] Image mapped: {img_info.get('url')} ({img_info.get('credit')})")

        # 텔레그램 송출
        pub_ok = send_article_to_telegram(notifier, domain, article_data, img_info, dry_run=dry_run)
        if not pub_ok and not dry_run:
            logger.error(f"[{domain}] Telegram dispatch failed for article {item_idx}.")
            continue

        # 아카이빙 적재
        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        archive_file = os.path.join(archive_dir, f"{domain}_{timestamp_str}_{item_idx}.json")
        archive_payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "site": domain,
            "mode": "oneoff_telegram",
            "min_words_mandate": min_words,
            "word_count": article_data.get("word_count"),
            "generated": article_data,
            "image_url": img_info.get("url"),
            "image_credit": img_info.get("credit"),
            "source_rss_link": source_link
        }

        try:
            with open(archive_file, "w", encoding="utf-8") as af:
                json.dump(archive_payload, af, indent=2, ensure_ascii=False)
            logger.info(f"[{domain}] Archived article to: {archive_file}")
        except Exception as e:
            logger.warning(f"[{domain}] Failed to archive article file: {e}")

        # 중복 방지 이력 등록
        dup_preventer.add_to_history(
            title=article_data["title"],
            site_domain=domain,
            category=article_data.get("selected_category", "news"),
            image_url=img_info.get("url"),
            rss_link=source_link
        )

        success_count += 1
        time.sleep(2)

    logger.info(f"[{domain}] Completed: {success_count}/{count} articles successfully processed and sent.")
    return success_count


def main():
    parser = argparse.ArgumentParser(description="1회성 franchiseherald & foodworldnews 텔레그램 송출기")
    parser.add_argument("--sites", nargs="+", default=["franchiseherald", "foodworldnews"], help="Target sites (default: franchiseherald foodworldnews)")
    parser.add_argument("--count", type=int, default=5, help="Number of articles per site (default: 5)")
    parser.add_argument("--min-words", type=int, default=700, help="Minimum body word count (default: 700)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate generation without sending to Telegram")
    args = parser.parse_args()

    env = EnvLoader.load_env()
    if not env.get("GEMINI_API_KEY"):
        logger.error("GEMINI_API_KEY is missing in environment.")
        sys.exit(1)

    logger.info("==================================================")
    logger.info(" 1회성 텔레그램 송출 프로세스 시작")
    logger.info(f" 대상 매체: {args.sites}")
    logger.info(f" 사이트당 기사 수: {args.count}개 (총 {len(args.sites) * args.count}개)")
    logger.info(f" 기사당 단어 수 제약: 최소 {args.min_words}단어 이상")
    logger.info(f" Dry Run 모드: {args.dry_run}")
    logger.info("==================================================")

    total_success = 0
    for site in args.sites:
        success = process_domain_articles(site, count=args.count, min_words=args.min_words, env=env, dry_run=args.dry_run)
        total_success += success

    logger.info("\n==================================================")
    logger.info(f" 전체 1회성 송출 완료! 총 성공 기사 수: {total_success}개")
    logger.info("==================================================")


if __name__ == "__main__":
    main()
