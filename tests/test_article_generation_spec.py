import unittest
from core.generation.article_generator import ArticleGenerator


class TestArticleGenerationSpec(unittest.TestCase):
    def test_count_body_words_excluding_headings(self):
        """소제목(<h3>)을 단어 수에서 완전히 제외하고 순수 본문 단어만 정확히 계측하는지 검증"""
        content_html = """
        <p>This is the first opening paragraph containing exactly ten words here.</p>
        <h3>Subheading One Which Should Not Be Counted</h3>
        <p>This is the second body paragraph containing eleven distinct words today.</p>
        <h3>Another Subheading To Exclude</h3>
        <p>Final paragraph with five words.</p>
        """
        # 첫 문단: 11단어, 두번째: 11단어, 세번째: 5단어 = 총 27단어
        # 소제목 6단어 + 4단어 = 10단어는 완전히 제외되어야 함
        word_count = ArticleGenerator.count_body_words_excluding_headings(content_html)
        self.assertEqual(word_count, 27)

    def test_normalize_headings_to_h3(self):
        """h2, h4 및 볼드체 소제목이 h3 태그로 정상 변환되고 개수가 산출되는지 검증"""
        raw_html = """
        <p>Opening lead paragraph establishing the main investigative story.</p>
        <h2>First Major Section</h2>
        <p>First section body text.</p>
        <h4>Second Major Section</h4>
        <p>Second section body text.</p>
        <p><b>Third Major Section</b></p>
        <p>Third section body text.</p>
        """
        norm_html, h_count = ArticleGenerator.normalize_and_enforce_structure(raw_html)
        self.assertEqual(h_count, 3)
        self.assertIn("<h3>First Major Section</h3>", norm_html)
        self.assertIn("<h3>Second Major Section</h3>", norm_html)
        self.assertIn("<h3>Third Major Section</h3>", norm_html)
        self.assertNotIn("<h2>", norm_html)
        self.assertNotIn("<h4>", norm_html)

    def test_deductive_lead_repositioning(self):
        """첫 문단 위에 소제목이 올 경우, 양괄식 리드 원칙에 따라 첫 문단 아래로 자동 재배치되는지 검증"""
        raw_html = """
        <h3>Premature Heading Before Lead</h3>
        <p>This is the true opening lead paragraph that should appear first.</p>
        <p>Follow-up content paragraph.</p>
        """
        norm_html, h_count = ArticleGenerator.normalize_and_enforce_structure(raw_html)
        self.assertEqual(h_count, 1)
        # 결과에서 첫 번째 문단이 맨 앞에 오고 그 다음에 <h3>가 와야 함
        self.assertTrue(norm_html.startswith("<p>This is the true opening lead paragraph"))
        self.assertIn("</p>\n<h3>Premature Heading Before Lead</h3>", norm_html)

    def test_validate_and_enrich_seo_tags(self):
        """부족한 SEO 태그가 전달되었을 때 본문 키워드를 활용해 중복 없이 20개로 완성되는지 검증"""
        raw_tags = "cancer research, oncology trial, clinical evidence"
        content_html = """
        <p>Researchers at Harvard University tested an innovative mRNA vaccine targeting melanoma tumors.
        The biotechnology company BioPharma announced significant therapeutic responses across diverse patient cohorts.
        Immunotherapy protocols demonstrated prolonged survival duration and enhanced cellular defense mechanisms.</p>
        """
        final_tags = ArticleGenerator.validate_and_enrich_seo_tags(raw_tags, content_html, "health-medicine")
        tag_list = [t.strip() for t in final_tags.split(",") if t.strip()]
        self.assertEqual(len(tag_list), 20)
        # 기존 태그 3개가 보존되었는지 검증
        self.assertIn("cancer research", tag_list)
        self.assertIn("oncology trial", tag_list)
        self.assertIn("clinical evidence", tag_list)
        # 중복이 없는지 검증
        self.assertEqual(len(tag_list), len(set([t.lower() for t in tag_list])))

    def test_is_clickbait_headline(self):
        """클릭베이트 제목 검출 및 정상 저널리즘 제목 통과 검증"""
        clickbait_1 = "You Won't Believe What Researchers Found in Ancient Tomb"
        clickbait_2 = "Shocking Results From New Clinical Trial"
        legit_headline = "Archaeologists Uncover 3,000-Year-Old Temple in Northern Peru"
        
        self.assertTrue(ArticleGenerator.is_clickbait_headline(clickbait_1))
        self.assertTrue(ArticleGenerator.is_clickbait_headline(clickbait_2))
        self.assertFalse(ArticleGenerator.is_clickbait_headline(legit_headline))


if __name__ == "__main__":
    unittest.main()
