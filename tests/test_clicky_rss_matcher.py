import os
import json
import pytest
from core.ingestion.clicky_puller import (
    get_medicaldaily_clicky_keywords,
    fetch_clicky_matched_rss_source,
)

def test_get_medicaldaily_clicky_keywords_returns_valid_keywords():
    """
    [요건 5] 3단계 안전 폴백 체인을 통해
    항상 1~3개의 유효한 헬스케어 관심 키워드가 반환되는지 검증
    """
    keywords = get_medicaldaily_clicky_keywords(limit=3)
    assert isinstance(keywords, list)
    assert 1 <= len(keywords) <= 3
    for kw in keywords:
        assert isinstance(kw, str) and len(kw.strip()) > 0
    print(f"\nExtracted Clicky Keywords: {keywords}")

def test_fetch_clicky_matched_rss_source_relevance_matching(tmp_path):
    """
    주어진 RSS 피드 중에서 Clicky 관심 키워드('비만치료제', 'GLP-1')와
    일치하는 아이템이 우선순위로 매칭되어 팩트 소스로 반환되는지 검증
    """
    # 임시 RSS XML 생성
    sample_rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Medical Feed</title>
    <item>
      <title>일반 병원 경영 동정 보고서</title>
      <link>https://example.com/hospital-news-1</link>
      <description>병원 경영 실적 및 인력 충원 계획을 다룹니다.</description>
    </item>
    <item>
      <title>차세대 GLP-1 비만치료제 신약 임상 3상 결과 발표</title>
      <link>https://example.com/obesity-drug-trial</link>
      <description>GLP-1 수용체 작용제 기반 비만치료제가 임상에서 탁월한 체중 감량 효과를 확인했습니다.</description>
    </item>
    <item>
      <title>의료 기기 박람회 개최 소식</title>
      <link>https://example.com/medical-expo</link>
      <description>글로벌 의료 기기 전시회 개막.</description>
    </item>
  </channel>
</rss>"""

    feed_file = tmp_path / "test_feed.xml"
    with open(feed_file, "w", encoding="utf-8") as f:
        f.write(sample_rss_xml)

    # 임시 rss_feeds.json 생성
    feeds_config = tmp_path / "rss_feeds.json"
    with open(feeds_config, "w", encoding="utf-8") as f:
        json.dump({"medicaldaily": [f"file://{feed_file}"]}, f)

    keywords = ["비만치료제 GLP-1"]
    result = fetch_clicky_matched_rss_source(keywords, feeds_file=str(feeds_config))

    assert result is not None, "Failed to match RSS source"
    payload, link, original_title, score = result

    # 1. 최고 점수 아이템(GLP-1 비만치료제)이 매칭되었는지 검증
    assert "비만치료제" in original_title
    assert "https://example.com/obesity-drug-trial" == link
    assert score > 0

    # 2. 팩트 원문 소스 포맷 및 Reference URL 무결성 검증 (환각 방지)
    assert "SOURCE REAL NEWS WIRE REPORT" in payload
    assert "Original Title: 차세대 GLP-1 비만치료제 신약 임상 3상 결과 발표" in payload
    assert "Reference URL: https://example.com/obesity-drug-trial" in payload

def test_fetch_clicky_matched_rss_source_fallback_on_no_match(tmp_path):
    """
    관심 키워드와 일치하는 단어가 없는 경우에도
    신선한 RSS 아이템으로 안전하게 폴백하여 팩트 소스를 반환하는지 검증
    """
    sample_rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>General Health</title>
    <item>
      <title>글로벌 보건 기구 정례 브리핑</title>
      <link>https://example.com/who-briefing</link>
      <description>보건 환경 개선 및 감염병 예방 수칙 발표.</description>
    </item>
  </channel>
</rss>"""

    feed_file = tmp_path / "general_feed.xml"
    with open(feed_file, "w", encoding="utf-8") as f:
        f.write(sample_rss_xml)

    feeds_config = tmp_path / "rss_feeds.json"
    with open(feeds_config, "w", encoding="utf-8") as f:
        json.dump({"medicaldaily": [f"file://{feed_file}"]}, f)

    # 매칭되지 않는 엉뚱한 키워드 제공
    keywords = ["우주왕복선 화성탐사선"]
    result = fetch_clicky_matched_rss_source(keywords, feeds_file=str(feeds_config))

    assert result is not None, "Fallback candidate should be returned even if keyword score is 0"
    payload, link, original_title, score = result
    assert score == 0
    assert link == "https://example.com/who-briefing"
    assert "Original Title: 글로벌 보건 기구 정례 브리핑" in payload

