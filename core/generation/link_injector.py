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

    @classmethod
    def inject_natural_inline_link(
        cls,
        html_content: str,
        contextual_link: Optional[Dict[str, Any]],
        sister_articles: List[Dict[str, Any]],
    ) -> str:
        """
        LLM이 식별한 문맥 구문(anchor_phrase)을 파이썬에서 5단계 결정론적 필터를 거쳐
        실존하는 자사 기사 URL로 안전하게 1회 치환합니다.
        
        [5대 결정론적 가드레일]
        1. Fail-Safe: contextual_link가 None/null이거나 필수 필드가 없으면 원본 그대로 반환 (Zero-Link)
        2. URL 무결성: 파이썬이 보유한 sister_articles 풀의 실존 URL 매핑 (환각 원천 차단)
        3. 앵커 길이 통제: 3~6단어 엄격 검증 (단일 명사나 7단어 초과 시 기각)
        4. 중첩 방지: 이미 <a> 태그나 헤딩/인용구 내부에 있는 텍스트는 치환 금지
        5. 단 1회 매칭: 본문 전체에서 최초 1회만 치환하여 과도한 링크 방지
        """
        if not html_content or not contextual_link or not sister_articles:
            return html_content

        if not isinstance(contextual_link, dict):
            return html_content

        target_id = contextual_link.get("target_article_id")
        anchor_phrase = str(contextual_link.get("anchor_phrase") or "").strip()

        if not target_id or not anchor_phrase:
            return html_content

        # 1. 앵커 단어 수 엄격 검증 (3~6단어)
        words = anchor_phrase.split()
        if len(words) < 3 or len(words) > 6:
            logger.info(f"[LinkInjector] Rejected anchor_phrase '{anchor_phrase}' (word count: {len(words)} not in 3~6)")
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

        # 3. BeautifulSoup 파싱 및 안전한 텍스트 노드 탐색
        soup = BeautifulSoup(html_content, "html.parser")

        # 금지 태그: 이미 링크가 걸려 있거나(a), 제목(h1~h6), 인용구/Readmore(blockquote), 스크립트 등
        forbidden_parents = {"a", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "script", "style"}

        p_tags = soup.find_all("p")
        replaced = False

        # 대소문자 무시 단어 경계 패턴
        pattern = re.compile(rf"\b({re.escape(anchor_phrase)})\b", re.IGNORECASE)

        for p in p_tags:
            if replaced:
                break

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
    ) -> str:
        """
        외부 링크 정제와 내부 인라인 링크 주입 및 Read more 위젯 주입을 순차적으로 수행하는 통합 진입점.
        - enable_internal_links: True일 경우 본문 내 고품질 문맥 인라인 내부 링크(data-sys="1") 주입.
        - enable_readmore_box: False일 경우 Read more 카드 박스를 생성하지 않음 (Ingest API 매체 전용 정책).
        - contextual_link & sister_articles가 제공되면 고품질 문맥 인라인 링크 주입(inject_natural_inline_link)을 우선 실행합니다.
        """
        if not html_content:
            return ""

        # 1. 외부 링크 정제
        sanitized = cls.sanitize_external_links(html_content, source_url)

        # 2. 내부 인라인 링크 처리
        if enable_internal_links:
            if contextual_link and sister_articles:
                # 고품질 문맥 기반 자연스러운 인라인 링크 주입 (5단계 가드레일)
                working_html = cls.inject_natural_inline_link(sanitized, contextual_link, sister_articles)
            elif internal_pool is not None:
                working_html = cls.inject_internal_links(sanitized, internal_pool)
            else:
                working_html = sanitized
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
            related_items = cls.load_related_articles(site, limit=4)
            final_html = cls.inject_related_articles_box(working_html, related_items)
        else:
            final_html = working_html

        return final_html

    @classmethod
    def load_related_articles(cls, site: str, limit: int = 4) -> List[Dict[str, Any]]:
        """
        Read more 위젯용 자사 실존 과거 기사 목록(id, title, img_url, img_id)을 추출합니다.
        """
        related: List[Dict[str, Any]] = []
        generated_dir = "data/generated_articles"

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

                for fname in files:
                    if len(related) >= limit:
                        break
                    fpath = os.path.join(generated_dir, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8") as gf:
                            gdata = json.load(gf)
                            art_id = str(gdata.get("article_id", ""))
                            title = gdata.get("generated", {}).get("title", "")
                            img_url = gdata.get("image_url", "")
                            # 이미지 URL에서 ID 추정 또는 기본 ID
                            img_id_match = re.search(r"/(\d{5,8})/", img_url)
                            img_id = img_id_match.group(1) if img_id_match else art_id

                            if art_id and title:
                                saved_url = gdata.get("url")
                                if saved_url and str(saved_url).startswith("/"):
                                    art_url = f"https://www.{site}.com{saved_url}"
                                elif saved_url and str(saved_url).startswith("http"):
                                    art_url = str(saved_url)
                                else:
                                    date_str = gdata.get("timestamp", "20261109")[:10].replace("-", "")
                                    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")
                                    art_url = f"https://www.{site}.com/articles/{art_id}/{date_str}/{slug}.htm"

                                related.append({
                                    "article_id": art_id,
                                    "title": title,
                                    "url": art_url,
                                    "image_url": img_url,
                                    "image_id": img_id,
                                })
                    except Exception as fe:
                        logger.debug("Error parsing related article %s: %s", fname, fe)

        except Exception as e:
            logger.warning("Error loading related articles for %s: %s", site, e)

        return related

    @classmethod
    def build_related_articles_box(cls, related_items: List[Dict[str, Any]]) -> str:
        """
        Ingest API 및 일반 articles.php 규격에 안전한 카드형 박스 디자인의 Read more 블록 HTML을 생성합니다.
        - 공백 없는 CSS 속성을 적용하여 PHP 백엔드의 addslashes() 따옴표 왜곡을 방어합니다.
        - 하단에 <p>&nbsp;</p>를 배치하여 Key Questions Answered 헤딩과의 시원한 공백을 보장합니다.
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

        box_html = (
            f'<blockquote class="readmore-box" style="{bq_style}">'
            f'<p style="{p_style}"><strong>Read more:</strong></p>'
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
    ) -> str:
        """
        Read more 리스트를 본문 Q&A 섹션(<h2>Key Questions Answered</h2>) 직전에 안전하게 주입합니다.
        - 이미 Read more 또는 relatedArticle이 존재할 경우 중복 주입을 방지 (멱등성 가드)
        - Q&A 헤딩이 없을 경우 본문 최하단에 부착 (Fallback)
        """
        if not html_content or not related_items:
            return html_content

        # 멱등성 검사: 이미 Read more 블록이나 relatedArticle이 본문에 포함되어 있으면 스킵
        if "readmore-box" in html_content or "<strong>Read more:</strong>" in html_content or 'class="relatedArticle"' in html_content:
            return html_content

        soup = BeautifulSoup(html_content, "html.parser")
        if soup.find("div", class_="relatedArticle"):
            return html_content

        box_html = cls.build_related_articles_box(related_items)
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
