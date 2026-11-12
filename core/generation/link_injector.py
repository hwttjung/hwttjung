"""
Link Injector Engine
Phase 2 Implementation:
- 외부 링크 정제: rel="nofollow", class="external_red", target="_blank"
- 내부 링크 주입: BeautifulSoup 기반 국소 텍스트 노드 탐색, 헤딩/기존 링크 보호, 2~4단어 구문 매칭
- 5대 부작용 방어: 문단당 1개 제한, 1 URL = 1 Link, 대소문자 보존, 싱글톤 캐시, Zero-Crash Fallback
"""
import os
import re
import json
import logging
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup, NavigableString
from common.logger_setup import get_domain_logger

logger = logging.getLogger(__name__)


class LinkInjector:
    """
    본문 내 외부 출처 링크 정제 및 자사 내부 관련 글 링크 주입 엔진.
    """

    _POOL_CACHE: Dict[str, List[Dict[str, Any]]] = {}

    @classmethod
    def load_internal_pool(cls, site: str, max_items: int = 50) -> List[Dict[str, Any]]:
        """
        자사 기사 풀 로더 (인메모리 캐싱 + Graceful Fallback).
        published_history.json 및 data/generated_articles에서 유효한 기사 목록을 추출합니다.
        """
        if site in cls._POOL_CACHE:
            return cls._POOL_CACHE[site]

        pool: List[Dict[str, Any]] = []
        history_path = "data/published_history.json"

        try:
            # 1. generated_articles 폴더에서 실존 기사 ID 및 URL 매핑 수집
            generated_dir = "data/generated_articles"
            id_url_map: Dict[str, Dict[str, Any]] = {}
            if os.path.exists(generated_dir):
                for fname in os.listdir(generated_dir):
                    if fname.startswith(f"{site}_") and fname.endswith(".json"):
                        fpath = os.path.join(generated_dir, fname)
                        try:
                            with open(fpath, "r", encoding="utf-8") as gf:
                                gdata = json.load(gf)
                                gen_info = gdata.get("generated", {})
                                art_id = gdata.get("article_id")
                                title = gen_info.get("title", "")
                                if art_id and title:
                                    saved_url = gdata.get("url")
                                    if saved_url and str(saved_url).startswith("/"):
                                        public_url = f"https://www.{site}.com{saved_url}"
                                    elif saved_url and str(saved_url).startswith("http"):
                                        public_url = str(saved_url)
                                    else:
                                        date_str = gdata.get("timestamp", "20261109")[:10].replace("-", "")
                                        slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")
                                        public_url = f"https://www.{site}.com/articles/{art_id}/{date_str}/{slug}.htm"
                                    
                                    # 키워드 추출
                                    raw_tags = gen_info.get("seo_tags", "")
                                    keywords = [k.strip() for k in raw_tags.split(",") if len(k.strip().split()) >= 2]
                                    id_url_map[title.lower()] = {
                                        "url": public_url,
                                        "title": title,
                                        "keywords": keywords[:5],
                                    }
                        except Exception as e:
                            logger.debug("Failed reading generated article %s: %s", fname, e)

            # 2. published_history.json과 결합
            if os.path.exists(history_path):
                with open(history_path, "r", encoding="utf-8") as f:
                    hist_data = json.load(f)
                    site_items = hist_data.get(site, []) if isinstance(hist_data, dict) else []
                    
                    for item in site_items[-max_items:]:
                        title = item.get("title", "").strip()
                        if not title:
                            continue
                        
                        mapped = id_url_map.get(title.lower())
                        if mapped:
                            pool.append(mapped)
                        else:
                            # fallback placeholder URL with title-based slug
                            date_str = item.get("date", "20261109").replace("-", "")
                            slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")
                            fallback_url = f"https://www.{site}.com/articles/recent/{date_str}/{slug}.htm"
                            words = title.split()
                            phrase = " ".join(words[:3]) if len(words) >= 3 else title
                            pool.append({
                                "url": fallback_url,
                                "title": title,
                                "keywords": [phrase],
                            })

        except Exception as e:
            logger.warning("Error loading internal pool for %s: %s", site, e)
            return []

        cls._POOL_CACHE[site] = pool
        return pool

    @staticmethod
    def extract_significant_keywords(text: str) -> set:
        """
        텍스트(제목/요약 등)에서 조사 및 일반 불용어를 제외한 의미 있는 핵심 키워드(한국어/영문) 집합을 추출합니다.
        """
        if not text:
            return set()
        clean = re.sub(r'<[^>]+>', ' ', text)
        words = re.findall(r'[가-힣]{2,}|[A-Za-z]{3,}', clean)
        stopwords = {
            "기사", "보도", "뉴스", "관련", "위한", "대한", "통해", "따른", "이번", "경우",
            "확인", "가이드", "총정리", "추천", "비교", "전망", "발표", "분석", "밝혔다",
            "사례", "대조적", "대조", "반면", "달리", "과거", "이와", "news", "report",
            "article", "about", "with", "from", "their", "this", "that", "what", "more",
            "also", "into", "than", "then", "some", "were", "been", "have", "could", "would"
        }
        return {w.lower() for w in words if w.lower() not in stopwords}

    @classmethod
    def inject_natural_inline_link(
        cls,
        html_content: str,
        contextual_link: Optional[Dict[str, Any]],
        sister_articles: List[Dict[str, Any]],
        article_context: Optional[str] = None,
    ) -> str:
        """
        LLM이 식별한 문맥 구문(anchor_phrase)을 파이썬에서 6단계 결정론적 필터를 거쳐
        실존하는 자사 기사 URL로 안전하게 1회 치환합니다.
        
        [6대 결정론적 가드레일]
        1. Fail-Safe: contextual_link가 None/null이거나 필수 필드가 없으면 원본 그대로 반환 (Zero-Link)
        2. URL 무결성: 파이썬이 보유한 sister_articles 풀의 실존 URL 매핑 (환각 원천 차단)
        3. 앵커 길이 통제: 3~6단어 (한국어 2~6어절) 엄격 검증
        4. 중첩 방지: 이미 <a> 태그나 헤딩/인용구/요약박스 내부에 있는 텍스트는 치환 금지
        5. 단 1회 매칭: 본문 전체에서 최초 1회만 치환하여 과도한 링크 방지
        6. 의미적 연관성(Semantic Relevance) 및 억지 대조 차단:
           - 대상 기사 제목과 현재 기사 컨텍스트 간 의미 있는 핵심 명사 교집합이 없으면 기각
           - 억지 대조 표현(~와는 대조적으로 등)이 수반된 무관한 링크 즉시 기각
        """
        if not html_content or not contextual_link or not sister_articles:
            return html_content

        if not isinstance(contextual_link, dict):
            return html_content

        target_id = contextual_link.get("target_article_id")
        anchor_phrase = str(contextual_link.get("anchor_phrase") or "").strip()

        if not target_id or not anchor_phrase:
            return html_content

        # 1. 앵커 단어 수 엄격 검증 (영문 3~6단어, 한국어 2~6어절)
        words = anchor_phrase.split()
        is_korean = bool(re.search(r"[가-힣]", anchor_phrase))
        min_w = 2 if is_korean else 3
        if len(words) < min_w or len(words) > 6:
            logger.info(f"[LinkInjector] Rejected anchor_phrase '{anchor_phrase}' (word count: {len(words)} not in {min_w}~6)")
            return html_content

        # 2. 자사 기사 풀에서 실존 URL 매핑
        matched_article = None
        for art in sister_articles:
            if str(art.get("id")) == str(target_id) or str(art.get("article_id")) == str(target_id):
                matched_article = art
                break

        if not matched_article or not matched_article.get("url"):
            logger.info(f"[LinkInjector] Target article id '{target_id}' not found in sister pool")
            return html_content

        clean_url = str(matched_article["url"]).strip()

        # 2-1. 6단계 가드레일: 의미적/주제적 연관성(Semantic Relevance) 및 억지 대조(Forced Contrast) 검증
        # 대상 자사 기사의 제목과 기사의 핵심 주제(article_context 및 본문 전체) 간 핵심 명사 교집합 검증
        overlap = set()
        if article_context:
            sister_title = str(matched_article.get("title") or "")
            sister_kws = cls.extract_significant_keywords(sister_title)
            # 제목/요약/키워드뿐만 아니라 html_content 본문 텍스트 전체와 교집합을 대조하여 과도한 기각(False Reject) 방지
            full_context = f"{article_context} {BeautifulSoup(html_content, 'html.parser').get_text()}"
            core_kws = cls.extract_significant_keywords(full_context)
            overlap = sister_kws.intersection(core_kws)
            if sister_kws and not overlap:
                logger.warning(
                    f"[LinkInjector] Rejected contextual_link (Zero Semantic Overlap): "
                    f"Sister title '{sister_title}' has no common keywords with article context. Falling back to Zero-Link."
                )
                return html_content

        # 2-2. 7단계 가드레일: [동향·경향·유사 사례·배경] 인과성(Causal Context) 검증
        # 앵커가 쓰인 문장이나 문맥에 업계 동향, 경향, 유사 사례, 배경, 원인, 여파 등 정당한 저널리즘 인용 표현이 존재하는지 검증
        causal_pattern = re.compile(
            r"(?:동향|경향|흐름|추세|사례|예시|일환|마찬가지|비슷|유사|앞서|지난|보고된|논의된|지적된|여파|힘입어|계기|배경|원인|영향|촉발|이어지|따라|따른|인해|결과|선행|이후|직후|통해|기반|분석|조회|안내|기준|관련|in the wake of|led by|driven by|prompted by|following|sparked by|as a result of|due to)",
            re.IGNORECASE,
        )

        # 3. BeautifulSoup 파싱 및 안전한 텍스트 노드 탐색
        soup = BeautifulSoup(html_content, "html.parser")

        # 금지 태그: 이미 링크가 걸려 있거나(a), 제목(h1~h6), 인용구/Readmore(blockquote), 스크립트 등
        forbidden_parents = {"a", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "script", "style"}

        p_tags = soup.find_all("p")
        replaced = False

        # 대소문자 무시 단어 경계 패턴 (한국어는 조사 결합을 허용하되 구문 전체 매칭)
        if is_korean:
            pattern = re.compile(rf"({re.escape(anchor_phrase)})", re.IGNORECASE)
        else:
            pattern = re.compile(rf"\b({re.escape(anchor_phrase)})\b", re.IGNORECASE)

        # 억지 대조 표현 패턴 (예: ~와는 대조적으로, ~와 달리, ~인 반면에 등)
        forced_contrast_pattern = re.compile(
            r"(?:대조적(?:으로|인|이다|을\s*이루)|이와\s*달리|반면(?:에|으로)|와는\s*달리|과는\s*달리|in\s+contrast\s+to|unlike\s+the)",
            re.IGNORECASE,
        )

        for p in p_tags:
            if replaced:
                break

            # 상단 요약 박스(md-summary-box) 내부 문단은 인라인 링크 주입 제외
            if p.find_parent("div", class_="md-summary-box"):
                continue

            p_full_text = p.get_text()
            if not pattern.search(p_full_text):
                continue

            # 문단 전체 텍스트에서 억지 대조 결합 검사 (앵커가 억지 대조 표현과 함께 쓰인 경우 전면 차단)
            if forced_contrast_pattern.search(p_full_text):
                logger.warning(
                    f"[LinkInjector] Rejected contextual_link (Forced Contrast Detected): "
                    f"Anchor '{anchor_phrase}' is embedded in a forced contrastive sentence ('{p_full_text[:60]}...')."
                )
                return html_content

            # 7단계 가드레일: 앵커 자체 또는 해당 문맥에 명확한 인과성 표현이 결합되어 있는지 검증
            if is_korean and not (causal_pattern.search(p_full_text) or causal_pattern.search(anchor_phrase)):
                logger.warning(
                    f"[LinkInjector] Rejected contextual_link (Lack of Causal Context): "
                    f"Anchor '{anchor_phrase}' and its sentence lack causal relationship markers ('{p_full_text[:60]}...')."
                )
                return html_content

            text_nodes = [
                node for node in p.find_all(string=True)
                if isinstance(node, NavigableString) and node.strip()
            ]

            for node in text_nodes:
                if replaced:
                    break

                # 상위 계층에 금지 태그가 있는지 검사
                if node.find_parent(forbidden_parents):
                    continue

                node_text = str(node)
                match = pattern.search(node_text)
                if match:
                    matched_text = match.group(1)
                    before = node_text[:match.start()]
                    after = node_text[match.end():]

                    new_a = soup.new_tag("a", href=clean_url, target="_blank")
                    new_a["rel"] = ["dofollow"]
                    new_a["data-sys"] = "1"
                    new_a.string = matched_text

                    replacement_elements = []
                    if before:
                        replacement_elements.append(NavigableString(before))
                    replacement_elements.append(new_a)
                    if after:
                        replacement_elements.append(NavigableString(after))

                    node.replace_with(*replacement_elements)
                    replaced = True
                    logger.info(f"[LinkInjector] Successfully injected natural inline link: '{matched_text}' -> {clean_url}")
                    break

        return str(soup) if replaced else html_content

    @classmethod
    def inject_fallback_internal_link(
        cls,
        html_content: str,
        sister_articles: List[Dict[str, Any]],
        site: str = None
    ) -> str:
        """
        [2단계 파이썬 자동 매칭 안전망]
        LLM이 contextual_link를 누락했거나 사후 검증에서 탈락하여 본문에 내부 인라인 링크가 없는 경우,
        자사 기사 풀(sister_articles)에서 현재 본문과 연관된 핵심 복합명사구(2~6어절)를
        본문 중후반 문단에서 직접 탐색하여 안전하게 1회 인라인 링크를 확정 주입합니다.
        """
        if not html_content or not sister_articles:
            return html_content

        soup = BeautifulSoup(html_content, "html.parser")

        # 이미 내부 인라인 링크가 있다면 건너뜀 (Readmore 카드 박스 내부 링크 제외)
        for a_tag in soup.find_all("a"):
            if a_tag.get("data-sys") == "1" and not a_tag.find_parent("blockquote", class_="readmore-box"):
                return html_content

        logger = get_domain_logger(site or "general")
        p_tags = soup.find_all("p")
        if not p_tags:
            return html_content

        forbidden_parents = {"a", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "script", "style"}

        for art in sister_articles:
            target_title = str(art.get("title") or "").strip()
            target_url = str(art.get("url") or "").strip()
            if not target_title or not target_url:
                continue

            # 대상 기사 제목에서 2어절 이상의 의미 있는 복합 명사구(Anchor 후보) 추출
            title_words = target_title.split()
            candidate_phrases = []
            for length in (4, 3, 2):
                for i in range(len(title_words) - length + 1):
                    phrase = " ".join(title_words[i:i + length]).strip(" ,.\"'‘’“”()[]")
                    clean_phrase = re.sub(r"[^\w\s]", "", phrase).strip()
                    words_in_phrase = clean_phrase.split()
                    if len(clean_phrase) >= 4 and len(words_in_phrase) >= 2:
                        # 너무 일반적인 범용 단어 제외
                        if clean_phrase not in ("건강 관리", "의료 현장", "국내외 보건", "의학계 연구", "최근 발표"):
                            candidate_phrases.append(clean_phrase)

            if not candidate_phrases:
                sig_kws = list(cls.extract_significant_keywords(target_title))
                if len(sig_kws) >= 2:
                    candidate_phrases.append(f"{sig_kws[0]} {sig_kws[1]}")

            replaced = False
            for phrase in candidate_phrases:
                if replaced:
                    break
                pat = re.compile(rf"({re.escape(phrase)})", re.IGNORECASE)
                for p in p_tags:
                    if replaced:
                        break
                    # 상단 요약 박스 내부 제외
                    if p.find_parent("div", class_="md-summary-box"):
                        continue
                    # 외부 링크가 이미 있는 문단은 분리하여 중복/충돌 방지
                    if p.find("a", class_="external_red"):
                        continue

                    for node in p.find_all(string=True):
                        if node.find_parent(forbidden_parents):
                            continue
                        node_text = str(node)
                        match = pat.search(node_text)
                        if match:
                            before = node_text[:match.start()]
                            after = node_text[match.end():]
                            new_a = soup.new_tag("a", href=target_url)
                            new_a["data-sys"] = "1"
                            new_a["style"] = "color: #1d4ed8; text-decoration: underline;"
                            new_a.string = match.group(1)

                            replacement = []
                            if before:
                                replacement.append(NavigableString(before))
                            replacement.append(new_a)
                            if after:
                                replacement.append(NavigableString(after))
                            node.replace_with(*replacement)
                            replaced = True
                            logger.info(
                                f"[LinkInjector] [Fallback Auto-Match Injected] "
                                f"Successfully injected fallback internal link on phrase '{phrase}' -> {target_url}"
                            )
                            return str(soup)

        return html_content

    @classmethod
    def inject_external_link(cls, html_content: str, source_url: Optional[str] = None) -> str:
        """
        본문 문단(<p>) 내의 자연스러운 외신/출처/기관 인용 어절을 탐색하여,
        100% 파이썬 코드 단에서 정확히 1회의 외부 링크(<a rel="nofollow" href="{source_url}" target="_blank" class="external_red">출처 어절</a>)를 직접 주입합니다.

        [가드레일]
        1. source_url 유효성: http:// 또는 https://로 시작하는 유효 URL이어야 함.
        2. 멱등성 보장: 이미 외부 링크(class="external_red" 또는 rel="nofollow")가 본문에 존재하면 중복 주입하지 않음.
        3. 금지 영역 보호: 헤딩(h1~h6), 요약박스(md-summary-box), 인용구/Readmore(blockquote), 기존 a 태그 내부 텍스트는 치환 금지.
        4. 문맥 기반 어절 탐색:
           - 1순위 (한국어/영문 인용 어절):
             한국어: "외신 보도에 따르면", "연구진에 따르면", "발표에 따르면", "보고서에 따르면", "보도에 따르면", "외신에 따르면", "당국에 따르면"
             영문: "according to reports", "according to the study", "officials stated", "published in the journal", "according to sources"
           - 2순위 (폴백): 1순위 패턴 부재 시, 본문 중반부(2~4번째 문단)에서 자연스러운 팩트/발표/보도 어절 매칭.
        5. 단 1회 주입: 본문 전체에서 최초 1회만 치환하고 즉시 종료.
        """
        if not html_content or not source_url:
            return html_content

        clean_url = str(source_url).strip()
        if not (clean_url.startswith("http://") or clean_url.startswith("https://")):
            return html_content

        soup = BeautifulSoup(html_content, "html.parser")

        # 멱등성: 이미 rel="nofollow" 또는 class="external_red"를 가진 외부 링크가 있다면 스킵
        for a_tag in soup.find_all("a"):
            if a_tag.get("data-sys") != "1":
                classes = a_tag.get("class", [])
                rel = a_tag.get("rel", [])
                if "external_red" in classes or "nofollow" in rel or a_tag.get("href") == clean_url:
                    return html_content

        # 금지 부모 태그
        forbidden_parents = {"a", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "script", "style"}

        # 출처 명시 문구 전용 정규식 (출처 기관/외신/연구자명 + 인용 어절 전체)
        # 첨부 이미지 표준 형태:
        # 형태 1: "CoStar에 따르면", "엔드포인츠뉴스(Endpoints News) 보도에 따르면", "CBRE의 2025년 숙박업 데이터에 따르면", "로이터 통신에 따르면", "미국 FDA 발표에 따르면"
        # 형태 2: "HAMA의 2026년 업계 전망", "보건복지부의 2026년 필수의료 지원계획"
        # 형태 3: "According to Reuters reports", "CBRE's 2025 Lodging Data"
        # *주의: '임상 시험', '데이터', '밝혔다' 등 출처가 없는 단순 단어에는 절대 링크를 걸지 않음
        citation_patterns = [
            # 1. [출처/기관/언론명] + (보도/발표/데이터/로드맵/계획 등) + 에 따르면
            re.compile(r"([A-Za-z0-9가-힣·\(\)]{2,30}(?:\s+[A-Za-z0-9가-힣·\(\)]{2,20})*?(?:보도|타전|발표|자료|보고서|데이터|통계|소식|조사|연구|로드맵|계획|가이드라인|지침|성명|권고안|분석)?에\s+따르면)", re.IGNORECASE),
            # 2. [기관명/데이터명]의 [연도/보고서/전망명] (예: HAMA의 2026년 업계 전망, FDA의 2026년 신약 승인 보고서)
            re.compile(r"([A-Za-z0-9가-힣·\(\)]{2,20}의\s+(?:20\d\d년\s+)?[A-Za-z0-9가-힣·]{2,15}(?:\s+[A-Za-z0-9가-힣·]{2,15})*?\s*(?:전망|보고서|백서|리포트|계획|로드맵))", re.IGNORECASE),
            # 3. 일반 외신/공식 인용 구문 (기관명이 없는 경우의 차선책)
            re.compile(r"((?:외신\s+보도|외신\s+타전|현지\s+언론|외신|공식\s+발표\s*자료|공식\s+발표|발표\s*자료|보도\s*자료|공식\s+성명|연구진\s+발표|연구팀\s+발표|당국\s+발표)에\s+따르면)", re.IGNORECASE),
            # 4. 영문 출처 패턴
            re.compile(r"(according\s+to\s+(?:reports|data|officials|sources|study|findings|[A-Za-z0-9\s,\.]{2,25}))", re.IGNORECASE),
            re.compile(r"([A-Za-z0-9\s]{2,20}'s\s+(?:20\d\d\s+)?[A-Za-z\s]{3,25}?(?:Outlook|Report|Data|Analysis))", re.IGNORECASE),
            re.compile(r"(reported\s+by\s+[A-Za-z0-9\s]{2,25})", re.IGNORECASE),
            re.compile(r"(published\s+in\s+[A-Za-z0-9\s]{2,25})", re.IGNORECASE),
        ]

        p_tags = soup.find_all("p")
        replaced = False

        for pattern in citation_patterns:
            if replaced:
                break
            for p in p_tags:
                if replaced:
                    break
                # 상단 요약 박스(md-summary-box) 내부 문단은 제외
                if p.find_parent("div", class_="md-summary-box"):
                    continue

                text_nodes = [
                    node for node in p.find_all(string=True)
                    if isinstance(node, NavigableString) and node.strip()
                ]

                for node in text_nodes:
                    if node.find_parent(forbidden_parents):
                        continue

                    node_text = str(node)
                    m = pattern.search(node_text)
                    if m:
                        matched_text = m.group(1).strip()
                        # 앞머리 접속사/부사 정리 (예: "또한 CoStar에 따르면" -> "CoStar에 따르면")
                        lead_strip = re.match(r"^(?:또한|그리고|하지만|특히|이어|한편|아울러|더불어|실제로|이와 함께)\s+(.*)", matched_text)
                        if lead_strip:
                            matched_text = lead_strip.group(1).strip()

                        # 문장 부호 정리 (쉼표, 마침표, 따옴표 등)
                        matched_text = matched_text.strip(" ,.\"'‘’“”()[]")

                        words = matched_text.split()
                        is_ko = bool(re.search(r"[가-힣]", matched_text))
                        # 출처 문구 길이 통제:
                        # 한국어: 글자 수(4~45자) 및 어절 수(1~10어절) 복합 가드레일 (띄어쓰기 가변성 완벽 수용 및 45자 상한으로 Over-greedy 차단)
                        # 영문: 기존 2~7단어 규격 100% 보존
                        if is_ko:
                            is_valid_len = (4 <= len(matched_text) <= 45) and (1 <= len(words) <= 10)
                        else:
                            is_valid_len = 2 <= len(words) <= 7

                        if is_valid_len:
                            idx = node_text.find(matched_text)
                            if idx != -1:
                                before = node_text[:idx]
                                after = node_text[idx + len(matched_text):]

                                new_a = soup.new_tag("a", href=clean_url, target="_blank")
                                new_a["rel"] = ["nofollow"]
                                new_a["class"] = ["external_red"]
                                new_a.string = matched_text

                                replacement_elements = []
                                if before:
                                    replacement_elements.append(NavigableString(before))
                                replacement_elements.append(new_a)
                                if after:
                                    replacement_elements.append(NavigableString(after))

                                node.replace_with(*replacement_elements)
                                replaced = True
                                logger.info(f"[LinkInjector] Successfully injected external link on full attribution phrase: '{matched_text}' -> {clean_url}")
                                break

        return str(soup) if replaced else html_content

    @classmethod
    def sanitize_external_links(cls, html_content: str, source_url: Optional[str] = None) -> str:
        """
        외부 링크에 rel="nofollow", class="external_red", target="_blank" 속성을 적용합니다.
        내부 링크(data-sys="1")는 정제 대상에서 제외합니다.
        """
        if not html_content:
            return ""

        soup = BeautifulSoup(html_content, "html.parser")

        for a_tag in soup.find_all("a"):
            # 내부 링크는 건너뜀
            if a_tag.get("data-sys") == "1":
                continue

            # target="_blank" 강제
            a_tag["target"] = "_blank"

            # rel="nofollow" 정규화
            rel_val = a_tag.get("rel", [])
            if isinstance(rel_val, str):
                rel_parts = rel_val.split()
            else:
                rel_parts = list(rel_val)
            if "nofollow" not in rel_parts:
                rel_parts.append("nofollow")
            a_tag["rel"] = rel_parts

            # class="external_red" 정규화
            class_val = a_tag.get("class", [])
            if isinstance(class_val, str):
                class_parts = class_val.split()
            else:
                class_parts = list(class_val)
            if "external_red" not in class_parts:
                class_parts.append("external_red")
            a_tag["class"] = class_parts

        return str(soup)

    @classmethod
    def inject_internal_links(
        cls,
        html_content: str,
        internal_pool: List[Dict[str, Any]],
        min_links: int = 3,
        max_links: int = 5,
    ) -> str:
        """
        본문 내 텍스트 노드를 탐색하여 자사 관련 기사 링크를 안전하게 주입합니다.
        - 헤딩 태그 및 기존 a 태그 보호
        - 2~4단어 복합구 매칭
        - 문단당 1개 제한
        - 1 URL당 1회 링크
        """
        if not internal_pool or not html_content:
            return html_content

        soup = BeautifulSoup(html_content, "html.parser")

        # 1. 키워드 매핑 테이블 준비 (긴 구문 우선 정렬)
        candidates: List[Dict[str, str]] = []
        for item in internal_pool:
            url = item.get("url", "")
            if not url:
                continue

            raw_kws = item.get("keywords", [])
            if isinstance(raw_kws, str):
                raw_kws = [k.strip() for k in raw_kws.split(",")]

            # 제목에서 2~4단어 후보 추가
            title = item.get("title", "")
            title_words = title.split()
            if len(title_words) >= 2:
                raw_kws.append(" ".join(title_words[:3]))

            for kw in raw_kws:
                cleaned_kw = kw.strip()
                words = cleaned_kw.split()
                # 2단어 이상 복합구만 채택 (단일 단어 제외)
                if len(words) >= 2 and len(cleaned_kw) >= 6:
                    candidates.append({"phrase": cleaned_kw, "url": url})

        # 긴 구문이 먼저 매칭되도록 내림차순 정렬
        candidates.sort(key=lambda x: len(x["phrase"]), reverse=True)

        if not candidates:
            return html_content

        inserted_count = 0
        used_urls = set()

        # 2. 문단(<p>) 단위 순회
        p_tags = soup.find_all("p")
        for p in p_tags:
            if inserted_count >= max_links:
                break

            p_inserted = False

            # 해당 문단 내의 텍스트 노드 순회
            # 리스트 복사본으로 순회하여 DOM 변형 중 안전성 확보
            text_nodes = [
                node
                for node in p.find_all(string=True)
                if isinstance(node, NavigableString) and node.strip()
            ]

            for node in text_nodes:
                if p_inserted or inserted_count >= max_links:
                    break

                # 상위 계층에 금지 태그(a, h1~h6, script, style)가 있는지 확인
                if node.find_parent(["a", "h1", "h2", "h3", "h4", "h5", "h6", "script", "style"]):
                    continue

                node_text = str(node)

                for cand in candidates:
                    phrase = cand["phrase"]
                    url = cand["url"]

                    if url in used_urls:
                        continue

                    # 단어 경계를 고려한 대소문자 무시 검색
                    pattern = re.compile(rf"\b({re.escape(phrase)})\b", re.IGNORECASE)
                    match = pattern.search(node_text)

                    if match:
                        matched_text = match.group(1)
                        # 일치 구간을 기준으로 분할
                        before = node_text[: match.start()]
                        after = node_text[match.end() :]

                        # 새로운 태그 요소 구성
                        new_a = soup.new_tag("a", href=url, target="_blank")
                        new_a["rel"] = ["dofollow"]
                        new_a["data-sys"] = "1"
                        new_a.string = matched_text

                        # DOM 교체: before + new_a + after
                        replacement_elements = []
                        if before:
                            replacement_elements.append(NavigableString(before))
                        replacement_elements.append(new_a)
                        if after:
                            replacement_elements.append(NavigableString(after))

                        # 부모 노드 내에서 해당 텍스트 노드를 새 요소들로 치환
                        node.replace_with(*replacement_elements)

                        used_urls.add(url)
                        inserted_count += 1
                        p_inserted = True
                        break

        return str(soup)

    @classmethod
    def process(
        cls,
        html_content: str,
        site: str,
        source_url: Optional[str] = None,
        internal_pool: Optional[List[Dict[str, Any]]] = None,
        contextual_link: Optional[Dict[str, Any]] = None,
        sister_articles: Optional[List[Dict[str, Any]]] = None,
        enable_internal_links: bool = False,
        enable_readmore_box: bool = True,
        article_context: Optional[str] = None,
    ) -> str:
        """
        외부 링크 정제와 내부 인라인 링크 주입 및 Read more 위젯 주입을 순차적으로 수행하는 통합 진입점.
        - enable_internal_links: True일 경우 본문 내 고품질 문맥 인라인 내부 링크(data-sys="1") 주입.
        - enable_readmore_box: False일 경우 Read more 카드 박스를 생성하지 않음 (Ingest API 매체 전용 정책).
        - contextual_link & sister_articles가 제공되면 고품질 문맥 인라인 링크 주입(inject_natural_inline_link)을 우선 실행합니다.
        - article_context: 기사 제목/요약 등 문맥을 전달받아 의미적 연관성(Semantic Relevance) 가드레일을 수행합니다.
        """
        if not html_content:
            return ""

        # 1. 외부 링크 주입 및 정제 (100% Python 단 결정론적 처리)
        injected_ext = cls.inject_external_link(html_content, source_url) if source_url else html_content
        sanitized = cls.sanitize_external_links(injected_ext, source_url)

        # 2. 내부 인라인 링크 처리
        if enable_internal_links:
            if contextual_link and sister_articles:
                # 고품질 문맥 기반 자연스러운 인라인 링크 주입 (6단계 가드레일: 주제 연관성 검증 포함)
                working_html = cls.inject_natural_inline_link(
                    sanitized, contextual_link, sister_articles, article_context=article_context
                )
            elif internal_pool is not None:
                working_html = cls.inject_internal_links(sanitized, internal_pool)
            else:
                working_html = sanitized

            # [2단계 파이썬 자동 매칭 안전망 (Fallback)]
            # 의약일보(medicaldaily)의 경우, 본문에 인라인 내부 링크가 아직 주입되지 않았다면 자사 기사 풀의 구체적 복합구로 확정 주입
            if site == "medicaldaily" and sister_articles:
                working_html = cls.inject_fallback_internal_link(working_html, sister_articles, site=site)
        else:
            # 내부 인라인 링크 비활성화: 기존에 존재하는 data-sys="1" 링크가 있다면 텍스트만 남기고 unwrap
            soup = BeautifulSoup(sanitized, "html.parser")
            existing_int_links = soup.find_all("a", attrs={"data-sys": "1"})
            if existing_int_links:
                for a_tag in existing_int_links:
                    a_tag.unwrap()
                working_html = str(soup)
            else:
                working_html = sanitized

        # 3. Read More (<blockquote class="readmore-box">...</blockquote><p>&nbsp;</p>) 위젯 주입
        if enable_readmore_box:
            related_items = cls.load_related_articles(site, limit=4, topic_query=article_context or "")
            final_html = cls.inject_related_articles_box(working_html, related_items, site=site)
        else:
            final_html = working_html

        return final_html

    @classmethod
    def _fetch_medicaldaily_live_articles(cls, limit: int = 4, topic_query: str = "") -> List[Dict[str, Any]]:
        """
        의약일보(medicaldaily.co.kr) 웹에서 실존 기사 목록(article_id, title, url, image_url)을 조회합니다.
        - topic_query가 제공되면 해당 주제어를 기반으로 연관 기사를 우선 검색합니다.
        - topic_query 검색 결과가 없거나 실패 시 일반 의약 주제어로 안전하게 폴백합니다.
        """
        import ssl
        import urllib.request
        import urllib.parse

        results: List[Dict[str, Any]] = []
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        # 검색어 결정
        search_terms = []
        if topic_query:
            kws = cls.extract_significant_keywords(topic_query)
            for kw in kws:
                if len(kw) >= 2 and kw not in search_terms:
                    search_terms.append(kw)
        if not search_terms:
            search_terms = ["제약", "임상", "건강", "의료"]

        seen_ids = set()
        for term in search_terms[:3]:
            if len(results) >= limit:
                break
            try:
                enc_term = urllib.parse.quote(term)
                req = urllib.request.Request(
                    f"https://www.medicaldaily.co.kr/search?q={enc_term}",
                    headers={"User-Agent": "Mozilla/5.0 (compatible; GlobalNewsDeskBot/1.0)"},
                )
                with urllib.request.urlopen(req, context=ctx, timeout=8) as res:
                    html_text = res.read().decode("utf-8", errors="ignore")
                    soup = BeautifulSoup(html_text, "html.parser")
                    for a_tag in soup.find_all("a", href=True):
                        href = str(a_tag.get("href", "")).strip()
                        m = re.match(r"^/(?:news|post)/(\d+)$", href)
                        if not m:
                            continue
                        art_id = m.group(1)
                        if art_id in seen_ids:
                            continue
                        h3 = a_tag.find("h3")
                        title = h3.get_text(strip=True) if h3 else a_tag.get_text(strip=True)
                        if not title or len(title) < 8:
                            continue
                        img_tag = a_tag.find("img")
                        img_src = str(img_tag.get("src", "")) if img_tag else ""
                        seen_ids.add(art_id)
                        results.append({
                            "article_id": art_id,
                            "title": title,
                            "url": f"https://www.medicaldaily.co.kr/news/{art_id}",
                            "image_url": img_src,
                            "image_id": art_id,
                        })
                        if len(results) >= limit:
                            break
            except Exception as e:
                logger.debug("Failed fetching live medicaldaily related articles for term '%s': %s", term, e)

        return results

    @classmethod
    def load_related_articles(cls, site: str, limit: int = 4, topic_query: str = "") -> List[Dict[str, Any]]:
        """
        Read more 위젯 및 자사 인라인 링크용 자사 실존 기사 목록(id, title, img_url, img_id)을 추출합니다.
        topic_query가 주어질 경우 주제 연관성이 높은 기사를 최우선으로 배치합니다.
        """
        related: List[Dict[str, Any]] = []
        generated_dir = "data/generated_articles"
        query_kws = cls.extract_significant_keywords(topic_query) if topic_query else set()

        try:
            if os.path.exists(generated_dir):
                # 파일 생성/수정 시간 역순 정렬
                files = [
                    f for f in os.listdir(generated_dir)
                    if f.startswith(f"{site}_") and f.endswith(".json")
                ]
                files.sort(
                    key=lambda x: os.path.getmtime(os.path.join(generated_dir, x)),
                    reverse=True
                )

                candidate_pool = []
                for fname in files:
                    fpath = os.path.join(generated_dir, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8") as gf:
                            gdata = json.load(gf)
                            art_id = str(gdata.get("article_id", ""))
                            title = gdata.get("generated", {}).get("title", "")
                            img_url = gdata.get("image_url", "")
                            img_id_match = re.search(r"/(\d{5,8})/", img_url)
                            img_id = img_id_match.group(1) if img_id_match else art_id

                            if art_id and title:
                                saved_url = gdata.get("url")
                                if saved_url and str(saved_url).startswith("/"):
                                    if site == "medicaldaily":
                                        art_url = f"https://www.medicaldaily.co.kr{saved_url}"
                                    else:
                                        art_url = f"https://www.{site}.com{saved_url}"
                                elif saved_url and str(saved_url).startswith("http"):
                                    art_url = str(saved_url)
                                elif site == "medicaldaily":
                                    art_url = f"https://www.medicaldaily.co.kr/news/{art_id}"
                                else:
                                    date_str = gdata.get("timestamp", "20261109")[:10].replace("-", "")
                                    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")
                                    art_url = f"https://www.{site}.com/articles/{art_id}/{date_str}/{slug}.htm"

                                # 주제 키워드 매칭 점수 계산
                                title_kws = cls.extract_significant_keywords(title)
                                match_score = len(query_kws.intersection(title_kws)) if query_kws else 0

                                candidate_pool.append({
                                    "article_id": art_id,
                                    "title": title,
                                    "url": art_url,
                                    "image_url": img_url,
                                    "image_id": img_id,
                                    "score": match_score,
                                })
                    except Exception as fe:
                        logger.debug("Error parsing related article %s: %s", fname, fe)

                # 점수 높은 순(주제 연관성 우선)으로 정렬
                candidate_pool.sort(key=lambda x: x["score"], reverse=True)
                for cand in candidate_pool[:limit]:
                    related.append(cand)

            # 의약일보(medicaldaily)의 경우 로컬 캐시가 부족하면 실시간 사이트 기사 목록으로 보충
            if site == "medicaldaily" and len(related) < limit:
                existing_urls = {r.get("url") for r in related}
                live_items = cls._fetch_medicaldaily_live_articles(limit=limit, topic_query=topic_query)
                for item in live_items:
                    if len(related) >= limit:
                        break
                    if item.get("url") not in existing_urls:
                        related.append(item)
                        existing_urls.add(item.get("url"))

        except Exception as e:
            logger.warning("Error loading related articles for %s: %s", site, e)

        return related

    @classmethod
    def build_related_articles_box(cls, related_items: List[Dict[str, Any]], site: str = "general") -> str:
        """
        Ingest API 및 일반 articles.php 규격에 안전한 카드형 박스 디자인의 Read more 블록 HTML을 생성합니다.
        - 공백 없는 CSS 속성을 적용하여 PHP 백엔드의 addslashes() 따옴표 왜곡을 방어합니다.
        - 하단에 <p>&nbsp;</p>를 배치하여 Key Questions Answered 헤딩과의 시원한 공백을 보장합니다.
        - site == "medicaldaily"인 경우 박스 제목을 '[의약일보 기사 더보기]'로 출력합니다.
        """
        if not related_items:
            return ""

        li_elements = []
        for item in related_items:
            title = item.get("title", "").strip()
            url = item.get("url", "").strip()
            if title:
                if url:
                    li_elements.append(
                        f'<li style="margin-bottom:8px;line-height:1.6;">'
                        f'<a href="{url}" target="_blank" style="color:#1d4ed8;font-weight:500;text-decoration:underline;">{title}</a>'
                        f'</li>'
                    )
                else:
                    li_elements.append(f'<li style="margin-bottom:8px;line-height:1.6;">{title}</li>')

        if not li_elements:
            return ""

        li_combined = "".join(li_elements)
        bq_style = (
            "background-color:#f8fafc;"
            "border-left-width:4px;"
            "border-left-style:solid;"
            "border-left-color:#2563eb;"
            "padding-top:14px;"
            "padding-bottom:14px;"
            "padding-left:18px;"
            "padding-right:18px;"
            "margin-top:24px;"
            "margin-bottom:28px;"
            "border-top-right-radius:6px;"
            "border-bottom-right-radius:6px;"
        )
        p_style = "margin-top:0;margin-bottom:8px;font-weight:bold;font-size:15px;color:#0f172a;"
        ul_style = "margin-top:0;margin-bottom:0;padding-left:18px;"
        box_title = "[의약일보 기사 더보기]" if site == "medicaldaily" else "Read more:"

        box_html = (
            f'<blockquote class="readmore-box" style="{bq_style}">'
            f'<p style="{p_style}"><strong>{box_title}</strong></p>'
            f'<ul style="{ul_style}">{li_combined}</ul>'
            f'</blockquote>'
            f'<p>&nbsp;</p>'
        )
        return box_html

    @classmethod
    def inject_related_articles_box(
        cls,
        html_content: str,
        related_items: List[Dict[str, Any]],
        site: str = "general",
    ) -> str:
        """
        Read more 리스트를 본문 Q&A 섹션(<h2>Key Questions Answered</h2>) 직전에 안전하게 주입합니다.
        - 이미 Read more 또는 relatedArticle이 존재할 경우 중복 주입을 방지 (멱등성 가드)
        - Q&A 헤딩이 없을 경우 본문 최하단에 부착 (Fallback)
        """
        if not html_content or not related_items:
            return html_content

        # 멱등성 검사: 이미 Read more 블록이나 relatedArticle이 본문에 포함되어 있으면 스킵
        if (
            "readmore-box" in html_content
            or "<strong>Read more:</strong>" in html_content
            or "<strong>[의약일보 기사 더보기]</strong>" in html_content
            or 'class="relatedArticle"' in html_content
        ):
            return html_content

        soup = BeautifulSoup(html_content, "html.parser")
        if soup.find("div", class_="relatedArticle"):
            return html_content

        box_html = cls.build_related_articles_box(related_items, site=site)
        if not box_html:
            return html_content

        box_soup = BeautifulSoup(box_html, "html.parser")
        new_elements = [el for el in box_soup.contents if str(el).strip()]
        if not new_elements:
            return html_content

        # Q&A 헤딩 탐색 (h2, h3, h4 중 "Key Questions" 포함 헤딩)
        qa_heading = soup.find(
            lambda t: t.name in ["h2", "h3", "h4"] and "Key Questions" in (t.string or t.text or "")
        )

        if qa_heading:
            for el in new_elements:
                qa_heading.insert_before(el)
        else:
            for el in new_elements:
                soup.append(el)

        return str(soup)
