from __future__ import annotations
import os
import json
import base64
import urllib.request
import ssl
from common.logger_setup import get_domain_logger
from core.media.cost_tracker import CostTracker

class ImageGatekeeper:
    """
    Gemini 멀티모달 기반의 뉴스 이미지 시각 심사 게이트키퍼
    - 기사 문맥(제목 및 요약)과 후보 이미지들의 썸네일을 대조 심사
    - 동음이의어 오류, 톤앤매너 불일치, 오보/왜곡 위험, 저품질 워터마크 자동 차단
    """
    
    def __init__(self, env: dict):
        self.api_key = env.get("GEMINI_API_KEY")
        self.cost_tracker = CostTracker()
        self.settings = self._load_settings()
        
    def _load_settings(self) -> dict:
        settings_path = "config/settings.json"
        if os.path.exists(settings_path):
            try:
                with open(settings_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}
        
    def _fetch_thumbnail_base64(self, thumb_url: str) -> tuple[str, str]:
        """초경량 썸네일 이미지를 다운로드하여 (base64_data, mime_type) 반환"""
        if not thumb_url:
            return None, None
            
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        req = urllib.request.Request(
            thumb_url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=6) as resp:
                data = resp.read()
                content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
                if "png" in content_type:
                    mime = "image/png"
                elif "webp" in content_type:
                    mime = "image/webp"
                else:
                    mime = "image/jpeg"
                b64_str = base64.b64encode(data).decode("utf-8")
                return b64_str, mime
        except Exception:
            return None, None

    def evaluate_image_match(
        self,
        article_summary: str,
        article_title: str,
        candidate_images: list,
        site_domain: str = None
    ) -> dict:
        """
        후보 이미지 리스트 중 기사 맥락에 가장 부합하는 최적의 1장 선정
        candidate_images: [
            {"id": "img_0", "url": full_url, "thumb_url": thumb_url, "credit": credit, "source": "..."},
            ...
        ]
        반환값:
        {
            "selected_image": dict (후보 1건) or None,
            "score": float,
            "is_acceptable": bool,
            "reason": str
        }
        """
        logger = get_domain_logger(site_domain or "general")
        
        if not candidate_images:
            logger.warning("[Image Gatekeeper] No candidate images provided for evaluation.")
            return {"selected_image": None, "score": 0.0, "is_acceptable": False, "reason": "No candidate images"}
            
        if not self.api_key:
            logger.warning("[Image Gatekeeper] GEMINI_API_KEY not found. Bypassing gatekeeper and picking first candidate.")
            first = candidate_images[0]
            return {"selected_image": first, "score": 7.0, "is_acceptable": True, "reason": "Bypassed due to missing API key"}
            
        # 1. 썸네일 이미지 다운로드 및 멀티모달 파트 구성
        parts = []
        valid_candidates_map = {}
        
        prompt_intro = f"""
당신은 뉴스 데스크의 최고 시각 편집 에디터(Visual Editor)입니다.
제공된 뉴스 기사의 제목/요약문과 후보 이미지들을 대조 심사하여, 보도 윤리와 기사 문맥에 가장 적합한 1장의 이미지를 선정하세요.

[뉴스 기사 정보]
- 기사 제목: {article_title}
- 기사 요약: {article_summary}

[5대 필수 검증 기준]
1. 의미 일치 (Semantic Accuracy):
   - 동음이의어(예: 기업 애플 vs 과일 사과, 환율 폭등 vs 폭발 화재, 오렌지카운티 vs 오렌지주스)나 엉뚱한 비유 배제.
2. 톤앤매너 (Tone & Sentiment):
   - 사건·사고, 파산, 질병, 사망 등 심각한/비극적 기사에 부적절하게 환하게 웃는 스톡 모델이나 가벼운 일러스트 배제.
   - 공식/진지한 뉴스에 과도하게 연출된 작위적인 스톡 사진이나 장난스러운 3D 그래픽 배제.
3. 사실 왜곡 및 오보 방지 (Factual Integrity):
   - 기사와 무관한 특정 인물의 얼굴이나 무관한 특정 기업 상표가 전면에 노출되었는지 확인.
4. 시각적 품질 (Visual Quality):
   - 과도한 자막 텍스트, 다른 언론사 워터마크가 박혀있지 않은지 확인.
5. 구글 SEO 및 구도 (Layout & Framing) & 인물 비율 예외조항:
   - 기본 원칙: 일반 사물, 풍경, 이벤트, 건물 등은 16:9 와이드 가로형 보도사진(통과 기준: 7.0점 이상)을 원칙으로 합니다.
   - [★핵심 인물 비율 예외조항 (Exception Clause for Prominent Persons)]:
     * 기사의 핵심 주인공 인물(스포츠 선수, 공인, 지도자 등)의 실제 얼굴 및 경기/공식 활동 사진이며 기사 내용과 정확히 일치하는 경우, 16:9 가로 비율이 아니더라도(세로형 3:4, 2:3 또는 정사각 1:1) 적합도 점수가 8.0점 이상이면 최우선 합격(is_acceptable: true)으로 채택하세요.
     * 단, 인물 사진이 아니거나 기사와 무관한 인물인 경우 세로형 이미지는 감점/배제(is_acceptable: false)하세요.

반드시 아래 JSON 스키마로만 응답하세요:
{{
  "selected_id": "선정된_image_id (예: img_0) 또는 적합한 이미지가 없으면 null",
  "score": 0.0부터 10.0까지의 적합도 점수,
  "is_acceptable": true 또는 false,
  "reason": "선택 또는 탈락에 대한 구체적 평가 사유 (한국어 1~2문장)"
}}
"""
        parts.append({"text": prompt_intro})
        
        for idx, cand in enumerate(candidate_images):
            cid = cand.get("id", f"img_{idx}")
            thumb_url = cand.get("thumb_url") or cand.get("url")
            b64_data, mime = self._fetch_thumbnail_base64(thumb_url)
            
            if b64_data:
                parts.append({"text": f"\n[Candidate Image ID: {cid}]\nSource: {cand.get('source', 'Unknown')}"})
                parts.append({
                    "inline_data": {
                        "mime_type": mime,
                        "data": b64_data
                    }
                })
                valid_candidates_map[cid] = cand
                
        if not valid_candidates_map:
            logger.warning("[Image Gatekeeper] Failed to load any valid candidate thumbnails. Falling back.")
            return {"selected_image": candidate_images[0], "score": 5.0, "is_acceptable": False, "reason": "Failed to load thumbnails"}
            
        # 2. Gemini 멀티모달 API 호출
        model_name = self.settings.get("ai_model", {}).get("model_name", "gemini-3.1-flash-lite")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={self.api_key}"
        
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.2,
                "maxOutputTokens": 512
            }
        }
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
                res_body = resp.read().decode("utf-8")
                res_json = json.loads(res_body)
                
                # 토큰 비용 추적 및 누적 기록
                usage = res_json.get("usageMetadata", {})
                in_tokens = usage.get("promptTokenCount", 0)
                out_tokens = usage.get("candidatesTokenCount", 0)
                self.cost_tracker.record_gemini_multimodal_call(in_tokens, out_tokens)
                
                text_out = res_json["candidates"][0]["content"]["parts"][0]["text"]
                eval_data = json.loads(text_out)
                
                selected_id = eval_data.get("selected_id")
                score = float(eval_data.get("score", 0.0))
                is_acceptable = bool(eval_data.get("is_acceptable", False))
                reason = eval_data.get("reason", "")
                
                logger.info(
                    f"[{site_domain}] [Image Gatekeeper Evaluation] Selected: '{selected_id}', "
                    f"Score: {score}/10.0, Acceptable: {is_acceptable}. Reason: {reason}"
                )
                
                # 심사 통과 기준 판정: 종횡비에 따른 이중 가드레일 적용
                if is_acceptable and selected_id in valid_candidates_map:
                    chosen_image = valid_candidates_map[selected_id]
                    aspect_ratio = float(chosen_image.get("aspect_ratio", 1.78))
                    is_vertical_or_square = aspect_ratio < 1.25

                    # 세로형/정사각(비율 < 1.25): 8.0점 이상인 경우에만 예외 승인
                    if is_vertical_or_square:
                        if score >= 8.0:
                            chosen_image["score"] = score
                            chosen_image["gatekeeper_reason"] = reason
                            logger.info(
                                f"[{site_domain}] [Image Gatekeeper Exception Passed ({score}점 >= 8.0점)] "
                                f"세로형/정사각(비율 {aspect_ratio:.2f}) 핵심 인물 사진 예외 승인 채택: {chosen_image.get('url')}"
                            )
                            return {
                                "selected_image": chosen_image,
                                "score": score,
                                "is_acceptable": True,
                                "reason": reason
                            }
                        else:
                            logger.warning(
                                f"[{site_domain}] [Image Gatekeeper Rejected] 세로형/정사각 이미지(비율 {aspect_ratio:.2f})이나 "
                                f"인물 예외 점수(8.0점) 미달 (Score: {score}). Reason: {reason}"
                            )
                            return {
                                "selected_image": None,
                                "score": score,
                                "is_acceptable": False,
                                "reason": f"세로형 이미지 인물 예외 기준(8.0점) 미달: {reason}"
                            }
                    else:
                        # 가로형 와이드(비율 >= 1.25): 기본 7.0점 이상 통과
                        if score >= 7.0:
                            chosen_image["score"] = score
                            chosen_image["gatekeeper_reason"] = reason
                            return {
                                "selected_image": chosen_image,
                                "score": score,
                                "is_acceptable": True,
                                "reason": reason
                            }
                        else:
                            logger.warning(
                                f"[{site_domain}] [Image Gatekeeper Rejected] 가로형 이미지 기준 점수(7.0점) 미달 (Score: {score}). "
                                f"Reason: {reason}"
                            )
                            return {
                                "selected_image": None,
                                "score": score,
                                "is_acceptable": False,
                                "reason": reason
                            }
                else:
                    logger.warning(
                        f"[{site_domain}] [Image Gatekeeper Rejected] All candidates fell below threshold (Score: {score}). "
                        f"Reason: {reason}"
                    )
                    return {
                        "selected_image": None,
                        "score": score,
                        "is_acceptable": False,
                        "reason": reason
                    }
        except Exception as e:
            logger.error(f"[{site_domain}] [Image Gatekeeper Error] Evaluation request failed: {e}")
            # 에러 발생 시 디펜시브 폴백: 1순위 후보 반환
            first_key = list(valid_candidates_map.keys())[0]
            fallback_img = valid_candidates_map[first_key]
            return {
                "selected_image": fallback_img,
                "score": 6.0,
                "is_acceptable": True,
                "reason": f"Fallback due to evaluation error: {e}"
            }
