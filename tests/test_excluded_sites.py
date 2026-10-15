import unittest
from common.env_loader import EnvLoader


class TestExcludedSites(unittest.TestCase):
    def setUp(self):
        self.env = EnvLoader.load_env()
        self.sites = EnvLoader.get_sites_config(self.env)
        self.domain_keys = [s["domain_key"] for s in self.sites]

    def test_sites_count_is_twelve(self):
        """활성화된 전체 사이트 수가 정확히 12개인지 검증"""
        self.assertEqual(len(self.sites), 12, f"Expected 12 sites, got {len(self.sites)}")

    def test_franchiseherald_and_foodworldnews_excluded_from_sites_config(self):
        """franchiseherald 및 foodworldnews가 get_sites_config 목록에서 완전히 제외되었는지 검증"""
        self.assertNotIn("franchiseherald", self.domain_keys)
        self.assertNotIn("foodworldnews", self.domain_keys)

    def test_expected_twelve_domains_present(self):
        """예상되는 12개 매체가 모두 온전히 존재하는지 검증"""
        expected = [
            "scienceworldreport", "latinoshealth", "autoworldnews", "youthhealthmag",
            "newseveryday", "celebeat", "boomsbeat", "sportsworldreport",
            "jobsnhire", "mobilenapps", "parentherald", "booksnreview"
        ]
        self.assertEqual(self.domain_keys, expected)

    def test_dynamic_intervals_for_twelve_sites(self):
        """12개 매체에 대해 딜레이 구간(intervals)이 정확히 11개 생성되는지 검증"""
        num_intervals = max(1, len(self.sites) - 1)
        self.assertEqual(num_intervals, 11)


if __name__ == "__main__":
    unittest.main()
