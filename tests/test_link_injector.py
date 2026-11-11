"""
Unit Test Suite for LinkInjector (Phase 1: Test Design)
Hermetic Testing: 외부 네트워크 호출 없이 정적 픽스처 및 모의 데이터를 사용하여 완전히 격리된 환경에서 검증합니다.
"""
import pytest
from bs4 import BeautifulSoup
from core.generation.link_injector import LinkInjector


SAMPLE_ARTICLE_HTML = """
<p>Hyundai Motor Manufacturing Alabama will invest nearly $450 million to expand its Montgomery plant, adding engine production for hybrid and extended-range electric vehicles, according to <a href="https://www.madeinalabama.com/expansion/">the state-run Made in Alabama site</a>. The governor's office lists 53 new full-time positions.</p>
<h2>Two Investment Figures, One Project</h2>
<p>The gap between nearly $450 million and $412.9 million is not explained in the official sources. For small-business owners and workers, workforce reductions and hiring trends in the automotive industry remain critical.</p>
<h3>Which Vehicles the Work Supports</h3>
<p>Moving production of a vehicle from one country to another shifts work and, over time, aerospace manufacturing and labor market dynamics. When corporate banking professionals assess job openings, modern leaders evaluate these strategic moves carefully.</p>
<p>Industry analysts emphasize that automation tools and workforce restructuring require continuous learning for technicians and factory workers.</p>
"""

MOCK_INTERNAL_POOL = [
    {
        "url": "https://www.jobsnhire.com/articles/60294/20261029/honeywell-tempe-aerospace-factory-600-jobs.htm",
        "title": "Honeywell Aerospace Plans New Factory in Tempe",
        "keywords": ["aerospace manufacturing", "Honeywell", "job openings"],
    },
    {
        "url": "https://www.jobsnhire.com/articles/60281/20261029/what-do-after-major-layoff.htm",
        "title": "What to Do After a Major Layoff: Action Guide",
        "keywords": ["workforce reductions", "layoff", "job loss"],
    },
    {
        "url": "https://www.jobsnhire.com/articles/60285/20261029/what-happens-401k-when-you-leave-job.htm",
        "title": "What Happens to Your 401k When Leaving a Job",
        "keywords": ["small-business owners", "401k retirement"],
    },
    {
        "url": "https://www.jobsnhire.com/articles/60316/20261105/mastering-difficult-conversations-guide-modern-leaders.htm",
        "title": "Mastering Difficult Conversations: A Guide for Leaders",
        "keywords": ["modern leaders", "leadership development"],
    },
    {
        "url": "https://www.jobsnhire.com/articles/60304/20261109/virgin-media-o2-initiates-major-workforce-restructuring-plan.htm",
        "title": "Virgin Media O2 Initiates Major Workforce Restructuring",
        "keywords": ["workforce restructuring", "telecom jobs"],
    },
]


def test_sanitize_external_links_attributes():
    """
    외부 링크에 rel="nofollow", class="external_red", target="_blank" 속성이
    정확히 부여 및 정규화되는지 검증합니다.
    """
    raw_html = '<p>Visit <a href="https://example.com/source">Official Source</a> for details.</p>'
    sanitized = LinkInjector.sanitize_external_links(raw_html)

    soup = BeautifulSoup(sanitized, "html.parser")
    link = soup.find("a")
    assert link is not None, "외부 링크 태그가 존재해야 합니다."
    assert link.get("href") == "https://example.com/source"
    assert "external_red" in link.get("class", []), "class에 'external_red'가 포함되어야 합니다."
    assert link.get("target") == "_blank", "target은 '_blank'여야 합니다."
    
    rel_parts = link.get("rel", [])
    if isinstance(rel_parts, str):
        rel_parts = rel_parts.split()
    assert "nofollow" in rel_parts, "rel 속성에 'nofollow'가 포함되어야 합니다."


def test_inject_internal_links_count_and_format():
    """
    내부 링크가 3개 이상 5개 이하로 주입되고,
    rel="dofollow", data-sys="1", target="_blank" 속성을 정확히 갖추는지 검증합니다.
    """
    result_html = LinkInjector.inject_internal_links(
        SAMPLE_ARTICLE_HTML,
        internal_pool=MOCK_INTERNAL_POOL,
        min_links=3,
        max_links=5,
    )

    soup = BeautifulSoup(result_html, "html.parser")
    internal_links = soup.find_all("a", attrs={"data-sys": "1"})

    assert 3 <= len(internal_links) <= 5, f"내부 링크 개수는 3~5개 사이여야 합니다. (실제: {len(internal_links)})"

    for link in internal_links:
        assert link.get("target") == "_blank", "내부 링크의 target은 '_blank'여야 합니다."
        assert link.get("data-sys") == "1", "내부 링크는 data-sys='1' 속성을 가져야 합니다."
        
        rel_parts = link.get("rel", [])
        if isinstance(rel_parts, str):
            rel_parts = rel_parts.split()
        assert "dofollow" in rel_parts, "내부 링크의 rel 속성은 'dofollow'여야 합니다."
        
        # 주입된 URL이 실제 풀에 존재하는지 검증
        pool_urls = [item["url"] for item in MOCK_INTERNAL_POOL]
        assert link.get("href") in pool_urls, f"주입된 URL({link.get('href')})이 내부 풀에 실존해야 합니다."


def test_no_nested_link_and_heading_protection():
    """
    1. 이미 <a> 태그가 걸려 있는 텍스트 내부에는 내부 링크가 중첩(nested) 삽입되지 않아야 합니다.
    2. <h2>, <h3> 소제목 태그 내부에는 내부 링크가 삽입되지 않아야 합니다.
    """
    html_with_nested_hazard = """
    <h2>Two Investment Figures with aerospace manufacturing</h2>
    <p>According to <a href="https://example.com">the state-run modern leaders report</a>, data is clear.</p>
    <h3>Which Vehicles the Work Supports with small-business owners</h3>
    <p>Plain body text mentioning workforce reductions for normal workers.</p>
    """
    result_html = LinkInjector.inject_internal_links(
        html_with_nested_hazard,
        internal_pool=MOCK_INTERNAL_POOL,
        min_links=1,
        max_links=3,
    )

    soup = BeautifulSoup(result_html, "html.parser")

    # 1. 중첩 링크 확인: <a> 태그 하위에 또 다른 <a> 태그가 없어야 함
    for a_tag in soup.find_all("a"):
        nested_a = a_tag.find("a")
        assert nested_a is None, f"중첩된 <a> 태그가 발견되었습니다: {a_tag}"

    # 2. 헤딩 보호 확인: <h2> 또는 <h3> 내부에 <a> 태그가 없어야 함
    for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        assert heading.find("a") is None, f"헤딩({heading.name}) 내부에 링크가 삽입되었습니다: {heading}"


def test_graceful_fallback_when_empty_pool():
    """
    내부 기사 풀이 비어 있거나 매칭되는 키워드가 없을 때,
    에러 없이 원본 본문 HTML이 100% 손상 없이 보존되어야 합니다.
    """
    result_html = LinkInjector.inject_internal_links(SAMPLE_ARTICLE_HTML, internal_pool=[])
    assert result_html == SAMPLE_ARTICLE_HTML, "풀이 비어 있을 때 원본 HTML이 그대로 반환되어야 합니다."


def test_process_end_to_end_integration():
    """
    process() 통합 메서드가 외부 링크 정제를 수행하고,
    기본 설정(enable_internal_links=False)에 따라 내부 인링크는 주입하지 않음을 검증합니다.
    """
    processed_html = LinkInjector.process(
        SAMPLE_ARTICLE_HTML,
        site="jobsnhire",
        source_url="https://www.madeinalabama.com/expansion/",
        internal_pool=MOCK_INTERNAL_POOL,
        enable_internal_links=False,
    )

    soup = BeautifulSoup(processed_html, "html.parser")
    
    # 1. 외부 링크 검증
    ext_links = soup.find_all("a", class_="external_red")
    assert len(ext_links) >= 1, "외부 출처 링크에 external_red 클래스가 적용되어야 합니다."
    for el in ext_links:
        rel_parts = el.get("rel", [])
        if isinstance(rel_parts, str):
            rel_parts = rel_parts.split()
        assert "nofollow" in rel_parts

    # 2. 내부 인링크 배제 검증 (0개여야 함)
    int_links = soup.find_all("a", attrs={"data-sys": "1"})
    assert len(int_links) == 0, "기본 설정 시 내부 인링크(data-sys='1')는 삽입되지 않아야 합니다."


def test_process_with_internal_links_enabled():
    """
    enable_internal_links=True로 명시할 경우,
    내부 인라인 링크(data-sys='1')가 정상 주입되는지 하위 호환성을 검증합니다.
    """
    processed_html = LinkInjector.process(
        SAMPLE_ARTICLE_HTML,
        site="jobsnhire",
        source_url="https://www.madeinalabama.com/expansion/",
        internal_pool=MOCK_INTERNAL_POOL,
        enable_internal_links=True,
    )

    soup = BeautifulSoup(processed_html, "html.parser")
    int_links = soup.find_all("a", attrs={"data-sys": "1"})
    assert 3 <= len(int_links) <= 5, "enable_internal_links=True일 때 내부 링크가 3~5개 삽입되어야 합니다."
    for il in int_links:
        rel_parts = il.get("rel", [])
        if isinstance(rel_parts, str):
            rel_parts = rel_parts.split()
        assert "dofollow" in rel_parts


def test_inject_related_articles_box():
    """
    Read more 위젯이 정확히 Q&A 섹션 바로 앞에
    카드형 박스 디자인(blockquote) 및 하단 빈 줄 공백(<p>&nbsp;</p>)과 함께
    삽입되는지 검증합니다.
    """
    sample_with_qa = SAMPLE_ARTICLE_HTML + "<h2>Key Questions Answered</h2>\n<p><strong>Q: Sample?</strong>A: Yes.</p>"
    
    mock_related = [
        {"article_id": "60294", "title": "Honeywell Aerospace Plans New Factory in Tempe", "url": "https://www.jobsnhire.com/articles/60294/test1.htm", "image_url": "https://img.example.com/1.jpg", "image_id": "1725405"},
        {"article_id": "60281", "title": "What to Do After a Major Layoff: Action Guide", "url": "https://www.jobsnhire.com/articles/60281/test2.htm", "image_url": "https://img.example.com/2.jpg", "image_id": "1725404"},
        {"article_id": "60285", "title": "What Happens to Your 401k When Leaving a Job", "url": "https://www.jobsnhire.com/articles/60285/test3.htm", "image_url": "https://img.example.com/3.jpg", "image_id": "1725403"},
        {"article_id": "60316", "title": "Mastering Difficult Conversations: A Guide for Leaders", "url": "https://www.jobsnhire.com/articles/60316/test4.htm", "image_url": "https://img.example.com/4.jpg", "image_id": "1725402"},
    ]

    result_html = LinkInjector.inject_related_articles_box(sample_with_qa, mock_related)
    soup = BeautifulSoup(result_html, "html.parser")

    # 1. 카드형 박스 컨테이너(blockquote) 검증
    bq_box = soup.find("blockquote", class_="readmore-box")
    assert bq_box is not None, "blockquote.readmore-box 컨테이너가 존재해야 합니다."
    assert "background-color:#f8fafc" in bq_box.get("style", "")
    assert "border-left-color:#2563eb" in bq_box.get("style", "")

    # 2. Read more 라벨 및 리스트 검증
    strong_tag = bq_box.find("strong", string="Read more:")
    assert strong_tag is not None, "<strong>Read more:</strong> 요소가 blockquote 내부에 존재해야 합니다."

    ul_tag = bq_box.find("ul")
    assert ul_tag is not None, "blockquote 내부에 <ul> 태그가 와야 합니다."

    # 3. 리스트 아이템 및 앵커 링크 검증
    li_items = ul_tag.find_all("li")
    assert len(li_items) == 4, "4개의 기사 항목이 <li>로 생성되어야 합니다."
    assert li_items[0].text == "Honeywell Aerospace Plans New Factory in Tempe"
    first_a = li_items[0].find("a")
    assert first_a is not None, "li 항목 내부에 <a> 앵커 태그가 포함되어야 합니다."
    assert first_a.get("href") == "https://www.jobsnhire.com/articles/60294/test1.htm"
    assert first_a.get("target") == "_blank"
    assert li_items[3].text == "Mastering Difficult Conversations: A Guide for Leaders"

    # 4. 하단 빈 줄 공백 문단(<p>&nbsp;</p>) 및 Q&A 섹션 앞 배치 위치 검증
    qa_heading = soup.find(lambda t: t.name in ["h2", "h3"] and "Key Questions" in t.text)
    assert qa_heading is not None
    assert "<blockquote" in result_html[:result_html.find("Key Questions Answered")]
    assert ("<p>&nbsp;</p>" in result_html or "<p>\xa0</p>" in result_html)

    # 5. 멱등성(Idempotency) 검증: 재호출 시 중복 생성되지 않아야 함
    re_result = LinkInjector.inject_related_articles_box(result_html, mock_related)
    re_soup = BeautifulSoup(re_result, "html.parser")
    read_more_boxes = re_soup.find_all("blockquote", class_="readmore-box")
    assert len(read_more_boxes) == 1, "중복 호출 시에도 Read more 박스는 1개만 존재해야 합니다."


def test_site_routing_internal_links_policy():
    """
    [최종 확립된 매체별 송출 표준 체계 검증]
    1. INGEST_API_SITES 매체(jobsnhire 등 4개 매체):
       - 내부 인라인 링크: 활성화 (enable_internal_links=True)
       - Read more 카드 박스: 비활성화 (enable_readmore_box=False) -> 박스 미생성 검증
    2. 8개 일반 매체(autoworldnews, scienceworldreport 등):
       - 내부 인라인 링크: 활성화 (enable_internal_links=True)
       - Read more 카드 박스: 활성화 (enable_readmore_box=True) -> 박스 생성 검증
    """
    from core.generation.article_generator import INGEST_API_SITES

    # 1. Ingest API 매체 정책 검증 (인라인 링크 O, Read more 박스 X)
    ingest_domain = "jobsnhire"
    is_ingest = ingest_domain in INGEST_API_SITES
    res_ingest = LinkInjector.process(
        SAMPLE_ARTICLE_HTML,
        site=ingest_domain,
        internal_pool=MOCK_INTERNAL_POOL,
        enable_internal_links=True,
        enable_readmore_box=(not is_ingest)
    )
    soup_ingest = BeautifulSoup(res_ingest, "html.parser")
    # 인라인 링크는 활성화되어 삽입됨
    assert len(soup_ingest.find_all("a", attrs={"data-sys": "1"})) >= 1, "Ingest API 매체도 내부 인링크는 정상 삽입되어야 합니다."
    # Read more 박스는 생성되지 않아야 함
    assert soup_ingest.find("blockquote", class_="readmore-box") is None, "Ingest API 매체는 Read more 카드 박스가 없어야 합니다."
    assert "Read more:" not in res_ingest, "Ingest API 매체는 Read more 텍스트가 없어야 합니다."

    # 2. 8개 일반 매체 정책 검증 (인라인 링크 O, Read more 박스 O)
    general_domain = "autoworldnews"
    is_general_ingest = general_domain in INGEST_API_SITES
    res_general = LinkInjector.process(
        SAMPLE_ARTICLE_HTML,
        site=general_domain,
        internal_pool=MOCK_INTERNAL_POOL,
        enable_internal_links=True,
        enable_readmore_box=(not is_general_ingest)
    )
    soup_general = BeautifulSoup(res_general, "html.parser")
    assert len(soup_general.find_all("a", attrs={"data-sys": "1"})) >= 1, "일반 매체는 내부 인링크가 삽입되어야 합니다."
    assert soup_general.find("blockquote", class_="readmore-box") is not None, "일반 매체는 Read more 카드 박스가 삽입되어야 합니다."
    assert "Read more:" in res_general, "일반 매체는 Read more 텍스트가 포함되어야 합니다."


def test_sanitize_html_for_legacy_php():
    """
    ArticlePublisher._sanitize_html_for_legacy_php가
    HTML 속성 따옴표를 안전하게 unquoted attribute 형태로 변환하여
    PHP 백엔드의 addslashes() 왜곡을 방어하고,
    BeautifulSoup으로 파싱 시 정상 속성으로 유지되는지 검증합니다.
    """
    from core.publishing.article_publisher import ArticlePublisher
    publisher = ArticlePublisher()

    sample_html = (
        '<p>Test paragraph with <a target="_blank" rel="dofollow" href="https://www.autoworldnews.com/articles/123/test.htm" data-sys="1">electric vehicles</a> '
        'and <a target="_blank" rel="nofollow" href="https://www.autonews.com/test" class="external_red">industry report</a>.</p>'
        '<ul><li><a href="https://www.autoworldnews.com/articles/456/recent.htm" target="_blank">Related Title</a></li></ul>'
    )

    sanitized = publisher._sanitize_html_for_legacy_php(sample_html)

    # 1. 태그 내 속성값의 큰따옴표가 제거되었는지 검증
    assert 'href=https://www.autoworldnews.com/articles/123/test.htm' in sanitized
    assert 'target=_blank' in sanitized
    assert 'rel=dofollow' in sanitized
    assert 'class=external_red' in sanitized

    # 2. BeautifulSoup 파싱 정합성 검증
    soup = BeautifulSoup(sanitized, "html.parser")
    a_tags = soup.find_all("a")
    assert len(a_tags) == 3

    # 내부 링크
    assert a_tags[0].get("href") == "https://www.autoworldnews.com/articles/123/test.htm"
    assert a_tags[0].get("target") == "_blank"
    assert a_tags[0].get("data-sys") == "1"

    # 외부 링크
    assert a_tags[1].get("href") == "https://www.autonews.com/test"
    assert "external_red" in a_tags[1].get("class", [])

    # Read more 리스트 링크
    assert a_tags[2].get("href") == "https://www.autoworldnews.com/articles/456/recent.htm"


def test_inject_natural_inline_link_success():
    """
    LLM의 contextual_link가 정상(3~6단어, 유효 ID)일 때
    파이썬 5단계 가드레일이 정확한 실존 URL로 단 1회 안전하게 치환하는지 검증합니다.
    """
    sample_html = (
        "<p>Hyundai is investing in electric platforms. "
        "This move builds on earlier manufacturing supply agreements across regional battery hubs. "
        "Further details are expected next month.</p>"
    )
    sister_articles = [
        {
            "id": 1,
            "title": "BMW Scales EV Production With New Supply Deals",
            "url": "https://www.autoworldnews.com/articles/40474/20261110/bmw-scales-ev-production.htm"
        },
        {
            "id": 2,
            "title": "Toyota Announces Solid-State Battery Retooling",
            "url": "https://www.autoworldnews.com/articles/40475/20261110/toyota-battery-retooling.htm"
        }
    ]
    contextual_link = {
        "target_article_id": 1,
        "anchor_phrase": "earlier manufacturing supply agreements",
        "rationale": "Direct parallel to regional EV battery supply chain investments."
    }

    result = LinkInjector.inject_natural_inline_link(sample_html, contextual_link, sister_articles)
    soup = BeautifulSoup(result, "html.parser")
    link = soup.find("a", attrs={"data-sys": "1"})

    assert link is not None, "자연스러운 인라인 링크가 주입되어야 합니다."
    assert link.get("href") == "https://www.autoworldnews.com/articles/40474/20261110/bmw-scales-ev-production.htm"
    assert link.get("target") == "_blank"
    assert "dofollow" in link.get("rel", [])
    assert link.string == "earlier manufacturing supply agreements"
    assert len(soup.find_all("a")) == 1, "정확히 단 1회만 치환되어야 합니다."


def test_inject_natural_inline_link_fail_safe_null():
    """
    연관성이 없거나 contextual_link가 None/null일 때
    Fail-Safe가 작동하여 원본 HTML이 변경 없이 그대로 보존되는지 검증합니다.
    """
    sample_html = "<p>Standard news body with no relevant sister stories.</p>"
    sister_articles = [{"id": 1, "title": "Unrelated Story", "url": "https://example.com/unrelated"}]

    assert LinkInjector.inject_natural_inline_link(sample_html, None, sister_articles) == sample_html
    assert LinkInjector.inject_natural_inline_link(sample_html, {}, sister_articles) == sample_html


def test_inject_natural_inline_link_reject_short_and_long_anchor():
    """
    2단어 이하(단일 명사)이거나 8단어 이상 긴 문장 앵커는
    파이썬 코드 레벨에서 엄격히 기각(Reject)되어 본문이 유지되는지 검증합니다.
    """
    sample_html = (
        "<p>Electric vehicles are transforming global mobility. "
        "This long sentence describing regional automotive supplier logistics across state lines should not be a link.</p>"
    )
    sister_articles = [{"id": 1, "title": "Test Title", "url": "https://example.com/test"}]

    # 1. 2단어 명사 ("electric vehicles") -> 기각
    short_link = {"target_article_id": 1, "anchor_phrase": "Electric vehicles"}
    res_short = LinkInjector.inject_natural_inline_link(sample_html, short_link, sister_articles)
    assert "<a" not in res_short, "2단어 이하 앵커는 기각되어야 합니다."

    # 2. 8단어 이상 긴 문장 -> 기각
    long_link = {
        "target_article_id": 1,
        "anchor_phrase": "This long sentence describing regional automotive supplier logistics across state lines"
    }
    res_long = LinkInjector.inject_natural_inline_link(sample_html, long_link, sister_articles)
    assert "<a" not in res_long, "8단어 이상 앵커는 기각되어야 합니다."


def test_inject_natural_inline_link_prevent_nested_links():
    """
    이미 <a> 태그 내부에 있는 텍스트는 중복 치환되지 않고 HTML 구조가 보호되는지 검증합니다.
    """
    sample_html = (
        '<p>According to <a href="https://reuters.com" class="external_red">the official federal automotive report</a>, '
        'manufacturing output is accelerating.</p>'
    )
    sister_articles = [{"id": 1, "title": "Test Title", "url": "https://example.com/test"}]
    conflict_link = {
        "target_article_id": 1,
        "anchor_phrase": "official federal automotive report"
    }

    result = LinkInjector.inject_natural_inline_link(sample_html, conflict_link, sister_articles)
    soup = BeautifulSoup(result, "html.parser")
    # 중첩 <a> 태그가 없어야 함
    assert len(soup.find_all("a")) == 1
    assert soup.find("a").get("href") == "https://reuters.com"


def test_process_end_to_end_with_contextual_link():
    """
    LinkInjector.process() 통합 실행 시,
    자연스러운 인라인 링크와 하단 Read more 카드 박스가 공존하는지 검증합니다.
    """
    sample_html = (
        "<p>Breaking news on regional manufacturing. "
        "The project follows earlier domestic supply chain expansions in key assembly corridors.</p>"
        "<h2>Key Questions Answered</h2>"
        "<p><strong>Q: What is the investment?</strong>A: It is $290M.</p>"
    )
    sister_articles = [
        {
            "id": 1,
            "title": "Domestic Battery Facilities Expand",
            "url": "https://www.autoworldnews.com/articles/40470/recent.htm"
        }
    ]
    contextual_link = {
        "target_article_id": 1,
        "anchor_phrase": "earlier domestic supply chain expansions"
    }

    result = LinkInjector.process(
        html_content=sample_html,
        site="autoworldnews",
        contextual_link=contextual_link,
        sister_articles=sister_articles,
        enable_internal_links=True
    )

    soup = BeautifulSoup(result, "html.parser")
    # 1. 인라인 링크 확인
    inline_link = soup.find("a", attrs={"data-sys": "1"})
    assert inline_link is not None
    assert inline_link.get("href") == "https://www.autoworldnews.com/articles/40470/recent.htm"
    assert inline_link.string == "earlier domestic supply chain expansions"

    # 2. Read more 박스 확인
    box = soup.find("blockquote", class_="readmore-box")
    assert box is not None
    assert "Read more:" in box.text





