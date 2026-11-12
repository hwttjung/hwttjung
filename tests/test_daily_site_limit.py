import os
import json
import pytest
from datetime import datetime, timedelta, timezone
from core.storage.duplicate_preventer import DuplicatePreventer

@pytest.fixture
def temp_history(tmp_path):
    history_file = tmp_path / "published_history.json"
    with open(history_file, "w", encoding="utf-8") as f:
        json.dump({}, f)
    return str(history_file)

def test_medicaldaily_category_limit_expanded(temp_history):
    preventer = DuplicatePreventer(history_path=temp_history)
    kst = timezone(timedelta(hours=9))
    today_kst = datetime.now(kst).strftime("%Y-%m-%d")

    # Simulate 5 articles in 'policy' category today for medicaldaily
    with preventer._lock():
        with open(temp_history, "w", encoding="utf-8") as f:
            json.dump({
                "medicaldaily": [
                    {"title": f"Article {i}", "category": "policy", "date": today_kst, "timestamp": datetime.now(timezone.utc).isoformat()}
                    for i in range(5)
                ]
            }, f)

    categories = [
        {"name": "정책", "slug": "policy", "id": 1},
        {"name": "경영", "slug": "management", "id": 2}
    ]

    # policy has 5 publications today, which is > 2, but < 15. It must be allowed for medicaldaily!
    allowed = preventer.get_allowed_categories("medicaldaily", categories)
    allowed_slugs = [c["slug"] for c in allowed]

    # 'policy' was the last category published, so consecutive check blocks it if it was immediately last.
    # To test daily limit without consecutive blockage:
    with preventer._lock():
        with open(temp_history, "w", encoding="utf-8") as f:
            json.dump({
                "medicaldaily": [
                    {"title": f"Article {i}", "category": "policy", "date": today_kst, "timestamp": datetime.now(timezone.utc).isoformat()}
                    for i in range(5)
                ] + [
                    {"title": "Management Article", "category": "management", "date": today_kst, "timestamp": datetime.now(timezone.utc).isoformat()}
                ]
            }, f)

    allowed = preventer.get_allowed_categories("medicaldaily", categories)
    allowed_slugs = [c["slug"] for c in allowed]
    assert "policy" in allowed_slugs, "policy should still be allowed since 5 < 15 for medicaldaily"
    assert "management" not in allowed_slugs, "management was immediately last published so consecutive check blocks it"

def test_other_site_category_limit_remains_2(temp_history):
    preventer = DuplicatePreventer(history_path=temp_history)
    kst = timezone(timedelta(hours=9))
    today_kst = datetime.now(kst).strftime("%Y-%m-%d")

    # Simulate 2 articles in 'tech' for scienceworldreport, followed by 1 in 'space'
    with preventer._lock():
        with open(temp_history, "w", encoding="utf-8") as f:
            json.dump({
                "scienceworldreport": [
                    {"title": "Tech 1", "category": "tech", "date": today_kst, "timestamp": datetime.now(timezone.utc).isoformat()},
                    {"title": "Tech 2", "category": "tech", "date": today_kst, "timestamp": datetime.now(timezone.utc).isoformat()},
                    {"title": "Space 1", "category": "space", "date": today_kst, "timestamp": datetime.now(timezone.utc).isoformat()}
                ]
            }, f)

    categories = [
        {"name": "Tech", "slug": "tech", "id": 10},
        {"name": "Space", "slug": "space", "id": 20},
        {"name": "Health", "slug": "health", "id": 30}
    ]

    allowed = preventer.get_allowed_categories("scienceworldreport", categories)
    allowed_slugs = [c["slug"] for c in allowed]

    assert "tech" not in allowed_slugs, "tech has 2 publications today and must be blocked for regular sites"
    assert "space" not in allowed_slugs, "space was last published and must be blocked by consecutive rule"
    assert "health" in allowed_slugs, "health has 0 publications and should be allowed"

def test_medicaldaily_reaches_max_limit_15(temp_history):
    preventer = DuplicatePreventer(history_path=temp_history)
    kst = timezone(timedelta(hours=9))
    today_kst = datetime.now(kst).strftime("%Y-%m-%d")

    # Simulate 15 articles in 'policy' followed by 1 in 'management'
    with preventer._lock():
        with open(temp_history, "w", encoding="utf-8") as f:
            json.dump({
                "medicaldaily": [
                    {"title": f"Policy {i}", "category": "policy", "date": today_kst, "timestamp": datetime.now(timezone.utc).isoformat()}
                    for i in range(15)
                ] + [
                    {"title": "Management 1", "category": "management", "date": today_kst, "timestamp": datetime.now(timezone.utc).isoformat()}
                ]
            }, f)

    categories = [
        {"name": "정책", "slug": "policy", "id": 1},
        {"name": "학술", "slug": "academic", "id": 3}
    ]

    allowed = preventer.get_allowed_categories("medicaldaily", categories)
    allowed_slugs = [c["slug"] for c in allowed]

    assert "policy" not in allowed_slugs, "policy has 15 publications today and must be blocked at limit 15"
    assert "academic" in allowed_slugs, "academic has 0 publications and must be allowed"
