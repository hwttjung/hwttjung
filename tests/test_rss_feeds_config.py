import unittest
import json
import os
import re

class TestRssFeedsConfiguration(unittest.TestCase):
    CONFIG_PATH = "config/rss_feeds.json"

    def setUp(self):
        self.assertTrue(os.path.exists(self.CONFIG_PATH), f"{self.CONFIG_PATH} does not exist.")
        with open(self.CONFIG_PATH, "r", encoding="utf-8") as f:
            self.feeds = json.load(f)

    def test_json_structure_and_types(self):
        """JSON 최상위 객체가 딕셔너리이고 각 도메인 값들이 문자열 리스트인지 검증"""
        self.assertIsInstance(self.feeds, dict)
        for domain, urls in self.feeds.items():
            self.assertIsInstance(domain, str)
            self.assertIsInstance(urls, list, f"Domain {domain} must have a list of URLs")
            for url in urls:
                self.assertIsInstance(url, str, f"URL {url} in {domain} must be a string")
                self.assertTrue(url.startswith("http://") or url.startswith("https://"),
                                f"URL {url} must start with http:// or https://")

    def test_14_domains_preserved(self):
        """14개 주요 발행 대상 도메인 키가 모두 온전히 보존되어 있는지 검증"""
        expected_domains = [
            "scienceworldreport", "latinoshealth", "autoworldnews", "youthhealthmag",
            "newseveryday", "celebeat", "boomsbeat", "sportsworldreport",
            "jobsnhire", "franchiseherald", "parentherald", "booksnreview",
            "foodworldnews", "mobilenapps"
        ]
        for domain in expected_domains:
            self.assertIn(domain, self.feeds, f"Domain {domain} must be present in rss_feeds.json")
            self.assertGreater(len(self.feeds[domain]), 0, f"Domain {domain} must have at least 1 feed URL")

    def test_scienceworldreport_expanded_count_and_no_duplicates(self):
        """scienceworldreport 피드가 28개로 확장되었고 중복이 0건인지 검증"""
        swr_urls = self.feeds.get("scienceworldreport", [])
        self.assertEqual(len(swr_urls), 28, f"scienceworldreport must have exactly 28 feeds, got {len(swr_urls)}")
        self.assertEqual(len(swr_urls), len(set(swr_urls)), "scienceworldreport must not contain duplicate URLs")

    def test_new_8_feeds_present(self):
        """신규 8종 검증 피드가 빠짐없이 scienceworldreport에 포함되어 있는지 검증"""
        expected_new_feeds = [
            "https://www.canarymedia.com/rss",
            "https://cleantechnica.com/feed/",
            "https://neurosciencenews.com/feed/",
            "https://braintomorrow.com/feed/",
            "https://phys.org/rss-feed/nanotech-news/",
            "https://rss.sciencedirect.com/publication/science/13697021",
            "https://www.archaeology.org/feed/",
            "https://www.sciencedaily.com/rss/fossils_ruins/paleontology.xml",
        ]
        swr_urls = set(self.feeds.get("scienceworldreport", []))
        for feed in expected_new_feeds:
            self.assertIn(feed, swr_urls, f"Expected feed {feed} not found in scienceworldreport")

    def test_forbidden_feeds_not_present(self):
        """HTTP 403 차단 피드(Science|Business) 등 결함 피드가 혼입되지 않았는지 검증"""
        swr_urls = set(self.feeds.get("scienceworldreport", []))
        self.assertNotIn("https://sciencebusiness.net/rss", swr_urls, "Blocked feed Science|Business must not be present")


if __name__ == "__main__":
    unittest.main()
