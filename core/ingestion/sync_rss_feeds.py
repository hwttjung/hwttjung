import os
import re
import json
from common.logger_setup import get_domain_logger

logger = get_domain_logger("general")

# 11대 대카테고리와 14개 기사 발행 대상 도메인 간의 매핑 매트릭스 정의
CATEGORY_TO_DOMAINS = {
    "과학-기술": ["scienceworldreport", "mobilenapps"],
    "의료-의약학": ["latinoshealth", "youthhealthmag"],
    "자동차-자동차산업": ["autoworldnews"],
    "일반": ["newseveryday"],
    "엔터테이먼트-연예": ["celebeat"],
    "유머-라이프": ["boomsbeat"],
    "스포츠-스포츠산업": ["sportsworldreport"],
    "경제-고용-비즈니스": ["jobsnhire", "franchiseherald"],
    "육아-교육": ["parentherald"],
    "책리뷰-출판산업": ["booksnreview"],
    "영양학": ["foodworldnews"]
}

VALID_CATEGORIES = set(CATEGORY_TO_DOMAINS.keys())

def parse_categories_md(file_path="categories.md"):
    if not os.path.exists(file_path):
        logger.error(f"[Error] {file_path} file not found.")
        return []
    
    logger.info(f"Reading and parsing {file_path}...")
    with open(file_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f]
        
    parsed_feeds = []
    
    for idx, line in enumerate(lines):
        # http:// 또는 https://로 시작하는 RSS 피드 주소 탐색
        if line.startswith("http://") or line.startswith("https://"):
            if idx >= 2:
                category = lines[idx - 2]
                site_name = lines[idx - 1]
                rss_url = line
                
                # 유효한 11대 카테고리에 속하는 경우만 수집 (참고 자료 섹션의 일반 웹 링크 제외 필터링)
                if category in VALID_CATEGORIES:
                    parsed_feeds.append({
                        "category": category,
                        "site_name": site_name,
                        "rss_url": rss_url
                    })
                    
    logger.info(f"Successfully extracted {len(parsed_feeds)} RSS feeds from {file_path}.")
    return parsed_feeds

def merge_rss_feeds(parsed_feeds, feeds_json_path="config/rss_feeds.json"):
    # 1. 기존 rss_feeds.json 읽기
    existing_feeds = {}
    if os.path.exists(feeds_json_path):
        try:
            with open(feeds_json_path, "r", encoding="utf-8") as f:
                existing_feeds = json.load(f)
            logger.info(f"Loaded existing feeds from {feeds_json_path}.")
        except Exception as e:
            logger.warning(f"[Warning] Failed to load {feeds_json_path}, starting fresh: {e}")
    else:
        logger.info(f"{feeds_json_path} does not exist, creating new feeds map.")
        
    # 14개 도메인 키가 누락되었을 경우를 대비해 초기 리스트 할당
    all_domains = []
    for domains in CATEGORY_TO_DOMAINS.values():
        all_domains.extend(domains)
        
    for domain in all_domains:
        if domain not in existing_feeds:
            existing_feeds[domain] = []
            
    added_count = 0
    duplicate_count = 0
    
    # 2. 신규 피드 병합 (중복 제거 검사)
    for feed in parsed_feeds:
        category = feed["category"]
        rss_url = feed["rss_url"]
        
        target_domains = CATEGORY_TO_DOMAINS.get(category, [])
        for domain in target_domains:
            # 중복 체크
            if rss_url not in existing_feeds[domain]:
                existing_feeds[domain].append(rss_url)
                added_count += 1
            else:
                duplicate_count += 1
                
    # 3. 변경 사항 저장
    os.makedirs(os.path.dirname(feeds_json_path), exist_ok=True)
    with open(feeds_json_path, "w", encoding="utf-8") as f:
        json.dump(existing_feeds, f, indent=2, ensure_ascii=False)
        
    logger.info("==================================================")
    logger.info(" RSS Feeds Merging Completed!")
    logger.info(f" - Target Config: {feeds_json_path}")
    logger.info(f" - Added New Feeds: {added_count}")
    logger.info(f" - Prevented Duplicates: {duplicate_count}")
    logger.info("==================================================")
    
    return added_count, duplicate_count

def main():
    parsed = parse_categories_md("categories.md")
    if parsed:
        merge_rss_feeds(parsed, "config/rss_feeds.json")
    else:
        logger.warning("No parsed RSS feeds to merge.")

parse_categories_markdown = parse_categories_md
sync_rss_feeds = main

if __name__ == "__main__":
    main()
