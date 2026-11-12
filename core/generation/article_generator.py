import os
import re
import json
import time
import urllib.request
import urllib.parse
import urllib.error
import ssl
from datetime import datetime
from core.generation.link_injector import LinkInjector

# Ingest API 계열 매체 (본문 내 인라인 내부 링크를 배제하고 Read more 텍스트 리스트만 유지)
INGEST_API_SITES = {"jobsnhire", "mobilenapps", "parentherald", "booksnreview"}

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
    "foodworldnews": "Food health news, culinary trends, food safety and recall notices, healthy gourmet recipes, and nutrition tips.",
    "medicaldaily": "보건의료 정책, 병원·제약바이오 산업 경영 및 신약 임상·R&D, 의학·약학 최신 학술 논문, 국민 건강관리 및 헬스 라이프스타일 전문 뉴스 (의약일보 한국어 보도 전용)."
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
                "max_tokens": 5120
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

    @staticmethod
    def count_body_words_excluding_headings(content_html: str) -> int:
        """
        소제목(<h3> 등)을 글자 수에서 완전히 제외하고,
        순수 본문 문단(<p> 등)의 영문 단어 수를 정확하게 계산합니다.
        """
        if not content_html:
            return 0
        # 모든 헤딩 태그(<h1~h6> 및 그 내부 텍스트) 완전 제거
        text_no_headings = re.sub(r'<h[1-6][^>]*>.*?</h[1-6]>', '', content_html, flags=re.DOTALL | re.IGNORECASE)
        # 잔여 HTML 태그 제거
        clean_text = re.sub(r'<[^>]+>', ' ', text_no_headings)
        # 영문 단어 및 한국어 어절 추출
        words = re.findall(r"[가-힣A-Za-z0-9'-]+", clean_text)
        return len(words)

    @staticmethod
    def build_top_summary_box(summary_bullets: list, fallback_summary: str = "") -> str:
        """
        의약일보(medicaldaily) 기사 본문 최상단에 배치할 고밀도·임팩트 [핵심 요약] 박스를 생성합니다.
        Q&A 섹션 대신 기사 상단에 핵심 팩트·수치·파급 효과를 길고 임팩트 있게 요약합니다.
        """
        cleaned_bullets = []
        if isinstance(summary_bullets, list):
            for b in summary_bullets:
                text = str(b or "").strip()
                if text:
                    cleaned_bullets.append(text)

        if not cleaned_bullets and fallback_summary:
            sentences = [s.strip() for s in re.split(r'(?<=[.!?다])\s+', fallback_summary.strip()) if s.strip()]
            cleaned_bullets = sentences[:3] if sentences else [fallback_summary.strip()]

        if not cleaned_bullets:
            return ""

        li_items = []
        for idx, item in enumerate(cleaned_bullets[:3]):
            margin_b = "0" if idx == len(cleaned_bullets[:3]) - 1 else "8px"
            li_items.append(
                f'<li style="margin-bottom:{margin_b};line-height:1.7;word-break:keep-all;">{item}</li>'
            )

        box_style = (
            "border:1px solid #c7d2fe;"
            "background-color:#ffffff;"
            "padding:16px 20px;"
            "margin-top:0;"
            "margin-bottom:24px;"
            "border-radius:4px;"
        )
        title_style = (
            "margin-top:0;"
            "margin-bottom:10px;"
            "font-weight:700;"
            "font-size:15px;"
            "color:#2563eb;"
            "letter-spacing:-0.3px;"
        )
        ul_style = (
            "margin-top:0;"
            "margin-bottom:0;"
            "padding-left:18px;"
            "color:#1e293b;"
            "font-size:14px;"
        )
        return (
            f'<div class="md-summary-box" style="{box_style}">'
            f'<p style="{title_style}">핵심 요약</p>'
            f'<ul style="{ul_style}">{"".join(li_items)}</ul>'
            f'</div>'
        )

    @staticmethod
    def strip_qa_section_for_medicaldaily(content_html: str) -> str:
        """
        의약일보(medicaldaily) 본문에서 Q&A / FAQ 섹션(Key Questions Answered, 자주 묻는 질문 등)을 제거합니다.
        """
        if not content_html:
            return ""
        pattern = re.compile(
            r'<h[234][^>]*>\s*(?:Key Questions Answered|자주 묻는 질문|핵심 Q&amp;A|핵심 Q&A|Q&amp;A).*',
            flags=re.IGNORECASE | re.DOTALL,
        )
        return pattern.sub("", content_html).strip()

    @staticmethod
    def normalize_and_enforce_structure(content_html: str, target_domain: str = "general") -> tuple:
        """
        1. 비표준 헤딩(h1, h2, h4, bold)을 <h3> 태그로 자동 정규화.
        2. 첫 문단 위에 소제목이 있을 경우, 양괄식 리드 원칙에 따라 첫 문단 아래로 자동 재배치.
        3. 소제목 개수를 카운트하여 반환.
        """
        if not content_html:
            return content_html, 0

        content = content_html.strip()

        # 1. h1, h2, h4, h5, h6 태그를 <h3>로 자동 정규화
        content = re.sub(r'<(h[12456])[^>]*>(.*?)</\1>', r'<h3>\2</h3>', content, flags=re.IGNORECASE | re.DOTALL)

        # 2. 독립 라인으로 작성된 볼드체 소제목(예: <p><b>Subheading</b></p>)을 <h3>로 정규화
        content = re.sub(r'<p>\s*<(?:b|strong)>(.*?)</(?:b|strong)>\s*</p>', r'<h3>\1</h3>', content, flags=re.IGNORECASE)

        # 3. 양괄식 첫 문단 강제 (소제목이 첫 문단 위에 오는 경우 자동 보정)
        heading_first_match = re.match(r'^\s*<h3>(.*?)</h3>\s*(<p>.*?</p>)', content, flags=re.DOTALL | re.IGNORECASE)
        if heading_first_match:
            heading_part = f"<h3>{heading_first_match.group(1)}</h3>"
            first_p = heading_first_match.group(2)
            rest_of_content = content[heading_first_match.end():]
            content = f"{first_p}\n{heading_part}\n{rest_of_content}".strip()

        # 4. 소제목 개수 산출
        headings = re.findall(r'<h3>(.*?)</h3>', content, flags=re.IGNORECASE | re.DOTALL)
        heading_count = len(headings)

        return content, heading_count

    @staticmethod
    def validate_and_enrich_seo_tags(raw_tags_str: str, content_html: str, selected_category: str) -> str:
        """
        LLM이 생성한 SEO 태그를 검증하고, 만약 20개 미만이거나 중복이 있을 경우
        본문의 핵심 키워드 및 카테고리를 활용하여 중복 없이 정확히 20개로 완성합니다.
        불필요한 LLM 재시도로 인한 비용 낭비를 원천 차단합니다.
        """
        tags = []
        if raw_tags_str:
            for t in raw_tags_str.split(","):
                cleaned = t.strip()
                if cleaned and cleaned.lower() not in [x.lower() for x in tags]:
                    tags.append(cleaned)

        if len(tags) < 20:
            clean_text = re.sub(r'<[^>]+>', ' ', content_html or "")
            words = re.findall(r"\b[A-Z][a-z]{3,}\b|\b[a-z]{4,}\b|[가-힣]{2,}", clean_text)
            stopwords = {
                "this", "that", "with", "from", "have", "were", "been", "their", "there", 
                "about", "which", "would", "could", "should", "article", "report", "news", 
                "they", "will", "what", "more", "also", "into", "than", "then", "some",
                "있는", "있다", "대한", "위해", "통해", "따르면", "경우", "이번", "관련", "밝혔다"
            }
            
            candidates = []
            if selected_category:
                candidates.append(selected_category.replace("-", " "))
            
            for w in words:
                wl = w.lower()
                if wl not in stopwords and wl not in [x.lower() for x in tags] and wl not in [x.lower() for x in candidates]:
                    candidates.append(w)
                    if len(tags) + len(candidates) >= 20:
                        break
            
            for c in candidates:
                if len(tags) < 20:
                    tags.append(c)
                    
        return ", ".join(tags[:20])

    @staticmethod
    def is_clickbait_headline(title: str) -> bool:
        """
        구글 뉴스 실무 가이드에 위배되는 자극적/과장된 클릭베이트 표현을 검출합니다.
        """
        if not title:
            return False
        clickbait_patterns = [
            r"\b(shocking|unbelievable|mind-blowing|you won't believe|jaw-dropping)\b",
            r"\b(will blow your mind|what happened next will|everyone is talking about)\b",
            r"\b(miracle cure|magic secret|the real reason why)\b"
        ]
        title_lower = title.lower()
        for pattern in clickbait_patterns:
            if re.search(pattern, title_lower):
                return True
        return False

    def generate(self, source_text, target_site_domain, available_categories, recommended_category=None, min_words=1200, max_tokens=None, source_url=None):
        if self._is_stop_publishing_active():
            from common.logger_setup import get_domain_logger
            logger = get_domain_logger(target_site_domain)
            logger.warning(f"[{target_site_domain}] [Stop Publishing Kill Switch] STOP_PUBLISHING is active. Aborting article generation.")
            return None

        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not set.")

        if not source_url and source_text:
            m_ref = re.search(r"Reference URL:\s*(https?://[^\s\n\r]+)", source_text)
            if m_ref:
                source_url = m_ref.group(1).strip()
            
        model_name = self.settings.get("ai_model", {}).get("model_name", "gemini-3.1-flash-lite")
        temperature = self.settings.get("ai_model", {}).get("temperature", 0.6)
        max_tokens = max_tokens if max_tokens is not None else self.settings.get("ai_model", {}).get("max_tokens", 5120)
        
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

        # 자사 과거 기사 풀 준비 (자연스러운 문맥 인라인 링크 결합용 - 12개 전 매체 활성화)
        enable_internal = True
        enable_readmore = target_site_domain not in INGEST_API_SITES
        sister_pool = []
        prompt_sister_lines = []
        sister_article_section = ""
        if enable_internal:
            try:
                # 소스 텍스트에서 주제 키워드 추출 (의약일보는 한국어 명사 추출 시맨틱 검색 적용)
                topic_query = ""
                if target_site_domain == "medicaldaily":
                    ko_words = [
                        w for w in re.findall(r"[가-힣]{2,}", source_text)
                        if len(w) >= 2 and w not in {"의약일보", "기사", "보도", "뉴스", "기자", "밝혔다", "따르면", "연구", "대한", "통해", "위해", "있는"}
                    ]
                    if ko_words:
                        topic_query = " ".join(ko_words[:4])
                    else:
                        orig_title_m = re.search(r"Original Title:\s*(.*)", source_text)
                        if orig_title_m:
                            topic_query = orig_title_m.group(1).strip()
                else:
                    orig_title_m = re.search(r"Original Title:\s*(.*)", source_text)
                    if orig_title_m:
                        topic_raw = orig_title_m.group(1).strip()
                        topic_words = [
                            w for w in re.findall(r"[A-Za-z]{4,}", topic_raw)
                            if w.lower() not in {"novel", "shows", "phase", "trial", "study", "pulls", "taps", "with", "from", "that"}
                        ]
                        if topic_words:
                            topic_query = " ".join(topic_words[:2])

                pool_limit = 5 if target_site_domain == "medicaldaily" else 2
                recent_arts = LinkInjector.load_related_articles(target_site_domain, limit=pool_limit, topic_query=topic_query)
                for idx, r_art in enumerate(recent_arts, start=1):
                    sister_pool.append({
                        "id": idx,
                        "article_id": r_art.get("article_id", ""),
                        "title": r_art.get("title", ""),
                        "url": r_art.get("url", "")
                    })
                    prompt_sister_lines.append(f"[{idx}] \"{r_art.get('title', '')}\"")
                
                if prompt_sister_lines:
                    sister_article_section = f"""
# [OPTIONAL SISTER ARTICLES FOR CONTEXTUAL BACKGROUND]
The following recent stories from our publication are available for background reference:
{chr(10).join(prompt_sister_lines)}

RULES FOR SISTER ARTICLES (9:1 HIERARCHY MANDATE):
1. PRIMARY FOCUS: The provided source text MUST constitute 90%+ of the article. Do NOT let sister articles dictate the topic or appear in headlines/lead sentences.
2. RELEVANCE CHECK: If and ONLY if one of the above stories has a natural journalistic link (parallel industry event, preceding milestone, or broader trend) to the primary news, weave that context into at most ONE body sentence.
3. FAIL-SAFE: If NEITHER story shares a legitimate, credible connection to the breaking news, DO NOT force an awkward link. Simply set "contextual_link": null.
4. CLEAN PROSE: DO NOT use <a> HTML tags in the 'content' narrative. Keep text natural and specify the 3-to-6 word anchor phrase in the JSON field below.
"""
            except Exception as e:
                from common.logger_setup import get_domain_logger
                get_domain_logger(target_site_domain).warning(f"Failed loading sister pool for prompt: {e}")

        if target_site_domain == "medicaldaily":
            sister_korean_section = ""
            if prompt_sister_lines:
                sister_korean_section = f"""
# [자사(의약일보) 관련 기사 문맥 인용 지침 - 동향·경향·유사 사례 결합]
현재 의약일보에 보도된 최근 관련 기사 목록입니다:
{chr(10).join(prompt_sister_lines)}

1. [동향·경향·유사 사례·배경] 4대 인용 프레임 적용:
   - 위 기사 중 현재 주제(질환 관리, 제약바이오, 의료 기술, 보건 정책, 생활 건강 등)와 가장 관련 있는 1건을 선정하여, 본문 3~4번째 문단에 아래 4대 프레임 중 하나로 자연스럽게 1문장 언급하십시오.
     * Frame A (업계 동향/추세): "국내외 보건·의료계에서도 최근 [앵커 문구] 흐름이 가속화되는 가운데..."
     * Frame B (정책/학술 경향): "의학계에서는 이번 연구가 앞선 [앵커 문구]와 같은 예방 중심 패러다임과 궤를 같이한다고 평가한다."
     * Frame C (유사 사례/예시): "이는 앞서 보고된 [앵커 문구] 사례와 마찬가지로, 환자 맞춤형 접근의 중요성을 시사한다."
     * Frame D (배경/선행 보도): "전문가들은 지난 [앵커 문구] 당시 지적되었던 인프라 확충이 동반되어야 한다고 강조했다."
2. 억지 대조/비교 인용 절대 금지:
   - '대조적으로', '이와 달리', '반면에', '사례와 달리' 등 인위적이고 어색한 억지 대조는 절대로 사용하지 마십시오.
3. 앵커 문구(anchor_phrase) 지정:
   - 본문 내 실제 작성한 자연스러운 2~6어절 서술 문구를 JSON의 "contextual_link" -> "anchor_phrase"에 정확히 기입하십시오.
   - 본문 HTML 안에 직접 <a> 태그를 작성하지 마십시오. (파이썬이 자동 치환합니다)
"""
            prompt = f"""
당신은 대한민국 대표 보건의료·제약바이오·병원·학술 전문 언론사 **'의약일보(Medical Daily)'**의 수석 의학·보건 전문기자입니다.
제공된 해외/국내 의학·보건·제약 뉴스 원문 팩트를 바탕으로, 한국 독자와 의료·제약 업계 관계자, 일반 국민이 깊이 있게 읽을 수 있는 **고품격 한국어 심층 기획 보도기사**를 작성하십시오.

# [필수 시스템 제약사항]
- 오늘 날짜: {current_date} (현재 연도: {current_year}년)
- 매체 도메인: 의약일보 (medicaldaily.co.kr)
- 허용된 분류(selected_category) 목록: [{categories_str}]
  * 기사의 핵심 주제에 맞춰 '정책', '경영', '학술', '병원·제약', '라이프', '오피니언' 중 가장 적합한 분류 1개를 정확히 선택하십시오.
  * 특히 '라이프' 분류는 국민 실생활 건강 상식, 건강 관리 팁, 식습관, 운동, 웰빙, 예방 의학을 집중 조명하는 핵심 분류입니다. 건강 상식·팁 및 생활 웰빙 뉴스인 경우 반드시 '라이프'로 분류하십시오.
{sister_korean_section}
# [의약일보 한국어 기사 작성 7대 원칙]
1. **100% 한국어 전문 보도 문체**:
   - 제목(title), 요약(summary), 상단 핵심 요약(top_summary_bullets), 본문(content), SEO 태그(seo_tags)는 모두 자연스럽고 격조 높은 한국어 언론 보도 문체(`~했다`, `~밝혔다`, `~분석됐다`, `~전망이다` 등 평서형 스트레이트/기획 기사체)로 작성하십시오.
2. **하단 Q&A(자주 묻는 질문) 전면 배제 & 상단 [핵심 요약] 불릿 생성**:
   - 본문 하단에 Q&A(`Key Questions Answered`, `자주 묻는 질문` 등) 섹션을 절대 넣지 마십시오.
   - 대신 기사 상단 요약 박스에 들어갈 `top_summary_bullets` 배열(3~4개 항목)을 작성하십시오.
   - 각 불릿 항목은 단순 단답형 한 줄이 아니라, **핵심 키워드 볼드 강조(`<strong>...</strong>`) + 구체적 수치·임상/정책 배경·의료 현장 및 시장 파급력을 담은 90~150자 내외의 길고 임팩트 있는 1~2문장**으로 밀도 있게 작성하십시오.
3. **양괄식 리드 문단 (서두)**:
   - 본문(`content`)의 첫 번째 `<p>` 문단 위에는 소제목(`<h3>`)을 두지 마십시오. 첫 문단에서 핵심 사건, 연구 기관/정부 부처, 주요 수치 및 의학적·사회적 함의를 명쾌하게 종합 제시하십시오.
4. **기승전결 심층 서사 및 소제목(`<h3>`) 3~5개 구성**:
   - 리드 문단 이후 `<h3>` 소제목을 3~5개 배치하여 (1) 연구·정책 배경과 발생 경위, (2) 구체적 임상 데이터·통계 수치 분석, (3) 보건의료계·제약바이오 산업 파급 효과 및 전문가 시각, (4) 향후 과제와 전망 순으로 깊이 있게 전개하십시오.
   - 분량은 공백 포함 최소 2,500자 이상(한국어 600~1,000어절 이상)의 풍부한 심층 기사로 작성하십시오.
5. **명확한 출처 명시 (In-Text Attribution - 필수 규칙)**:
   - 본문 2~3번째 문단 중 하나에는 반드시 원문 소스를 제공한 해외/국내 언론사, 연구기관, 학술지(NEJM, Nature, Lancet 등), 또는 보건당국(FDA, CDC, WHO 등)의 명칭을 명시한 정규 인용 문구를 1회 자연스럽게 포함하십시오.
   - [표준 인용 문구 형태]:
     * 형태 1: `[기관/외신명] 보도에 따르면`, `[기관명] 발표에 따르면`, `[기관명] 통계 자료에 따르면` (예: "엔드포인츠뉴스(Endpoints News) 보도에 따르면", "미국 FDA 발표에 따르면", "로이터 통신 보도에 따르면", "외신 보도에 따르면")
     * 형태 2: `[기관명]의 [연도/보고서/전망명]` (예: "HAMA의 2026년 업계 전망", "보건복지부의 2026년 필수의료 지원계획", "국립보건원의 최신 임상 보고서", "CBRE의 2025년 숙박업 데이터에 따르면")
   - 원문에 없는 허위 수치나 사실을 날조하지 마십시오.
6. **이미지 검색 쿼리 이원화 (`image_search_queries`)**:
   - 0순위 의약일보 DB 검색을 위해 첫 번째·두 번째 원소에는 **한국어 핵심 주제어 2개**(예: `"건강검진"`, `"제약 임상시험"`)를 넣고, 1~3순위 글로벌 스톡(Pexels, Wikimedia, Unsplash) 검색을 위해 세 번째·네 번째 원소에는 **영문 핵심 검색어 2개**(예: `"medical researcher laboratory"`, `"clinical trial hospital"`)를 함께 배열로 작성하십시오.

# Output Schema (반드시 순수 JSON만 출력):
{{
  "fact_check_rationale": "원문 팩트를 왜곡 없이 의약일보 독자 관점으로 재구성한 편집 근거 요약",
  "title": "핵심 팩트와 수치가 살아있는 45자 이내의 한국어 헤드라인 (클릭베이트 금지)",
  "summary": "기사의 핵심 내용을 압축한 150~200자 한국어 요약문",
  "top_summary_bullets": [
    "<strong>핵심 연구·정책 결론:</strong> 구체적인 임상 수치와 발표 기관, 핵심 발견 내용을 임팩트 있게 설명하는 1~2문장 요약",
    "<strong>작용 기전 및 주요 데이터:</strong> 기존 치료법·제도 대비 개선된 지표와 안전성·유효성 근거를 상세히 짚어주는 1~2문장 요약",
    "<strong>의료 현장 및 산업계 파급력:</strong> 환자 치료 가이드라인 변화나 제약·바이오 시장 및 보건 정책에 미칠 실질적 영향을 짚어주는 1~2문장 요약"
  ],
  "content": "<p>양괄식 첫 리드 문단...</p><p>도입 상세 설명 문단...</p><h3>첫 번째 소제목</h3><p>심층 본문...</p><h3>두 번째 소제목</h3><p>심층 본문...</p><h3>세 번째 소제목</h3><p>심층 본문...</p>",
  "contextual_link": {{
    "target_article_id": 1,
    "anchor_phrase": "본문 내 정확히 등장하는 2~5어절 한국어 구문",
    "rationale": "자사 기사와의 문맥적 연관성 설명 (연관성이 없으면 contextual_link 전체를 null로 설정)"
  }},
  "selected_category": "허용된 분류 중 1개 (예: 학술, 병원·제약, 정책, 경영, 라이프, 오피니언)",
  "featured_persons": ["주요 인물명(영문 또는 한글)"],
  "fallback_topic_keyword": "medical research",
  "image_search_queries": ["한국어 핵심키워드1", "한국어 핵심키워드2", "english medical keyword 1", "english medical keyword 2"],
  "search_keyword": "대표 한국어 핵심 키워드",
  "seo_tags": "한국어태그1, 한국어태그2, 한국어태그3, 한국어태그4, 한국어태그5, 한국어태그6, 한국어태그7, 한국어태그8, 한국어태그9, 한국어태그10, 한국어태그11, 한국어태그12, 한국어태그13, 한국어태그14, 한국어태그15, 한국어태그16, 한국어태그17, 한국어태그18, 한국어태그19, 한국어태그20"
}}

# Source Article / Raw Text to Reconstruct:
{source_text}
"""
        else:
            prompt = f"""
{self.prompt_instruction}

---

# [IMPORTANT SYSTEM CONSTRAINTS]
Today's Date: {current_date}
The current year is {current_year}. Make sure all time-specific statements, statistics, and forecasts in the generated article are relative to the current year {current_year}. Do not write about past years (like 2024 or 2025) as the current or upcoming year.{domain_specific_constraint}{sister_article_section}

# [CORE INVESTIGATIVE JOURNALISM MANDATES - {min_words}+ WORDS & NARRATIVE ARC]
1. LENGTH REQUIREMENT: The narrative body text (<p> paragraphs) MUST contain AT LEAST {min_words} WORDS (excluding subheadings). Write a rich, thorough, deep-dive investigative article with extensive context, verifiable data, and multi-faceted analysis.
2. DEDUCTIVE OPENING LEAD (양괄식 서두): The very first paragraph (<p>) MUST synthesize the core breaking development, key figures, and broader significance WITHOUT any preceding subheading and without cliché summary phrases.
3. PROGRESSIVE NARRATIVE ARC (기승전결): After the opening lead, develop the story progressively using EXACTLY 3 TO 5 contextual <h3> subheadings covering:
   - 기 (Context & Origins): Chronological background and trigger event.
   - 승 (Evidence & Data): Detailed breakdown of official numbers, metrics, and primary findings.
   - 전 (Systemic Impact & Critical Analysis): Repercussions on market/society/science, diverse expert perspectives, and counterarguments.
   - 결 (Outlook & Key Milestones): Strategic implications and concrete forward-looking variables.
4. IN-TEXT ATTRIBUTION: Attribute facts, numbers, and quotes explicitly to named entities (e.g., "According to Reuters...", "Data released by the FDA indicates..."). Never use anonymous phrases like "Sources say" or "Studies show".
5. HEADLINE: Informative, active-verb, fact-based title under 70 characters. Strictly avoid sensational or clickbait expressions.
6. Allowed Slugs for site '{target_site_domain}': [{categories_str}]

# Output Schema (JSON only):
{{
  "fact_check_rationale": "Briefly explain how you will adapt the facts to the site's theme without distortion.",
  "title": "Clear, Fact-Driven Headline Under 70 Chars",
  "summary": "Compelling 150-character summary paragraph",
  "content": "<p>Opening lead paragraph establishing core event and significance...</p><h3>Subheading 1</h3><p>Detailed background...</p><h3>Subheading 2</h3><p>Data and evidence...</p><h3>Subheading 3</h3><p>Critical impact...</p>",
  "contextual_link": {{
    "target_article_id": 1,
    "anchor_phrase": "3 to 6 word contextual phrase",
    "rationale": "Why this sister article is contextually relevant (or null if no natural connection)"
  }},
  "selected_category": "selected-category-slug-from-allowed-list",
  "featured_persons": ["Prominent Person 1", "Prominent Person 2"],
  "fallback_topic_keyword": "A clean topical keyword (e.g. 'space telescope')",
  "image_search_queries": ["Prominent Person 1", "space telescope"],
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
            with urllib.request.urlopen(req, context=ctx, timeout=60) as response:
                body = response.read().decode("utf-8")
                res_json = json.loads(body)
                
                # Extract text content from Gemini response
                text_out = res_json['candidates'][0]['content']['parts'][0]['text']
                # Parse output JSON from LLM
                generated_data = json.loads(text_out)
                generated_data = self._normalize_image_queries(generated_data)
                
                # --- [코드 레벨 결정론적 후처리 & 가드레일 (비용 최소화 및 정합성 보장)] ---
                raw_content = generated_data.get("content", "")
                if target_site_domain == "medicaldaily":
                    raw_content = self.strip_qa_section_for_medicaldaily(raw_content)
                norm_content, h_count = self.normalize_and_enforce_structure(raw_content, target_site_domain)

                # --- [외·내부 인라인 하이퍼링크 주입 후처리 (매체별 분기)] ---
                try:
                    enable_internal = True
                    enable_readmore = target_site_domain not in INGEST_API_SITES
                    contextual_link = generated_data.get("contextual_link")
                    article_ctx = f"{generated_data.get('title', '')} {generated_data.get('summary', '')} {generated_data.get('search_keyword', '')}"
                    norm_content = LinkInjector.process(
                        html_content=norm_content,
                        site=target_site_domain,
                        source_url=source_url,
                        contextual_link=contextual_link,
                        sister_articles=sister_pool,
                        enable_internal_links=enable_internal,
                        enable_readmore_box=enable_readmore,
                        article_context=article_ctx,
                    )
                except Exception as link_err:
                    from common.logger_setup import get_domain_logger
                    get_domain_logger(target_site_domain).warning(f"Link injection failed, using raw content: {link_err}")

                # 의약일보(medicaldaily)의 경우 Q&A 대신 본문 최상단에 고밀도 [핵심 요약] 박스 배치
                if target_site_domain == "medicaldaily" and "md-summary-box" not in norm_content:
                    top_box = self.build_top_summary_box(
                        generated_data.get("top_summary_bullets"),
                        generated_data.get("summary", ""),
                    )
                    if top_box:
                        norm_content = f"{top_box}\n{norm_content}"

                word_count = self.count_body_words_excluding_headings(norm_content)
                
                # 20개 SEO 태그 코드 레벨 보정 완성
                raw_tags = generated_data.get("seo_tags", "")
                cat_slug = generated_data.get("selected_category", "")
                final_tags = self.validate_and_enrich_seo_tags(raw_tags, norm_content, cat_slug)
                
                generated_data["content"] = norm_content
                generated_data["word_count"] = word_count
                generated_data["heading_count"] = h_count
                generated_data["seo_tags"] = final_tags
                
                from common.logger_setup import get_domain_logger
                logger = get_domain_logger(target_site_domain)
                logger.info(f"[{target_site_domain}] [Investigative Metrics] Word Count: {word_count} words (headings excluded), Subheadings: {h_count} (<h3>)")
                
                # 클릭베이트 검증 로깅
                if self.is_clickbait_headline(generated_data.get("title", "")):
                    logger.warning(f"[{target_site_domain}] Potential clickbait phrasing detected in title: '{generated_data.get('title')}'")
                
                # 익명 클레임 코드 레벨 검증
                self.validate_anonymous_claims(norm_content, target_site_domain)
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
        max_tokens = self.settings.get("ai_model", {}).get("max_tokens", 2048)
        
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
            with urllib.request.urlopen(req, context=ctx, timeout=60) as response:
                body = response.read().decode("utf-8")
                res_json = json.loads(body)
                
                text_out = res_json['candidates'][0]['content']['parts'][0]['text']
                generated_data = json.loads(text_out)
                generated_data = self._normalize_image_queries(generated_data)
                
                # --- [코드 레벨 결정론적 후처리 & 가드레일] ---
                raw_content = generated_data.get("content", "")
                norm_content, h_count = self.normalize_and_enforce_structure(raw_content, target_site_domain)

                # --- [외·내부 인라인 하이퍼링크 주입 후처리 (매체별 분기)] ---
                try:
                    enable_internal = target_site_domain not in INGEST_API_SITES
                    m_ref = re.search(r"Reference URL:\s*(https?://[^\s\n\r]+)", source_text or "")
                    trend_source_url = m_ref.group(1).strip() if m_ref else None
                    norm_content = LinkInjector.process(
                        html_content=norm_content,
                        site=target_site_domain,
                        source_url=trend_source_url,
                        enable_internal_links=enable_internal,
                    )
                except Exception as link_err:
                    from common.logger_setup import get_domain_logger
                    get_domain_logger(target_site_domain).warning(f"Trend link injection failed, using raw content: {link_err}")

                word_count = self.count_body_words_excluding_headings(norm_content)
                
                raw_tags = generated_data.get("seo_tags", "")
                cat_slug = generated_data.get("selected_category", "")
                final_tags = self.validate_and_enrich_seo_tags(raw_tags, norm_content, cat_slug)
                
                generated_data["content"] = norm_content
                generated_data["word_count"] = word_count
                generated_data["heading_count"] = h_count
                generated_data["seo_tags"] = final_tags
                
                from common.logger_setup import get_domain_logger
                logger = get_domain_logger(target_site_domain)
                logger.info(f"[{target_site_domain}] [Trend Investigative Metrics] Word Count: {word_count} words (headings excluded), Subheadings: {h_count} (<h3>)")
                
                if self.is_clickbait_headline(generated_data.get("title", "")):
                    logger.warning(f"[{target_site_domain}] Potential clickbait phrasing detected in trend title: '{generated_data.get('title')}'")
                
                self.validate_anonymous_claims(norm_content, target_site_domain)
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
