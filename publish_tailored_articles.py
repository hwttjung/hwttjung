from common.logger_setup import get_domain_logger
logger = get_domain_logger("general")
import os
import re
import json
import time
import urllib.request
import ssl
import threading
import random
import xml.etree.ElementTree as ET
from main import EnvLoader, run_pipeline

def reserve_source_url(domain_key, source_url):
    """
    14개 스레드 간 동일 RSS URL을 선점 예약하여 Race Condition을 방지합니다.
    """
    import fcntl
    logger = get_domain_logger(domain_key)
    res_file = "data/reservation.json"
    lock_file = res_file + ".lock"
    
    os.makedirs(os.path.dirname(res_file), exist_ok=True)
    
    # 락 획득
    try:
        lock_f = open(lock_file, "w")
        fcntl.flock(lock_f, fcntl.LOCK_EX)
    except Exception as e:
        logger.error(f"[{domain_key}] [Reservation Lock Error] Failed to acquire lock: {e}")
        return False
        
    try:
        data = {}
        if os.path.exists(res_file):
            try:
                with open(res_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
                
        reserved = data.setdefault("reserved_urls", {})
        
        # 기 예약 여부 확인
        norm_url = source_url.strip().lower()
        if norm_url in reserved:
            logger.warning(f"[{domain_key}] [Reservation Conflict] Source URL '{source_url}' is already reserved.")
            return False
            
        # 신규 예약 기록
        from datetime import datetime, timezone
        reserved[norm_url] = datetime.now(timezone.utc).isoformat()
        
        # 원자적 파일 쓰기
        tmp_file = res_file + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as tf:
            json.dump(data, tf, indent=2, ensure_ascii=False)
        os.replace(tmp_file, res_file)
        
        logger.info(f"[{domain_key}] [Reservation Success] Reserved source URL: {source_url}")
        return True
    except Exception as err:
        logger.error(f"[{domain_key}] [Reservation Error] Failed during write: {err}")
        return False
    finally:
        fcntl.flock(lock_f, fcntl.LOCK_UN)
        lock_f.close()

# 1. Configuration Map for each site theme (used as fallback)
DOMAINS_THEME = {
    "scienceworldreport": "Comprehensive breakthroughs across modern science: neuroscience, archaeology, climate innovation, biotechnology, physics, human evolution, and space exploration. Tailored for science enthusiasts with balanced multidisciplinary coverage.",
    "latinoshealth": "Important medical breakthroughs, health tips, disease prevention, and clinical research updates. Tailored for Hispanic readers and health-conscious audiences.",
    "autoworldnews": "Automotive technology, electric vehicle launches, autonomous driving systems, car design refreshes, and performance upgrades. Focus on cars and mobility.",
    "youthhealthmag": "Teen wellness tips, healthy eating habits, skincare routines, youth mental health, and active lifestyle guides. Focus on medicine and health for the younger generation.",
    "newseveryday": "General global news, curated daily news highlights, technology mergers, market shifts, and major corporate business transformations.",
    "celebeat": "Hollywood movie releases, celebrity interview highlights, music awards previews, entertainment gossip, and pop culture trends.",
    "boomsbeat": "Humorous news curations, funny tech and science community trends, internet memes, and lighthearted scientific stories.",
    "sportsworldreport": "Major sports tournament recaps (Soccer, NFL, NBA, etc.), athletic achievements, sports match previews, tournament schedule details, and sports health (exercise routines, diet, weight control).",
    "jobsnhire": "Employment market updates, hiring trends, job policies, career development advice, professional leadership, and related government policy news.",
    "franchiseherald": "Global economy news, corporate business developments, enterprise updates, small business strategies, and economic policy news.",
    "mobilenapps": "Cell phones, latest technology, consumer mobile applications, console/PC game releases, app patches, and digital culture trends.",
    "parentherald": "Parenting, family life, child-rearing, motherhood, fatherhood, baby care, and educational news.",
    "booksnreview": "Book reviews, new novel releases, publishing industry updates, author interviews, and literary analysis.",
}

FALLBACK_FEED_KEYWORDS = {
    "scienceworldreport": ["neuro", "brain", "energy", "clean", "climate", "archaeol", "fossil", "tech", "phys", "science", "newscientist", "space"],
    "latinoshealth": ["habit", "nutrition", "diet", "lifestyle", "prevention", "diabetes", "cardio", "cancer", "health", "well", "medical", "nejm", "lancet", "jama", "plos", "biopharma"],
    "autoworldnews": ["motor", "auto", "car", "driver", "jalopnik", "bmw"],
    "youthhealthmag": ["mind", "brain", "mental", "sleep", "diet", "fitness", "nutrition", "skin", "beauty", "teen", "youth", "social", "health", "well", "medical", "nature", "jama", "plos"],
    "newseveryday": ["world", "us", "business", "economy", "forbes", "guardian", "cnn", "time"],
    "celebeat": ["variety", "hollywood", "arts", "movies", "music", "television", "fashion", "deadline", "ew", "rollingstone", "pitchfork"],
    "boomsbeat": ["tech", "wired", "personaltech", "lifehacker", "onion", "buzzfeed", "boredpanda"],
    "sportsworldreport": ["sports", "football", "baseball", "golf", "soccer", "basketball", "hockey", "tennis", "espn", "bleacher", "skysports", "cbssports"],
    "jobsnhire": ["job", "business", "economy", "hbr", "economist", "ft", "bloomberg", "reuters", "forbes", "marketwatch", "cnbc", "inc"],
    "franchiseherald": ["business", "economy", "forbes", "hbr", "economist", "ft", "bloomberg", "reuters", "marketwatch", "cnbc", "inc"],
    "mobilenapps": ["tech", "wired", "personaltech", "technology", "verge", "arstechnica", "engadget", "krebsonsecurity"],
    "parentherald": ["edu", "teacher", "scholastic", "fatherly", "mother"],
    "booksnreview": ["books", "read", "novel", "author", "publish", "literary"],
    "foodworldnews": ["dining", "wine", "food", "nutrition", "examine", "recipe", "cooking"]
}

def get_primary_feed_keywords(domain_key, config_path="config/feed_keywords.json"):
    """
    외부 JSON 설정 파일(config/feed_keywords.json)에서 도메인별 1차 수집 키워드를 동적으로 로드합니다.
    설정 파일이 없거나 오류 발생 시 코드 내 FALLBACK_FEED_KEYWORDS를 안전하게 사용합니다.
    """
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and domain_key in data:
                    kw_list = data[domain_key]
                    if isinstance(kw_list, list) and kw_list:
                        return [str(k).strip().lower() for k in kw_list if str(k).strip()]
        except Exception as e:
            from common.logger_setup import get_domain_logger
            logger = get_domain_logger(domain_key)
            logger.warning(f"[{domain_key}] [Feed Keywords] Failed to load external keywords from {config_path}: {e}")
            
    return FALLBACK_FEED_KEYWORDS.get(domain_key, [])

def clean_html(raw_html):
    if not raw_html:
        return ""
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    return cleantext.strip()

def fetch_rss_wire_source(domain_key, exclude_links=None, rss_feeds_path="config/rss_feeds.json"):
    logger = get_domain_logger(domain_key)
    if not os.path.exists(rss_feeds_path):
        logger.info(f"[{domain_key}] [RSS Parser] Settings file {rss_feeds_path} not found.")
        return None
    return _fetch_rss_wire_source_core(domain_key, exclude_links, rss_feeds_path)

def _fetch_rss_wire_source_core(domain_key, exclude_links=None, rss_feeds_path="config/rss_feeds.json"):
    logger = get_domain_logger(domain_key)
    try:
        with open(rss_feeds_path, "r", encoding="utf-8") as f:
            feeds_map = json.load(f)
    except Exception as e:
        logger.info(f"[{domain_key}] [RSS Parser] Failed to load feeds map: {e}")
        return []
        
    urls = feeds_map.get(domain_key, [])
    if not urls:
        logger.info(f"[{domain_key}] [RSS Parser] No RSS feed URLs defined for this domain.")
        return []
        
    keywords = get_primary_feed_keywords(domain_key)
    primary_urls = []
    secondary_urls = []
    for url in urls:
        url_lower = url.lower()
        is_primary = False
        for kw in keywords:
            if kw in url_lower:
                is_primary = True
                break
        if is_primary:
            primary_urls.append(url)
        else:
            secondary_urls.append(url)
            
    random.shuffle(primary_urls)
    random.shuffle(secondary_urls)
    urls_copy = primary_urls + secondary_urls
    
    import socket
    socket.setdefaulttimeout(15)
    
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    candidates = []
    global_index = 0
    
    for url in urls_copy:
        url = url.strip()
        if not url:
            continue
            
        logger.info(f"[{domain_key}] [RSS Parser] Fetching feed from: {url}")
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        )
        
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=15) as res:
                xml_data = res.read()
                
            root = ET.fromstring(xml_data)
            items = root.findall(".//item")
            if not items:
                logger.info(f"[{domain_key}] [RSS Parser] No items found in feed: {url}")
                continue
                
            # 단일 피드 독점 방지: 피드당 최대 2건까지만 선별하여 출처 및 주제 다양성 극대화
            candidate_items = items[:min(2, len(items))]
            random.shuffle(candidate_items)
            
            from email.utils import parsedate_to_datetime
            from datetime import datetime, timezone
            
            for item in candidate_items:
                link_node = item.find("link")
                link = link_node.text.strip() if link_node is not None and link_node.text else ""
                
                if exclude_links and link in exclude_links:
                    logger.info(f"[{domain_key}] [RSS Filter] Excluded already used source link: {link}")
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
                            item_title = item.find("title").text.strip() if item.find("title") is not None and item.find("title").text else "N/A"
                            logger.info(f"[{domain_key}] [RSS Freshness Filter] Excluded old article (published {round(age_hours, 1)} hours ago): '{item_title}'")
                            continue
                    except Exception as parse_err:
                        logger.info(f"[{domain_key}] [RSS Freshness Warning] Skipped item due to date parsing error: {parse_err}")
                        continue
                else:
                    logger.info(f"[{domain_key}] [RSS Freshness Filter] Excluded article due to missing pubDate.")
                    continue
                
                title_node = item.find("title")
                desc_node = item.find("description")
                
                title = title_node.text.strip() if title_node is not None and title_node.text else "N/A"
                desc = desc_node.text.strip() if desc_node is not None and desc_node.text else "N/A"
                desc_clean = clean_html(desc)
                
                source_payload = (
                    f"SOURCE REAL NEWS WIRE REPORT\n"
                    f"============================\n"
                    f"Original Title: {title}\n"
                    f"Original Summary: {desc_clean}\n"
                    f"Reference URL: {link}\n"
                    f"============================\n"
                    f"Please write a high quality article based on the facts and guidelines above."
                )
                
                candidates.append({
                    "index": global_index,
                    "title": title,
                    "description": desc_clean,
                    "link": link,
                    "payload": source_payload
                })
                global_index += 1
                
                # 최대 10개의 후보까지만 제한하여 과도한 연산 방지
                if len(candidates) >= 10:
                    break
            
            if len(candidates) >= 10:
                break
                
        except Exception as e:
            logger.info(f"[{domain_key}] [RSS Parser Warning] Failed parsing feed URL '{url}': {e}")
            
    return candidates

def fetch_rss_wire_source_multipass(domain_key, local_recent_links, global_restricted_links, rss_feeds_path="config/rss_feeds.json"):
    logger = get_domain_logger(domain_key)
    
    # Pass 1: 자사(local) 및 타사(global) 중복 배제 필터를 둘 다 적용하여 72시간 이내 뉴스 탐색
    combined_exclude = set()
    if local_recent_links:
        combined_exclude = combined_exclude.union(local_recent_links)
    if global_restricted_links:
        combined_exclude = combined_exclude.union(global_restricted_links)
        
    logger.info(f"[{domain_key}] [RSS Pass 1] Searching with local & global exclusion list...")
    candidates = _fetch_rss_wire_source_core(domain_key, combined_exclude, rss_feeds_path)
    if candidates:
        return candidates, False  # is_reused_seed = False
        
    # Pass 2: Pass 1 실패 시, "하루 1개 송출 보장"을 위해 타사 배제 리스트(global)를 해제하고 자사 중복만 차단해 재탐색
    logger.info(f"[{domain_key}] [RSS Pass 2 Fallback] Pass 1 failed. Retrying with local exclusion list only (Global reuse allowed)...")
    candidates = _fetch_rss_wire_source_core(domain_key, local_recent_links, rss_feeds_path)
    if candidates:
        return candidates, True  # is_reused_seed = True
        
    logger.warning(f"[{domain_key}] [RSS Fetch Failed] No valid 72h articles found in any Pass.")
    return [], False

def is_stop_publishing_active(env=None):
    if env is None:
        from main import EnvLoader
        env = EnvLoader.load_env()
    stop_publishing = env.get("STOP_PUBLISHING", "False").strip().lower() in ("true", "1", "yes")
    status_file = "config/status.json"
    if os.path.exists(status_file):
        try:
            with open(status_file, "r", encoding="utf-8") as sf:
                status_data = json.load(sf)
                if status_data.get("STOP_PUBLISHING") is True:
                    stop_publishing = True
        except Exception:
            pass
    return stop_publishing

def process_site_with_delay(api_key, site, temp_dir):
    logger = get_domain_logger(site["domain_key"])
    domain = site["domain_key"]
    
    import sys
    if "--now" in sys.argv or "--no-delay" in sys.argv:
        delay_seconds = site.get("index", 0) * 3
    else:
        delay_seconds = site.get("delay_seconds", 0)
    delay_minutes = round(delay_seconds / 60, 1)
    
    logger.info(f"[{domain}] [Schedule] Dispatched thread. Scheduled to run in {delay_minutes} minutes.")
    time.sleep(delay_seconds)
    
    # [STOP_PUBLISHING 가드] 대기 후 깨어났을 때 즉시 중지 여부 재확인
    if is_stop_publishing_active():
        logger.warning(f"[{domain}] [Stop Publishing] STOP_PUBLISHING is active after delay. Exiting thread immediately.")
        return
        
    logger.info(f"\n>>> [{domain}] Starting tailored publication process after {delay_minutes} min delay...")
    logger.info(f"[{domain}] [Mode Selection] Selected 'Site Theme' mode (100% probability).")
    
    from main import DuplicatePreventer
    try:
        dup_preventer = DuplicatePreventer()
        local_recent_links = dup_preventer.get_recent_rss_links(domain)
        global_restricted_links = dup_preventer.get_globally_restricted_rss_links(max_allowed_sites=2)
        logger.info(f"[{domain}] [RSS Filter] {len(local_recent_links)} local & {len(global_restricted_links)} global restricted links loaded.")
    except Exception as dp_err:
        logger.warning(f"[{domain}] [Warning] Failed to load duplicate preventer links: {dp_err}")
        local_recent_links = set()
        global_restricted_links = set()
        
    candidates, is_reused_seed = fetch_rss_wire_source_multipass(domain, local_recent_links, global_restricted_links)
    
    if not candidates:
        logger.warning(f"[{domain}] [WAIT / SKIP] No active 72h RSS content available. Skipping article generation.")
        return
        
    # Shift-Left LLM Selector 호출: 매체 테마에 가장 최적인 시드 추천 인덱스 확보
    from core.generation.fact_checker import select_best_rss_seeds
    ranked_indexes = select_best_rss_seeds(api_key, candidates, domain)
    
    # 추천된 인덱스 우선순위대로 정렬
    ranked_candidates = []
    # 1. 추천받은 순서대로 채워 넣기
    for idx in ranked_indexes:
        for c in candidates:
            if c["index"] == idx:
                ranked_candidates.append(c)
                break
    # 2. 추천받지 못한 나머지 후보들도 백업용으로 뒤에 덧붙임 (0건 방지 안전장치)
    for c in candidates:
        if c["index"] not in ranked_indexes:
            ranked_candidates.append(c)
            
    logger.info(f"[{domain}] [Shift-Left Selector] Evaluated {len(candidates)} seeds. Ordered ranked sequence: {[c['index'] for c in ranked_candidates]}")
    
    success = False
    for candidate in ranked_candidates:
        # 루프 진행 중 STOP_PUBLISHING 상태 감지 시 즉시 중단
        if is_stop_publishing_active():
            logger.warning(f"[{domain}] [Stop Publishing] STOP_PUBLISHING is active. Aborting candidate attempts.")
            return

        link = candidate["link"]
        payload = candidate["payload"]
        
        # 실제 생성 진입 시점에 락(선점) 예약 획득 시도
        if not reserve_source_url(domain, link):
            logger.info(f"[{domain}] [Reservation Skip] Link '{link}' already reserved by another thread. Trying next...")
            continue
            
        if is_reused_seed:
            payload = f"[SYSTEM_ALERT_REUSED_SEED=True]\n{payload}"
            logger.info(f"[{domain}] [RSS Source Success] Reused seed from sister site detected. Marked with REUSED_SEED=True.")
        else:
            logger.info(f"[{domain}] [RSS Source Success] Selected seed title: '{candidate['title']}'")
            
        temp_file_path = os.path.join(temp_dir, f"{domain}_src.txt")
        with open(temp_file_path, "w", encoding="utf-8") as tf:
            tf.write(payload)
            
        logger.info(f"[{domain}] [Source Saved] Saved unique source wire draft to {temp_file_path}")
        
        try:
            # main.py의 run_pipeline 실행 및 Boolean 결과 수신
            success = run_pipeline(temp_file_path, target_sites=[domain], mode="tailored")
            if success:
                logger.info(f"[{domain}] [Pipeline Success] Tailored article successfully published for index {candidate['index']}.")
                break # 송출 성공 시 즉시 루프 종료
            else:
                if is_stop_publishing_active():
                    logger.warning(f"[{domain}] [Stop Publishing] STOP_PUBLISHING is active. Aborting remaining candidates.")
                    return
                logger.warning(f"[{domain}] [Pipeline Rejected] Index {candidate['index']} was rejected or failed. Trying next ranked candidate...")
        except Exception as pipeline_err:
            logger.error(f"[{domain}] [Pipeline Error] Failed running pipeline for index {candidate['index']}: {pipeline_err}")
            
    if not success:
        if is_stop_publishing_active():
            logger.warning(f"[{domain}] [Stop Publishing] STOP_PUBLISHING is active. Skipping Forced Bypass.")
            return
        logger.warning(f"[{domain}] All candidates failed or were rejected. Activating Forced Bypass safety net.")
        # 1순위 후보 기사로 강제 발행 시도
        candidate = ranked_candidates[0]
        link = candidate["link"]
        payload = candidate["payload"]
        
        # 강제 우회용 메타 정보 주입
        payload = f"[SYSTEM_ALERT_FORCE_BYPASS=True]\n{payload}"
        if is_reused_seed:
            payload = f"[SYSTEM_ALERT_REUSED_SEED=True]\n{payload}"
            
        temp_file_path = os.path.join(temp_dir, f"{domain}_src.txt")
        with open(temp_file_path, "w", encoding="utf-8") as tf:
            tf.write(payload)
            
        logger.info(f"[{domain}] [Forced Bypass Save] Saved source with FORCE_BYPASS to {temp_file_path}")
        try:
            success = run_pipeline(temp_file_path, target_sites=[domain], mode="tailored")
            if success:
                logger.info(f"[{domain}] [Forced Bypass Success] Article successfully published via Forced Bypass.")
            else:
                logger.error(f"[{domain}] [Forced Bypass Failed] Forced Bypass publication also failed.")
        except Exception as bypass_err:
            logger.error(f"[{domain}] [Forced Bypass Error] Exception during Forced Bypass: {bypass_err}")

def main():
    import sys
    import fcntl
    logger = get_domain_logger("general")
    logger.info("==================================================")
    logger.info(" Starting Randomized Tailored Publishing for 8 Sites")
    logger.info("==================================================")
    
    # Process Lock 검사
    lock_file_path = "data/publish_tailored.lock"
    os.makedirs(os.path.dirname(lock_file_path), exist_ok=True)
    try:
        global_lock_f = open(lock_file_path, "w")
        fcntl.flock(global_lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        logger.warning("[Process Lock] Another instance of publish_tailored_articles.py is already running. Exiting.")
        sys.exit(0)
    
    # Load env variables
    env = EnvLoader.load_env()
    
    # Unified Stop State 검사
    if is_stop_publishing_active(env):
        logger.warning("[Stop Publishing] STOP_PUBLISHING is active. Skipping tailored publishing process.")
        return
        
    api_key = env.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("[Error] GEMINI_API_KEY not found in .env.")
        return
        
    sites = EnvLoader.get_sites_config(env)
    if not sites:
        logger.error("[Error] No configured sites found.")
        return
        
    # 1. 매번 실행할 때마다 매체 순서를 무작위로 셔플
    import random
    random.shuffle(sites)
    
    # 2. 9시간(32400초) 이내 100% 송출 완료 및 최소 5분(300초)~최대 60분(3600초) 간격 보장을 위한 정밀 딜레이 배분
    # 13개 구간에 기본 최소 5분(300초) 배정
    intervals = [300] * 13
    
    # 안정적인 9시간 이내 전원 완료를 위해 4~6시간 대의 랜덤 여유 시간 배분
    extra_seconds = random.randint(10000, 20000)
    for _ in range(extra_seconds):
        idx = random.randint(0, 12)
        intervals[idx] += 1
        
    # 구간 최대치 (60분 = 3600초) 적용
    for i in range(13):
        if intervals[i] > 3600:
            intervals[i] = 3600
            
    # 3. 셔플된 매체들에 최종 누적 딜레이 초 적용
    for idx, site in enumerate(sites):
        site["index"] = idx
        if idx == 0:
            site["delay_seconds"] = 0
        else:
            site["delay_seconds"] = sum(intervals[:idx])
        
    # Temp directory for generated source files
    temp_dir = "data/temp_sources"
    os.makedirs(temp_dir, exist_ok=True)
    
    threads = []
    for site in sites:
        t = threading.Thread(target=process_site_with_delay, args=(api_key, site, temp_dir))
        threads.append(t)
        t.start()
        
    # Wait for all threads to complete
    for t in threads:
        t.join()
        
    logger.info("\n==================================================")
    logger.info(" Tailored Publishing Process Completed!")
    logger.info("==================================================")

def update_cron_with_random_time():
    import random
    import subprocess
    import os
    
    # 미국 서머타임(EDT) 기준 09:00~18:00 = UTC 13:00~22:00
    # UTC 13시부터 22시 사이의 랜덤 시간(hour), 0분~59분 사이의 랜덤 분(minute)
    rand_hour = random.randint(13, 22)
    rand_minute = random.randint(0, 59)
    
    backup_file = "data/cron_backup.txt"
    try:
        res = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        # 1. 크론탭 백업 생성
        os.makedirs(os.path.dirname(backup_file), exist_ok=True)
        with open(backup_file, "w", encoding="utf-8") as bf:
            bf.write(res.stdout)
            
        lines = res.stdout.splitlines()
        new_lines = []
        target_pattern = "publish_tailored_articles.py"
        found = False
        
        for line in lines:
            if target_pattern in line:
                new_line = f"{rand_minute} {rand_hour} * * * cd /home/stock_trading_bot && /home/stock_trading_bot/.venv/bin/python publish_tailored_articles.py >> logs/cron.log 2>&1"
                new_lines.append(new_line)
                found = True
            else:
                new_lines.append(line)
                
        if not found:
            new_line = f"{rand_minute} {rand_hour} * * * cd /home/stock_trading_bot && /home/stock_trading_bot/.venv/bin/python publish_tailored_articles.py >> logs/cron.log 2>&1"
            new_lines.append(new_line)
            
        cron_content = "\n".join(new_lines) + "\n"
        subprocess.run(["crontab", "-"], input=cron_content, text=True, check=True)
        
        from common.logger_setup import get_domain_logger
        logger = get_domain_logger("general")
        logger.info(f"[Cron-Scheduler] publish_tailored_articles.py 다음 예약 완료: UTC {rand_hour:02d}:{rand_minute:02d}")
    except Exception as e:
        from common.logger_setup import get_domain_logger
        logger = get_domain_logger("general")
        logger.warning(f"[Cron-Scheduler] 크론탭 랜덤 갱신 실패, 롤백을 수행합니다: {e}")
        if os.path.exists(backup_file):
            try:
                with open(backup_file, "r", encoding="utf-8") as bf:
                    old_cron = bf.read()
                subprocess.run(["crontab", "-"], input=old_cron, text=True, check=True)
                logger.info("[Cron-Scheduler] 기존 크론 설정 복원(Rollback) 성공.")
            except Exception as rollback_err:
                logger.error(f"[Cron-Scheduler] 롤백 복구조차 실패하였습니다: {rollback_err}")

if __name__ == "__main__":
    import sys
    main()
    # 파이프라인 가동 완료 후 다음 날을 위한 동적 크론 시간 갱신 수행 (테스트/수동 옵션 시 보존)
    if "--no-cron-update" not in sys.argv and "--test" not in sys.argv:
        update_cron_with_random_time()
