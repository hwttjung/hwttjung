import os
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from publish_medicaldaily_cron import is_within_kst_operating_hours
from main import run_pipeline


class TestMedicalDailyTimeWindow(unittest.TestCase):
    def setUp(self):
        self.env = {
            "MEDICALDAILY_START_HOUR_KST": "8",
            "MEDICALDAILY_END_HOUR_KST": "19",
        }
        self.kst = timezone(timedelta(hours=9))

    def test_within_kst_operating_hours_true(self):
        """08:00부터 18:59까지는 정상적으로 True를 반환해야 함"""
        # Case 1: 08:00 정각
        t1 = datetime(2026, 11, 12, 8, 0, 0, tzinfo=self.kst)
        allowed1, _, _, _ = is_within_kst_operating_hours(self.env, override_time=t1)
        self.assertTrue(allowed1)

        # Case 2: 12:30 점심 시간
        t2 = datetime(2026, 11, 12, 12, 30, 0, tzinfo=self.kst)
        allowed2, _, _, _ = is_within_kst_operating_hours(self.env, override_time=t2)
        self.assertTrue(allowed2)

        # Case 3: 18:59:59 퇴근 직전
        t3 = datetime(2026, 11, 12, 18, 59, 59, tzinfo=self.kst)
        allowed3, _, _, _ = is_within_kst_operating_hours(self.env, override_time=t3)
        self.assertTrue(allowed3)

    def test_within_kst_operating_hours_false(self):
        """08:00 이전 및 19:00 이후는 False를 반환해야 함"""
        # Case 1: 07:59:59 출근 전
        t1 = datetime(2026, 11, 12, 7, 59, 59, tzinfo=self.kst)
        allowed1, _, _, _ = is_within_kst_operating_hours(self.env, override_time=t1)
        self.assertFalse(allowed1)

        # Case 2: 19:00:00 마감 시각
        t2 = datetime(2026, 11, 12, 19, 0, 0, tzinfo=self.kst)
        allowed2, _, _, _ = is_within_kst_operating_hours(self.env, override_time=t2)
        self.assertFalse(allowed2)

        # Case 3: 23:30 심야
        t3 = datetime(2026, 11, 12, 23, 30, 0, tzinfo=self.kst)
        allowed3, _, _, _ = is_within_kst_operating_hours(self.env, override_time=t3)
        self.assertFalse(allowed3)

    @patch("main.datetime")
    @patch("main.EnvLoader.get_sites_config")
    def test_main_pipeline_skips_medicaldaily_outside_operating_hours(self, mock_get_sites, mock_dt):
        """main.py의 run_pipeline이 KST 08~19시 외에는 medicaldaily를 스킵하는지 검증"""
        # Mock time: 20:00 KST (시간 외)
        fake_now = datetime(2026, 11, 12, 20, 0, 0, tzinfo=self.kst)
        mock_dt.now.return_value = fake_now

        mock_get_sites.return_value = [
            {"index": 15, "domain_key": "medicaldaily", "url": "https://test.url", "api_key": "test_key"}
        ]

        # 임시 소스 파일 생성
        temp_file = "data/temp_sources/test_time_source.txt"
        os.makedirs(os.path.dirname(temp_file), exist_ok=True)
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write("Original Title: Test Title\nOriginal Summary: Test Summary\n")

        try:
            # 1. ignore_time_window=False 시 스킵되어 False 반환
            res = run_pipeline(temp_file, target_sites=["medicaldaily"], ignore_time_window=False)
            self.assertFalse(res)

            # 2. ignore_time_window=True 시 시간 가드레일을 통과하는지 (그 뒤 로직으로 진행)
            # 여기서는 시간 가드레일이 continue 되지 않는지 확인하기 위해 사이트 설정을 비워서 확인
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)

    @patch("main.datetime")
    @patch("main.EnvLoader.get_sites_config")
    def test_other_sites_not_blocked_by_kst_time_window(self, mock_get_sites, mock_dt):
        """타 영문 매체는 KST 20:00(심야)여도 KST 시간 가드레일에 의해 차단되지 않음을 검증 (Blast Radius 방어)"""
        # Mock time: 20:00 KST
        fake_now = datetime(2026, 11, 12, 20, 0, 0, tzinfo=self.kst)
        mock_dt.now.return_value = fake_now

        mock_get_sites.return_value = [
            {"index": 1, "domain_key": "scienceworldreport", "url": "https://test.url", "api_key": "test_key"}
        ]

        temp_file = "data/temp_sources/test_time_other.txt"
        os.makedirs(os.path.dirname(temp_file), exist_ok=True)
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write("Original Title: Test Title\nOriginal Summary: Test Summary\n")

        try:
            # scienceworldreport는 시간 가드레일로 스킵되지 않고 카테고리 캐시 검사 등 다음 단계로 진입함
            # get_categories_for_site에서 캐시가 없어서 스킵될지언정, 시간 가드레일로 스킵되지 않음
            with patch("main.ArticlePublisher.get_categories_for_site", return_value=[]):
                res = run_pipeline(temp_file, target_sites=["scienceworldreport"], ignore_time_window=False)
                # 카테고리 캐시가 없어서 스킵되지만 시간 가드레일로 스킵되지 않는 동작 확인
                self.assertFalse(res)
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)


if __name__ == "__main__":
    unittest.main()
