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


def test_inject_external_link_korean_citation():
    """
    한국어 외신/출처 인용 구문("외신 보도에 따르면")을 100% 파이썬 단에서 탐색하여
    class="external_red", rel="nofollow" 외부 링크를 정확히 1회 주입하는지 검증합니다.
    """
    html = (
        "<p>미국 제약바이오 기업 뉴로스테릭스가 대규모 시리즈A 투자를 유치했다. "
        "외신 보도에 따르면 이번 투자에는 글로벌 벤처캐피털들이 대거 참여한 것으로 확인됐다.</p>"
        "<p>연구진은 조현병 치료제 임상에 본격 착수할 예정이다.</p>"
    )
    source_url = "https://www.bioworld.com/articles/neurosterix-launch"
    result = LinkInjector.inject_external_link(html, source_url)

    soup = BeautifulSoup(result, "html.parser")
    links = soup.find_all("a")
    assert len(links) == 1
    ext_link = links[0]
    assert ext_link.get("href") == source_url
    assert "external_red" in ext_link.get("class", [])
    assert "nofollow" in ext_link.get("rel", [])
    assert ext_link.get("target") == "_blank"
    assert ext_link.string == "외신 보도에 따르면"


def test_inject_external_link_english_citation():
    """
    영문 출처 인용 구문("according to reports")을 100% 파이썬 단에서 정확히 1회 주입하는지 검증합니다.
    """
    html = (
        "<p>The automotive industry is preparing for major changes. "
        "According to reports from industry insiders, the company will invest $500M.</p>"
    )
    source_url = "https://www.reuters.com/business/autos"
    result = LinkInjector.inject_external_link(html, source_url)

    soup = BeautifulSoup(result, "html.parser")
    links = soup.find_all("a")
    assert len(links) == 1
    assert links[0].get("href") == source_url
    assert "external_red" in links[0].get("class", [])
    assert "nofollow" in links[0].get("rel", [])
    assert links[0].string == "According to reports"


def test_inject_external_link_idempotency():
    """
    이미 본문에 외부 링크가 존재할 경우 중복 주입하지 않는 멱등성을 검증합니다.
    """
    html = (
        '<p>Visit <a href="https://example.com" class="external_red" rel="nofollow">source</a> for details. '
        '외신 보도에 따르면 추가 정보가 있다.</p>'
    )
    source_url = "https://www.reuters.com/news"
    result = LinkInjector.inject_external_link(html, source_url)
    soup = BeautifulSoup(result, "html.parser")
    links = soup.find_all("a")
    assert len(links) == 1
    assert links[0].get("href") == "https://example.com"


def test_inject_external_link_skip_forbidden_elements():
    """
    상단 요약 박스(md-summary-box) 내부나 헤딩(<h3>) 내부 텍스트는 외부 링크 주입 대상에서 제외되는지 검증합니다.
    """
    html = (
        '<div class="md-summary-box"><p>외신 보도에 따르면 요약 내용입니다.</p></div>'
        '<h3>외신 보도에 따르면 소제목입니다</h3>'
        '<p>본문 문단입니다. 공식 발표에 따르면 이번 조치는 즉시 시행된다.</p>'
    )
    source_url = "https://www.fda.gov/news"
    result = LinkInjector.inject_external_link(html, source_url)
    soup = BeautifulSoup(result, "html.parser")

    # summary-box나 h3 내부에는 a 태그가 없어야 함
    assert soup.find("div", class_="md-summary-box").find("a") is None
    assert soup.find("h3").find("a") is None

    # 본문 p 태그에만 a 태그가 있어야 함
    p_tags = soup.find_all("p")
    body_p = [p for p in p_tags if not p.find_parent("div", class_="md-summary-box")]
    assert len(body_p) == 1
    a_tag = body_p[0].find("a")
    assert a_tag is not None
    assert a_tag.string == "공식 발표에 따르면"
    assert a_tag.get("href") == source_url


def test_inject_external_link_full_named_attribution_phrase():
    """
    첨부 이미지 표준과 일치하도록,
    'CoStar에 따르면', 'HAMA의 2026년 업계 전망', 'CBRE의 2025년 숙박업 데이터에 따르면' 등
    기관/출처명이 포함된 출처 구문 전체가 링크로 연결되는지 검증합니다.
    """
    source_url = "https://www.costar.com/report"

    # 케이스 1: CoStar에 따르면
    html1 = "<p>평균 객실 요금이 사상 최고치를 경신했으며, CoStar에 따르면 이러한 상승세는 전반적이다.</p>"
    res1 = LinkInjector.inject_external_link(html1, source_url)
    soup1 = BeautifulSoup(res1, "html.parser")
    link1 = soup1.find("a")
    assert link1 is not None
    assert link1.string == "CoStar에 따르면"
    assert link1.get("href") == source_url
    assert "external_red" in link1.get("class", [])

    # 케이스 2: HAMA의 2026년 업계 전망
    html2 = "<p>협회장은 HAMA의 2026년 업계 전망에서 이러한 긴장감을 명확히 지적했다.</p>"
    res2 = LinkInjector.inject_external_link(html2, source_url)
    soup2 = BeautifulSoup(res2, "html.parser")
    link2 = soup2.find("a")
    assert link2 is not None
    assert link2.string == "HAMA의 2026년 업계 전망"

    # 케이스 3: CBRE의 2025년 숙박업 데이터에 따르면
    html3 = "<p>CBRE의 2025년 숙박업 데이터에 따르면 미국 호텔 영업 수익은 증가했다.</p>"
    res3 = LinkInjector.inject_external_link(html3, source_url)
    soup3 = BeautifulSoup(res3, "html.parser")
    link3 = soup3.find("a")
    assert link3 is not None
    assert link3.string == "CBRE의 2025년 숙박업 데이터에 따르면"


def test_inject_external_link_reject_isolated_words():
    """
    '임상 시험', '데이터', '밝혔다' 등 출처 기관/매체명이 없는 단순 단어에는
    외부 링크를 걸지 않고 기각(Zero-Link)하는지 검증합니다.
    """
    html = "<p>뉴로스테릭스는 차세대 후보물질의 임상 시험을 본격화하고 우수한 데이터를 확보했다고 밝혔다.</p>"
    source_url = "https://endpoints.news/article"
    res = LinkInjector.inject_external_link(html, source_url)
    soup = BeautifulSoup(res, "html.parser")
    assert len(soup.find_all("a")) == 0, "출처 명시 문구가 없는 단순 단어에는 외부 링크를 걸지 않아야 합니다."


def test_inject_natural_inline_link_causal_context_verification():
    """
    제7가드레일 검증:
    1. 인과 관계 표현(~에 힘입어, ~의 여파로, ~이후 등)이 포함된 문맥 앵커는 통과.
    2. 인과 관계가 없는 단순 나열 문맥은 Zero-Link로 즉시 기각.
    """
    sister_articles = [{
        "id": 1,
        "title": "코벤피 FDA 승인 획득",
        "url": "https://www.medicaldaily.co.kr/news/123000"
    }]

    # Case A: 인과 관계가 명확한 문맥 (통과)
    html_pass = "<p>앞서 성공한 코벤피의 FDA 승인 이후 차세대 조현병 치료제 시장에 글로벌 자금이 대거 몰리고 있다.</p>"
    ctx_pass = {
        "target_article_id": 1,
        "anchor_phrase": "코벤피의 FDA 승인 이후"
    }
    res_pass = LinkInjector.inject_natural_inline_link(
        html_pass, ctx_pass, sister_articles, article_context="코벤피 조현병 FDA 승인"
    )
    soup_pass = BeautifulSoup(res_pass, "html.parser")
    link_pass = soup_pass.find("a", attrs={"data-sys": "1"})
    assert link_pass is not None
    assert link_pass.string == "코벤피의 FDA 승인 이후"

    # Case B: 인과 관계가 없는 단순 나열 (기각)
    html_reject = "<p>한편 코벤피 FDA 승인 소식이 있었다. 그러나 오늘 행사는 별개로 진행되었다.</p>"
    ctx_reject = {
        "target_article_id": 1,
        "anchor_phrase": "코벤피 FDA 승인"
    }
    res_reject = LinkInjector.inject_natural_inline_link(
        html_reject, ctx_reject, sister_articles, article_context="코벤피 조현병 FDA 승인"
    )
    soup_reject = BeautifulSoup(res_reject, "html.parser")
    assert soup_reject.find("a", attrs={"data-sys": "1"}) is None, "인과성 없는 단순 앵커는 기각되어야 합니다."


def test_korean_external_link_multi_word_and_char_boundary():
    """8어절 36자 정책 출처 문구 정상 주입 및 45자 이내 다중 복합 가드레일 검증"""
    source_url = "https://journals.plos.org/plosmedicine/article?id=10.1371/journal.pmed.1005285"
    html = (
        "<p>2026년 대한민국 의료 현장이 거대한 디지털 전환을 맞이하고 있다.</p>"
        "<p>보건복지부의 2026년 만성질환 관리 디지털 전환 로드맵에 따르면, 향후 3년 내 1차 의료기관 참여가 대폭 확대된다.</p>"
    )

    injected = LinkInjector.inject_external_link(html, source_url)
    soup = BeautifulSoup(injected, "html.parser")
    ext_a = soup.find("a", class_="external_red")
    assert ext_a is not None, "8어절 정책 로드맵 출처 문구에 외부 링크가 정상 주입되어야 합니다."
    assert ext_a["href"] == source_url
    assert ext_a.string == "보건복지부의 2026년 만성질환 관리 디지털 전환 로드맵에 따르면"


def test_trend_and_precedent_inline_link_injection():
    """[동향·경향·유사 사례] 마커 인라인 내부 링크 정상 주입 검증"""
    sister_articles = [
        {
            "id": 1,
            "article_id": 123613,
            "title": "인도주의적 위기 속 폐렴구균 백신, 질병 부담 낮추는 최선의 전략",
            "url": "https://www.medicaldaily.co.kr/news/123613"
        }
    ]

    html = "<p>의학계에서는 이번 연구가 앞서 보고된 폐렴구균 백신 접종 확대 사례와 마찬가지로 예방 중심 패러다임과 궤를 같이한다고 평가한다.</p>"
    ctx = {
        "target_article_id": 1,
        "anchor_phrase": "폐렴구균 백신 접종 확대 사례"
    }

    result = LinkInjector.inject_natural_inline_link(
        html, ctx, sister_articles, article_context="예방 백신 의료 정책"
    )
    soup = BeautifulSoup(result, "html.parser")
    link = soup.find("a", attrs={"data-sys": "1"})
    assert link is not None
    assert link["href"] == "https://www.medicaldaily.co.kr/news/123613"
    assert link.string == "폐렴구균 백신 접종 확대 사례"


def test_fallback_auto_match_internal_link():
    """LLM이 contextual_link를 누락했을 때 2단계 파이썬 자동 매칭 안전망 동작 검증"""
    sister_articles = [
        {
            "id": 1,
            "article_id": 123613,
            "title": "인도주의적 위기 속 폐렴구균 백신 접종 확대 전략",
            "url": "https://www.medicaldaily.co.kr/news/123613"
        }
    ]

    # 본문에 폐렴구균 백신 접종 키워드가 있으나 LLM이 contextual_link를 주지 않은 경우
    html = (
        "<p>성인 호흡기 질환 관리에서 예방 접종의 중요성이 날로 부각되고 있다.</p>"
        "<p>전문가들은 고위험군 환자들에게 폐렴구균 백신 접종 확대를 선제적으로 권고해야 한다고 입을 모았다.</p>"
    )

    result = LinkInjector.inject_fallback_internal_link(html, sister_articles, site="medicaldaily")
    soup = BeautifulSoup(result, "html.parser")
    link = soup.find("a", attrs={"data-sys": "1"})
    assert link is not None, "파이썬 자동 매칭에 의해 자사 기사 링크가 100% 주입되어야 합니다."
    assert link["href"] == "https://www.medicaldaily.co.kr/news/123613"








