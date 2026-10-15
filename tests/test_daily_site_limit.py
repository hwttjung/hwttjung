import os
import sys
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.storage.duplicate_preventer import DuplicatePreventer


class TestDailySiteLimit(unittest.TestCase):
    """
    매체당 일일 송출 기사 수(1개) 상한 제한 가드레일 Hermetic 단위 테스트
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.history_file = os.path.join(self.temp_dir, "published_history.json")
        self.kst = timezone(timedelta(hours=9))
        self.today_kst = datetime.now(self.kst).strftime("%Y-%m-%d")
        self.yesterday_kst = (datetime.now(self.kst) - timedelta(days=1)).strftime("%Y-%m-%d")

    def test_daily_limit_zero_articles_allowed(self):
        """당일 발행 기사가 0건일 때 일일 상한선(1건) 미달로 정상 허용 검증"""
        mock_history = {
            "scienceworldreport": [
                {
                    "title": "Yesterday Article",
                    "category": "physics",
                    "date": self.yesterday_kst,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            ]
        }
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(mock_history, f)

        preventer = DuplicatePreventer(history_path=self.history_file)
        with preventer._lock():
            history = preventer._load_history()

        site_hist = history.get("scienceworldreport", [])
        today_count = sum(1 for item in site_hist if item.get("date") == self.today_kst)
        daily_limit = 1

        self.assertEqual(today_count, 0)
        self.assertLess(today_count, daily_limit, "0건일 때는 일일 상한 미달이어야 함")

    def test_daily_limit_reached_blocked(self):
        """당일 발행 기사가 이미 1건 존재할 때 일일 상한선(1건) 도달로 스킵 차단 검증"""
        mock_history = {
            "autoworldnews": [
                {
                    "title": "Today First Article",
                    "category": "auto-news",
                    "date": self.today_kst,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            ]
        }
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(mock_history, f)

        preventer = DuplicatePreventer(history_path=self.history_file)
        with preventer._lock():
            history = preventer._load_history()

        site_hist = history.get("autoworldnews", [])
        today_count = sum(1 for item in site_hist if item.get("date") == self.today_kst)
        daily_limit = 1

        self.assertEqual(today_count, 1)
        self.assertGreaterEqual(today_count, daily_limit, "1건 이상일 때는 일일 상한 도달로 스킵되어야 함")

    def test_run_pipeline_skips_when_daily_limit_reached(self):
        """main.py의 run_pipeline이 당일 1건 발행 매체에 대해 기사 생성/송출을 조기 스킵하는지 검증"""
        from main import run_pipeline

        mock_history = {
            "latinoshealth": [
                {
                    "title": "Today Published Health Article",
                    "category": "wellness",
                    "date": self.today_kst,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            ]
        }

        # Mock DuplicatePreventer to use our mock history
        with patch("main.DuplicatePreventer") as mock_dp_cls:
            mock_dp_inst = MagicMock()
            mock_dp_inst._load_history.return_value = mock_history
            mock_dp_cls.return_value = mock_dp_inst

            # Mock ArticleGenerator to verify it is NEVER called when skipped
            with patch("main.ArticleGenerator") as mock_gen_cls:
                mock_gen_inst = MagicMock()
                mock_gen_cls.return_value = mock_gen_inst

                # Mock ArticlePublisher to verify publish is NEVER called
                with patch("main.ArticlePublisher") as mock_pub_cls:
                    mock_pub_inst = MagicMock()
                    mock_pub_cls.return_value = mock_pub_inst

                    # 임시 소스 파일
                    temp_src = os.path.join(self.temp_dir, "test_src.txt")
                    with open(temp_src, "w", encoding="utf-8") as tf:
                        tf.write("Sample test headline and body text.")

                    # run_pipeline 실행
                    res = run_pipeline(
                        source_file_path=temp_src,
                        target_sites=["latinoshealth"],
                        mode="tailored"
                    )

                    # 조기 스킵으로 기사 생성 및 송출 호출이 0회여야 함
                    self.assertFalse(res, "스킵 시 성공 플래그는 False여야 함")
                    mock_gen_inst.generate.assert_not_called()
                    mock_pub_inst.publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
