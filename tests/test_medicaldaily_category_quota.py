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

def test_medicaldaily_50_article_category_quota_simulation(temp_history):
    """
    [요건 4 시뮬레이션 검증]
    의약일보 50개 기사를 순차적으로 발행할 때:
    1. '라이프' (건강 상식, 건강 팁) 카테고리가 최소 30% (>= 15개) 이상 유지되는지
    2. 6개 카테고리('정책', '경영', '학술', '병원·제약', '라이프', '오피니언') 전체가 누락 없이 골고루 채워지는지
    3. 연속 2회 동일 카테고리 발행 차단 규칙이 100% 준수되는지
    """
    preventer = DuplicatePreventer(history_path=temp_history)
    kst = timezone(timedelta(hours=9))
    today_kst = datetime.now(kst).strftime("%Y-%m-%d")

    available_categories = [
        {"id": 1, "name": "정책", "slug": "정책"},
        {"id": 2, "name": "경영", "slug": "경영"},
        {"id": 3, "name": "학술", "slug": "학술"},
        {"id": 4, "name": "병원·제약", "slug": "병원·제약"},
        {"id": 5, "name": "라이프", "slug": "라이프"},
        {"id": 6, "name": "오피니언", "slug": "오피니언"},
    ]

    selected_history = []

    # 50회 연속 발행 시뮬레이션
    for i in range(50):
        chosen = preventer.get_stochastically_weighted_category("medicaldaily", available_categories)
        assert chosen is not None, f"Category selection failed at turn {i}"
        slug = chosen["slug"]

        # 직전 카테고리와 연속 동일 여부 검증
        if selected_history:
            assert slug != selected_history[-1], f"Turn {i}: Consecutive category '{slug}' detected!"

        selected_history.append(slug)

        # 이력에 기록
        with preventer._lock():
            history = preventer._load_history()
            medi_list = history.get("medicaldaily", [])
            medi_list.append({
                "title": f"MedicalDaily Article {i}",
                "category": slug,
                "date": today_kst,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            history["medicaldaily"] = medi_list
            with open(temp_history, "w", encoding="utf-8") as f:
                json.dump(history, f)

    # 1. '라이프' 카테고리 30% (>= 15개) 보장 검증
    life_count = selected_history.count("라이프")
    life_ratio = life_count / 50.0
    print(f"\nSimulation Results (50 articles):")
    for cat in available_categories:
        c_slug = cat["slug"]
        cnt = selected_history.count(c_slug)
        print(f"  - {c_slug}: {cnt}개 ({round(cnt/50*100, 1)}%)")

    assert life_count >= 15, f"Expected at least 15 '라이프' articles (30%), but got {life_count} ({round(life_ratio*100, 1)}%)"
    assert life_ratio >= 0.30, f"Expected life ratio >= 0.30, got {life_ratio}"

    # 2. 6개 카테고리 전체가 채워졌는지 검증 (최소 3개 이상 분배)
    for cat in available_categories:
        c_slug = cat["slug"]
        c_cnt = selected_history.count(c_slug)
        assert c_cnt >= 3, f"Category '{c_slug}' is starved with only {c_cnt} articles!"

def test_other_sites_unaffected_by_medicaldaily_quota(temp_history):
    """타 영문 사이트는 '라이프 30%' 로직의 영향을 전혀 받지 않음을 검증 (Blast Radius 방어)"""
    preventer = DuplicatePreventer(history_path=temp_history)
    kst = timezone(timedelta(hours=9))
    today_kst = datetime.now(kst).strftime("%Y-%m-%d")

    categories = [
        {"id": 1, "name": "News", "slug": "news"},
        {"id": 2, "name": "Tech", "slug": "tech"},
        {"id": 3, "name": "Space", "slug": "space"},
    ]

    # scienceworldreport에서 선택 시 일반 7일 역가중치로 동작
    chosen = preventer.get_stochastically_weighted_category("scienceworldreport", categories)
    assert chosen is not None
    assert chosen["slug"] in ["news", "tech", "space"]

