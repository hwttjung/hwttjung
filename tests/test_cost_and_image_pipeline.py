import os
import sys
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.media.cost_tracker import CostTracker
from core.media.image_gatekeeper import ImageGatekeeper
from core.media.image_searcher import ImageSearcher
from core.generation.article_generator import ArticleGenerator

class TestCostTracker(unittest.TestCase):
    """CostTracker 예산 방어선 및 비용 누적 기능 Hermetic 단위 테스트"""
    
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.tracker_file = os.path.join(self.test_dir, "test_api_cost_tracker.json")
        self.tracker = CostTracker(tracker_path=self.tracker_file)
        
    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        
    def test_initial_state_can_use_google_cse(self):
        # 초기 상태에서는 100회 미만이므로 True
        self.assertTrue(self.tracker.can_use_google_cse(max_free_limit=100))
        
    def test_google_cse_budget_guard(self):
        # 99회 호출
        self.tracker.record_google_cse_call(99)
        self.assertTrue(self.tracker.can_use_google_cse(max_free_limit=100))
        
        # 1회 추가 -> 100회 도달
        self.tracker.record_google_cse_call(1)
        self.assertFalse(self.tracker.can_use_google_cse(max_free_limit=100, allow_paid=False))
        
        # allow_paid=True인 경우 허용
        self.assertTrue(self.tracker.can_use_google_cse(max_free_limit=100, allow_paid=True))
        
    def test_record_unsplash_and_pexels_calls(self):
        self.tracker.record_unsplash_call(3)
        self.tracker.record_pexels_call(2)
        
        summary = self.tracker.get_daily_summary()
        self.assertEqual(summary["unsplash_calls"], 3)
        self.assertEqual(summary["pexels_calls"], 2)
        
    def test_gemini_multimodal_cost_calculation(self):
        # 1,000,000 input tokens ($0.075), 1,000,000 output tokens ($0.30)
        # Total USD = 0.375, Total KRW = 0.375 * 1350 = 506.25 KRW
        self.tracker.record_gemini_multimodal_call(1_000_000, 1_000_000)
        
        summary = self.tracker.get_daily_summary()
        self.assertEqual(summary["gemini_multimodal_calls"], 1)
        self.assertEqual(summary["gemini_input_tokens"], 1_000_000)
        self.assertEqual(summary["gemini_output_tokens"], 1_000_000)
        self.assertAlmostEqual(summary["estimated_cost_usd"], 0.375, places=4)
        self.assertAlmostEqual(summary["estimated_cost_krw"], 506.25, places=1)
        
    def test_format_telegram_report(self):
        self.tracker.record_google_cse_call(10)
        self.tracker.record_unsplash_call(5)
        self.tracker.record_gemini_multimodal_call(10_000, 2_000)
        
        report = self.tracker.format_telegram_report()
        self.assertIn("API 비용 및 쿼리 현황", report)
        self.assertIn("10/100회", report)
        self.assertIn("잔여: 90회", report)
        self.assertIn("Unsplash/Pexels: 5회", report)
        self.assertIn("Gemini 심사: 1회", report)

class TestImageGatekeeper(unittest.TestCase):
    """ImageGatekeeper 멀티모달 심사 로직 Hermetic 단위 테스트"""
    
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.env = {"GEMINI_API_KEY": "dummy_gemini_key"}
        self.gatekeeper = ImageGatekeeper(self.env)
        self.gatekeeper.cost_tracker = CostTracker(tracker_path=os.path.join(self.test_dir, "cost.json"))
        
    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        
    @patch.object(ImageGatekeeper, "_fetch_thumbnail_base64", return_value=("fake_b64", "image/jpeg"))
    @patch("urllib.request.urlopen")
    def test_evaluate_image_match_pass(self, mock_urlopen, mock_thumb):
        # 8.5점 합격 응답 모킹
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": json.dumps({
                            "selected_id": "img_0",
                            "score": 8.5,
                            "is_acceptable": True,
                            "reason": "기사 내용과 정확히 부합하는 의료 연구 이미지입니다."
                        })
                    }]
                }
            }],
            "usageMetadata": {
                "promptTokenCount": 500,
                "candidatesTokenCount": 60
            }
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        candidates = [{
            "id": "img_0",
            "url": "https://example.com/highres.jpg",
            "thumb_url": "https://example.com/thumb.jpg",
            "credit": "Test Credit",
            "source": "Google CSE"
        }]
        
        res = self.gatekeeper.evaluate_image_match(
            article_summary="새로운 소아과 임상 연구 결과 발표",
            article_title="소아 건강 관리 혁신",
            candidate_images=candidates,
            site_domain="scienceworldreport"
        )
        
        self.assertTrue(res["is_acceptable"])
        self.assertEqual(res["score"], 8.5)
        self.assertEqual(res["selected_image"]["id"], "img_0")
        self.assertEqual(res["selected_image"]["url"], "https://example.com/highres.jpg")
        
    @patch.object(ImageGatekeeper, "_fetch_thumbnail_base64", return_value=("fake_b64", "image/jpeg"))
    @patch("urllib.request.urlopen")
    def test_evaluate_image_match_reject_below_threshold(self, mock_urlopen, mock_thumb):
        # 5.0점 불합격 응답 모킹 (동음이의어 또는 부적합)
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": json.dumps({
                            "selected_id": "img_0",
                            "score": 5.0,
                            "is_acceptable": False,
                            "reason": "기사와 무관한 과일 사과 이미지로 동음이의어 오류입니다."
                        })
                    }]
                }
            }],
            "usageMetadata": {
                "promptTokenCount": 400,
                "candidatesTokenCount": 50
            }
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        candidates = [{
            "id": "img_0",
            "url": "https://example.com/apple.jpg",
            "thumb_url": "https://example.com/thumb_apple.jpg",
            "credit": "Apple Credit",
            "source": "Google CSE"
        }]
        
        res = self.gatekeeper.evaluate_image_match(
            article_summary="애플 주가 급등 분석",
            article_title="Apple Earnings Report",
            candidate_images=candidates,
            site_domain="scienceworldreport"
        )
        
        self.assertFalse(res["is_acceptable"])
        self.assertIsNone(res["selected_image"])
        self.assertEqual(res["score"], 5.0)

class TestImageSearcher(unittest.TestCase):
    """ImageSearcher 1순위/2순위 파이프라인 및 Fallback 검증"""
    
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.env = {
            "GOOGLE_CSE_API_KEY": "valid_cse_key",
            "GOOGLE_CSE_CX": "valid_cse_cx",
            "ALLOW_PAID_GOOGLE_CSE": "False",
            "UNSPLASH_ACCESS_KEY": "valid_unsplash_key",
            "PIXELS_API_KEY": "valid_pexels_key",
            "GEMINI_API_KEY": "valid_gemini_key"
        }
        self.searcher = ImageSearcher(self.env)
        self.searcher.cost_tracker = CostTracker(tracker_path=os.path.join(self.test_dir, "cost.json"))
        self.searcher.gatekeeper.cost_tracker = self.searcher.cost_tracker
        
    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        
    @patch.object(ImageSearcher, "_search_wikimedia")
    @patch.object(ImageGatekeeper, "evaluate_image_match")
    def test_1st_priority_wikimedia_commons_success(self, mock_gatekeeper, mock_wikimedia):
        # 1순위 Wikimedia Commons 성공 시나리오 (16:9 비율)
        mock_wikimedia.return_value = [{
            "id": "wiki_0",
            "url": "https://thumb.wikimedia.org/image1_1600px.jpg",
            "thumb_url": "https://thumb.wikimedia.org/image1_1600px.jpg",
            "credit": "Photo by NASA via Wikimedia Commons (Public domain)",
            "source": "Wikimedia Commons",
            "aspect_ratio": 1.78
        }]
        mock_gatekeeper.return_value = {
            "selected_image": mock_wikimedia.return_value[0],
            "score": 9.2,
            "is_acceptable": True,
            "reason": "16:9 구도와 기사 문맥이 완벽히 일치하는 고화질 보도사진"
        }
        
        res = self.searcher.search_image(
            query="Cardiology clinical research",
            site_domain="scienceworldreport",
            article_summary="심혈관 연구 성과 발표",
            article_title="Cardiology Advances"
        )
        
        self.assertEqual(res["url"], "https://thumb.wikimedia.org/image1_1600px.jpg")
        self.assertEqual(res["source"], "Wikimedia Commons")
        self.assertEqual(res["gatekeeper_score"], 9.2)
        mock_wikimedia.assert_called_once()
        
    @patch.object(ImageSearcher, "_search_wikimedia", return_value=[])
    @patch.object(ImageSearcher, "_get_unsplash_candidates")
    @patch.object(ImageGatekeeper, "evaluate_image_match")
    def test_wikimedia_empty_falls_back_to_unsplash_16_9(
        self, mock_gatekeeper, mock_unsplash, mock_wikimedia
    ):
        # Wikimedia 결과 부재 시 Unsplash 16:9 스마트 크롭 Fallback 검증
        mock_unsplash.return_value = [{
            "id": "un_0",
            "url": "https://images.unsplash.com/photo-1234?w=1600&q=80&ar=16:9&fit=crop",
            "thumb_url": "https://images.unsplash.com/photo-1234?w=200",
            "credit": "Photo by John on Unsplash",
            "source": "Unsplash"
        }]
        mock_gatekeeper.return_value = {
            "selected_image": mock_unsplash.return_value[0],
            "score": 8.0,
            "is_acceptable": True,
            "reason": "적합한 16:9 대체 이미지"
        }
        
        res = self.searcher.search_image(
            query="AI Robotics",
            site_domain="scienceworldreport",
            article_summary="로봇 공학 혁신 발표",
            article_title="Robotics Breakthrough"
        )
        
        mock_wikimedia.assert_called_once()
        mock_unsplash.assert_called_once()
        self.assertIn("ar=16:9", res["url"])
        self.assertEqual(res["source"], "Unsplash")

    @patch("urllib.request.urlopen")
    def test_search_wikimedia_aspect_ratio_and_license_filter(self, mock_urlopen):
        # 1) 극단적 세로형 문서(800x2000, aspect_ratio=0.4) -> 탈락
        # 2) NC 라이선스 사진(1920x1080, CC-BY-NC) -> 탈락
        # 3) 안전한 16:9 사진(1920x1080, aspect_ratio=1.78, CC-BY 4.0) -> 합격
        # 4) 인물 후보용 세로형 사진(1200x1600, aspect_ratio=0.75, CC-BY 4.0) -> 후보군 합격
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "query": {
                "pages": {
                    "1": {
                        "title": "File:Extreme_Vertical_Scan.jpg",
                        "imageinfo": [{
                            "mime": "image/jpeg",
                            "width": 800,
                            "height": 2000,  # 극단적 세로형 (aspect_ratio = 0.40)
                            "thumburl": "https://thumb.wikimedia.org/scan.jpg",
                            "extmetadata": {"LicenseShortName": {"value": "CC-BY 4.0"}}
                        }]
                    },
                    "2": {
                        "title": "File:NonCommercial_Chart.jpg",
                        "imageinfo": [{
                            "mime": "image/jpeg",
                            "width": 1920,
                            "height": 1080,
                            "thumburl": "https://thumb.wikimedia.org/nc.jpg",
                            "extmetadata": {"LicenseShortName": {"value": "CC-BY-NC 3.0"}}  # NC 탈락
                        }]
                    },
                    "3": {
                        "title": "File:Perfect_16_9_Hospital.jpg",
                        "imageinfo": [{
                            "mime": "image/jpeg",
                            "width": 1920,
                            "height": 1080,  # 16:9 (aspect_ratio = 1.78)
                            "thumburl": "https://thumb.wikimedia.org/perfect_16_9.jpg",
                            "extmetadata": {
                                "LicenseShortName": {"value": "CC-BY 4.0"},
                                "Artist": {"value": "Dr. Smith"}
                            }
                        }]
                    },
                    "4": {
                        "title": "File:Portrait_Doctor.jpg",
                        "imageinfo": [{
                            "mime": "image/jpeg",
                            "width": 1200,
                            "height": 1600,  # 세로형 인물 후보 (aspect_ratio = 0.75)
                            "thumburl": "https://thumb.wikimedia.org/portrait_doc.jpg",
                            "extmetadata": {
                                "LicenseShortName": {"value": "CC-BY 4.0"},
                                "Artist": {"value": "Dr. Jane"}
                            }
                        }]
                    }
                }
            }
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        candidates = self.searcher._search_wikimedia("hospital", [], "scienceworldreport")
        # 1(0.40 탈락), 2(NC 탈락) -> 3(16:9), 4(0.75 세로형) 2건 후보 통과
        self.assertEqual(len(candidates), 2)
        urls = [c["url"] for c in candidates]
        self.assertIn("https://thumb.wikimedia.org/perfect_16_9.jpg", urls)
        self.assertIn("https://thumb.wikimedia.org/portrait_doc.jpg", urls)

    @patch.object(ImageSearcher, "_search_wikimedia", return_value=[])
    @patch.object(ImageSearcher, "_get_unsplash_candidates", return_value=[])
    @patch.object(ImageSearcher, "_get_pexels_candidates", return_value=[])
    def test_backward_compatibility_positional_domain(self, mock_pex, mock_un, mock_wiki):
        res = self.searcher.search_image("technology", "scienceworldreport")
        self.assertIn("url", res)
        self.assertIn("credit", res)

    @patch.object(ImageSearcher, "_search_wikimedia")
    @patch.object(ImageGatekeeper, "evaluate_image_match")
    def test_cascade_image_search_primary_person_success(self, mock_gatekeeper, mock_wikimedia):
        # 1순위 주인공 인명에서 합격 이미지를 찾아 즉시 반환하는 시나리오
        queries = ["Ben Whittaker", "Conor Wallace", "boxing match"]
        
        mock_wikimedia.return_value = [{
            "id": "ben_0",
            "url": "https://thumb.wikimedia.org/ben_whittaker_1600.jpg",
            "thumb_url": "https://thumb.wikimedia.org/ben_whittaker_1600.jpg",
            "credit": "Photo by Sports Wire via Wikimedia Commons (CC-BY 4.0)",
            "source": "Wikimedia Commons",
            "aspect_ratio": 1.78
        }]
        mock_gatekeeper.return_value = {
            "selected_image": mock_wikimedia.return_value[0],
            "score": 9.0,
            "is_acceptable": True,
            "reason": "기사 주인공 Ben Whittaker의 선명한 가로형 16:9 보도사진"
        }
        
        res = self.searcher.search_image(
            query=queries,
            site_domain="sportsworldreport",
            article_summary="Ben Whittaker faces scrutiny after bout",
            article_title="Ben Whittaker Faces Scrutiny"
        )
        
        self.assertEqual(res["url"], "https://thumb.wikimedia.org/ben_whittaker_1600.jpg")
        self.assertEqual(res["source"], "Wikimedia Commons")
        self.assertEqual(res["gatekeeper_score"], 9.0)
        self.assertEqual(mock_wikimedia.call_count, 1)

    @patch.object(ImageSearcher, "_get_pexels_candidates", return_value=[])
    @patch.object(ImageSearcher, "_get_unsplash_candidates", return_value=[])
    @patch.object(ImageSearcher, "_search_wikimedia")
    @patch.object(ImageGatekeeper, "evaluate_image_match")
    def test_cascade_image_search_fallback_to_secondary_person(
        self, mock_gatekeeper, mock_wikimedia, mock_unsplash, mock_pexels
    ):
        # 1순위 Ben Whittaker 부재 -> 2순위 Conor Wallace에서 합격 이미지 채택
        queries = ["Ben Whittaker", "Conor Wallace", "boxing match"]
        
        def wikimedia_side_effect(q, exclude_urls, domain):
            if "Ben" in q:
                return []
            if "Conor" in q:
                return [{
                    "id": "conor_0",
                    "url": "https://thumb.wikimedia.org/conor_wallace.jpg",
                    "thumb_url": "https://thumb.wikimedia.org/conor_wallace.jpg",
                    "credit": "Photo by Boxing Club via Wikimedia Commons (Public domain)",
                    "source": "Wikimedia Commons",
                    "aspect_ratio": 1.6
                }]
            return []
            
        mock_wikimedia.side_effect = wikimedia_side_effect
        mock_gatekeeper.return_value = {
            "selected_image": {
                "id": "conor_0",
                "url": "https://thumb.wikimedia.org/conor_wallace.jpg",
                "thumb_url": "https://thumb.wikimedia.org/conor_wallace.jpg",
                "credit": "Photo by Boxing Club via Wikimedia Commons (Public domain)",
                "source": "Wikimedia Commons",
                "aspect_ratio": 1.6
            },
            "score": 8.5,
            "is_acceptable": True,
            "reason": "핵심 상대방 Conor Wallace의 경기 사진"
        }
        
        res = self.searcher.search_image(
            query=queries,
            site_domain="sportsworldreport",
            article_summary="Challenging bout details",
            article_title="Ben Whittaker Faces Scrutiny After Challenging Bout"
        )
        
        self.assertEqual(res["url"], "https://thumb.wikimedia.org/conor_wallace.jpg")
        self.assertEqual(res["gatekeeper_score"], 8.5)
        self.assertEqual(mock_wikimedia.call_count, 2)

    @patch.object(ImageSearcher, "_get_pexels_candidates", return_value=[])
    @patch.object(ImageSearcher, "_get_unsplash_candidates")
    @patch.object(ImageSearcher, "_search_wikimedia", return_value=[])
    @patch.object(ImageGatekeeper, "evaluate_image_match")
    def test_cascade_image_search_fallback_to_topic_keyword(
        self, mock_gatekeeper, mock_wikimedia, mock_unsplash, mock_pexels
    ):
        # 인명 사진이 모두 부재하여 마지막 주제 키워드(boxing match)의 Unsplash 16:9 사진 채택
        queries = ["Ben Whittaker", "Conor Wallace", "boxing match"]
        
        def unsplash_side_effect(q, exclude_urls, domain):
            if q == "boxing match":
                return [{
                    "id": "boxing_ring",
                    "url": "https://images.unsplash.com/photo-boxing?w=1600&q=80&ar=16:9&fit=crop",
                    "thumb_url": "https://images.unsplash.com/photo-boxing?w=200",
                    "credit": "Photo by Match Photographer on Unsplash",
                    "source": "Unsplash"
                }]
            return []
            
        mock_unsplash.side_effect = unsplash_side_effect
        mock_gatekeeper.return_value = {
            "selected_image": {
                "id": "boxing_ring",
                "url": "https://images.unsplash.com/photo-boxing?w=1600&q=80&ar=16:9&fit=crop",
                "thumb_url": "https://images.unsplash.com/photo-boxing?w=200",
                "credit": "Photo by Match Photographer on Unsplash",
                "source": "Unsplash"
            },
            "score": 8.0,
            "is_acceptable": True,
            "reason": "복싱 링 경기 현장 16:9 보도사진"
        }
        
        res = self.searcher.search_image(
            query=queries,
            site_domain="sportsworldreport",
            article_summary="Bout summary",
            article_title="Ben Whittaker vs Conor Wallace"
        )
        
        self.assertIn("photo-boxing", res["url"])
        self.assertEqual(res["source"], "Unsplash")

    def test_article_generator_normalize_image_queries(self):
        # ArticleGenerator 인명 우선순위 쿼리 정규화 및 가드레일 단위 테스트
        generator = ArticleGenerator(env={"GEMINI_API_KEY": "fake_key"})
        
        # 케이스 1: 인명 2명과 fallback 주제 키워드가 완벽히 있는 경우
        data1 = {
            "featured_persons": ["Ben Whittaker", "Conor Wallace"],
            "fallback_topic_keyword": "boxing match",
            "image_search_queries": ["Ben Whittaker", "Conor Wallace", "boxing match"]
        }
        norm1 = generator._normalize_image_queries(data1)
        self.assertEqual(norm1["image_search_queries"], ["Ben Whittaker", "Conor Wallace", "boxing match"])
        self.assertEqual(norm1["search_keyword"], "Ben Whittaker")
        
        # 케이스 2: 인물이 없는 일반 기술 기사 (featured_persons=[])
        data2 = {
            "featured_persons": [],
            "fallback_topic_keyword": "artificial intelligence robotics",
            "image_search_queries": []
        }
        norm2 = generator._normalize_image_queries(data2)
        self.assertEqual(norm2["image_search_queries"], ["artificial intelligence robotics"])
        self.assertEqual(norm2["search_keyword"], "artificial intelligence robotics")
        
        # 케이스 3: 구버전 응답 (featured_persons 누락, search_keyword만 있음)
        data3 = {
            "search_keyword": "space telescope"
        }
        norm3 = generator._normalize_image_queries(data3)
        self.assertEqual(norm3["image_search_queries"], ["space telescope"])
        self.assertEqual(norm3["search_keyword"], "space telescope")
        self.assertEqual(norm3["featured_persons"], [])

    @patch.object(ImageGatekeeper, "_fetch_thumbnail_base64", return_value=("fake_b64", "image/jpeg"))
    @patch("urllib.request.urlopen")
    def test_gatekeeper_person_aspect_ratio_exception_8_0_pass(self, mock_urlopen, mock_thumb):
        # 세로형(0.75) 인물 사진이 8.5점 합격 판정 시 예외조항 통과 검증
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": json.dumps({
                            "selected_id": "img_portrait",
                            "score": 8.5,
                            "is_acceptable": True,
                            "reason": "기사 주인공의 실제 세로형 프로필 사진으로 주제 적합성이 매우 높음"
                        })
                    }]
                }
            }]
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        candidates = [{
            "id": "img_portrait",
            "url": "https://thumb.wikimedia.org/boxer_portrait.jpg",
            "thumb_url": "https://thumb.wikimedia.org/boxer_portrait.jpg",
            "credit": "Photo on Wikimedia",
            "aspect_ratio": 0.75  # 세로형
        }]

        gatekeeper = ImageGatekeeper(env={"GEMINI_API_KEY": "fake_key"})
        res = gatekeeper.evaluate_image_match(
            article_summary="Ben Whittaker bout victory",
            article_title="Ben Whittaker Bout",
            candidate_images=candidates,
            site_domain="sportsworldreport"
        )

        self.assertTrue(res["is_acceptable"])
        self.assertEqual(res["score"], 8.5)
        self.assertEqual(res["selected_image"]["id"], "img_portrait")

    @patch.object(ImageGatekeeper, "_fetch_thumbnail_base64", return_value=("fake_b64", "image/jpeg"))
    @patch("urllib.request.urlopen")
    def test_gatekeeper_person_aspect_ratio_exception_below_8_0_reject(self, mock_urlopen, mock_thumb):
        # 세로형(0.75) 사진이 7.5점(7.0점은 넘지만 8.0점 미달)인 경우 예외 기준 미달 탈락 검증
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": json.dumps({
                            "selected_id": "img_portrait",
                            "score": 7.5,
                            "is_acceptable": True,
                            "reason": "세로형 인물 사진이나 일치도가 다소 애매함"
                        })
                    }]
                }
            }]
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        candidates = [{
            "id": "img_portrait",
            "url": "https://thumb.wikimedia.org/boxer_portrait.jpg",
            "thumb_url": "https://thumb.wikimedia.org/boxer_portrait.jpg",
            "credit": "Photo on Wikimedia",
            "aspect_ratio": 0.75  # 세로형
        }]

        gatekeeper = ImageGatekeeper(env={"GEMINI_API_KEY": "fake_key"})
        res = gatekeeper.evaluate_image_match(
            article_summary="Ben Whittaker bout victory",
            article_title="Ben Whittaker Bout",
            candidate_images=candidates,
            site_domain="sportsworldreport"
        )

        self.assertFalse(res["is_acceptable"])
        self.assertIsNone(res["selected_image"])
        self.assertIn("8.0점", res["reason"])

if __name__ == "__main__":
    unittest.main()
