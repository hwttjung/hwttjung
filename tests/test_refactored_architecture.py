import os
import sys
import unittest
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class TestHermeticFixtures(unittest.TestCase):
    """외부 네트워크 호출 없이 정적 피스처 기반으로만 수행되는 Hermetic 단위 테스트"""

    def setUp(self):
        self.fixtures_dir = os.path.join(PROJECT_ROOT, "tests", "fixtures")

    def test_valid_rss_fixture_parsing(self):
        fixture_path = os.path.join(self.fixtures_dir, "valid_rss.xml")
        self.assertTrue(os.path.exists(fixture_path), "valid_rss.xml fixture must exist")

        with open(fixture_path, "r", encoding="utf-8") as f:
            xml_text = f.read()

        root = ET.fromstring(xml_text)
        items = root.findall(".//item")
        self.assertEqual(len(items), 2, "Valid RSS must contain exactly 2 items")

        # First item checks (CDATA extraction & UTC normalisation)
        item1 = items[0]
        title1 = item1.find("title").text.strip()
        link1 = item1.find("link").text.strip()
        pub1 = item1.find("pubDate").text.strip()
        desc1 = item1.find("description").text.strip()

        self.assertIn("Exoplanet", title1)
        self.assertEqual(link1, "https://example.com/science/exoplanet-discovery-2026")
        self.assertIn("circumstellar habitable zone", desc1)

        dt1 = parsedate_to_datetime(pub1)
        if dt1.tzinfo is None:
            dt1 = dt1.replace(tzinfo=timezone.utc)
        else:
            dt1 = dt1.astimezone(timezone.utc)
        self.assertEqual(dt1.year, 2026)

    def test_missing_fields_fixture_handling(self):
        fixture_path = os.path.join(self.fixtures_dir, "missing_fields.xml")
        self.assertTrue(os.path.exists(fixture_path), "missing_fields.xml fixture must exist")

        with open(fixture_path, "r", encoding="utf-8") as f:
            xml_text = f.read()

        root = ET.fromstring(xml_text)
        items = root.findall(".//item")
        self.assertEqual(len(items), 2)

        valid_items = []
        for it in items:
            link = it.find("link")
            pub = it.find("pubDate")
            if link is not None and link.text and pub is not None and pub.text:
                valid_items.append(it)

        # 1st item should be dropped (missing link & pubDate), 2nd retained
        self.assertEqual(len(valid_items), 1, "Malformed item without link/pubDate must be dropped while valid item is retained")
        self.assertEqual(valid_items[0].find("title").text.strip(), "Valid Item In Mixed Feed")


class TestPackageArchitectureImports(unittest.TestCase):
    """신규 패키지 구조 및 레거시 Facade Re-export 하위 호환성 검증 테스트"""

    def test_common_package_imports(self):
        from common.logger_setup import get_domain_logger
        logger = get_domain_logger("test_domain")
        self.assertIsNotNone(logger)

        from common.env_loader import EnvLoader, TelegramNotifier
        self.assertTrue(callable(EnvLoader.load_env))
        self.assertTrue(callable(TelegramNotifier.send_notification))

    def test_core_generation_package_imports(self):
        from core.generation.article_generator import ArticleGenerator
        from core.generation.travel_article_generator import TravelArticleGenerator
        from core.generation.crossword_generator import create_crossword_article
        from core.generation.fact_checker import evaluate_article_suitability, verify_article_facts

        self.assertIsNotNone(ArticleGenerator)
        self.assertIsNotNone(TravelArticleGenerator)
        self.assertTrue(callable(create_crossword_article))
        self.assertTrue(callable(evaluate_article_suitability))
        self.assertTrue(callable(verify_article_facts))

    def test_core_publishing_package_imports(self):
        from core.publishing.article_publisher import ArticlePublisher
        self.assertIsNotNone(ArticlePublisher)

    def test_core_storage_package_imports(self):
        from core.storage.duplicate_preventer import DuplicatePreventer
        from core.storage.history_archiver import HistoryArchiver
        self.assertIsNotNone(DuplicatePreventer)
        self.assertIsNotNone(HistoryArchiver)

    def test_core_media_package_imports(self):
        from core.media.image_searcher import ImageSearcher
        self.assertIsNotNone(ImageSearcher)

    def test_core_ingestion_package_imports(self):
        from core.ingestion.trend_analyzer import extract_core_seed_keyword
        self.assertTrue(callable(extract_core_seed_keyword))

    def test_daemons_package_imports(self):
        from daemons.telegram_listener import check_stop_publishing
        self.assertTrue(callable(check_stop_publishing))

    def test_core_and_common_component_instantiation(self):
        """신규 패키지의 핵심 컴포넌트들이 정상 인스턴스화되고 메서드가 호출 가능한지 검증"""
        from common.logger_setup import get_domain_logger
        from common.env_loader import EnvLoader, TelegramNotifier
        from core.storage.duplicate_preventer import DuplicatePreventer
        from core.storage.history_archiver import HistoryArchiver
        from core.media.image_searcher import ImageSearcher
        from core.publishing.article_publisher import ArticlePublisher
        from core.generation.article_generator import ArticleGenerator

        logger = get_domain_logger("test")
        self.assertIsNotNone(logger)

        env = EnvLoader.load_env()
        self.assertIsInstance(env, dict)

        dp = DuplicatePreventer(history_path="data/test_dup_history.json")
        self.assertIsNotNone(dp)

        ha = HistoryArchiver()
        self.assertIsNotNone(ha)

        img = ImageSearcher(env)
        self.assertIsNotNone(img)

        pub = ArticlePublisher()
        self.assertIsNotNone(pub)

        gen = ArticleGenerator(env)
        self.assertIsNotNone(gen)



if __name__ == "__main__":
    unittest.main()
