import unittest
from unittest.mock import patch, MagicMock
from common.env_loader import EnvLoader
from core.generation.article_generator import ArticleGenerator
from core.generation.link_injector import LinkInjector
from core.media.image_searcher import ImageSearcher
from core.publishing.article_publisher import ArticlePublisher, MEDICALDAILY_REPORTERS


class TestReceiveArticleApiBranch(unittest.TestCase):
    def setUp(self):
        self.publisher = ArticlePublisher()
        self.site_config = {
            "index": 15,
            "domain_key": "medicaldaily",
            "url": "https://www.medicaldaily.co.kr/api/receive-article?paper=medi",
            "api_key": "test-dummy-medicaldaily-token",
        }
        self.sample_article = {
            "title": "차세대 GLP-1 비만치료제 임상 3상에서 심혈관 위험 24% 감소 확인",
            "content": "<div class=\"md-summary-box\"><p>핵심 요약</p></div><p>글로벌 임상 결과 심혈관 질환 위험이 감소했다.</p>",
            "summary": "차세대 GLP-1 수용체 작용제가 대규모 임상 3상에서 심혈관 사건 발생률을 24% 낮춘 것으로 나타났다.",
            "search_keyword": "비만치료제",
            "seo_tags": "비만치료제, GLP-1, 임상3상, 심혈관질환, 신약개발",
            "selected_category": "병원·제약",
        }
        self.sample_img = {
            "url": "https://images.medicaldaily.co.kr/data/images/full/0/203/20399.jpg?width=1200",
            "credit": "사진=의약일보 DB",
        }

    @patch("core.publishing.article_publisher.requests.post")
    def test_publish_to_receive_article_api_payload_and_headers(self, mock_post):
        """의약일보 Receive-Article API 송출 시 헤더(Bearer) 및 JSON 페이로드 규격 검증"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "success": True,
            "article_id": 123999,
            "status": "draft",
        }
        mock_post.return_value = mock_resp

        res, err = self.publisher.publish_to_receive_article_api(
            self.site_config,
            self.sample_article,
            self.sample_img,
            rss_link="https://www.nejm.org/doi/full/10.1056/example",
            mode="draft",
            remote_id=2026111201,
        )

        self.assertIsNone(err)
        self.assertIsNotNone(res)
        self.assertEqual(res["remote_id"], 2026111201)
        self.assertEqual(res["article_id"], 123999)
        self.assertIn(res["reporter"], MEDICALDAILY_REPORTERS)

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        headers = call_kwargs["headers"]
        payload = call_kwargs["json"]

        self.assertEqual(
            headers["Authorization"],
            "Bearer test-dummy-medicaldaily-token",
        )
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(payload["remote_id"], 2026111201)
        self.assertEqual(payload["title"], self.sample_article["title"])
        self.assertEqual(payload["body"], self.sample_article["content"])
        self.assertEqual(payload["topic_category"], "병원·제약")
        self.assertIn(payload["reporter"], ["고진아", "장선희", "정휘"])
        self.assertEqual(payload["author"], payload["reporter"])
        self.assertEqual(payload["mode"], "draft")
        self.assertIsInstance(payload["tags"], list)
        self.assertEqual(len(payload["tags"]), 5)
        self.assertEqual(payload["image_url"], self.sample_img["url"])
        self.assertEqual(payload["image_credit"], "사진=의약일보 DB")

    @patch("core.publishing.article_publisher.requests.get")
    def test_verify_receive_article_status_get_endpoint(self, mock_get):
        """GET &remote_id=<번호> 상태 확인 API 호출 검증"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "success": True,
            "remote_id": 2026111201,
            "article_id": 123999,
            "status": "draft",
        }
        mock_get.return_value = mock_resp

        res, err = self.publisher.verify_receive_article_status(self.site_config, 2026111201)
        self.assertIsNone(err)
        self.assertEqual(res["article_id"], 123999)
        called_url = mock_get.call_args[0][0]
        self.assertEqual(
            called_url,
            "https://www.medicaldaily.co.kr/api/receive-article?paper=medi&remote_id=2026111201",
        )

    def test_top_summary_box_and_qa_removal(self):
        """본문 최상단 [핵심 요약] 박스 생성 및 Q&A 섹션 제거 검증"""
        bullets = [
            "<strong>임상 3상 핵심 결과:</strong> 차세대 대사질환 치료제가 주요 심혈관 사건 위험을 24% 감소시켰다.",
            "<strong>안전성 및 내약성:</strong> 4,500명 대상 36개월 추적 관찰에서 중대한 이상반응 발생률이 대조군과 유사하게 유지됐다.",
            "<strong>국내 도입 전망:</strong> 내년 상반기 식품의약품안전처 품목허가 신청 및 급여 등재 논의가 본격화될 전망이다.",
        ]
        box_html = ArticleGenerator.build_top_summary_box(bullets)
        self.assertIn('class="md-summary-box"', box_html)
        self.assertIn("핵심 요약", box_html)
        self.assertIn("임상 3상 핵심 결과:", box_html)

        raw_with_qa = "<p>본문 문단입니다.</p><h3>자주 묻는 질문 (FAQ)</h3><h4>Q1. 질문?</h4><p>답변</p>"
        cleaned = ArticleGenerator.strip_qa_section_for_medicaldaily(raw_with_qa)
        self.assertIn("<p>본문 문단입니다.</p>", cleaned)
        self.assertNotIn("자주 묻는 질문", cleaned)

    def test_medicaldaily_readmore_box_title_and_korean_inline_link(self):
        """[의약일보 기사 더보기] 박스 제목 분기 및 한국어 인라인 링크 주입 검증"""
        related = [
            {
                "article_id": "123565",
                "title": "2026년 국가건강검진 대상자 확인법 및 모바일 간편 조회 가이드",
                "url": "https://www.medicaldaily.co.kr/news/123565",
            }
        ]
        medi_box = LinkInjector.build_related_articles_box(related, site="medicaldaily")
        self.assertIn("<strong>[의약일보 기사 더보기]</strong>", medi_box)
        self.assertNotIn("<strong>Read more:</strong>", medi_box)

        default_box = LinkInjector.build_related_articles_box(related, site="autoworldnews")
        self.assertIn("<strong>Read more:</strong>", default_box)

        # 한국어 2~5어절 인라인 링크 주입 검증 (상단 요약 박스 내부는 보호)
        html_body = (
            '<div class="md-summary-box"><p>국가 일반건강검진 대상자 요약</p></div>'
            '<p>올해 국가 일반건강검진 대상자는 공단 앱에서 간편하게 조회할 수 있다.</p>'
        )
        sister_pool = [
            {
                "id": 1,
                "article_id": "123565",
                "title": "2026년 국가건강검진 대상자 확인법",
                "url": "https://www.medicaldaily.co.kr/news/123565",
            }
        ]
        contextual_link = {
            "target_article_id": 1,
            "anchor_phrase": "국가 일반건강검진 대상자",
            "rationale": "건강검진 대상자 안내 기사와 직접 연관",
        }
        injected = LinkInjector.inject_natural_inline_link(
            html_body,
            contextual_link,
            sister_pool,
            article_context="국가 일반건강검진 대상자 조회 안내",
        )
        self.assertIn(
            '<a data-sys="1" href="https://www.medicaldaily.co.kr/news/123565" rel="dofollow" target="_blank">국가 일반건강검진 대상자</a>는',
            injected,
        )

    def test_reject_unrelated_sister_link_and_forced_contrast(self):
        """무관한 자사 기사(군산의료원) 억지 비교 인용 시 제6가드레일에 의해 자동 기각(Zero-Link)되는지 검증"""
        html_body = (
            "<p>뉴로스테릭스는 미국 FDA 승인을 획득한 조현병 치료제 코벤피 개발 주역들을 영입했다. "
            "이는 과거 군산의료원 전문의 줄고 감염병 전담병동 미운영 사례처럼 공공의료가 겪는 한계와는 대조적으로, "
            "민간 바이오 분야의 혁신 인재 집결을 보여준다.</p>"
        )
        unrelated_sister_pool = [
            {
                "id": 1,
                "article_id": "123569",
                "title": "군산의료원 전문의 줄고 감염병 전담병동 미운영",
                "url": "https://www.medicaldaily.co.kr/news/123569",
            }
        ]
        forced_link = {
            "target_article_id": 1,
            "anchor_phrase": "군산의료원 전문의 줄고",
            "rationale": "공공의료 한계 대조군으로 인용",
        }
        # 기사 맥락: 조현병 치료제 및 바이오 투자
        article_ctx = "뉴로스테릭스 1억 500만 달러 조달 조현병 치료제 개발 코벤피 무스카린 수용체"

        # 1. 의미적 교집합 제로 및 억지 대조 표현 감지 -> 링크 삽입 전면 기각
        res = LinkInjector.inject_natural_inline_link(
            html_body,
            forced_link,
            unrelated_sister_pool,
            article_context=article_ctx,
        )
        self.assertNotIn("data-sys=\"1\"", res)
        self.assertNotIn("<a ", res)
        self.assertEqual(res, html_body)  # 원본 텍스트 100% 보존 확인

    def test_medicaldaily_image_search_priority_order(self):
        """의약일보 이미지 검색 우선순위(0순위 의약일보 DB -> 1순위 Pexels -> 2순위 Wikimedia -> 3순위 Unsplash) 검증"""
        env = {
            "GEMINI_API_KEY": "dummy",
            "PIXELS_API_KEY": "dummy_pexels",
            "UNSPLASH_ACCESS_KEY": "dummy_unsplash",
        }
        searcher = ImageSearcher(env)
        call_order = []

        def fake_medi(q, exc, dom):
            call_order.append("0_medicaldaily")
            return []

        def fake_pexels(q, exc, dom):
            call_order.append("1_pexels")
            return [{"url": "https://images.pexels.com/photos/1/test.jpg", "credit": "Photo on Pexels", "source": "Pexels"}]

        def fake_wiki(q, exc, dom):
            call_order.append("2_wikimedia")
            return []

        def fake_unsplash(q, exc, dom):
            call_order.append("3_unsplash")
            return []

        with patch.object(searcher, "_search_medicaldaily_images", side_effect=fake_medi), \
             patch.object(searcher, "_get_pexels_candidates", side_effect=fake_pexels), \
             patch.object(searcher, "_search_wikimedia", side_effect=fake_wiki), \
             patch.object(searcher, "_get_unsplash_candidates", side_effect=fake_unsplash):
            res = searcher.search_image(
                ["건강검진", "medical checkup"],
                site_domain="medicaldaily",
            )
            self.assertEqual(res["source"], "Pexels")
            self.assertEqual(call_order[:2], ["0_medicaldaily", "0_medicaldaily"])
            self.assertEqual(call_order[2], "1_pexels")

    def test_env_loader_isolates_medicaldaily_from_default_twelve(self):
        """기본 get_sites_config(env)는 12개 영문 매체를 유지하고 include_receive_api=True 시에만 medicaldaily 포함"""
        env = EnvLoader.load_env()
        default_sites = EnvLoader.get_sites_config(env)
        self.assertEqual(len(default_sites), 12)
        self.assertNotIn("medicaldaily", [s["domain_key"] for s in default_sites])

        all_sites = EnvLoader.get_sites_config(env, include_receive_api=True)
        self.assertEqual(len(all_sites), 13)
        self.assertIn("medicaldaily", [s["domain_key"] for s in all_sites])

    @patch("core.publishing.article_publisher.requests.post")
    def test_publish_to_receive_article_api_publish_mode(self, mock_post):
        """[요건 2] mode='publish' 전달 시 페이로드에 mode='publish' 주입 및 ar_status: 1 응답 정상 처리 검증"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "success": True,
            "article_id": 123999,
            "status": "publish",
            "ar_status": 1,
        }
        mock_post.return_value = mock_resp

        # 1. mode="publish" 명시 전달
        res, err = self.publisher.publish_to_receive_article_api(
            self.site_config,
            self.sample_article,
            self.sample_img,
            rss_link="https://www.nejm.org/doi/full/10.1056/example",
            mode="publish",
            remote_id=2026111202,
        )

        self.assertIsNone(err)
        self.assertIsNotNone(res)
        self.assertEqual(res["status"], "publish")
        self.assertEqual(res["ar_status"], 1)

        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs["json"]
        self.assertEqual(payload["mode"], "publish")

        # 2. mode 인자 생략 시 기본값(publish) 검증
        mock_post.reset_mock()
        res_default, err_default = self.publisher.publish_to_receive_article_api(
            self.site_config,
            self.sample_article,
            self.sample_img,
            rss_link="https://www.nejm.org/doi/full/10.1056/example",
            remote_id=2026111203,
        )
        self.assertIsNone(err_default)
        payload_default = mock_post.call_args[1]["json"]
        self.assertEqual(payload_default["mode"], "publish")



if __name__ == "__main__":
    unittest.main()

