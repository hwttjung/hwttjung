#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
publish_medicaldaily_cron.py
의약일보(medicaldaily.co.kr) 전용 1일 50개 분산 기사 생성 및 자동 송출 배치 스크립트.
- 허용 시간대: 한국시간(KST) 08:00:00 ~ 18:59:59 (08시~19시)
- 일일 송출 쿼터: 50개
- 송출 모드: publish (정식 즉시 발행)
- 권장 크론 설정: */13 23,0-9 * * * (UTC 23:00~09:59 = KST 08:00~18:59, 약 13분 간격)
"""

import os
import sys
import json
import random
import argparse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from common.logger_setup import get_domain_logger
from common.env_loader import EnvLoader
from core.storage.duplicate_preventer import DuplicatePreventer
from core.ingestion.clicky_puller import get_medicaldaily_clicky_keywords, fetch_clicky_matched_rss_source
from main import run_pipeline

logger = get_domain_logger("medicaldaily")

def is_within_kst_operating_hours(env, override_time=None):
    """현재 KST 시각이 의약일보 송출 허용 시간대(08:00 ~ 19:00 이전)인지 검증합니다."""
    kst = timezone(timedelta(hours=9))
    now_kst = override_time if override_time is not None else datetime.now(kst)
    start_hour = int(env.get("MEDICALDAILY_START_HOUR_KST", "8"))
    end_hour = int(env.get("MEDICALDAILY_END_HOUR_KST", "19"))
    return start_hour <= now_kst.hour < end_hour, now_kst, start_hour, end_hour

def fetch_medicaldaily_wire_source(env):
    """config/rss_feeds.json에서 medicaldaily 피드 중 최근 7일 내 미사용된 신선한 RSS 기사를 추출합니다."""
    feeds_file = "config/rss_feeds.json"
    if not os.path.exists(feeds_file):
        logger.error("[Error] config/rss_feeds.json not found.")
        return None

    try:
        with open(feeds_file, "r", encoding="utf-8") as f:
            all_feeds = json.load(f)
    except Exception as e:
        logger.error(f"[Error] Failed to load config/rss_feeds.json: {e}")
        return None

    medi_feeds = all_feeds.get("medicaldaily", [])
    if not medi_feeds:
        logger.error("[Error] No medicaldaily RSS feeds found in config/rss_feeds.json.")
        return None

    random.shuffle(medi_feeds)
    preventer = DuplicatePreventer()
    used_links = preventer.get_recent_rss_links("medicaldaily")

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    for feed_url in medi_feeds:
        try:
            req = urllib.request.Request(feed_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                xml_data = resp.read()
            root = ET.fromstring(xml_data)
            items = root.findall(".//item")
            if not items:
                items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

            for item in items[:15]:
                title_elem = item.find("title") or item.find("{http://www.w3.org/2005/Atom}title")
                link_elem = item.find("link") or item.find("{http://www.w3.org/2005/Atom}link")
                desc_elem = item.find("description") or item.find("{http://www.w3.org/2005/Atom}summary")

                title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
                if link_elem is not None:
                    link = link_elem.get("href") or link_elem.text or ""
                    link = link.strip()
                else:
                    link = ""
                desc = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ""

                if not title or not link:
                    continue

                if link in used_links:
                    continue

                payload = (
                    f"SOURCE REAL NEWS WIRE REPORT\n"
                    f"============================\n"
                    f"Original Title: {title}\n"
                    f"Original Summary: {desc}\n"
                    f"Reference URL: {link}\n"
                    f"============================\n"
                    f"Please write a high quality article based on the facts and guidelines above."
                )
                return payload, link, title
        except Exception as e:
            logger.debug(f"[RSS Fetch] Failed to fetch {feed_url}: {e}")
            continue

    logger.warning("[Warning] No unused RSS source found in medicaldaily feeds.")
    return None

def main():
    parser = argparse.ArgumentParser(description="MedicalDaily 1일 50개 분산 기사 생성 및 자동 송출 배치 스크립트")
    parser.add_argument("--dry-run", action="store_true", help="실제 생성/송출 없이 시간대 및 설정만 검증합니다.")
    parser.add_argument("--ignore-time-window", action="store_true", help="KST 08:00~19:00 시간 가드레일을 무시하고 강제 실행합니다.")
    parser.add_argument("--clicky", action="store_true", help="Clicky 독자 관심 키워드 기반으로 기사를 작성합니다 (주어진 RSS 기반 매칭).")
    args = parser.parse_args()

    env = EnvLoader.load_env()

    # 1. 시간대 가드레일 검사
    is_allowed, now_kst, start_hour, end_hour = is_within_kst_operating_hours(env)
    if not is_allowed and not args.ignore_time_window:
        logger.info(
            f"[Operating Hours] Current KST is {now_kst.strftime('%H:%M:%S')}. "
            f"Outside operating hours ({start_hour:02d}:00~{end_hour:02d}:00 KST). Execution skipped."
        )
        return

    # 2. 일일 쿼터 사전 점검
    preventer = DuplicatePreventer()
    with preventer._lock():
        history = preventer._load_history()
    medi_history = history.get("medicaldaily", [])
    today_kst_str = now_kst.strftime("%Y-%m-%d")
    today_count = sum(1 for item in medi_history if item.get("date") == today_kst_str)
    today_life = sum(1 for item in medi_history if item.get("date") == today_kst_str and item.get("category") == "라이프")
    life_ratio_pct = round((today_life / today_count * 100), 1) if today_count > 0 else 0.0
    daily_limit = int(env.get("MEDICALDAILY_DAILY_LIMIT", "50"))

    if today_count >= daily_limit:
        logger.info(
            f"[Daily Limit Reached] MedicalDaily already published {today_count}/{daily_limit} articles today ({today_kst_str} KST). Execution skipped."
        )
        return

    logger.info(
        f"[MedicalDaily Batch Start] Current KST: {now_kst.strftime('%Y-%m-%d %H:%M:%S')}, "
        f"Today Published: {today_count}/{daily_limit} (Life: {today_life}/{today_count} [{life_ratio_pct}%]), "
        f"Mode: {env.get('MEDICALDAILY_PUBLISH_MODE', 'publish')}"
    )

    if args.dry_run:
        logger.info("[Dry Run] All pre-flight checks passed successfully. No actual article was generated.")
        return

    # 3. 신선한 RSS 소스 추출 (Clicky 관심 키워드 매칭 여부 결정)
    # 하루 50개 중 1~3개(예: 3번째, 18번째, 33번째 기사 또는 --clicky 플래그 시)를 관심 키워드 기반으로 작성
    use_clicky = args.clicky or (today_count in (3, 18, 33))
    source_result = None

    if use_clicky:
        clicky_keywords = get_medicaldaily_clicky_keywords(limit=3)
        logger.info(f"[Clicky Pipeline] Target interest keywords: {clicky_keywords}")
        clicky_match = fetch_clicky_matched_rss_source(clicky_keywords)
        if clicky_match:
            payload, link, original_title, score = clicky_match
            logger.info(f"[Clicky Pipeline] Matched RSS article: '{original_title}' (Score: {score})")
            source_result = (payload, link, original_title)

    if not source_result:
        source_result = fetch_medicaldaily_wire_source(env)

    if not source_result:
        logger.error("[MedicalDaily Batch Aborted] Failed to find an unused fresh RSS wire source.")
        return

    payload, link, original_title = source_result
    temp_dir = "data/temp_sources"
    os.makedirs(temp_dir, exist_ok=True)
    temp_file = os.path.join(temp_dir, f"medi_wire_{int(datetime.now().timestamp())}.txt")
    with open(temp_file, "w", encoding="utf-8") as f:
        f.write(payload)

    try:
        # 4. 파이프라인 실행
        success = run_pipeline(
            source_file_path=temp_file,
            target_sites=["medicaldaily"],
            mode="tailored",
            ignore_time_window=args.ignore_time_window,
        )
        logger.info(f"[MedicalDaily Batch Done] Pipeline execution success={success}")
    finally:
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass

if __name__ == "__main__":
    main()

