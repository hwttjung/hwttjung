from __future__ import annotations
import os
import re
import json
import time
import random
import urllib.request
import urllib.parse
import urllib.error
import ssl
from common.logger_setup import get_domain_logger
from core.media.cost_tracker import CostTracker
from core.media.image_gatekeeper import ImageGatekeeper

class ImageSearcher:
    """
    뉴스 기사 이미지 자동 검색 & 멀티모달 검증 & 비용 제어 파이프라인
    - 1순위: Wikimedia Commons API (API 키 불필요, 100% 무료, 구글 SEO 1600px & 16:9 와이드 가로형 & 안전 라이선스 필터)
    - 2순위: Unsplash API (16:9 스마트 크롭 & 가로 1600px 고화질 & 무료)
    - 3순위: Pexels API (대체 무료 스톡) / Google CSE (키 설정 시)
    - 시각 검증: Gemini 멀티모달 Gatekeeper (동음이의어, 톤앤매너, 오보 방지, 16:9 가로 구도 심사)
    - 4순위 (비상 Fallback): 고품질 랜덤 추상 이미지
    """
    def __init__(self, env: dict):
        self.env = env
        self.google_cse_key = env.get("GOOGLE_CSE_API_KEY")
        self.google_cse_cx = env.get("GOOGLE_CSE_CX")
        self.allow_paid_google_cse = str(env.get("ALLOW_PAID_GOOGLE_CSE", "false")).lower() in ("true", "1", "yes")
        
        self.unsplash_key = env.get("UNSPLASH_ACCESS_KEY")
        self.pexels_key = env.get("PIXELS_API_KEY") or env.get("PEXELS_API_KEY")
        
        self.cost_tracker = CostTracker()
        self.gatekeeper = ImageGatekeeper(env)
        
    def _normalize_image_url(self, url: str) -> str:
        if not url:
            return ""
        return url.split("?")[0].strip().lower()

    def search_image(
        self,
        query: str | list[str],
        exclude_urls=None,
        site_domain: str = None,
        article_summary: str = None,
        article_title: str = None
    ) -> dict:
        """
        뉴스 기사용 최적 이미지 다단계 순차 검색 (Cascade Waterfall) 및 게이트키퍼 심사
        - query가 list인 경우: 중요도 순서대로 [주인공 인명, 조연 인명, 종목/주제 키워드] 순차 탐색
        - query가 str인 경우: 단일 키워드 검색 (100% 하위 호환성)
        - 각 쿼리별로:
          1순위: Wikimedia Commons (구글 SEO 1600px, 16:9 와이드, CC/PD 안전 라이선스)
          2순위: Unsplash (16:9 스마트 크롭)
          3순위: Pexels
        - Gatekeeper 점수 7.0점 이상 합격 시 즉시 채택하여 리턴
        - 미달/부재 시 다음 우선순위 쿼리로 자동 전환
        - 전체 탐색 후에도 7.0점 이상이 없는 경우: 수집된 최고 점수 후보를 비즈니스 안전망으로 채택
        """
        # 하위 호환성 방어: 2번째 인자로 domain 문자열이 잘못 전달된 경우 자동 보정
        if isinstance(exclude_urls, str) and not site_domain:
            site_domain = exclude_urls
            exclude_urls = None

        logger = get_domain_logger(site_domain or "general")
        
        # 쿼리 리스트 정규화
        if isinstance(query, list):
            queries = [str(q).strip() for q in query if str(q).strip()]
        elif isinstance(query, str):
            clean_q = query.strip()
            queries = [clean_q] if clean_q else []
        else:
            queries = []

        if not queries:
            queries = ["news"]

        logger.info(f"[{site_domain}] [Image Search Pipeline] 다단계 검색 쿼리: {queries}")

        # 의약일보(medicaldaily) 전용 우선순위 분기:
        # 0순위: 의약일보(medicaldaily.co.kr) 기존 기사 연관 이미지
        # 1순위: Pexels -> 2순위: Wikimedia Commons -> 3순위: Unsplash
        if site_domain == "medicaldaily":
            return self._search_image_medicaldaily(
                queries=queries,
                exclude_urls=exclude_urls,
                site_domain=site_domain,
                article_summary=article_summary,
                article_title=article_title,
            )

        best_candidate = None
        best_candidate_meta = None

        for idx, current_query in enumerate(queries, start=1):
            logger.info(f"[{site_domain}] [다단계 검색 {idx}/{len(queries)}] 시도 쿼리: '{current_query}'")

            # 1. 1순위: Wikimedia Commons 검색
            candidates = []
            ingest_api_sites = ["jobsnhire", "mobilenapps", "parentherald", "booksnreview"]
            if site_domain in ingest_api_sites:
                logger.info(f"[{site_domain}] Ingest API 매체는 Wikimedia 차단 방지를 위해 1순위 탐색을 건너뜁니다.")
            else:
                logger.info(f"[{site_domain}] [1순위 Wikimedia Commons] Searching: '{current_query}'...")
                candidates = self._search_wikimedia(current_query, exclude_urls, site_domain)

            if candidates:
                if article_summary and article_title:
                    eval_result = self.gatekeeper.evaluate_image_match(
                        article_summary=article_summary,
                        article_title=article_title,
                        candidate_images=candidates,
                        site_domain=site_domain
                    )
                    score = eval_result.get("score", 0.0)
                    if eval_result.get("is_acceptable") and eval_result.get("selected_image"):
                        selected = eval_result["selected_image"]
                        logger.info(
                            f"[{site_domain}] [Image Gatekeeper Passed ({score}점)] "
                            f"'{current_query}' Wikimedia Commons 선정: {selected['url']}"
                        )
                        return {
                            "url": selected["url"],
                            "credit": selected["credit"],
                            "gatekeeper_score": score,
                            "gatekeeper_reason": eval_result.get("reason"),
                            "source": "Wikimedia Commons"
                        }
                    else:
                        logger.warning(
                            f"[{site_domain}] [Gatekeeper Rejected ({score}점)] '{current_query}' Wikimedia 부적합 판정. "
                            f"Unsplash/Pexels 또는 다음 쿼리로 전환합니다."
                        )
                        if eval_result.get("selected_image") and (best_candidate is None or score > best_candidate_meta.get("score", 0.0)):
                            best_candidate = eval_result["selected_image"]
                            best_candidate_meta = {
                                "score": score,
                                "reason": eval_result.get("reason"),
                                "source": "Wikimedia Commons"
                            }
                else:
                    first = candidates[0]
                    return {"url": first["url"], "credit": first["credit"], "source": "Wikimedia Commons"}

            # 2. 2순위: Unsplash 및 Pexels 병합 검색 (후보군 통합 경쟁)
            fallback_candidates = []
            if self.unsplash_key and self.unsplash_key not in ("your_unsplash_access_key_here", ""):
                logger.info(f"[{site_domain}] [2순위 Unsplash 16:9] Searching fallback: '{current_query}'...")
                unsplash_cands = self._get_unsplash_candidates(current_query, exclude_urls, site_domain)
                fallback_candidates.extend(unsplash_cands)

            if self.pexels_key and self.pexels_key not in ("your_pexels_api_key_here", ""):
                logger.info(f"[{site_domain}] [2순위 Pexels] Searching fallback: '{current_query}'...")
                pexels_cands = self._get_pexels_candidates(current_query, exclude_urls, site_domain)
                fallback_candidates.extend(pexels_cands)
                
            if fallback_candidates:
                # 두 API의 결과물이 공평하게 심사받도록 순서를 섞어줍니다.
                random.shuffle(fallback_candidates)

            if fallback_candidates:
                if article_summary and article_title:
                    eval_result = self.gatekeeper.evaluate_image_match(
                        article_summary=article_summary,
                        article_title=article_title,
                        candidate_images=fallback_candidates,
                        site_domain=site_domain
                    )
                    score = eval_result.get("score", 0.0)
                    if eval_result.get("is_acceptable") and eval_result.get("selected_image"):
                        selected = eval_result["selected_image"]
                        source_name = selected.get("source", "Unsplash")
                        logger.info(
                            f"[{site_domain}] [Image Gatekeeper Passed ({score}점)] "
                            f"'{current_query}' {source_name} 선정: {selected['url']}"
                        )
                        return {
                            "url": selected["url"],
                            "credit": selected["credit"],
                            "gatekeeper_score": score,
                            "gatekeeper_reason": eval_result.get("reason"),
                            "source": source_name
                        }
                    else:
                        logger.warning(
                            f"[{site_domain}] [Gatekeeper Rejected ({score}점)] '{current_query}' 2/3순위 부적합 판정."
                        )
                        if eval_result.get("selected_image") and (best_candidate is None or score > best_candidate_meta.get("score", 0.0)):
                            best_candidate = eval_result["selected_image"]
                            best_candidate_meta = {
                                "score": score,
                                "reason": eval_result.get("reason"),
                                "source": eval_result["selected_image"].get("source", "Unsplash")
                            }
                else:
                    first = fallback_candidates[0]
                    return {"url": first["url"], "credit": first["credit"], "source": first.get("source", "Unsplash")}

        # 모든 쿼리를 돌았으나 7.0점 이상 합격 이미지가 없는 경우 비즈니스 안전망(Graceful Fallback)
        if best_candidate and best_candidate_meta:
            logger.warning(
                f"[{site_domain}] 모든 쿼리({queries})에서 7.0점 이상을 달성하지 못했으나, "
                f"기사 송출 연속성을 위해 최고 점수({best_candidate_meta['score']}점) 후보를 채택합니다: {best_candidate['url']}"
            )
            return {
                "url": best_candidate["url"],
                "credit": best_candidate["credit"],
                "gatekeeper_score": best_candidate_meta["score"],
                "gatekeeper_reason": best_candidate_meta["reason"],
                "source": best_candidate_meta["source"]
            }

        # 4. 4순위 비상 Fallback (추상/기본 이미지 - 16:9 비율 유지)
        sig = random.randint(1, 100000)
        logger.warning(f"[{site_domain}] 모든 다단계 쿼리 검색 실패 또는 키 미설정. 비상 기본 이미지를 사용합니다.")
        return {
            "url": f"https://images.unsplash.com/photo-1451187580459-43490279c0fa?q=80&w=1600&ar=16:9&fit=crop&sig={sig}",
            "credit": "Photo on Unsplash",
            "source": "Emergency Fallback"
        }

    @staticmethod
    def _categorize_aspect_ratio_tier(aspect_ratio: float) -> int:
        """
        [의약일보 요건 6] 종횡비 3단계 우선순위 티어 분류:
        - Tier 1: 가로가 긴 이미지 (4:3 or 16:9, aspect_ratio >= 1.25)
        - Tier 2: 1:1 정사각 이미지 (0.90 <= aspect_ratio <= 1.10)
        - Tier 3: 세로가 긴 이미지 (aspect_ratio < 0.90) 및 기타 비정형
        """
        if aspect_ratio >= 1.25:
            return 1
        elif 0.90 <= aspect_ratio <= 1.10:
            return 2
        else:
            return 3

    def _search_image_medicaldaily(
        self,
        queries: list[str],
        exclude_urls=None,
        site_domain: str = "medicaldaily",
        article_summary: str = None,
        article_title: str = None,
    ) -> dict:
        """
        의약일보(medicaldaily) 전용 이미지 검색 파이프라인:
        - [요건 6] 종횡비 우선순위: 가로형(4:3 or 16:9) 1순위 -> 1:1 정사각 2순위 -> 세로형 3순위 (계층적 평가)
        - [요건 7] 이미지 크기: 가로 1000px 이하 한정 (width <= 1000)
        - 검색 소스 캐스케이드:
          0순위: 의약일보(medicaldaily.co.kr) 자체 연관 기사 이미지
          1순위: Pexels API
          2순위: Wikimedia Commons API
          3순위: Unsplash API
        """
        logger = get_domain_logger(site_domain)
        best_candidate = None
        best_candidate_meta = None

        def _evaluate_tier_group(cands: list, source_label: str, query_str: str, tier_name: str):
            nonlocal best_candidate, best_candidate_meta
            if not cands:
                return None
            if article_summary and article_title:
                eval_result = self.gatekeeper.evaluate_image_match(
                    article_summary=article_summary,
                    article_title=article_title,
                    candidate_images=cands,
                    site_domain=site_domain,
                )
                score = eval_result.get("score", 0.0)
                if eval_result.get("is_acceptable") and eval_result.get("selected_image"):
                    selected = eval_result["selected_image"]
                    actual_source = selected.get("source", source_label)
                    logger.info(
                        f"[{site_domain}] [Image Gatekeeper Passed ({score}점, {tier_name})] "
                        f"'{query_str}' {actual_source} 선정: {selected['url']}"
                    )
                    return {
                        "url": selected["url"],
                        "credit": selected["credit"],
                        "gatekeeper_score": score,
                        "gatekeeper_reason": eval_result.get("reason"),
                        "source": actual_source,
                    }
                logger.warning(
                    f"[{site_domain}] [Gatekeeper Rejected ({score}점, {tier_name})] '{query_str}' ({source_label}) 부적합 판정."
                )
                if eval_result.get("selected_image") and (
                    best_candidate is None or score > best_candidate_meta.get("score", 0.0)
                ):
                    best_candidate = eval_result["selected_image"]
                    best_candidate_meta = {
                        "score": score,
                        "reason": eval_result.get("reason"),
                        "source": eval_result["selected_image"].get("source", source_label),
                    }
                return None
            first = cands[0]
            return {
                "url": first["url"],
                "credit": first["credit"],
                "source": first.get("source", source_label),
            }

        def _evaluate_or_pick(candidates: list, source_label: str, query_str: str):
            if not candidates:
                return None

            # [요건 6] 3단계 계층적 우선순위 평가:
            # 1순위: 가로가 긴 이미지 (Tier 1: aspect_ratio >= 1.25)
            # 2순위: 1:1 비율 이미지 (Tier 2: 0.90 <= aspect_ratio <= 1.10)
            # 3순위: 세로가 긴 이미지 (Tier 3: aspect_ratio < 0.90) 및 기타
            tier1 = [c for c in candidates if self._categorize_aspect_ratio_tier(float(c.get("aspect_ratio", 1.5))) == 1]
            tier2 = [c for c in candidates if self._categorize_aspect_ratio_tier(float(c.get("aspect_ratio", 1.5))) == 2]
            tier3 = [c for c in candidates if self._categorize_aspect_ratio_tier(float(c.get("aspect_ratio", 1.5))) == 3]

            if tier1:
                res = _evaluate_tier_group(tier1, source_label, query_str, "Tier 1: 가로형 우선")
                if res:
                    return res
            if tier2:
                res = _evaluate_tier_group(tier2, source_label, query_str, "Tier 2: 1:1 차선")
                if res:
                    return res
            if tier3:
                res = _evaluate_tier_group(tier3, source_label, query_str, "Tier 3: 세로형 최후선")
                if res:
                    return res
            return None

        # 한국어 쿼리(의약일보 내부 검색용)와 영문 쿼리(글로벌 스톡 API용) 분류
        korean_queries = [q for q in queries if re.search(r"[가-힣]", q)]
        english_queries = [q for q in queries if not re.search(r"[가-힣]", q)]
        medi_search_queries = korean_queries + [q for q in english_queries if q not in korean_queries]
        stock_search_queries = english_queries + [q for q in korean_queries if q not in english_queries]

        # 0순위: 의약일보(medicaldaily.co.kr) 내부 연관 이미지 검색
        for q in medi_search_queries:
            logger.info(f"[{site_domain}] [0순위 의약일보 DB] Searching: '{q}'...")
            medi_cands = self._search_medicaldaily_images(q, exclude_urls, site_domain)
            res = _evaluate_or_pick(medi_cands, "MedicalDaily DB", q)
            if res:
                return res

        # 1순위: Pexels API
        if self.pexels_key and self.pexels_key not in ("your_pexels_api_key_here", ""):
            for q in stock_search_queries:
                logger.info(f"[{site_domain}] [1순위 Pexels] Searching: '{q}'...")
                pex_cands = self._get_pexels_candidates(q, exclude_urls, site_domain)
                res = _evaluate_or_pick(pex_cands, "Pexels", q)
                if res:
                    return res

        # 2순위: Wikimedia Commons API
        for q in stock_search_queries:
            logger.info(f"[{site_domain}] [2순위 Wikimedia Commons] Searching: '{q}'...")
            wiki_cands = self._search_wikimedia(q, exclude_urls, site_domain)
            res = _evaluate_or_pick(wiki_cands, "Wikimedia Commons", q)
            if res:
                return res

        # 3순위: Unsplash API
        if self.unsplash_key and self.unsplash_key not in ("your_unsplash_access_key_here", ""):
            for q in stock_search_queries:
                logger.info(f"[{site_domain}] [3순위 Unsplash] Searching: '{q}'...")
                un_cands = self._get_unsplash_candidates(q, exclude_urls, site_domain)
                res = _evaluate_or_pick(un_cands, "Unsplash", q)
                if res:
                    return res

        if best_candidate and best_candidate_meta:
            logger.warning(
                f"[{site_domain}] 0~3순위 전체 탐색에서 7.0점 이상 미달, 최고 점수({best_candidate_meta['score']}점) 채택: {best_candidate['url']}"
            )
            return {
                "url": best_candidate["url"],
                "credit": best_candidate["credit"],
                "gatekeeper_score": best_candidate_meta["score"],
                "gatekeeper_reason": best_candidate_meta["reason"],
                "source": best_candidate_meta["source"],
            }

        sig = random.randint(1, 100000)
        return {
            "url": f"https://images.unsplash.com/photo-1505751172876-fa1923c5c528?q=80&w=1000&ar=16:9&fit=crop&sig={sig}",
            "credit": "Photo on Unsplash",
            "source": "Emergency Fallback",
        }

    def _search_medicaldaily_images(self, query: str, exclude_urls: list, site_domain: str = "medicaldaily") -> list:
        """
        의약일보(https://www.medicaldaily.co.kr/search?q=...)에서 연관 기사의 기존 이미지를 검색하여
        가로 1000px 이하(width=1000) 이미지 후보 리스트를 반환합니다 (0순위).
        """
        from bs4 import BeautifulSoup

        logger = get_domain_logger(site_domain or "medicaldaily")
        clean_q = query.strip()
        if not clean_q:
            return []

        search_url = f"https://www.medicaldaily.co.kr/search?q={urllib.parse.quote(clean_q)}"
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        try:
            req = urllib.request.Request(
                search_url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; GlobalNewsDeskBot/1.0)"},
            )
            with urllib.request.urlopen(req, context=ctx, timeout=8) as response:
                html_body = response.read().decode("utf-8", errors="ignore")
                soup = BeautifulSoup(html_body, "html.parser")
                candidates = []
                seen_norms = set()

                for idx, img in enumerate(soup.find_all("img")):
                    src = str(img.get("src") or "").strip()
                    if "images.medicaldaily.co.kr/data/images/full/" not in src:
                        continue

                    base_img_url = src.split("?")[0]
                    v_match = re.search(r"[?&]v=(\d+)", src)
                    target_width = 1000 if site_domain == "medicaldaily" else 1200
                    if v_match:
                        high_res_url = f"{base_img_url}?v={v_match.group(1)}&width={target_width}"
                    else:
                        high_res_url = f"{base_img_url}?width={target_width}"

                    norm = self._normalize_image_url(high_res_url)
                    if norm in seen_norms:
                        continue
                    if exclude_urls and norm in exclude_urls:
                        continue

                    seen_norms.add(norm)
                    alt_text = str(img.get("alt") or "").strip()
                    candidates.append({
                        "id": f"medi_{idx}",
                        "url": high_res_url,
                        "thumb_url": src,
                        "credit": "사진=의약일보 DB",
                        "source": "MedicalDaily DB",
                        "alt": alt_text,
                        "aspect_ratio": 1.52,
                    })
                    if len(candidates) >= 5:
                        break

                return candidates
        except Exception as e:
            logger.warning(f"[{site_domain}] 의약일보 자체 이미지 검색 실패: {e}")
            return []

    def _search_wikimedia(self, query: str, exclude_urls: list, site_domain: str) -> list:
        """
        Wikimedia Commons API를 호출하여 구글 SEO 규격(가로 1600px) 및 16:9 와이드 가로형 안전 라이선스 이미지 추출
        """
        logger = get_domain_logger(site_domain or "general")
        api_url = "https://commons.wikimedia.org/w/api.php"
        
        # 위키미디어 특화 검색어 정제: 2단어 이상의 복합어일 경우 앞쪽 핵심 단어 우선 탐색
        words = query.strip().split()
        search_term = " ".join(words[:2]) if len(words) > 2 else query.strip()
        
        # 파라미터: 썸네일 자동 생성 및 메타데이터, 치수(dimensions), MIME 요청
        # [요건 7] 의약일보(medicaldaily)는 가로 1000px 이하(iiurlwidth=1000), 영문 매체는 기존 1280px 유지
        wiki_target_width = 1000 if site_domain == "medicaldaily" else 1280
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"File:{search_term}",
            "gsrlimit": 30,  # 가로형 와이드 사진 발굴 확률을 높이기 위해 30개로 확장
            "prop": "imageinfo",
            "iiprop": "url|thumburl|extmetadata|dimensions|mime",
            "iiurlwidth": wiki_target_width  # 의약일보 1000px / 영문 매체 1280px
        }
        
        headers = {
            "User-Agent": "GlobalNewsDeskBot/1.0 (contact@stocktradingbot.com)"
        }
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        try:
            full_url = f"{api_url}?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(full_url, headers=headers)
            with urllib.request.urlopen(req, context=ctx, timeout=8) as response:
                body = response.read().decode("utf-8")
                data = json.loads(body)
                
                pages = data.get("query", {}).get("pages", {})
                candidates = []
                
                for idx, (page_id, page_data) in enumerate(pages.items()):
                    title = page_data.get("title", "")
                    image_info = page_data.get("imageinfo", [{}])[0]
                    if not image_info:
                        continue
                        
                    # 1. MIME 타입 검증: 일반 사진 포맷(jpeg, png, webp)만 허용 (svg, pdf, gif, video 제외)
                    mime = image_info.get("mime", "").lower()
                    if mime not in ("image/jpeg", "image/png", "image/webp", "image/jpg"):
                        continue
                        
                    # 2. 구글 SEO 해상도 및 종횡비(Aspect Ratio) 필터링
                    orig_width = int(image_info.get("width", 0))
                    orig_height = int(image_info.get("height", 0))
                    
                    # 최소 해상도: 가로 또는 세로가 최소 600px 이상의 선명한 사진
                    if orig_width < 600 or orig_height < 600:
                        continue
                        
                    aspect_ratio = orig_width / orig_height
                    # 기본 가로형(1.25~2.4) 및 인물 예외 수용 세로/정사각/1:2전신(0.50~1.25) 범위의 고화질 사진 수집
                    # (극단적인 세로 문서 스캔본이나 얇은 띠 배너: aspect_ratio < 0.50 또는 > 2.5 제외)
                    if not (0.50 <= aspect_ratio <= 2.5):
                        logger.info(
                            f"[{site_domain}] [Wikimedia 종횡비 탈락] 극단적 비정형 이미지 배제: "
                            f"{title} ({orig_width}x{orig_height}, 비율: {aspect_ratio:.2f})"
                        )
                        continue
                        
                    # 3. 안전 라이선스 필터링 (가이드 준수)
                    metadata = image_info.get("extmetadata", {})
                    license_name = metadata.get("LicenseShortName", {}).get("value", "Unknown").upper()
                    
                    # 3-1. 상업적 이용 불가 조건인 NC, ND 즉시 제외
                    if any(forbidden in license_name for forbidden in ["NC", "ND"]):
                        continue
                        
                    # 3-2. 안전 라이선스(CC0, Public Domain, CC-BY, CC-BY-SA 등) 확인 (공백/하이픈 통합 정규화)
                    license_clean = license_name.replace(" ", "-")
                    is_free = any(allowed in license_name for allowed in ["CC0", "PUBLIC DOMAIN", "PD"])
                    is_cc_by = "CC-BY" in license_clean
                    if not (is_free or is_cc_by):
                        continue
                        
                    # 4. 이미지 URL (1600px 썸네일 우선)
                    img_url = image_info.get("thumburl") or image_info.get("url")
                    if not img_url:
                        continue
                        
                    # 불필요한 트래킹 파라미터(?utm_source=...) 제거 (URL 확장자 이슈 방지)
                    img_url = img_url.split("?")[0]
                        
                    norm = self._normalize_image_url(img_url)
                    if exclude_urls and norm in exclude_urls:
                        continue
                        
                    # 5. 크레딧 생성 (저작자 + 출처)
                    raw_artist = metadata.get("Artist", {}).get("value", "Wikimedia Contributor")
                    artist = re.sub(r'<[^>]+>', '', raw_artist).strip() or "Wikimedia Contributor"
                    clean_license = metadata.get("LicenseShortName", {}).get("value", "CC License")
                    credit = f"Photo by {artist} via Wikimedia Commons ({clean_license})"
                    
                    candidates.append({
                        "id": f"wiki_{idx}",
                        "url": img_url,
                        "thumb_url": img_url,  # 1600px 이미지는 멀티모달 다운로드에도 적합
                        "credit": credit,
                        "source": "Wikimedia Commons",
                        "aspect_ratio": round(aspect_ratio, 2)
                    })
                    
                    if len(candidates) >= 5:
                        break
                        
                return candidates
        except Exception as e:
            logger.warning(f"[{site_domain}] Wikimedia Commons 검색 실패: {e}")
            return []

    def _get_unsplash_candidates(self, query: str, exclude_urls: list, site_domain: str) -> list:
        """
        Unsplash API에서 16:9 스마트 크롭 및 가로 1600px 고화질 후보군 추출
        """
        logger = get_domain_logger(site_domain or "general")
        safe_query = urllib.parse.quote(query)
        url = f"https://api.unsplash.com/search/photos?query={safe_query}&per_page=10&client_id={self.unsplash_key}"
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, context=ctx, timeout=8) as response:
                body = response.read().decode("utf-8")
                data = json.loads(body)
                
                # 비용 추적 기록 (무료)
                self.cost_tracker.record_unsplash_call(1)
                
                results = data.get("results", [])
                candidates = []
                for idx, photo in enumerate(results):
                    raw_url = photo.get("urls", {}).get("raw") or photo.get("urls", {}).get("full", "")
                    if not raw_url:
                        continue
                        
                    orig_w = int(photo.get("width", 0))
                    orig_h = int(photo.get("height", 0))
                    aspect_ratio = (orig_w / orig_h) if orig_h > 0 else 1.78

                    base_url = raw_url.split("?")[0]
                    # [요건 7] 의약일보(medicaldaily)는 가로 1000px 이하로 한정
                    target_w = 1000 if site_domain == "medicaldaily" else 1600
                    target_w_vert = 1000 if site_domain == "medicaldaily" else 1280
                    # 인물 및 세로/정사각(비율 < 1.25): 원본 종횡비 보존 (얼굴/신체 잘림 방지)
                    # 일반 가로형(비율 >= 1.25): 구글 SEO 최적화 16:9 크롭 적용
                    if aspect_ratio < 1.25:
                        img_url = f"{base_url}?w={target_w_vert}&q=80&fit=max"
                    else:
                        img_url = f"{base_url}?w={target_w}&q=80&ar=16:9&fit=crop"
                        
                    norm = self._normalize_image_url(img_url)
                    if exclude_urls and norm in exclude_urls:
                        continue
                        
                    thumb_url = photo.get("urls", {}).get("thumb") or photo.get("urls", {}).get("small") or img_url
                    photographer = photo.get("user", {}).get("name", "Unknown")
                    candidates.append({
                        "id": f"un_{idx}",
                        "url": img_url,
                        "thumb_url": thumb_url,
                        "credit": f"Photo by {photographer} on Unsplash",
                        "source": "Unsplash",
                        "aspect_ratio": round(aspect_ratio, 2)
                    })
                    if len(candidates) >= 5:
                        break
                return candidates
        except Exception as e:
            logger.warning(f"[{site_domain}] Unsplash 검색 실패: {e}")
            return []

    def _get_pexels_candidates(self, query: str, exclude_urls: list, site_domain: str) -> list:
        """Pexels API에서 후보 이미지 추출"""
        logger = get_domain_logger(site_domain or "general")
        safe_query = urllib.parse.quote(query)
        url = f"https://api.pexels.com/v1/search?query={safe_query}&per_page=10"
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        try:
            req = urllib.request.Request(url)
            req.add_header("Authorization", self.pexels_key)
            req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            with urllib.request.urlopen(req, context=ctx, timeout=8) as response:
                body = response.read().decode("utf-8")
                data = json.loads(body)
                
                self.cost_tracker.record_pexels_call(1)
                
                photos = data.get("photos", [])
                candidates = []
                for idx, photo in enumerate(photos):
                    orig_w = int(photo.get("width", 0))
                    orig_h = int(photo.get("height", 0))
                    aspect_ratio = (orig_w / orig_h) if orig_h > 0 else 1.78

                    # [요건 7] 의약일보(가로 1000px 이하): large (~940~1000px) 우선
                    # 타 영문 매체(구글 Discover): large2x (~1880px) 우선
                    if site_domain == "medicaldaily":
                        img_url = photo.get("src", {}).get("large") or photo.get("src", {}).get("medium") or photo.get("src", {}).get("large2x", "")
                    else:
                        img_url = photo.get("src", {}).get("large2x") or photo.get("src", {}).get("large", "")
                    if not img_url:
                        continue
                        
                    norm = self._normalize_image_url(img_url)
                    if exclude_urls and norm in exclude_urls:
                        continue
                        
                    thumb_url = photo.get("src", {}).get("tiny") or photo.get("src", {}).get("small") or img_url
                    photographer = photo.get("photographer", "Unknown")
                    candidates.append({
                        "id": f"pex_{idx}",
                        "url": img_url,
                        "thumb_url": thumb_url,
                        "credit": f"Photo by {photographer} on Pexels",
                        "source": "Pexels",
                        "aspect_ratio": round(aspect_ratio, 2)
                    })
                    if len(candidates) >= 5:
                        break
                return candidates
        except Exception as e:
            logger.warning(f"[{site_domain}] Pexels 검색 실패: {e}")
            return []
