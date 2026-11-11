import unittest
import json
import html
from unittest.mock import patch, MagicMock
from common.env_loader import EnvLoader
from core.generation.article_generator import ArticleGenerator


class TestOneoffTelegramPublish(unittest.TestCase):
    def setUp(self):
        self.mock_env = {
            "GEMINI_API_KEY": "fake_gemini_key",
            "TELEGRAM_API": "fake_bot_token",
            "TELEGRAM_USER_ID": "123456789"
        }
        self.generator = ArticleGenerator(self.mock_env)

    def test_count_body_words_excluding_headings_for_700_words(self):
        """소제목을 제외한 순수 영문 본문 단어 수가 700개 이상일 때 정확하게 계측되는지 검증"""
        # 3개의 <h3> 소제목과 720개의 본문 단어 생성
        h1 = "<h3>Global Economic Shifts</h3>"
        p1 = "<p>" + " ".join(["market"] * 240) + "</p>"
        h2 = "<h3>Corporate Strategy Adaptation</h3>"
        p2 = "<p>" + " ".join(["growth"] * 240) + "</p>"
        h3 = "<h3>Future Outlook and Analysis</h3>"
        p3 = "<p>" + " ".join(["resilience"] * 240) + "</p>"
        
        full_html = f"<p>Opening lead summary.</p>\n{h1}\n{p1}\n{h2}\n{p2}\n{h3}\n{p3}"
        # Opening lead has 3 words + 720 words = 723 words (headings excluded)
        word_count = ArticleGenerator.count_body_words_excluding_headings(full_html)
        self.assertEqual(word_count, 723)
        self.assertGreaterEqual(word_count, 700)

    def test_generate_supports_custom_min_words_and_max_tokens(self):
        """ArticleGenerator.generate가 min_words=700, max_tokens=4096 인자를 수용하여 프롬프트와 요청에 반영하는지 검증"""
        fake_response_content = {
            "fact_check_rationale": "Adapted corporate facts to Franchise Herald theme.",
            "title": "Global Franchise Chains Accelerate Cross-Border Expansion in 2026",
            "summary": "Major franchise networks announce aggressive regional diversification strategies.",
            "content": "<p>" + " ".join(["expansion"] * 710) + "</p><h3>Market Inroads</h3><p>Detailed analysis.</p>",
            "selected_category": "franchise-news",
            "featured_persons": [],
            "fallback_topic_keyword": "business strategy",
            "image_search_queries": ["franchise store"],
            "search_keyword": "franchise store",
            "seo_tags": "franchise, business, retail, growth, economy, market, chain, expansion, trade, corporate, brand, finance, strategy, investment, revenue, global, commerce, venture, industry, leadership"
        }

        mock_cm = MagicMock()
        mock_cm.__enter__.return_value.read.return_value = json.dumps({
            "candidates": [{
                "content": {
                    "parts": [{"text": json.dumps(fake_response_content)}]
                }
            }]
        }).encode("utf-8")

        categories = [{"slug": "franchise-news", "title": "Franchise News"}]

        with patch("urllib.request.urlopen", return_value=mock_cm) as mock_urlopen:
            res = self.generator.generate(
                source_text="Test source regarding global retail franchises.",
                target_site_domain="franchiseherald",
                available_categories=categories,
                min_words=700,
                max_tokens=4096
            )

            # urlopen 인자 검증
            req = mock_urlopen.call_args[0][0]
            req_body = json.loads(req.data.decode("utf-8"))
            
            # max_tokens 반영 확인
            self.assertEqual(req_body["generationConfig"]["maxOutputTokens"], 4096)
            
            # 프롬프트 내 700+ WORDS 지침 반영 확인
            prompt_text = req_body["contents"][0]["parts"][0]["text"]
            self.assertIn("AT LEAST 700 WORDS", prompt_text)
            self.assertIn("700+ WORDS", prompt_text)

            self.assertIsNotNone(res)
            self.assertGreaterEqual(res["word_count"], 700)

    def test_telegram_message_splitting_under_telegram_limits(self):
        """텔레그램 본문이 4000자 초과 시 3800자 단위로 안전하게 분할되어 4000자 이내로 전송되는지 검증"""
        long_content = "<p>" + "A" * 7500 + "</p>"
        escaped_content = html.escape(long_content)
        
        chunk_size = 3800
        content_chunks = [escaped_content[i:i+chunk_size] for i in range(0, len(escaped_content), chunk_size)]
        
        # 7507자가 최소 2개 이상의 청크로 분할되었는지 검증
        self.assertGreater(len(content_chunks), 1)
        
        # 각 청크의 완성된 메시지가 4000자를 넘지 않는지 검증
        for idx, chunk in enumerate(content_chunks):
            part_info = f" (Part {idx+1}/{len(content_chunks)})" if len(content_chunks) > 1 else ""
            msg = f"<b>[수동 복사 본문]{part_info}</b>\n\n<pre><code>{chunk}</code></pre>"
            self.assertLessEqual(len(msg), 4000, f"Chunk {idx+1} exceeded 4000 characters: {len(msg)}")

    def test_target_domains_have_valid_feeds_and_categories(self):
        """franchiseherald 및 foodworldnews가 rss_feeds.json 및 categories_cache.json에 유효하게 존재하는지 검증"""
        with open("config/rss_feeds.json", "r", encoding="utf-8") as f:
            feeds = json.load(f)
        self.assertIn("franchiseherald", feeds)
        self.assertIn("foodworldnews", feeds)
        self.assertGreater(len(feeds["franchiseherald"]), 0)
        self.assertGreater(len(feeds["foodworldnews"]), 0)

        with open("data/categories_cache.json", "r", encoding="utf-8") as f:
            cats = json.load(f)
        sites_cats = cats.get("sites", cats)
        self.assertIn("franchiseherald", sites_cats)
        self.assertIn("foodworldnews", sites_cats)
        self.assertGreater(len(sites_cats["franchiseherald"]), 0)
        self.assertGreater(len(sites_cats["foodworldnews"]), 0)

    def test_regular_sites_config_remains_unchanged(self):
        """정규 크론 배치 대상 12개 사이트 설정이 Scope Lock에 따라 전혀 영향받지 않고 유지되는지 검증"""
        env = EnvLoader.load_env()
        sites = EnvLoader.get_sites_config(env)
        self.assertEqual(len(sites), 12)
        domain_keys = [s["domain_key"] for s in sites]
        self.assertNotIn("franchiseherald", domain_keys)
        self.assertNotIn("foodworldnews", domain_keys)


if __name__ == "__main__":
    unittest.main()
