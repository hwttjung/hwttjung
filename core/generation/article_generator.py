import os
import re
import json
import time
import urllib.request
import urllib.parse
import urllib.error
import ssl
from datetime import datetime

DOMAIN_CONSTRAINTS = {
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
    "foodworldnews": "Food health news, culinary trends, food safety and recall notices, healthy gourmet recipes, and nutrition tips."
}

class ArticleGenerator:
    def __init__(self, env):
        self.env = env
        self.api_key = env.get("GEMINI_API_KEY")
        self.settings = self._load_settings()
        self.prompt_instruction = self._load_instruction()
        
    def _is_stop_publishing_active(self):
        """STOP_PUBLISHING 긴급 중단 플래그 검사 (status.json 및 .env)"""
        status_file = "config/status.json"
        if os.path.exists(status_file):
            try:
                with open(status_file, "r", encoding="utf-8") as sf:
                    data = json.load(sf)
                    if data.get("STOP_PUBLISHING") is True:
                        return True
            except Exception:
                pass
        if hasattr(self, "env") and self.env:
            if str(self.env.get("STOP_PUBLISHING", "False")).strip().lower() in ("true", "1", "yes"):
                return True
        return False
        
    def _load_settings(self):
        settings_path = "config/settings.json"
        if os.path.exists(settings_path):
            with open(settings_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "ai_model": {
                "provider": "gemini",
                "model_name": "gemini-3.1-flash-lite",
                "temperature": 0.6,
                "max_tokens": 1024
            }
        }
        
    def _load_instruction(self):
        instruction_path = "data/Prompts/general_art.md"
        if os.path.exists(instruction_path):
            with open(instruction_path, "r", encoding="utf-8") as f:
                return f.read()
        return "Write a professional news article."

    def _normalize_image_queries(self, generated_data: dict) -> dict:
        """
        인명 우선순위 및 다단계 이미지 검색 쿼리 후처리 & 안전 가드레일
        """
        featured = generated_data.get("featured_persons")
        if not isinstance(featured, list):
            featured = []
            
        clean_persons = [str(p).strip() for p in featured if str(p).strip()]
        generated_data["featured_persons"] = clean_persons
        
        fallback_kw = str(generated_data.get("fallback_topic_keyword") or "").strip()
        search_kw = str(generated_data.get("search_keyword") or "").strip()
        
        if not fallback_kw:
            fallback_kw = search_kw if search_kw and search_kw not in clean_persons else "news"
        generated_data["fallback_topic_keyword"] = fallback_kw
        
        raw_queries = generated_data.get("image_search_queries")
        queries = []
        if isinstance(raw_queries, list):
            queries = [str(q).strip() for q in raw_queries if str(q).strip()]
            
        if not queries:
            queries = list(clean_persons)
            if fallback_kw and fallback_kw not in queries:
                queries.append(fallback_kw)
                
        if not queries:
            queries = [search_kw] if search_kw else ["news"]
            
        generated_data["image_search_queries"] = queries
        if not search_kw or search_kw not in queries:
            generated_data["search_keyword"] = queries[0]
            
        return generated_data

    def generate(self, source_text, target_site_domain, available_categories, recommended_category=None):
        if self._is_stop_publishing_active():
            from common.logger_setup import get_domain_logger
            logger = get_domain_logger(target_site_domain)
            logger.warning(f"[{target_site_domain}] [Stop Publishing Kill Switch] STOP_PUBLISHING is active. Aborting article generation.")
            return None

        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not set.")
            
        model_name = self.settings.get("ai_model", {}).get("model_name", "gemini-3.1-flash-lite")
        temperature = self.settings.get("ai_model", {}).get("temperature", 0.6)
        max_tokens = self.settings.get("ai_model", {}).get("max_tokens", 1024)
        
        # categories formatting for prompt insertion
        categories_str = ", ".join([f"'{c['slug']}' ({c.get('title', c.get('name', ''))})" for c in available_categories])
        
        # Get current date info
        current_date = datetime.now().strftime("%Y-%m-%d")
        current_year = datetime.now().strftime("%Y")
        
        # Build prompt incorporating general_art.md and constraints
        domain_focus = DOMAIN_CONSTRAINTS.get(target_site_domain, "General news and trends.")
        
        domain_specific_constraint = f"""
CRITICAL RULE FOR {target_site_domain.upper()}:
This site is a dedicated channel for: {domain_focus}
You MUST strictly focus the article around this specific theme. If the provided source text is about a different topic, you must find a valid, factual intersection between the source text and the domain's theme. 
CRITICAL FACT-CHECKING RULE: You must base the article STRICTLY on the facts provided in the source text. DO NOT hallucinate, invent, or twist facts to artificially fit the theme. If no factual intersection exists, focus purely on the facts that align closest with the theme while maintaining strict journalistic integrity.
"""
        if "[SYSTEM_ALERT_REUSED_SEED=True]" in source_text:
            reused_seed_instruction = f"""
[CRITICAL DOMAIN REWRITE DIRECTIVE - REUSED SEED DETECTED]
- Note: This source article has already been covered or shared by sister websites.
- Therefore, you MUST NOT write a generic summary of this news.
- You MUST strictly frame this news around the target theme of '{target_site_domain.upper()}' ({domain_focus}) and the selected category.
- Write this article from a completely unique, highly differentiated editorial angle of analysis tailored only for our target audience.
"""
            domain_specific_constraint += reused_seed_instruction

        if recommended_category:
            rec_slug = recommended_category.get("slug") if isinstance(recommended_category, dict) else recommended_category
            rec_title = recommended_category.get("title", rec_slug) if isinstance(recommended_category, dict) else rec_slug
            diversity_directive = f"""
[EDITORIAL CATEGORY DIVERSITY DIRECTIVE]
- Our editorial team strongly recommends targeting the category '{rec_slug}' ({rec_title}) for balanced topical coverage.
- You are heavily encouraged to frame the source facts through the lens of this category (e.g., lifestyle application, mental well-being, nutrition, preventative habit), without distorting or fabricating facts.
- Select '{rec_slug}' as the 'selected_category' if the source article can be legitimately framed around this perspective. If the source material cannot reasonably fit this category, you may choose another closely matching allowed slug.
"""
            domain_specific_constraint += diversity_directive

        prompt = f"""
{self.prompt_instruction}

---

# [IMPORTANT SYSTEM CONSTRAINTS]
Today's Date: {current_date}
The current year is {current_year}. Make sure all time-specific statements, statistics, and forecasts in the generated article are relative to the current year {current_year}. Do not write about past years (like 2024 or 2025) as the current or upcoming year.{domain_specific_constraint}

# [In-Text Citation & Attribution Rules]
1. Attribution in Sentence: Whenever citing specific statistics, quotes, or exclusive breaking reports, explicitly name the source in the text using natural journalistic attribution:
   - Examples:
     * "According to a report by Reuters..."
     * "...as first reported by Bloomberg."
     * "Data from the U.S. Bureau of Labor Statistics shows that..."
     * "Speaking to The Wall Street Journal, [Name] stated..."
2. No Anonymous Claims: Never use vague phrases like "Sources say", "Studies show", or "Recent studies suggest" without specifying the organization or publication.
3. Anchor Formatting: Mark key source names or data points with markdown brackets if needed, e.g., "[Reuters reported](source_link)".

1. You must select the single most appropriate category slug from the following list of allowed slugs for the site '{target_site_domain}':
   Allowed Slugs: [{categories_str}]
   - FASHION & STYLE CRITICAL RULE: If you select the 'style' or 'fashion&style' category, the article MUST be strictly limited to celebrity outfits, clothing styles, fashion designers, runway shows, apparel, or the fashion industry. Do NOT use it for general building architecture, monuments, or logo/branding design. If the article is not about clothing/apparel fashion, you must select 'news' or other appropriate categories instead.
   - HEADLINE VARIETY RULE: Do NOT start article titles with government agency or institutional press-release acronyms like 'NASA', 'ESA', 'CDC', or 'FDA'. Instead, craft active, highly engaging journalistic headlines focusing on the scientific breakthrough, celestial body, phenomenon, or research finding itself (e.g., instead of 'NASA Telescope Finds...', write 'Deep Space Survey Detects Potential Atmosphere on Distant Exoplanet').
2. You must output the result strictly in JSON format matching the schema below.
3. The article must be written in English.
4. The article body content must be in HTML format (use only <p>, <h3>, etc. No H1-H2, H4-H6 tags. Subheadings must be written in <h3> tags (e.g., <h3>Subheading</h3>) and cannot be bold text (<b> or <strong>).
5. Do NOT include any "Sources:" or reference section at the end of the article content. All citations must be integrated naturally in the text.
6. Provide exactly 20 highly relevant SEO tags or keywords for the generated article in the "seo_tags" field. The 20 tags must be separated by commas (e.g., "keyword1, keyword2, ...").
7. IMAGE SEARCH STRATEGY & PERSON RELEVANCE RULES:
   - Identify whether one or more specific persons (athletes, celebrities, public figures, leaders) are genuinely the CENTRAL FOCUS of this article.
   - If a person is merely mentioned in passing, incidental, or part of a broad team/institution, DO NOT treat them as featured persons (return an empty list [] for "featured_persons").
   - If one or more persons ARE the central focus/protagonists of the article:
     * Rank them in "featured_persons" in strict order of prominence/importance (Protagonist #1 first, key opponent/counterpart #2). Maximum 2 persons.
   - In "fallback_topic_keyword", provide a clean, specific topical keyword representing the core subject or sport/event (e.g., 'boxing match', 'electric vehicle', 'cardiology surgery').
   - In "image_search_queries", provide an ordered array of search queries for finding header images, starting with the primary person (if any), then secondary person (if any), followed by the fallback topic keyword.
     * Example (Person-centric): ["Ben Whittaker", "Conor Wallace", "boxing match"]
     * Example (Topic-centric / No prominent person): ["space telescope", "astronomy exoplanet"]
   - Keep "search_keyword" as the primary query (the first item of "image_search_queries") for backwards compatibility.

# Output Schema (JSON):
{{
  "fact_check_rationale": "Before writing the article, briefly explain how you will adapt the facts from the source text to fit the site's theme WITHOUT distorting or inventing any facts.",
  "title": "Article Title",
  "summary": "150-character summary paragraph",
  "content": "<p>Article body in HTML format...</p>",
  "selected_category": "selected-category-slug-from-allowed-list",
  "featured_persons": ["Prominent Person 1", "Prominent Person 2"],
  "fallback_topic_keyword": "A clean topic or sport keyword (e.g. 'boxing match' or 'space technology')",
  "image_search_queries": ["Prominent Person 1", "Prominent Person 2", "boxing match"],
  "search_keyword": "Prominent Person 1",
  "seo_tags": "tag1, tag2, tag3, tag4, tag5, tag6, tag7, tag8, tag9, tag10, tag11, tag12, tag13, tag14, tag15, tag16, tag17, tag18, tag19, tag20"
}}

# Source Article / Raw Text to Reconstruct:
{source_text}
"""
        # Call Gemini REST API (v1beta)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={self.api_key}"
        
        headers = {
            "Content-Type": "application/json"
        }
        
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": temperature,
                "maxOutputTokens": max_tokens
            }
        }
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=30) as response:
                body = response.read().decode("utf-8")
                res_json = json.loads(body)
                
                # Extract text content from Gemini response
                text_out = res_json['candidates'][0]['content']['parts'][0]['text']
                # Parse output JSON from LLM
                generated_data = json.loads(text_out)
                generated_data = self._normalize_image_queries(generated_data)
                self.validate_anonymous_claims(generated_data.get("content", ""), target_site_domain)
                return generated_data
        except Exception as e:
            from common.logger_setup import get_domain_logger
            logger = get_domain_logger(target_site_domain)
            logger.error(f"Gemini API generation failed: {e}")
            raise

    def generate_trend(self, source_text, target_site_domain, available_categories, trend_report, angle):
        if self._is_stop_publishing_active():
            from common.logger_setup import get_domain_logger
            logger = get_domain_logger(target_site_domain)
            logger.warning(f"[{target_site_domain}] [Stop Publishing Kill Switch] STOP_PUBLISHING is active. Aborting trend article generation.")
            return None

        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not set.")
            
        model_name = self.settings.get("ai_model", {}).get("model_name", "gemini-3.1-flash-lite")
        temperature = self.settings.get("ai_model", {}).get("temperature", 0.6)
        max_tokens = self.settings.get("ai_model", {}).get("max_tokens", 1024)
        
        categories_str = ", ".join([f"'{c['slug']}' ({c.get('title', c.get('name', ''))})" for c in available_categories])
        current_date = datetime.now().strftime("%Y-%m-%d")
        current_year = datetime.now().strftime("%Y")
        
        domain_focus = DOMAIN_CONSTRAINTS.get(target_site_domain, "General news and trends.")
        
        domain_specific_constraint = f"""
CRITICAL RULE FOR {target_site_domain.upper()}:
This site is a dedicated channel for: {domain_focus}
You MUST strictly focus the article around this specific theme. If the provided source text is about a different topic, you must find a valid, factual intersection between the source text and the domain's theme. 
CRITICAL FACT-CHECKING RULE: You must base the article STRICTLY on the facts provided in the source text. DO NOT hallucinate, invent, or twist facts to artificially fit the theme. If no factual intersection exists, focus purely on the facts that align closest with the theme while maintaining strict journalistic integrity.
"""
        if "[SYSTEM_ALERT_REUSED_SEED=True]" in source_text:
            reused_seed_instruction = f"""
[CRITICAL DOMAIN REWRITE DIRECTIVE - REUSED SEED DETECTED]
- Note: This source article has already been covered or shared by sister websites.
- Therefore, you MUST NOT write a generic summary of this news.
- You MUST strictly frame this news around the target theme of '{target_site_domain.upper()}' ({domain_focus}) and the selected category.
- Write this article from a completely unique, highly differentiated editorial angle of analysis tailored only for our target audience.
"""
            domain_specific_constraint += reused_seed_instruction

        # 후속 기사 정체성 및 중복 재서술 전면 금지 규칙 추가 주입
        follow_up_instructions = """
# [CRITICAL FOLLOW-UP ARTICLE INSTRUCTIONS]
1. DO NOT simply paraphrase or repeat the core paragraphs of the SOURCE TEXT in a different tone. Avoid making the new article feel like a duplicate or a rephrased version of the source.
2. TREAT the SOURCE TEXT purely as an 'Initial Trigger Event' or 'Contextual Anchor'. 
3. FOCUS the new article on:
   - What happened next: Subsequent developments or updates that arose after this trigger event.
   - Deep Industry/Scientific Impact: How this news affects the broader market, consumer behavior, or scientific community.
   - Expert Interpretations & Debate: Diverse viewpoints, professional consensus, or alternative debates surrounding this breakthrough/policy.
   - Trend Integration: Naturally tie these follow-up points to the latest search behaviors found in the [ADDITIONAL TREND ANALYSIS & SEARCH DATA].
4. Ensure the article provides completely fresh, new analytical value that a reader would find useful AFTER having read the original source article.
"""

        # 트렌드 관련 컨텍스트 구성
        import json
        trend_context = f"""
---
# [ADDITIONAL TREND ANALYSIS & SEARCH DATA]
Core Seed Keyword: {trend_report.get('seed_keyword', '')}
Selected Article Angle: {angle.upper()} (Write the article using this dynamic journalistic lens)

1. USA Real-Time Google Daily Trends: {json.dumps(trend_report.get('google_trends', []))}
2. Pinterest Interest/Lifestyle Trends: {json.dumps(trend_report.get('pinterest_trends', {}))}
3. Microsoft Ads Monthly Keyword Volume & Ideas: {json.dumps(trend_report.get('ms_ads_keyword_ideas', []))}

You MUST integrate the core insights, search intent, and trending context above naturally into the article narrative. 
Additionally, strictly adhere to the following Editorial Angle directions:
- BREAKING/FOLLOW-UP: Focus on "What happened next", immediate developments, and future implications.
- DEEP ANALYSIS: Focus on "Why it matters", break down the data/statistics, and provide detailed analytical insight.
- PRACTICAL GUIDE: Focus on "How to", best practices, actionable tips, and steps for the reader.
"""

        seo_title_instructions = """
# [SEO TITLE OPTIMIZATION RULES]
1. DO NOT use any academic or generic prefixes using colons (e.g., Avoid "Clinical Progress:", "Breaking News:", "Market Shift:", "Industry Update:").
2. LEFT-LOAD the primary target keyword (e.g. "mRNA Cancer Vaccine", "US Job Market") right at the very beginning of the title.
3. Keep the title concise, active, and strictly under 60-70 characters. 
4. Use powerful, active, and engaging verbs (e.g., "Cuts", "Boosts", "Accelerates", "Resists", "Redefines") to improve the Click-Through Rate (CTR).
5. Example: 
   - BAD: "Clinical Progress: Personalized mRNA Cancer Vaccine Shows Promise in Melanoma Trial"
   - GOOD: "mRNA Cancer Vaccine Cuts Melanoma Recurrence in Phase 3 Trial"
"""

        prompt = f"""
{self.prompt_instruction}

{follow_up_instructions}

{seo_title_instructions}

{trend_context}

---

# [IMPORTANT SYSTEM CONSTRAINTS]
Today's Date: {current_date}
The current year is {current_year}. Make sure all time-specific statements, statistics, and forecasts in the generated article are relative to the current year {current_year}. Do not write about past years (like 2024 or 2025) as the current or upcoming year.{domain_specific_constraint}

# [In-Text Citation & Attribution Rules]
1. Attribution in Sentence: Whenever citing specific statistics, quotes, or exclusive breaking reports, explicitly name the source in the text using natural journalistic attribution:
   - Examples:
     * "According to a report by Reuters..."
     * "...as first reported by Bloomberg."
     * "Data from the U.S. Bureau of Labor Statistics shows that..."
     * "Speaking to The Wall Street Journal, [Name] stated..."
2. No Anonymous Claims: Never use vague phrases like "Sources say", "Studies show", or "Recent studies suggest" without specifying the organization or publication.
3. Anchor Formatting: Mark key source names or data points with markdown brackets if needed, e.g., "[Reuters reported](source_link)".

1. You must select the single most appropriate category slug from the following list of allowed slugs for the site '{target_site_domain}':
   Allowed Slugs: [{categories_str}]
   - FASHION & STYLE CRITICAL RULE: If you select the 'style' or 'fashion&style' category, the article MUST be strictly limited to celebrity outfits, clothing styles, fashion designers, runway shows, apparel, or the fashion industry. Do NOT use it for general building architecture, monuments, or logo/branding design. If the article is not about clothing/apparel fashion, you must select 'news' or other appropriate categories instead.
2. You must output the result strictly in JSON format matching the schema below.
3. The article must be written in English.
4. The article body content must be in HTML format (use only <p>, <h3>, etc. No H1-H2, H4-H6 tags. Subheadings must be written in <h3> tags (e.g., <h3>Subheading</h3>) and cannot be bold text (<b> or <strong>).
5. Do NOT include any "Sources:" or reference section at the end of the article content. All citations must be integrated naturally in the text.
6. Provide exactly 20 highly relevant SEO tags or keywords for the generated article in the "seo_tags" field. The 20 tags must be separated by commas (e.g., "keyword1, keyword2, ...").
7. IMAGE SEARCH STRATEGY & PERSON RELEVANCE RULES:
   - Identify whether one or more specific persons (athletes, celebrities, public figures, leaders) are genuinely the CENTRAL FOCUS of this article.
   - If a person is merely mentioned in passing, incidental, or part of a broad team/institution, DO NOT treat them as featured persons (return an empty list [] for "featured_persons").
   - If one or more persons ARE the central focus/protagonists of the article:
     * Rank them in "featured_persons" in strict order of prominence/importance (Protagonist #1 first, key opponent/counterpart #2). Maximum 2 persons.
   - In "fallback_topic_keyword", provide a clean, specific topical keyword representing the core subject or sport/event (e.g., 'boxing match', 'electric vehicle', 'cardiology surgery').
   - In "image_search_queries", provide an ordered array of search queries for finding header images, starting with the primary person (if any), then secondary person (if any), followed by the fallback topic keyword.
     * Example (Person-centric): ["Ben Whittaker", "Conor Wallace", "boxing match"]
     * Example (Topic-centric / No prominent person): ["space telescope", "astronomy exoplanet"]
   - Keep "search_keyword" as the primary query (the first item of "image_search_queries") for backwards compatibility.

# Output Schema (JSON):
{{
  "fact_check_rationale": "Before writing the article, briefly explain how you will adapt the facts from the source text and trends to fit the site's theme WITHOUT distorting or inventing any facts.",
  "title": "Article Title",
  "summary": "150-character summary paragraph",
  "content": "<p>Article body in HTML format...</p>",
  "selected_category": "selected-category-slug-from-allowed-list",
  "featured_persons": ["Prominent Person 1", "Prominent Person 2"],
  "fallback_topic_keyword": "A clean topic or sport keyword (e.g. 'boxing match' or 'space technology')",
  "image_search_queries": ["Prominent Person 1", "Prominent Person 2", "boxing match"],
  "search_keyword": "Prominent Person 1",
  "seo_tags": "tag1, tag2, tag3, tag4, tag5, tag6, tag7, tag8, tag9, tag10, tag11, tag12, tag13, tag14, tag15, tag16, tag17, tag18, tag19, tag20"
}}

# Source Article / Raw Text to Reconstruct:
{source_text}
"""
        # Call Gemini REST API (v1beta)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={self.api_key}"
        
        headers = {
            "Content-Type": "application/json"
        }
        
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": temperature,
                "maxOutputTokens": max_tokens
            }
        }
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=30) as response:
                body = response.read().decode("utf-8")
                res_json = json.loads(body)
                
                text_out = res_json['candidates'][0]['content']['parts'][0]['text']
                generated_data = json.loads(text_out)
                generated_data = self._normalize_image_queries(generated_data)
                self.validate_anonymous_claims(generated_data.get("content", ""), target_site_domain)
                return generated_data
        except Exception as e:
            from common.logger_setup import get_domain_logger
            logger = get_domain_logger(target_site_domain)
            logger.error(f"Gemini API trend-based generation failed: {e}")
            raise

    def generate_concise_trend_article(self, trend_keyword, traffic_val, news_context, raw_fact_text):
        """
        실시간 구글 트렌드 및 뉴스 팩트 소스를 기반으로 600단어 이하의 영문 저널리즘 기사를 생성합니다.
        """
        # 구글 트렌드 미국 기사는 14개 사이트용 STOP_PUBLISHING의 영향을 받지 않으며, 전용 플래그(STOP_GOOGLE_TREND)가 True일 때만 중단
        status_file = "config/status.json"
        if os.path.exists(status_file):
            try:
                with open(status_file, "r", encoding="utf-8") as sf:
                    data = json.load(sf)
                    if data.get("STOP_GOOGLE_TREND") is True:
                        from common.logger_setup import get_domain_logger
                        logger = get_domain_logger("google_trend_telegram")
                        logger.warning("[Stop Google Trend] STOP_GOOGLE_TREND is active. Aborting concise trend article generation.")
                        return None
            except Exception:
                pass

        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not set.")
            
        model_name = self.settings.get("ai_model", {}).get("model_name", "gemini-3.1-flash-lite")
        temperature = 0.5
        max_tokens = 1500  # 600단어 이하를 안전하게 수용하는 최적 토큰 수
        
        current_date = datetime.now().strftime("%Y-%m-%d")
        current_year = datetime.now().strftime("%Y")
        
        prompt = f"""
{self.prompt_instruction}

---

# [CRITICAL TASK REQUIREMENTS]
You are a senior investigative journalist writing a real-time breaking & analytical news report for a global news platform.
The topic is the real-time trending topic: "{trend_keyword}" (Google Search Traffic: {traffic_val}).

# [STRICT LENGTH CONSTRAINT - MANDATORY]
- The body content (<p>, <h3> paragraphs) MUST contain UNDER 600 WORDS (strictly between 400 and 550 words).
- DO NOT exceed 600 words. Keep the article concise, structured, punchy, and highly informative.

# [EDITORIAL & FORMATTING RULES]
1. TITLE:
   - High CTR, fact-based, active verb title under 70 characters.
   - Left-load key subject. Do NOT use colon prefixes like "Breaking:" or "Update:".
2. SUBHEADINGS:
   - Use ONLY <h3> tags for subheadings (e.g., <h3>Why This Shift Matters</h3>).
   - NEVER use <h1>, <h2>, <h4>-<h6>, or bold text (<b>, <strong>) as standalone subheadings.
3. IN-TEXT CITATIONS:
   - Attribute facts, figures, and quotes to reputable sources mentioned in the source data (e.g. "According to reports...", "Data indicates...").
   - NEVER use vague phrases like "Sources say" or "Studies show" without naming the entity.
4. NO SOURCES LIST:
   - Do NOT include any 'Sources:' or reference list at the end of the article.
5. HTML FORMAT:
   - Output HTML tags (<p>, <h3>) inside the JSON "content" field.
6. METADATA:
   - Exactly 20 comma-separated SEO tags.
   - 1-2 sentence compelling summary (under 160 characters).
   - A descriptive image search keyword.
   - Appropriate high-level category (e.g., Technology, Entertainment, Business, Sports, Science, Politics, Lifestyle).

# [SOURCE DATA & REAL-TIME NEWS ANCHOR]
Trend Keyword: {trend_keyword}
Estimated Search Volume: {traffic_val}
Today's Date: {current_date}, Year: {current_year}

Related Breaking News Headlines & Summaries:
{news_context}

Raw Fact & Context Extract:
{raw_fact_text}

# Output Schema (JSON only):
{{
  "title": "Clear, Fact-Driven Headline Under 70 Chars",
  "summary": "Compelling 150-char summary for meta description and notifications.",
  "category": "Technology | Entertainment | Business | Sports | Science | Politics",
  "content": "<p>Opening lead paragraph establishing the 5Ws and 1H...</p><h3>Analytical Context</h3><p>...</p><h3>Broader Implications</h3><p>...</p>",
  "search_keyword": "Precise search term for high-quality thumbnail image",
  "seo_tags": "tag1, tag2, tag3, tag4, tag5, tag6, tag7, tag8, tag9, tag10, tag11, tag12, tag13, tag14, tag15, tag16, tag17, tag18, tag19, tag20"
}}
"""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": temperature,
                "maxOutputTokens": max_tokens
            }
        }
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, context=ctx, timeout=35) as response:
            body = response.read().decode("utf-8")
            res_json = json.loads(body)
            
            text_out = res_json['candidates'][0]['content']['parts'][0]['text']
            generated_data = json.loads(text_out)
            
            # 1. 모호한 표현 검증
            self.validate_anonymous_claims(generated_data.get("content", ""), "google_trends")
            
            # 2. 단어 수 검증 (600단어 이하 엄격 검사)
            content_html = generated_data.get("content", "")
            clean_text = re.sub(r'<[^>]+>', ' ', content_html)
            words = re.findall(r'\b[A-Za-z0-9\'-]+\b', clean_text)
            word_count = len(words)
            generated_data["word_count"] = word_count
            
            return generated_data

    def validate_anonymous_claims(self, content_html, domain_key):
        """
        저널리즘 가이드라인 위배 모호한 표현(Sources say 등)이 본문에 포함되어 있는지 파이썬 코드 단에서 강제 검증합니다.
        """
        forbidden_pattern = r"\b(sources\s+say|studies\s+show|recent\s+studies\s+suggest|studies\s+suggest|anonymous\s+sources)\b"
        if re.search(forbidden_pattern, content_html, re.IGNORECASE):
            from common.logger_setup import get_domain_logger
            logger = get_domain_logger(domain_key)
            logger.warning(f"[{domain_key.upper()}] Anonymous claim detected in article body! Triggering regeneration...")
            raise ValueError("Factual Enforcer: Article contains forbidden anonymous claim phrases.")




# ==============================================================================
# 3. 이미지 검색 모듈 (ImageSearcher)
# ==============================================================================
