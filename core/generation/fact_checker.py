import os
import json
import urllib.parse
import re
import requests
import ssl
from common.logger_setup import get_domain_logger

logger = get_domain_logger("general")

# 1. 단축/CDN/패밀리 도메인 정규화 맵
DOMAIN_ALIASES = {
    "wsj.net": "wsj.com",
    "bloomberg.net": "bloomberg.com",
    "reuters.tv": "reuters.com"
}

# ac(학술), go(정부/기관) 등 국가별 기관 서브 접미사 포괄
ALLOWED_PRIMARY_SUFFIX_PAT = r"\.(gov|go|edu|ac|mil|int)(\.[a-z]{2})?$"
ALLOWED_TIER_DOMAINS = {
    "reuters.com", "apnews.com", "bloomberg.com", "wsj.com", "ft.com", 
    "nytimes.com", "washingtonpost.com", "forbes.com", "cnbc.com", 
    "techcrunch.com", "wired.com", "theverge.com", "economist.com", "marketwatch.com", "barrons.com",
    "imf.org", "worldbank.org", "un.org", "who.int", "europa.eu"
}

# 도메인 경계를 명확히 한 블랙리스트 패턴
FORBIDDEN_PATTERNS = [
    r"(^|\.)(twitter|x|reddit|medium|blogspot|wordpress|substack|weebly)\.com$"
]

def enforce_factcheck_sources(res_json, logger, main_subject_domains=None, references_list=None):
    """
    구글 Grounding 메타데이터를 파싱하여 파이썬 코드 단에서 출처 신뢰성을 강제합니다.
    """
    try:
        candidates = res_json.get('candidates', [])
        if not candidates:
            return False, "No candidates found in API response."
            
        metadata = candidates[0].get('groundingMetadata', {})
        chunks = metadata.get('groundingChunks', [])
        supports = metadata.get('groundingSupports', [])
        
        # [폴백 가드] 검색 도구가 모델에 의해 호출되지 않은 경우, 1차 내용 검증(Semantic Check)을 신뢰하여 스킵 없이 통과시킴
        if not chunks:
            logger.info("[Enforcer] No grounding sources returned. Falling back to semantic consistency verification.")
            return True, "Verified via semantic consistency (No web grounding chunks cited)."
            
        # 1. groundingChunkIndices 정확한 키 파싱 (실제 본문 인용 청크만 추출)
        used_indices = set()
        for sup in supports:
            indices = sup.get('groundingChunkIndices') or sup.get('grounding_chunk_indices') or []
            used_indices.update(indices)
            
        target_indices = used_indices if used_indices else set(range(len(chunks)))
        
        valid_domains = set()
        has_primary_source = False
        
        # main_subject_domains 대소문자 정규화 및 None 방지
        normalized_subjects = [d.lower() for d in main_subject_domains] if main_subject_domains else []
        
        for idx in target_indices:
            if idx >= len(chunks):
                continue
            uri = chunks[idx].get('web', {}).get('uri', '')
            if not uri:
                continue
                
            parsed = urllib.parse.urlparse(uri)
            domain = parsed.netloc.lower()
            if not domain:
                continue
            if domain.startswith("www."):
                domain = domain[4:]
                
            # A. 단축/CDN 도메인 정규화
            for alias, main_domain in DOMAIN_ALIASES.items():
                if domain == alias or domain.endswith("." + alias):
                    domain = main_domain
                    break
                
            # [룰 3] 블랙리스트 도메인 매칭 시 0% 규정에 의거 즉시 기각 차단
            if any(re.search(p, domain) for p in FORBIDDEN_PATTERNS):
                return False, f"Rule 3 Violation: Forbidden source detected in active citation: {uri}"
                
            # [룰 2 - Primary] 국가별 ccTLD 및 국제기구 포괄
            match_primary = re.search(ALLOWED_PRIMARY_SUFFIX_PAT, domain)
            if match_primary:
                has_primary_source = True
                valid_domains.add(match_primary.group(0))
                if references_list is not None:
                    # 도메인을 대표 명칭으로 사용
                    references_list.append((domain, uri))
                continue
                
            # [룰 2 - Primary 기업 보도자료] 대상 기업 도메인(서브도메인 포함) 동적 수용
            if normalized_subjects:
                is_subject_domain = any(domain == d or domain.endswith("." + d) for d in normalized_subjects)
                if is_subject_domain:
                    has_primary_source = True
                    for d in normalized_subjects:
                        if domain == d or domain.endswith("." + d):
                            valid_domains.add(d)
                            if references_list is not None:
                                references_list.append((d, uri))
                            break
                    continue
                
            # [룰 2 - Tier 1/2] 화이트리스트 매체 확인
            for allowed in ALLOWED_TIER_DOMAINS:
                if domain == allowed or domain.endswith("." + allowed):
                    valid_domains.add(allowed)
                    if references_list is not None:
                        # 튜플 형태로 (도메인, URL) 추가
                        references_list.append((allowed, uri))
                    break
        
        # [폴백 추가] 만약 primary_source나 대상기업 도메인이 발견되었는데 references_list에 누락되었다면 일괄 등록
        if references_list is not None:
            # unique화 처리
            temp_list = []
            seen = set()
            for d, u in references_list:
                if u not in seen:
                    seen.add(u)
                    temp_list.append((d, u))
            references_list.clear()
            references_list.extend(temp_list)
        
        logger.info(f"[Enforcer] Valid Unique Domains Actually Cited: {valid_domains}")
        
        # [룰 4] 교차 검증 조건 판별
        if has_primary_source or len(valid_domains) >= 2:
            return True, f"Verified successfully with sources: {list(valid_domains)}"
        else:
            return False, f"Rule 4 Violation: Insufficient cross-verification (Valid unique domains: {len(valid_domains)}, expected >= 2)"
            
    except Exception as e:
        return False, f"Error during enforcement: {str(e)}"

def verify_article_facts(api_key, source_text, generated_content, target_site_domain, trend_report=None, main_subject_domains=None, references_list=None):
    """
    사후 검증(Post-Validation) 로직:
    원문 소스(Anchor Facts)와 구글 실시간 검색(Web Grounding)을 활용하여
    생성된 후속 기사 본문의 사실 왜곡 및 날조 여부를 이원화하여 철저히 검증합니다.
    (파이썬 Enforcer v2.2로 신뢰 출처 규칙을 강력 강제합니다.)
    """
    if not api_key:
        logger.warning("GEMINI_API_KEY is not set for fact checking.")
        return True # Fallback to true if no key

    model_name = "gemini-3.1-flash-lite"
    temperature = 0.0 # 확정적(deterministic) 팩트체크를 위해 0.0 설정
    
    trend_data = json.dumps(trend_report) if trend_report else "{}"

    prompt = f"""
You are a strict and objective Fact Checker and Editorial Editor for the news site '{target_site_domain}'.
Your task is to analyze the GENERATED ARTICLE (which is a follow-up/analytical expansion) against the SOURCE TEXT (which is the initial trigger event) using Google Search Grounding for live context.

# REFERENCE SOURCES OF TRUTH:
1. SOURCE TEXT (Ground Truth for Anchor Facts):
{source_text}

2. TREND DATA (Ground Truth for Trend context):
{trend_data}

# GENERATED ARTICLE (Follow-up / Trend Expansion):
{generated_content}

# DUAL-PHASE EVALUATION RULES:
Rule 1. ANCHOR FACT CONSISTENCY (기초 팩트 일치성):
- Does the GENERATED ARTICLE distort, reverse, or contradict any of the specific numbers, dates, statistics, or facts reported in the SOURCE TEXT? (e.g., If SOURCE says "49% risk reduction", did the article change it to "90%" or claim it increased risk?) 
- If yes, this is a distortion (is_distorted = true).

Rule 2. ANALYTICAL LOGICAL SOUNDNESS & FABRICATION BAN (분석적 논리성 및 날조 방지):
- Since this is a follow-up/trend-aligned article, it naturally includes background analysis, expert perspectives, and future outlooks not explicitly written in the SOURCE TEXT.
- Plausible domain insights (e.g., "This will influence future monetary policy" or "The medical community welcomes this mRNA progress") are ACCEPTABLE and NOT distorted.
- However, if the article invents/fabricates specific, non-existent, fake events or false facts (e.g., claiming "A new federal law banning mRNA was passed", or "Merck filed for bankruptcy today"), this is a distortion (is_distorted = true).

Rule 3. GOOGLE SEARCH GROUNDING REQUIRED:
- You MUST perform Google Search grounding queries to cross-verify the current consensus, dates, and names mentioned in the generated article against official public reports to provide grounding chunks.

Rule 4. JOURNALISTIC ATTRIBUTION (저널리즘 출처 인용 필수):
- All statistics, official announcements, direct quotes, and findings in the GENERATED ARTICLE must clearly attribute their sources (e.g., "According to Reuters...", "Data from the U.S. Bureau of Labor Statistics shows...", "Company X said in a statement...").
- Vague and untraceable source expressions such as "Sources say" or "Insiders claim" are strictly FORBIDDEN. If any such vague source is used, is_distorted must be set to true.

Rule 5. CLAIM CROSS-VERIFICATION (클레임 상호 검증):
- For each key claim, ensure the source text or grounding chunks actually support it. Do not allow speculative AI claims without empirical backing.

Evaluate the GENERATED ARTICLE. Output ONLY a JSON response matching this schema exactly, and nothing else.
{{
  "is_distorted": true or false,
  "reason": "Explain clearly why it is a distortion (referencing Rule 1, 2, 4 or 5) or why it is acceptable."
}}
"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"googleSearch": {}}], # Google Search Grounding 실시간 검색 연동 활성화
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": temperature,
            "maxOutputTokens": 512
        }
    }

    logger.info(f"[{target_site_domain.upper()}] Running factual inference check via Gemini Search Grounding...")
    try:
        response = requests.post(url, json=payload, headers=headers, verify=False, timeout=30)
        if response.status_code == 200:
            res_json = response.json()
            text_out = res_json['candidates'][0]['content']['parts'][0]['text']
            
            # 1. 1차 내용 왜곡 판정 JSON 해석
            validation_result = json.loads(text_out)
            is_distorted = validation_result.get("is_distorted", False)
            reason = validation_result.get("reason", "")
            
            if is_distorted:
                logger.warning(f"[FactChecker-Grounding] Semantic distortion detected: {reason}")
                return False
                
            # 2. 내용상 이상이 없으므로(is_distorted == False), 2차 파이썬 Enforcer 출처 강제화 검증 돌입 (결합 체인)
            valid_sources, enforcer_reason = enforce_factcheck_sources(
                res_json, logger, main_subject_domains=main_subject_domains, references_list=references_list
            )
            
            if not valid_sources:
                logger.warning(f"[FactChecker-Enforcer] Grounding sources violation: {enforcer_reason}")
                return False
                
            logger.info(f"[FactChecker-Enforcer] Passed all validation steps. {enforcer_reason}")
            return True
        else:
            logger.error(f"[FactChecker-Grounding] API error (HTTP {response.status_code}): {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"[FactChecker-Grounding] Validation failed due to exception: {e}")
        return False


# ==============================================================================
# 14개 매체별 공식 고유 편집 테마 지침 가이드라인 매핑
# ==============================================================================
SITES_THEME_GUIDELINE = {
    "scienceworldreport": "뇌과학·신경기술, 고고학·인류학, 기후변화·청정에너지, 신소재·양자물리, 의학·바이오, 우주탐사·천문학 등 현대 과학 전 분야의 균형 잡힌 심층 보도",
    "latinoshealth": "중대 의학 돌파구, 건강관리, 질병 예방, 임상 연구",
    "autoworldnews": "자동차 신기술, EV, 자율주행, 신차, 디자인, 모빌리티",
    "youthhealthmag": "청소년·청년 웰빙, 건강 식습관, 스킨케어, 정신건강, 라이프스타일",
    "newseveryday": "글로벌 뉴스, 테크 기업 M&A, 시장 변화, 비즈니스 트랜스포메이션",
    "celebeat": "할리우드, 영화, 유명인, 음악, 연예, 대중문화",
    "boomsbeat": "위트 있는 뉴스, 재미있는 테크·과학, 커뮤니티 트렌드, 밈, 가벼운 과학",
    "sportsworldreport": "스포츠 경기, 스포츠 속보, 경기 분석, 스포츠 웰빙",
    "jobsnhire": "고용시장, 구직, 커리어, 비즈니스 리더십, 노동정책 (주의: 단순 비즈니스나 테크라 하더라도 고용/커리어/노동시장과 직접 연결되지 않으면 절대 탈락)",
    "franchiseherald": "글로벌 경제, 기업 비즈니스 전략, 중소기업, 창업, 통상정책",
    "mobilenapps": "모바일 하드웨어, 스마트폰 앱, 모바일·콘솔 게임, 패치, 디지털 팝컬처",
    "parentherald": "육아, 가족, 자녀교육, 임신·출산, 아동 심리",
    "booksnreview": "서적 비평, 신간, 논픽션, 출판업계, 저자 인터뷰",
    "foodworldnews": "식품 안전, 식품 리콜, 요리, 레시피, 영양, 식품 트렌드"
}

def select_best_rss_seeds(api_key, candidates, site_domain):
    """
    Shift-Left LLM Selector:
    여러 개의 72시간 내 신선한 RSS 기사 후보 목록을 한 번에 읽어,
    해당 매체 고유 테마에 가장 적합한 기사 후보의 인덱스 순위 목록을 리턴합니다.
    """
    from common.logger_setup import get_domain_logger
    logger = get_domain_logger(site_domain)
    
    if not api_key:
        logger.warning(f"[{site_domain}] [Shift-Left Selector] No API key, bypassing selector (defaulting to sequential).")
        return [c["index"] for c in candidates]
        
    if not candidates:
        return []
        
    theme_guideline = SITES_THEME_GUIDELINE.get(site_domain, "General global news highlights and trends.")
    
    # 간소화된 후보 리스트 생성
    simplified_candidates = []
    for c in candidates:
        simplified_candidates.append({
            "index": c["index"],
            "title": c.get("title", "N/A"),
            "description": c.get("description", "N/A")
        })
        
    prompt = f"""
You are the Editorial Selector for the news site '{site_domain}'.
Our exclusive domain focus theme is: "{theme_guideline}"

Below is a list of candidate news items fetched from recent RSS feeds:
{json.dumps(simplified_candidates, indent=2, ensure_ascii=False)}

Your task is to evaluate each candidate against our focus theme and return a ranked list of candidate indexes that directly match our editorial standards.
- Order the indexes from most suitable to least suitable.
- Do NOT include candidates that clearly violate or stretch our theme (e.g., general business/commodity news for jobsnhire, or general health tips for foodworldnews).
- If no candidates match our theme, return an empty list.

Output ONLY a JSON response matching this schema:
{{
  "selected_indexes": [list of integers representing candidate indexes, sorted by priority]
}}
"""

    model_name = "gemini-3.1-flash-lite"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.0
        }
    }
    
    try:
        import requests
        import ssl
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        response = requests.post(url, json=payload, headers=headers, verify=False, timeout=10)
        if response.status_code == 200:
            res_json = response.json()
            text_out = res_json['candidates'][0]['content']['parts'][0]['text'].strip()
            
            # JSON markdown 전처리
            if text_out.startswith("```"):
                match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text_out)
                if match:
                    text_out = match.group(1).strip()
                    
            sel_res = json.loads(text_out)
            ranked_indexes = sel_res.get("selected_indexes", [])
            logger.info(f"[{site_domain}] [Shift-Left Selector SUCCESS] Evaluated {len(candidates)} candidates. Ranked indexes: {ranked_indexes}")
            return ranked_indexes
        else:
            logger.error(f"[{site_domain}] [Shift-Left Selector] API HTTP Error {response.status_code}: {response.text}")
            return [c["index"] for c in candidates]
    except Exception as e:
        logger.error(f"[{site_domain}] [Shift-Left Selector Error] Failed: {e}")
        return [c["index"] for c in candidates]

def evaluate_article_suitability(api_key, headline, seed_url, description, site_domain, active_category_slugs):
    """
    14개 매체별 고유 테마 및 카테고리 룰에 따라 기사 후보의 적합성을 사전에 검증합니다.
    (Theme 우선 원칙 및 7대 의사결정 분류 가이드를 강력 집행합니다.)
    """
    if not api_key:
        return {"suitability": "APPROVED", "decision": "CREATE", "category_slug": None, "reason": "No API key"}

    theme_guideline = SITES_THEME_GUIDELINE.get(site_domain, "General global news highlights and trends.")
    slugs_list = list(active_category_slugs)
    
    prompt = f"""
You are the Chief Editorial Director for the news site '{site_domain}'.
Your task is to strictly evaluate whether a candidate news article is suitable for publication based on our site's exclusive theme, active categories, and editorial guidelines.

# EDITORIAL PARAMETERS FOR {site_domain}:
1. SITE EXCLUSIVE THEME:
{theme_guideline}

2. ACTIVE CATEGORIES FOR {site_domain}:
{json.dumps(slugs_list)}

# CANDIDATE ARTICLE INFO:
- Headline: {headline}
- Seed Source URL: {seed_url}
- Description/Summary: {description}

# STRICT EDITORIAL DECISION RULES:

Rule 1. DECISION TYPE DEFINITIONS & ORDER:
Evaluate the candidate in the following order and classify into one type:
- REJECT: Candidate has no new facts, is a minor paraphrase/title spin of existing info, contains weak theme fit, or lacks independent news value.
- UPDATE: Correting, adjusting, or finalizing previously published facts (e.g., expected figures confirmed, timeline shifts, errata).
- FOLLOW_UP: Directly continues an existing story/event but MUST contain new factual developments (e.g., new official release,실적, statistics, product launches, policy updates). If no new facts exist, REJECT.
- RELATED: Directly related to an existing story/industry but is a separate, independent new event. Must meet 3 conditions (matches theme, has independent news value, has a direct relationship type).
- ANALYSIS: Provides in-depth interpretation/expert analysis. MUST be backed by hard evidence (e.g., stats, expert quotes, market data). General AI speculations without data MUST be classified as WAIT or REJECT.
- CREATE: A completely new, independent factual news event matching the theme.
- WAIT: Valuable but currently lacks sufficient data, or is waiting for major follow-up info.

Rule 2. THEME OVER CATEGORY (Theme 우선 원칙):
- Category matching alone is NOT enough. The article's main subject MUST align directly with the site's exclusive theme.
- For 'jobsnhire': Topics MUST connect directly to employment, hiring, careers, leadership, or labor markets. General business or tech articles with no employment angle MUST be REJECTED.

Rule 3. RELATED RELATIONSHIP TYPE & DISTANCE CONSTRAINT:
If decision is 'RELATED', you must classify the relationship into exactly one of these 11 types:
- SAME_COMPANY, COMPETITOR, SAME_PRODUCT, SAME_TECHNOLOGY, SAME_INDUSTRY, SUPPLY_CHAIN, POLICY, MARKET, CONSUMER_IMPACT, RESEARCH, OTHER_DIRECT_RELATION
- If relationship does not match any (NONE), or if it is a multi-step logical stretch (e.g. Nvidia GPU -> TSMC -> ASML -> European Policy -> Nuclear Investment), REJECT.

Rule 4. MULTI-SITE REPLICATION BAN:
- Do not replicate the same core article across multiple sites via simple title changing, synonym swapping, or rewriting. Each publication must have independent value tailored to the site's target audience.

Rule 4-1. FASHION & STYLE CATEGORY LIMITATION:
- If the selected category_slug is 'style' or 'fashion&style', the article content MUST be strictly limited to celebrity outfits, clothing styles, fashion designers, runway shows, apparel, or the fashion industry.
- Do NOT classify general building architecture, historical markers, monuments, logo/branding, or interior design under 'style'. If the article is not about clothing/apparel fashion, you MUST reject the 'style' classification (classify as 'news' or suitable non-fashion category instead, or set suitability to REJECT if no other valid category matches).

Output ONLY a JSON response matching this schema exactly:
{{
  "suitability": "APPROVED" or "REJECT",
  "decision": "CREATE" or "FOLLOW_UP" or "UPDATE" or "RELATED" or "ANALYSIS" or "WAIT" or "REJECT",
  "category_slug": "one of the active category slugs or null",
  "relation_type": "one of the 11 relationship types or null",
  "reason": "Clear explanation of editorial suitability decision mapping"
}}
"""

    model_name = "gemini-3.1-flash-lite"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.0
        }
    }
    
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        response = requests.post(url, json=payload, headers=headers, verify=False, timeout=15)
        if response.status_code == 200:
            res_json = response.json()
            text_out = res_json['candidates'][0]['content']['parts'][0]['text'].strip()
            
            # JSON markdown fence 제거 정규식 전처리
            if text_out.startswith("```"):
                match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text_out)
                if match:
                    text_out = match.group(1).strip()
                    
            eval_result = json.loads(text_out)
            return eval_result
        else:
            logger.error(f"[EditorialGuard] API HTTP Error {response.status_code}: {response.text}")
            return {"suitability": "REJECT", "decision": "REJECT", "category_slug": None, "relation_type": None, "reason": f"API HTTP Error {response.status_code}"}
    except Exception as e:
        logger.error(f"[EditorialGuard] suitability check failed: {e}")
        return {"suitability": "REJECT", "decision": "REJECT", "category_slug": None, "relation_type": None, "reason": f"Exception: {str(e)}"}

def verify_article_differentiated_rewrite(api_key, generated_content, target_site_domain, selected_category):
    """
    [Rule 5 Post-Validation]
    생성된 기사 본문이 대상 도메인의 테마 및 카테고리에 적합하며, 타사 단순 요약/번역이 아닌 독창적인 분석 앵글로 각색되었는지 파이썬 코드로 사후 검증합니다.
    """
    from common.logger_setup import get_domain_logger
    logger = get_domain_logger(target_site_domain)
    
    # article_generator의 DOMAIN_CONSTRAINTS 참조
    DOMAIN_THEMES = {
        "scienceworldreport": "Latest discoveries in deep space, astronomy, climate science, quantum physics, and advanced research findings. Tailored for scientists and science enthusiasts.",
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
        "foodworldnews": "Food health news, culinary trends, food safety and recall notices, healthy gourmet recipes, and nutrition tips."
    }
    
    domain_focus = DOMAIN_THEMES.get(target_site_domain, "General global news.")
    
    prompt = f"""
You are a Senior Newsroom Editor performing post-publication verification.
Review the following generated article content for the target news site '{target_site_domain}' under the category '{selected_category}'.

Target Site Focus Theme: {domain_focus}
Selected Category: {selected_category}

Generated Article Content:
\"\"\"
{generated_content}
\"\"\"

Verify if the article strictly satisfies these conditions:
1. THEME FIT: The core subject of the article must directly align with the site's exclusive focus theme.
2. CATEGORY FIT: The content must match the chosen category. Especially, if the category is 'style' or 'fashion&style', the content MUST be strictly limited to celebrity outfits, clothing styles, fashion designers, runway shows, apparel, or the fashion industry. General building architecture, historical markers, monuments, logo/branding, or interior design is NOT allowed under style.
3. DIFFERENTIATED REWRITE: The article must NOT be a generic or plain summary/translation of general news. It must present a highly unique, differentiated narrative or analytical angle tailored only for our target domain's readership.

Output ONLY a JSON response matching this schema:
{{
  "passed": true or false,
  "reason": "Detailed reason why it passed or failed verification"
}}
"""

    model_name = "gemini-3.1-flash-lite"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.0
        }
    }
    
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        response = requests.post(url, json=payload, headers=headers, verify=False, timeout=15)
        if response.status_code == 200:
            res_json = response.json()
            text_out = res_json['candidates'][0]['content']['parts'][0]['text'].strip()
            
            if text_out.startswith("```"):
                match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text_out)
                if match:
                    text_out = match.group(1).strip()
                    
            eval_result = json.loads(text_out)
            logger.info(f"[{target_site_domain}] [Post-Validation] Passed={eval_result.get('passed')} - Reason: {eval_result.get('reason')}")
            return eval_result
        else:
            logger.error(f"[{target_site_domain}] [Post-Validation] HTTP Error {response.status_code}")
            return {"passed": False, "reason": f"API HTTP Error {response.status_code}"}
    except Exception as e:
        logger.error(f"[{target_site_domain}] [Post-Validation] Exception: {e}")
        return {"passed": False, "reason": f"Exception during post-validation: {str(e)}"}
