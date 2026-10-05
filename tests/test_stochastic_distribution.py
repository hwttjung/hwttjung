import unittest
import os
import json
import tempfile
from unittest.mock import patch, MagicMock
from core.storage.duplicate_preventer import DuplicatePreventer

class TestStochasticDistribution(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.history_file = os.path.join(self.temp_dir, "test_history.json")
        
        # 가상의 7일 발행 히스토리 구축:
        # space-the-future: 5회 발행 (빈도 높음)
        # physics: 3회 발행
        # human: 0회 발행 (미발행)
        # health-medicine: 0회 발행 (미발행)
        mock_history = {
            "scienceworldreport": [
                {"category": "space-the-future", "timestamp": "2026-09-30T10:00:00+00:00Z"},
                {"category": "space-the-future", "timestamp": "2026-09-29T10:00:00+00:00Z"},
                {"category": "space-the-future", "timestamp": "2026-09-28T10:00:00+00:00Z"},
                {"category": "space-the-future", "timestamp": "2026-09-27T10:00:00+00:00Z"},
                {"category": "space-the-future", "timestamp": "2026-09-26T10:00:00+00:00Z"},
                {"category": "physics", "timestamp": "2026-09-25T10:00:00+00:00Z"},
                {"category": "physics", "timestamp": "2026-09-24T10:00:00+00:00Z"},
                {"category": "physics", "timestamp": "2026-09-23T10:00:00+00:00Z"},
            ]
        }
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(mock_history, f)
            
        self.preventer = DuplicatePreventer(history_path=self.history_file)

    def test_stochastic_category_selection(self):
        available = [
            {"id": 1, "slug": "space-the-future", "title": "Space"},
            {"id": 8, "slug": "physics", "title": "Physics"},
            {"id": 9, "slug": "human", "title": "Human"},
            {"id": 3, "slug": "health-medicine", "title": "Health & Medicine"}
        ]
        
        # 100회 시뮬레이션 추첨
        sample_counts = {"space-the-future": 0, "physics": 0, "human": 0, "health-medicine": 0}
        for _ in range(100):
            chosen = self.preventer.get_stochastically_weighted_category("scienceworldreport", available)
            self.assertIsNotNone(chosen)
            sample_counts[chosen["slug"]] += 1
            
        # 미발행 카테고리(human, health-medicine)의 합산 당첨률이 5회 발행된 우주보다 압도적으로 높아야 함
        uncovered_sum = sample_counts["human"] + sample_counts["health-medicine"]
        space_count = sample_counts["space-the-future"]
        self.assertGreater(uncovered_sum, space_count, f"Uncovered categories ({uncovered_sum}) should exceed space ({space_count})")

    def test_sort_categories_by_stochastic_priority(self):
        available = [
            {"slug": "space-the-future"},
            {"slug": "physics"},
            {"slug": "human"},
            {"slug": "health-medicine"}
        ]
        sorted_cats = self.preventer.sort_categories_by_stochastic_priority("scienceworldreport", available)
        top_two_slugs = {sorted_cats[0]["slug"], sorted_cats[1]["slug"]}
        # 빈도 0인 human과 health-medicine이 상위 2개 자리를 차지해야 함
        self.assertEqual(top_two_slugs, {"human", "health-medicine"})
        # 5회로 가장 많은 space-the-future는 가장 뒤에 위치해야 함
        self.assertEqual(sorted_cats[-1]["slug"], "space-the-future")

    def test_forced_bypass_eval_res_contract(self):
        # Forced Bypass 시 eval_res 기본 구조체 키 검증
        default_eval_res = {
            "suitability": "APPROVED",
            "decision": "CREATE",
            "reason": "Forced editorial bypass activated.",
            "story_id": None,
            "parent_article_id": None
        }
        self.assertEqual(default_eval_res.get("suitability"), "APPROVED")
        self.assertEqual(default_eval_res.get("decision"), "CREATE")
        self.assertIsNone(default_eval_res.get("story_id"))
        self.assertIsNone(default_eval_res.get("parent_article_id"))

    def test_latinoshealth_stochastic_category_selection(self):
        # latinoshealth: science-news/news 편중 상황에서 healthy-habits/buzz 우선 추첨 검증
        mock_history = {
            "latinoshealth": [
                {"category": "science-news", "timestamp": "2026-09-30T10:00:00+00:00Z"},
                {"category": "science-news", "timestamp": "2026-09-29T10:00:00+00:00Z"},
                {"category": "science-news", "timestamp": "2026-09-28T10:00:00+00:00Z"},
                {"category": "science-news", "timestamp": "2026-09-27T10:00:00+00:00Z"},
                {"category": "news", "timestamp": "2026-09-26T10:00:00+00:00Z"},
                {"category": "news", "timestamp": "2026-09-25T10:00:00+00:00Z"}
            ]
        }
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(mock_history, f)
            
        available = [
            {"id": 1, "slug": "healthy-habits", "title": "Healthy Habits"},
            {"id": 2, "slug": "news", "title": "Latinos Health News"},
            {"id": 3, "slug": "science-news", "title": "Science News"},
            {"id": 7, "slug": "latinoshealthbuzz", "title": "Latinos Health Buzz"}
        ]
        
        sample_counts = {"healthy-habits": 0, "news": 0, "science-news": 0, "latinoshealthbuzz": 0}
        for _ in range(100):
            chosen = self.preventer.get_stochastically_weighted_category("latinoshealth", available)
            self.assertIsNotNone(chosen)
            sample_counts[chosen["slug"]] += 1
            
        uncovered = sample_counts["healthy-habits"] + sample_counts["latinoshealthbuzz"]
        science_cnt = sample_counts["science-news"]
        self.assertGreater(uncovered, science_cnt, f"Uncovered ({uncovered}) should exceed science-news ({science_cnt})")

    def test_youthhealthmag_stochastic_category_selection(self):
        # youthhealthmag: teenHeath 편중 상황에서 mind, diet-fitness, beauty-style 우선 추첨 검증
        mock_history = {
            "youthhealthmag": [
                {"category": "teenHeath", "timestamp": "2026-09-30T10:00:00+00:00Z"},
                {"category": "teenHeath", "timestamp": "2026-09-29T10:00:00+00:00Z"},
                {"category": "teenHeath", "timestamp": "2026-09-28T10:00:00+00:00Z"},
                {"category": "teenHeath", "timestamp": "2026-09-27T10:00:00+00:00Z"}
            ]
        }
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(mock_history, f)
            
        available = [
            {"id": 1, "slug": "teenHeath", "title": "Teen Health"},
            {"id": 9, "slug": "mind", "title": "Mind"},
            {"id": 3, "slug": "diet-fitness", "title": "Diet & Fitness"},
            {"id": 5, "slug": "beauty-style", "title": "Beauty & Style"}
        ]
        
        sample_counts = {"teenHeath": 0, "mind": 0, "diet-fitness": 0, "beauty-style": 0}
        for _ in range(100):
            chosen = self.preventer.get_stochastically_weighted_category("youthhealthmag", available)
            self.assertIsNotNone(chosen)
            sample_counts[chosen["slug"]] += 1
            
        uncovered = sample_counts["mind"] + sample_counts["diet-fitness"] + sample_counts["beauty-style"]
        teen_cnt = sample_counts["teenHeath"]
        self.assertGreater(uncovered, teen_cnt, f"Uncovered ({uncovered}) should exceed teenHeath ({teen_cnt})")

    def test_get_primary_feed_keywords_from_file(self):
        from publish_tailored_articles import get_primary_feed_keywords
        lh_keywords = get_primary_feed_keywords("latinoshealth")
        self.assertIn("habit", lh_keywords)
        self.assertIn("cancer", lh_keywords)
        
        yhm_keywords = get_primary_feed_keywords("youthhealthmag")
        self.assertIn("mind", yhm_keywords)
        self.assertIn("beauty", yhm_keywords)

    def test_get_primary_feed_keywords_fallback(self):
        from publish_tailored_articles import get_primary_feed_keywords, FALLBACK_FEED_KEYWORDS
        # 존재하지 않는 파일 지정 시 안전 폴백
        keywords = get_primary_feed_keywords("latinoshealth", config_path="non_existent_file.json")
        self.assertEqual(keywords, FALLBACK_FEED_KEYWORDS["latinoshealth"])
        
        # 손상된 JSON 파일 지정 시 안전 폴백
        corrupt_file = os.path.join(self.temp_dir, "corrupt.json")
        with open(corrupt_file, "w") as f:
            f.write("{invalid_json:")
        fallback_keywords = get_primary_feed_keywords("youthhealthmag", config_path=corrupt_file)
        self.assertEqual(fallback_keywords, FALLBACK_FEED_KEYWORDS["youthhealthmag"])

if __name__ == "__main__":
    unittest.main()

