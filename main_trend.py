import os
import re
import json
import time
import urllib.request
import urllib.parse
import urllib.error
import ssl
from datetime import datetime

# 기존 핵심 컴포넌트 임포트
from common.env_loader import EnvLoader, TelegramNotifier
from core.generation.article_generator import ArticleGenerator
from core.publishing.article_publisher import ArticlePublisher
from core.media.image_searcher import ImageSearcher
from core.generation.fact_checker import verify_article_facts
from core.ingestion.trend_analyzer import gather_trends
from core.storage.history_archiver import HistoryArchiver

# logger 세팅
from common.logger_setup import get_domain_logger
logger = get_domain_logger("trend_pipeline")

# 어필리에이트(할인, 쿠폰, 딜, 리뷰 등) 기사 필터링 함수
def is_affiliate_page(url, title):
    url_lower = url.lower()
    title_lower = title.lower()
    
    # 어필리에이트 판별 블랙리스트 단어군
    blacklist = [
        "coupon", "promo", "deal", "discount", "sale", 
        "best-deals", "product", "price", "shop", "buy", "purchase",
        "save-money", "cheap", "gift-card", "retailer", "clearance"
    ]
    
    # 도메인명(예: booksnreview)으로 인한 차단을 방지하기 위해 URL의 path와 query 영역만 블랙리스트 검사
    parsed = urllib.parse.urlparse(url_lower)
    path_and_query = parsed.path + parsed.query
    
    for word in blacklist:
        if word in path_and_query or word in title_lower:
            return True
            
    # 홈페이지 메인/카테고리/태그 페이지 등 기사가 아닌 단순 인덱스 페이지도 필터링
    path_clean = parsed.path.strip("/")
    if not path_clean or "/" not in path_clean:
        # 도메인 메인 페이지(예: /) 혹은 하위 마디가 없는 1단계 카테고리 수준만 차단
        return True
        
    return False

# 인기 기사 원문 본문 실시간 크롤러 헬퍼
def fetch_article_body_text(url):
    try:
        req = urllib.request.Request(
            url, 
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"}
        )
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
            html = response.read().decode("utf-8", errors="ignore")
            # <p> 태그 정규식 매칭
            paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', html, re.DOTALL)
            text_lines = []
            for p in paragraphs:
                cleaned = re.sub(r'<[^>]+>', '', p).strip()
                if len(cleaned) > 30:
                    text_lines.append(cleaned)
            # 최대 1500자로 잘라서 팩트 소스로 리턴
            return " ".join(text_lines)[:1500]
    except Exception as e:
        logger.warning(f"인기 기사 원문 본문 크롤링 실패 (URL: {url}): {e}")
        return ""

# Clicky API를 사용하여 최근 7일 인기 기사 수집 및 Top N 선별
def get_clicky_top_articles(site_id, sitekey, limit=3):
    articles = []
    # Clicky API pages 요청 (최근 7일)
    url = f"https://api.clicky.com/api/stats/4?site_id={site_id}&sitekey={sitekey}&type=pages&date=last-7-days&output=json"
    
    try:
        req = urllib.request.Request(
            url, 
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        with urllib.request.urlopen(req, context=ctx, timeout=15) as response:
            body = response.read().decode("utf-8")
            data = json.loads(body)
            
            # Clicky 응답 구조 파싱 (data[0]['dates'][0]['items'] 형태)
            items = []
            if isinstance(data, list) and len(data) > 0:
                dates = data[0].get("dates", [])
                if dates and len(dates) > 0:
                    items = dates[0].get("items", [])
                else:
                    items = data[0].get("items", [])
            elif isinstance(data, dict):
                items = data.get("items", [])
                
            for item in items:
                title = item.get("title", "")
                page_url = item.get("url", "")
                # Clicky 응답에서 value에 조회수가 문자열로 담겨서 내려옴
                views = int(item.get("value", 0))
                
                # 어필리에이트 기사가 아닌 진짜 기사만 수집
                if page_url and not is_affiliate_page(page_url, title):
                    articles.append({
                        "title": title,
                        "url": page_url,
                        "views": views
                    })
    except Exception as e:
        logger.warning(f"Clicky API 수집 실패 (site_id: {site_id}): {e}")
        
    # 조회수 기준 내림차순 정렬 후 최상위 limit개 반환
    articles.sort(key=lambda x: x["views"], reverse=True)
    return articles[:limit]

# Gemini를 사용하여 최고 인기 기사로부터 구체적인 Core Seed Keyword 추출
def extract_core_seed_keyword(api_key, top_articles):
    if not top_articles:
        return "latest trends"
        
    # 최고 인기 1위 기사를 기준으로 핀포인트 키워드를 생성
    target_article = top_articles[0]
    
    prompt = f"""
You are a professional SEO Specialist and Editor.
Analyze the title of our top popular article: "{target_article['title']}"
 
Your task is to extract exactly ONE highly specific 'Core Seed Keyword' (1-3 words) representing the concrete subject, technology, proper noun, or medical/business condition of this article.
This seed keyword will be used to look up search volume ideas and real-time trends.
 
CRITICAL RULES:
1. DO NOT extract broad, generic, or category-level words like "Scientific discovery", "Labor Market", "Business", "Sports", "Politics", "Technology", "Health", "Medicine", etc.
2. DO extract the highly specific, concrete core noun or term. For example:
   - "Moderna and Merck's mRNA Vaccine Show Promising Results Against Skin Cancer" ➡️ Extract "mRNA vaccine" or "skin cancer"
   - "US Job Market Shows Surprising Resilience" ➡️ Extract "US job market" or "nonfarm payrolls"
3. Output ONLY the clean keyword and nothing else. No quote marks, no bullet points, no explanations.
"""
    
    model_name = "gemini-3.1-flash-lite"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3}
    }
    
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, context=ctx, timeout=15) as response:
            body = response.read().decode("utf-8")
            res_json = json.loads(body)
            keyword = res_json['candidates'][0]['content']['parts'][0]['text'].strip()
            # 쌍따옴표 등 래퍼 특수문자 제거
            keyword = keyword.replace('"', '').replace("'", "").strip()
            return keyword
    except Exception as e:
        logger.error(f"Seed keyword extraction failed: {e}")
        return "lifestyle trends"

# 3가지 앵글 중 가장 적절한 앵글을 결정하는 함수
def decide_editorial_angle(api_key, seed_keyword, trend_report):
    google_trends = json.dumps(trend_report.get("google_trends", []))
    prompt = f"""
Based on the seed keyword '{seed_keyword}' and the following USA Google Trends data:
{google_trends}
 
Decide which of the following 3 editorial angles is the most appropriate for writing a follow-up/trend-aligned article:
1. 'breaking': What happened next? Focus on immediate news updates/developments. (Choose if the keyword is related to highly time-sensitive events or viral news)
2. 'analysis': Why it matters? Focus on statistics, in-depth breakdown, and implications. (Choose if the keyword involves tech, finance, science, or policy shifts)
3. 'guide': How to? Focus on actionable steps, best practices, and practical tips. (Choose if the keyword is related to lifestyle, wellness, coding, or tutorials)
 
Respond with ONLY one word: either 'breaking', 'analysis', or 'guide'. Do not explain your choice.
"""
    
    model_name = "gemini-3.1-flash-lite"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2}
    }
    
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, context=ctx, timeout=15) as response:
            body = response.read().decode("utf-8")
            res_json = json.loads(body)
            angle = res_json['candidates'][0]['content']['parts'][0]['text'].strip().lower()
            if angle in ['breaking', 'analysis', 'guide']:
                return angle
    except Exception as e:
        logger.warning(f"Failed to decide editorial angle, fallback to 'analysis': {e}")
    return "analysis"

# Clicky 설정 정보 로드
def load_clicky_credentials():
    try:
        with open("config/clicky_settings.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            mapped = {}
            for item in data.get("sites", []):
                mapped[item["domain"]] = {
                    "site_id": item["site_id"],
                    "sitekey": item["sitekey"]
                }
            return mapped
    except Exception as e:
        logger.warning(f"clicky_settings.json 로드 실패: {e}")
        return {}

def is_stop_publishing_active(env=None):
    if env is None:
        env = EnvLoader.load_env()
    stop_publishing = env.get("STOP_PUBLISHING", "False").strip().lower() in ("true", "1", "yes")
    status_file = "config/status.json"
    if os.path.exists(status_file):
        try:
            with open(status_file, "r", encoding="utf-8") as sf:
                status_data = json.load(sf)
                if status_data.get("STOP_PUBLISHING") is True:
                    stop_publishing = True
        except Exception as e:
            logger.warning(f"[Warning] Failed to read status file {status_file}: {e}")
    return stop_publishing

# 트렌드 연관 기사 생성 메인 오케스트레이션 함수
def run_trend_pipeline():
    logger.info("==================================================")
    logger.info(" Starting Clicky-based Trend Article Pipeline...")
    logger.info("==================================================")
    
    env = EnvLoader.load_env()
    
    # STOP_PUBLISHING 플래그 검사 (조기 종료)
    if is_stop_publishing_active(env):
        logger.warning("[Stop Publishing] STOP_PUBLISHING is active. Skipping Clicky trend pipeline.")
        return
        
    sites = EnvLoader.get_sites_config(env)
    clicky_creds = load_clicky_credentials()
    
    gemini_key = env.get("GEMINI_API_KEY")
    if not gemini_key:
        logger.error("GEMINI_API_KEY is missing in env.")
        return
        
    generator = ArticleGenerator(env)
    notifier = TelegramNotifier(env)
    
    for site in sites:
        domain = site["domain_key"]
        
        # 루프 진행 중 STOP_PUBLISHING 상태 변경 감지 시 즉시 중단
        if is_stop_publishing_active(env):
            logger.warning(f"[Stop Publishing] STOP_PUBLISHING is active. Stopping trend pipeline loop at {domain}.")
            break
        
        # 특정 테스트 타겟 도메인이 지정되었을 때, 다른 도메인은 스킵 (API 오남용 방지)
        test_target = os.getenv("TEST_TARGET_DOMAIN")
        if test_target and domain != test_target:
            continue
            
        logger.info(f"\n>>> [{domain.upper()}] Processing Clicky-based Trend Article...")
        
        # Clicky 크리덴셜 룩업
        cred = clicky_creds.get(domain)
        if not cred:
            logger.info(f"[{domain.upper()}] clicky_settings.json에 등록되어 있지 않아 스킵합니다.")
            continue
            
        site_id = cred.get("site_id")
        sitekey = cred.get("sitekey")
        
        # 1. 기발행 이력 및 카테고리 사전 로드
        history_path = "data/published_history.json"
        already_used_urls = set()
        site_history_list = []
        if os.path.exists(history_path):
            try:
                with open(history_path, "r", encoding="utf-8") as f:
                    history_data = json.load(f)
                    site_history_list = history_data.get(domain, [])
                    for hist in site_history_list:
                        if hist.get("rss_link"):
                            already_used_urls.add(hist["rss_link"].strip().lower())
            except Exception as e:
                logger.warning(f"[{domain.upper()}] published_history.json 로드 실패: {e}")

        publisher = ArticlePublisher()
        history_archiver = HistoryArchiver()
        available_categories = publisher.get_categories_for_site(domain)
        if not available_categories:
            logger.error(f"[{domain.upper()}] 카테고리 목록을 로드할 수 없어 스킵합니다.")
            continue
            
        from core.generation.fact_checker import evaluate_article_suitability
        active_slugs = {c["slug"] for c in available_categories}
        
        # 2. 다단계 시드 수집 (Pass 1 -> Pass 2 -> Pass 3)
        clicky_top_n = int(os.getenv("CLICKY_TOP_N", env.get("CLICKY_TOP_N", "3")))
        top_articles = get_clicky_top_articles(site_id, sitekey, limit=clicky_top_n)
        
        candidates = []
        is_reused_seed = False
        
        # Pass 1: 기발행 이력 배제 인기 기사 수집
        if top_articles:
            logger.info(f"[{domain.upper()}] [Pass 1] Checking un-used popular articles (N={len(top_articles)})...")
            for art in top_articles:
                art_url = art.get("url", "").strip().lower()
                if art_url in already_used_urls:
                    continue
                candidates.append(art)
                
        # [NEW RULE] 만약 인기 기사가 모두 중복(이미 사용됨)이라면, 연관 기사를 스킵하고 대신 tailored 기사를 송출
        is_all_duplicate = False
        if top_articles and not candidates:
            is_all_duplicate = True
            
        if is_all_duplicate:
            target_trend_count = 1
            logger.info(f"[{domain.upper()}] 인기 기사가 모두 중복되었습니다. 연관 기사를 스킵하고 대신 tailored 기사를 {target_trend_count}개 송출합니다.")
            
            from publish_tailored_articles import fetch_rss_wire_source_multipass, reserve_source_url
            from main import DuplicatePreventer, run_pipeline
            
            try:
                dup_preventer = DuplicatePreventer()
                local_recent_links = dup_preventer.get_recent_rss_links(domain)
                global_restricted_links = dup_preventer.get_globally_restricted_rss_links(max_allowed_sites=2)
            except Exception as dp_err:
                logger.warning(f"[{domain.upper()}] tailored 듀플리케이트 링크 로드 실패: {dp_err}")
                local_recent_links = set()
                global_restricted_links = set()
                
            tailored_candidates, is_tailored_reused = fetch_rss_wire_source_multipass(domain, local_recent_links, global_restricted_links)
            
            if not tailored_candidates:
                logger.warning(f"[{domain.upper()}] 대체할 tailored RSS 기사 후보가 없어 송출을 건너뜁니다.")
                continue
                
            from core.generation.fact_checker import select_best_rss_seeds
            ranked_indexes = select_best_rss_seeds(gemini_key, tailored_candidates, domain)
            
            ranked_candidates = []
            for idx in ranked_indexes:
                for c in tailored_candidates:
                    if c["index"] == idx:
                        ranked_candidates.append(c)
                        break
            for c in tailored_candidates:
                if c["index"] not in ranked_indexes:
                    ranked_candidates.append(c)
                    
            tailored_success_count = 0
            import tempfile
            temp_dir = tempfile.gettempdir()
            
            for candidate in ranked_candidates:
                if tailored_success_count >= target_trend_count:
                    break
                    
                link = candidate["link"]
                payload = candidate["payload"]
                
                if not reserve_source_url(domain, link):
                    continue
                    
                if is_tailored_reused:
                    payload = f"[SYSTEM_ALERT_REUSED_SEED=True]\n{payload}"
                    
                temp_file_path = os.path.join(temp_dir, f"trend_alt_tailored_{domain}_src.txt")
                with open(temp_file_path, "w", encoding="utf-8") as tf:
                    tf.write(payload)
                    
                try:
                    success_tailored = run_pipeline(temp_file_path, target_sites=[domain], mode="tailored")
                    if success_tailored:
                        logger.info(f"[{domain.upper()}] 대체 tailored 기사 송출 성공! ({tailored_success_count + 1}/{target_trend_count})")
                        tailored_success_count += 1
                except Exception as p_err:
                    logger.error(f"[{domain.upper()}] 대체 tailored 기사 송출 중 에러: {p_err}")
                    
            continue  # 연관 기사 스킵 처리 후 다음 도메인 루프로 진입
            
        # Pass 3: Clicky 통계가 0건일 때 자사 최근 발행 역사에서 가장 최신 기사 1건을 백업 시드로 강제 채택 (0건 방지)
        if not candidates and not top_articles:
            logger.info(f"[{domain.upper()}] [Pass 3 Bailout] Clicky statistics is empty. Pulling backup seed from published history.")
            if site_history_list:
                # 가장 최신에 송출 성공했던 자사 기사를 시드로 역채택
                latest_hist = site_history_list[-1]
                backup_seed = {
                    "title": latest_hist.get("title", "Recent Update"),
                    "url": latest_hist.get("rss_link", f"https://{domain}.com/"),
                    "views": 1
                }
                candidates = [backup_seed]
                is_reused_seed = True
                logger.info(f"[{domain.upper()}] Bailout Seed Adopted: '{backup_seed['title']}' (URL: {backup_seed['url']})")
            else:
                # 히스토리 조차 없는 극단적 초기 상태일 경우의 강제 기본 데모 시드
                demo_seed = {
                    "title": "US Job Market and Modern Employment Trends Analysis",
                    "url": f"https://{domain}.com/articles/demo-employment-trends-analysis.htm",
                    "views": 1
                }
                candidates = [demo_seed]
                is_reused_seed = True
                logger.info(f"[{domain.upper()}] Initial Demo Seed Adopted: '{demo_seed['title']}'")
                
        # 3. AI 에디토리얼 가드 적합성 검증 순차 루프
        filtered_articles = []
        for art in candidates:
            eval_res = evaluate_article_suitability(
                gemini_key, 
                art.get("title", ""), 
                art.get("url", ""), 
                art.get("title", ""), 
                domain, 
                active_slugs
            )
            suitability = eval_res.get("suitability", "APPROVED")
            decision = eval_res.get("decision", "CREATE")
            reason = eval_res.get("reason", "")
            
            if suitability == "REJECT" or decision == "REJECT":
                logger.warning(f"[{domain.upper()}] 시드 기사 '{art['title']}' 가이드라인 REJECT 판정: {reason}. 차순위 검토.")
                continue
                
            logger.info(f"[{domain.upper()}] 시드 기사 '{art['title']}' 가이드라인 APPROVED 판정 ({decision}): {reason}")
            filtered_articles.append((art, eval_res))
            
        if not filtered_articles:
            # 0건 완전 스킵 방지를 위해 에디토리얼 가드가 전체 REJECT 하더라도 1순위 시드는 무조건 살려 강제 진행
            logger.warning(f"[{domain.upper()}] 모든 시드가 에디토리얼 가드에서 반려되었습니다. 0건 송출을 차단하기 위해 1순위 시드로 강제 송출을 감행합니다.")
            fallback_eval = {"suitability": "APPROVED", "decision": "CREATE", "reason": "Bailout override for daily publishing guarantee", "story_id": None, "parent_article_id": None}
            filtered_articles.append((candidates[0], fallback_eval))
            
        # 4. 순차 재생성 재시도 루프 기동 (성공 시 즉시 break)
        success = False
        for target_seed_article, suitability_result in filtered_articles:
            logger.info(f"[{domain.upper()}] 최종 집필 대상 채택 시드 기사: '{target_seed_article['title']}'")
            
            seed_keyword = extract_core_seed_keyword(gemini_key, [target_seed_article])
            logger.info(f"[{domain.upper()}] Extracted Core Seed Keyword: '{seed_keyword}'")
            
            logger.info(f"[{domain.upper()}] Gathering search volumes and trends for '{seed_keyword}'...")
            trend_report = gather_trends(seed_keyword, env)
            
            angle = decide_editorial_angle(gemini_key, seed_keyword, trend_report)
            logger.info(f"[{domain.upper()}] Decided Editorial Angle: '{angle.upper()}'")
            
            article_body = fetch_article_body_text(target_seed_article['url'])
            
            # 중복 재사용 기사일 경우 헤더 강제 기입하여 generator 지침에 연계
            source_text_payload = f"Original Title: {target_seed_article['title']}\nOriginal Source URL: {target_seed_article['url']}\nOriginal Article Facts: {article_body}\nTrending Trigger Keyword: {seed_keyword}"
            if is_reused_seed:
                source_text_payload = f"[SYSTEM_ALERT_REUSED_SEED=True]\n{source_text_payload}"
                logger.info(f"[{domain.upper()}] Seed reuse flagged. Injecting [SYSTEM_ALERT_REUSED_SEED=True] alert header.")
                
            source_text = f"Theme: Follow-up and Trend Expansion on our popular article\n{source_text_payload}"
            
            # 3중 팩트체크 교차 검증 생성 루프
            for attempt in range(1, 4):
                logger.info(f"[{domain.upper()}] Generating article (Attempt {attempt}/3)...")
                try:
                    article_data = generator.generate_trend(
                        source_text, 
                        domain, 
                        available_categories, 
                        trend_report, 
                        angle
                    )
                    
                    # 팩트체크 도메인 추출 및 검증
                    subject_domains = []
                    seed_url = target_seed_article.get("url")
                    if seed_url:
                        parsed_seed = urllib.parse.urlparse(seed_url)
                        seed_domain = parsed_seed.netloc.lower()
                        if seed_domain.startswith("www."):
                            seed_domain = seed_domain[4:]
                        subject_domains.append(seed_domain)
                        
                    content_html = article_data.get("content", "")
                    verified_references = []
                    is_valid = verify_article_facts(
                        gemini_key, source_text, content_html, domain, 
                        trend_report=trend_report, main_subject_domains=subject_domains,
                        references_list=verified_references
                    )
                    
                    if is_valid:
                        logger.info(f"[{domain.upper()}] Fact-check PASSED on attempt {attempt}.")
                        
                        if verified_references:
                            ref_html = "<br/><h3>References</h3><ul>"
                            for d, u in verified_references:
                                name = d.split('.')[0].capitalize()
                                ref_html += f'<li><a href="{u}" target="_blank" rel="noopener">{name}</a></li>'
                            ref_html += "</ul>"
                            article_data["content"] = article_data.get("content", "") + ref_html
                            logger.info(f"[{domain.upper()}] Dynamic References block attached to article body.")
                            
                        # 어드민 CMS 배포
                        logger.info(f"[{domain.upper()}] Publishing draft article to CMS...")
                        image_searcher = ImageSearcher(env)
                        img_data = image_searcher.search_image(
                            article_data.get("image_search_queries") or article_data.get("search_keyword", seed_keyword),
                            site_domain=domain,
                            article_summary=article_data.get("summary", ""),
                            article_title=article_data.get("title", "")
                        )
                        
                        INGEST_API_SITES = ["jobsnhire", "franchiseherald", "mobilenapps", "parentherald", "booksnreview", "foodworldnews"]
                        if domain in INGEST_API_SITES:
                            res_data, err = publisher.publish_to_ingest_api(domain, article_data, img_data, rss_link=target_seed_article.get("url", ""))
                            if err is None and res_data:
                                res_data["article_id"] = res_data.get("a_id")
                                res_data["url"] = res_data.get("cms_url")
                        else:
                            res_data, err = publisher.publish(site, article_data, img_data)
                        story_id = suitability_result.get("story_id")
                        parent_article_id = suitability_result.get("parent_article_id")
                        decision_type = suitability_result.get("decision", "CREATE")
                        
                        if res_data:
                            article_id = res_data.get("article_id", "Draft-OK")
                            logger.info(f"[{domain.upper()}] 송출 성공! Article ID: {article_id}")
                            
                            # data/published_history.json에 시드 정보와 함께 기록 세이브
                            try:
                                history_path = "data/published_history.json"
                                history_data = {}
                                if os.path.exists(history_path):
                                    with open(history_path, "r", encoding="utf-8") as f:
                                        history_data = json.load(f)
                                        
                                if domain not in history_data:
                                    history_data[domain] = []
                                    
                                history_data[domain].append({
                                    "title": article_data.get("title", ""),
                                    "category": article_data.get("selected_category", ""),
                                    "date": datetime.now().strftime("%Y-%m-%d"),
                                    "image_url": img_data.get("url", ""),
                                    "timestamp": datetime.now().isoformat() + "Z",
                                    "rss_link": target_seed_article.get("url", "")
                                })
                                
                                with open(history_path, "w", encoding="utf-8") as f:
                                    json.dump(history_data, f, indent=2, ensure_ascii=False)
                                logger.info(f"[{domain.upper()}] published_history.json 이력 누적 완료")
                            except Exception as ex:
                                logger.warning(f"[{domain.upper()}] published_history.json 이력 저장 실패: {ex}")
                                
                            # 90일 보관소 연동
                            try:
                                article_hash = history_archiver.make_article_hash(article_data.get("content", ""))
                                content_payload = {
                                    "article_id": str(article_id),
                                    "headline": article_data.get("title", ""),
                                    "image_url": img_data.get("url"),
                                    "seed_url": target_seed_article.get("url", "") if target_seed_article else "",
                                    "source_urls": [target_seed_article.get("url")] if target_seed_article and target_seed_article.get("url") else [],
                                    "fact_check_urls": [],
                                    "article_hash": article_hash,
                                    "category": article_data.get("selected_category", ""),
                                    "created_at": datetime.now().isoformat(),
                                    "story_id": story_id,
                                    "parent_article_id": parent_article_id,
                                    "article_type": decision_type
                                }
                                history_archiver.save_content(content_payload)
                                
                                pub_payload = {
                                    "article_id": str(article_id),
                                    "site_id": domain,
                                    "status": "published",
                                    "published_at": datetime.now().isoformat(),
                                    "published_url": res_data.get("url") if res_data else None,
                                    "retry_count": 0,
                                    "mode": "trend",
                                    "error": None
                                }
                                history_archiver.save_publication(pub_payload)
                                history_archiver.clean_expired_archives()
                            except Exception as arch_ex:
                                logger.error(f"[{domain.upper()}] [HistoryArchiver-Error] Failed to save archive: {arch_ex}")
                                
                            # 텔레그램 단순 요약 알림
                            tg_msg = f"""<b>[송출 성공 - Trend]</b>
• 사이트명: {domain} (ID: {article_id})
• 기사명: {article_data.get('title', 'Unknown')}
• 카테고리: {article_data.get('selected_category', 'Unknown')} (Trend-Based)"""
                            notifier.send_notification(tg_msg)
                            
                            success = True
                            break
                        else:
                            logger.error(f"[{domain.upper()}] 어드민 업로드 실패. 에러: {err}")
                    else:
                        logger.warning(f"[{domain.upper()}] Fact-check FAILED on attempt {attempt}. Regenerating...")
                except Exception as e:
                    logger.error(f"[{domain.upper()}] 기사 생성 도중 예외 발생: {e}")
                    time.sleep(2)
                    
            if success:
                break # 1건 성공 시 즉시 루프 종료
            else:
                logger.warning(f"[{domain.upper()}] 시드 '{target_seed_article['title']}' 실패. 차순위 재시도 수행.")
                
        if not success:
            logger.error(f"[{domain.upper()}] 모든 후보 시드가 실패했거나 팩트체크를 통과하지 못했습니다. 트렌드 기사 송출 건너뜀.")
            
        # 매체 간 Rate Limit 예방을 위한 안전 지연 대기
        time.sleep(2)

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
        target_pattern = "main_trend.py"
        found = False
        
        for line in lines:
            if target_pattern in line:
                # 새로운 랜덤 시간대 스케줄로 치환
                new_line = f"{rand_minute} {rand_hour} * * * cd /home/stock_trading_bot && /home/stock_trading_bot/.venv/bin/python main_trend.py >> logs/trend_cron.log 2>&1"
                new_lines.append(new_line)
                found = True
            else:
                new_lines.append(line)
                
        if not found:
            new_line = f"{rand_minute} {rand_hour} * * * cd /home/stock_trading_bot && /home/stock_trading_bot/.venv/bin/python main_trend.py >> logs/trend_cron.log 2>&1"
            new_lines.append(new_line)
            
        cron_content = "\n".join(new_lines) + "\n"
        subprocess.run(["crontab", "-"], input=cron_content, text=True)
        logger.info(f"[Cron-Scheduler] 다음 실행 스케줄이 랜덤 예약되었습니다: UTC {rand_hour:02d}:{rand_minute:02d} (동부시각 EDT {rand_hour-4:02d}:{rand_minute:02d})")
    except Exception as e:
        logger.warning(f"[Cron-Scheduler] 크론탭 랜덤 갱신 실패: {e}")

if __name__ == "__main__":
    run_trend_pipeline()
    # 파이프라인 가동 완료 후 다음 날을 위한 동적 크론 시간 갱신 수행
    update_cron_with_random_time()
