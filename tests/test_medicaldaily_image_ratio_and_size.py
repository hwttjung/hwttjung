import pytest
from unittest.mock import MagicMock, patch
from core.media.image_searcher import ImageSearcher
from core.media.image_gatekeeper import ImageGatekeeper


def test_categorize_aspect_ratio_tier():
    """[요건 6] 종횡비 3단계 티어 분류 정밀 검증"""
    # Tier 1: 가로가 긴 이미지 (4:3 = 1.33, 16:9 = 1.78, aspect_ratio >= 1.25)
    assert ImageSearcher._categorize_aspect_ratio_tier(1.78) == 1
    assert ImageSearcher._categorize_aspect_ratio_tier(1.33) == 1
    assert ImageSearcher._categorize_aspect_ratio_tier(1.25) == 1

    # Tier 2: 1:1 정사각 (0.90 <= aspect_ratio <= 1.10)
    assert ImageSearcher._categorize_aspect_ratio_tier(1.0) == 2
    assert ImageSearcher._categorize_aspect_ratio_tier(0.95) == 2
    assert ImageSearcher._categorize_aspect_ratio_tier(1.05) == 2

    # Tier 3: 세로가 긴 이미지 (aspect_ratio < 0.90) 및 기타
    assert ImageSearcher._categorize_aspect_ratio_tier(0.75) == 3
    assert ImageSearcher._categorize_aspect_ratio_tier(0.67) == 3
    assert ImageSearcher._categorize_aspect_ratio_tier(0.50) == 3


def test_hierarchical_aspect_ratio_selection():
    """[요건 6] 가로형 우선 -> 1:1 차선 -> 세로형 최후선 계층적 우선순위 검증"""
    mock_env = {
        "UNSPLASH_ACCESS_KEY": "fake_key",
        "PEXELS_API_KEY": "fake_key",
        "GEMINI_API_KEY": "fake_key",
    }
    searcher = ImageSearcher(mock_env)
    searcher.gatekeeper = MagicMock()

    # Case 1: 가로형(Tier 1), 정사각(Tier 2), 세로형(Tier 3) 후보가 함께 있을 때 Tier 1이 최우선 평가 및 선정됨
    candidates = [
        {"id": "c_vert", "url": "https://example.com/vert.jpg", "credit": "Credit Vert", "source": "Pexels", "aspect_ratio": 0.67},
        {"id": "c_sq", "url": "https://example.com/square.jpg", "credit": "Credit Sq", "source": "Pexels", "aspect_ratio": 1.0},
        {"id": "c_horiz", "url": "https://example.com/horiz.jpg", "credit": "Credit Horiz", "source": "Pexels", "aspect_ratio": 1.78},
    ]

    # Gatekeeper가 Tier 1 후보군을 받았을 때 합격 리턴
    searcher.gatekeeper.evaluate_image_match.side_effect = lambda **kwargs: {
        "selected_image": kwargs["candidate_images"][0],
        "score": 8.5,
        "is_acceptable": True,
        "reason": "최적의 이미지",
    }

    # Pexels 검색 결과로 위 candidates를 반환하도록 모킹
    with patch.object(searcher, "_search_medicaldaily_images", return_value=[]), \
         patch.object(searcher, "_get_pexels_candidates", return_value=candidates):
        result = searcher._search_image_medicaldaily(
            queries=["health"],
            site_domain="medicaldaily",
            article_summary="테스트 요약",
            article_title="테스트 제목"
        )
        assert result is not None
        # Tier 1(가로형) 이미지가 선택되어야 함
        assert result["url"] == "https://example.com/horiz.jpg"
        # gatekeeper에 전달된 candidate_images는 Tier 1 그룹만 포함되어 있어야 함
        first_call_candidates = searcher.gatekeeper.evaluate_image_match.call_args_list[0][1]["candidate_images"]
        assert len(first_call_candidates) == 1
        assert first_call_candidates[0]["id"] == "c_horiz"

    # Case 2: 가로형이 없고 1:1 정사각과 세로형만 있을 때 1:1 정사각(Tier 2)이 차선으로 선정됨
    candidates_no_horiz = [
        {"id": "c_vert", "url": "https://example.com/vert.jpg", "credit": "Credit Vert", "source": "Pexels", "aspect_ratio": 0.67},
        {"id": "c_sq", "url": "https://example.com/square.jpg", "credit": "Credit Sq", "source": "Pexels", "aspect_ratio": 1.0},
    ]
    searcher.gatekeeper.evaluate_image_match.reset_mock()
    searcher.gatekeeper.evaluate_image_match.side_effect = lambda **kwargs: {
        "selected_image": kwargs["candidate_images"][0],
        "score": 8.0,
        "is_acceptable": True,
        "reason": "1:1 이미지 합격",
    }

    with patch.object(searcher, "_search_medicaldaily_images", return_value=[]), \
         patch.object(searcher, "_get_pexels_candidates", return_value=candidates_no_horiz):
        result = searcher._search_image_medicaldaily(
            queries=["health"],
            site_domain="medicaldaily",
            article_summary="테스트 요약",
            article_title="테스트 제목"
        )
        assert result is not None
        assert result["url"] == "https://example.com/square.jpg"

    # Case 3: 세로형만 있을 때 세로형(Tier 3)이 최후선으로 채택됨
    candidates_vert_only = [
        {"id": "c_vert", "url": "https://example.com/vert.jpg", "credit": "Credit Vert", "source": "Pexels", "aspect_ratio": 0.75},
    ]
    searcher.gatekeeper.evaluate_image_match.reset_mock()
    searcher.gatekeeper.evaluate_image_match.side_effect = lambda **kwargs: {
        "selected_image": kwargs["candidate_images"][0],
        "score": 7.5,
        "is_acceptable": True,
        "reason": "세로형 차선 합격",
    }

    with patch.object(searcher, "_search_medicaldaily_images", return_value=[]), \
         patch.object(searcher, "_get_pexels_candidates", return_value=candidates_vert_only):
        result = searcher._search_image_medicaldaily(
            queries=["health"],
            site_domain="medicaldaily",
            article_summary="테스트 요약",
            article_title="테스트 제목"
        )
        assert result is not None
        assert result["url"] == "https://example.com/vert.jpg"


def test_medicaldaily_image_size_1000px_limit():
    """[요건 7] 의약일보 이미지 가로 1000px 이하 파라미터 적용 및 타 영문 매체 1280~1600px 유지(Blast Radius 0%) 검증"""
    searcher = ImageSearcher({})

    # 1. Unsplash 파라미터 검증
    sample_unsplash_results = {
        "results": [
            {
                "width": 1920,
                "height": 1080,
                "urls": {"raw": "https://images.unsplash.com/photo-sample"},
                "user": {"name": "Test User"}
            }
        ]
    }
    with patch("urllib.request.urlopen") as mock_url:
        mock_resp = MagicMock()
        mock_resp.read.return_value = '{"results": [{"width": 1920, "height": 1080, "urls": {"raw": "https://images.unsplash.com/photo-sample"}, "user": {"name": "Test"}}]}'.encode("utf-8")
        mock_url.return_value.__enter__.return_value = mock_resp

        # 의약일보: w=1000
        medi_cands = searcher._get_unsplash_candidates("health", [], site_domain="medicaldaily")
        assert len(medi_cands) > 0
        assert "w=1000" in medi_cands[0]["url"]

        # 타 영문 매체: w=1600 유지 (Blast Radius 0%)
        eng_cands = searcher._get_unsplash_candidates("health", [], site_domain="scienceworldreport")
        assert len(eng_cands) > 0
        assert "w=1600" in eng_cands[0]["url"]

    # 2. Pexels 파라미터 검증
    sample_pexels_json = '{"photos": [{"width": 1920, "height": 1080, "src": {"large2x": "https://images.pexels.com/large2x.jpg", "large": "https://images.pexels.com/large.jpg"}, "photographer": "Pexels Artist"}]}'
    with patch("urllib.request.urlopen") as mock_url:
        mock_resp = MagicMock()
        mock_resp.read.return_value = sample_pexels_json.encode("utf-8")
        mock_url.return_value.__enter__.return_value = mock_resp

        # 의약일보: large (~1000px) 우선 채택
        medi_pex = searcher._get_pexels_candidates("health", [], site_domain="medicaldaily")
        assert len(medi_pex) > 0
        assert medi_pex[0]["url"] == "https://images.pexels.com/large.jpg"

        # 타 영문 매체: large2x (~1880px) 채택 유지
        eng_pex = searcher._get_pexels_candidates("health", [], site_domain="autoworldnews")
        assert len(eng_pex) > 0
        assert eng_pex[0]["url"] == "https://images.pexels.com/large2x.jpg"

    # 3. 비상 Fallback URL 검증
    with patch.object(searcher, "_search_medicaldaily_images", return_value=[]), \
         patch.object(searcher, "_get_pexels_candidates", return_value=[]), \
         patch.object(searcher, "_search_wikimedia", return_value=[]), \
         patch.object(searcher, "_get_unsplash_candidates", return_value=[]):
        fb_result = searcher._search_image_medicaldaily(["query"], site_domain="medicaldaily")
        assert "w=1000" in fb_result["url"]

