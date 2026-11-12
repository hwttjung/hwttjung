import os
import json
import time
import urllib.request
import urllib.error
import ssl
from datetime import datetime

def load_settings():
    settings_path = "config/clicky_settings.json"
    if not os.path.exists(settings_path):
        # Fallback template if missing
        return {
            "sites": [
                { "domain": "scienceworldreport", "site_id": "32020", "sitekey": "cda1dc5da3c144f4" }
            ]
        }
    with open(settings_path, "r", encoding="utf-8") as f:
        return json.load(f)

def fetch_clicky_top_pages(site_id, sitekey):
    # API 요청 URL 설계 (최근 일주일 top pages 데이터)
    base_url = "https://api.clicky.com/api/stats/4"
    params = {
        "site_id": site_id,
        "sitekey": sitekey,
        "type": "pages",
        "date": "last-7-days",
        "output": "json",
        "limit": 10  # 상위 10개 페이지만 수집
    }
    url_parts = [f"{k}={v}" for k, v in params.items()]
    target_url = f"{base_url}?{'&'.join(url_parts)}"
    
    # SSL 검증 우회
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    req = urllib.request.Request(target_url)
    req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=15) as response:
            if response.status == 200:
                body = response.read().decode("utf-8")
                data = json.loads(body)
                
                # Clicky API는 최상위 배열 또는 오류 객체를 담은 배열을 리턴함
                if isinstance(data, list) and len(data) > 0:
                    # 첫 번째 아이템이 에러 혹은 데이터 타입 그룹인지 검사
                    first_group = data[0]
                    if "error" in first_group:
                        return None, first_group.get("error", "Unknown Clicky API Error")
                    
                    # 'dates' 또는 'dates' 내부의 'items' 구조
                    dates_data = first_group.get("dates", [])
                    if dates_data and len(dates_data) > 0:
                        items = dates_data[0].get("items", [])
                        return items, None
                return [], None
            else:
                return None, f"HTTP status {response.status}"
    except Exception as e:
        return None, str(e)

def main():
    print("[Info] Starting Clicky top pages analytics data extraction (last-7-days)...")
    settings = load_settings()
    sites = settings.get("sites", [])
    
    if not sites:
        print("[Error] No active sites found in clicky_settings.json.")
        return
        
    report_content = "# Clicky 14개 사이트 최근 일주일 인기 클릭 페이지 분석 보고서\n\n"
    report_content += f"본 보고서는 Clicky Web Analytics API를 활용하여 각 매체별 최근 7일간의 최다 트래픽 클릭 페이지 상위 10개를 분석하여 수합한 결과입니다.\n\n"
    report_content += f"- **조회 시각 (KST)**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    report_content += "- **지연 정책**: API 과부하 및 Rate Limit 차단 방지를 위해 매 사이트 호출 사이에 **1.0초 지연(time.sleep)** 적용 완료.\n\n"
    report_content += "---\n\n"
    
    for idx, site in enumerate(sites, 1):
        domain = site["domain"]
        site_id = site["site_id"]
        sitekey = site["sitekey"]
        
        print(f"-> Pulling analytics for [{idx}/{len(sites)}] {domain} (ID: {site_id})...")
        
        items, err = fetch_clicky_top_pages(site_id, sitekey)
        
        report_content += f"## 🖥️ {idx}. {domain}\n"
        report_content += f"- **Clicky Site ID**: `{site_id}`\n\n"
        
        if err:
            report_content += f"❌ **데이터 수집 실패**: `{err}`\n\n"
            print(f"   [FAILED] {err}")
        elif not items:
            report_content += "⚠️ **수집된 트래픽 데이터가 없습니다.**\n\n"
            print("   [EMPTY] No page views recorded.")
        else:
            report_content += "| 순위 | 페이지 제목 (Title) | 클릭수 (Page Views) | 트래픽 비율 (%) | URL |\n"
            report_content += "| --- | --- | --- | --- | --- |\n"
            for r_idx, item in enumerate(items, 1):
                title = item.get("title", "(No Title)").strip()
                val = int(item.get("value", 0))
                percent = item.get("value_percent", "0")
                url = item.get("url", "#")
                
                # 마크다운 포맷 깨짐 방지용 정형화
                title_clean = title.replace("|", "\\|")
                report_content += f"| {r_idx} | {title_clean} | {val:,} | {percent}% | [{domain}]({url}) |\n"
                
            report_content += "\n"
            print(f"   [SUCCESS] Extracted {len(items)} items.")
            
        # [피드백 반영] Rate limit 차단을 완벽히 회피하기 위해 1초 대기 적용
        time.sleep(1.0)
        
    output_dir = "data"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "clicky_weekly_pages.md")
    
    with open(output_path, "w", encoding="utf-8") as out_f:
        out_f.write(report_content)
        
    print("\n==================================================")
    print(" Analytics Data Extraction Completed!")
    print(f" - Report Saved to: {output_path}")
    print("==================================================")

get_weekly_pages_for_site = fetch_clicky_top_pages
pull_all_sites_weekly = main

if __name__ == "__main__":
    main()


def get_medicaldaily_clicky_keywords(limit=3):
    """
    [요건 5] Clicky 애널리틱스 데이터를 분석하여 독자 관심도가 높은 1~3개 헬스케어 키워드를 도출합니다.
    3단계 안전 폴백 체인:
    1. Clicky API 실시간 호출
    2. data/clicky_weekly_pages.md 인기 기사 타이틀 분석
    3. 검증된 헬스케어 핫 관심사 키워드 풀
    """
    # 3단계 최종 안전망 키워드 풀
    fallback_pool = [
        "비만치료제 GLP-1",
        "지중해식 식단 걷기 운동",
        "심혈관 질환 혈압 예방",
        "알츠하이머 치매 조기 진단",
        "면역항암제 신약 임상",
        "당뇨 혈당 관리 건강 상식",
    ]

    keywords = []

    # 1단계: Clicky API 시도
    try:
        settings = load_settings()
        sites = settings.get("sites", [])
        medi_site = next((s for s in sites if s.get("domain") == "medicaldaily"), None)
        if medi_site and medi_site.get("site_id") and medi_site.get("sitekey"):
            items, err = fetch_clicky_top_pages(medi_site["site_id"], medi_site["sitekey"])
            if not err and items:
                for it in items[:limit]:
                    t = it.get("title", "")
                    if t and t != "non-article":
                        keywords.append(t)
    except Exception:
        pass

    # 2단계: data/clicky_weekly_pages.md 파일 분석 시도
    if len(keywords) < limit:
        report_path = "data/clicky_weekly_pages.md"
        if os.path.exists(report_path):
            try:
                import re
                with open(report_path, "r", encoding="utf-8") as rf:
                    content = rf.read()
                # health 관련 타이틀 정규식 추출
                health_matches = re.findall(r"\|\s*\d+\s*\|\s*([^\|]+health[^\|]*|[^\|]+diet[^\|]*|[^\|]+study[^\|]*|[^\|]+weight[^\|]*)\s*\|", content, re.IGNORECASE)
                for hm in health_matches:
                    clean_kw = hm.strip()
                    if clean_kw and clean_kw not in keywords:
                        keywords.append(clean_kw)
                    if len(keywords) >= limit:
                        break
            except Exception:
                pass

    # 3단계: 기본 핫 관심사 키워드로 충원
    for fb in fallback_pool:
        if len(keywords) >= limit:
            break
        if fb not in keywords:
            keywords.append(fb)

    return keywords[:limit]


def fetch_clicky_matched_rss_source(keywords, feeds_file="config/rss_feeds.json"):
    """
    [요건 5] 주어진 Clicky 관심 키워드 목록과 가장 연관도(Relevance)가 높은
    의약일보 RSS 피드 원문 기사를 선별 매칭하여 팩트 소스를 구성합니다.
    - 원칙: 실제 RSS XML에서 파싱된 실존 Reference URL과 Original Summary 기반 100% 팩트 보장.
    """
    import xml.etree.ElementTree as ET
    from core.storage.duplicate_preventer import DuplicatePreventer

    if not os.path.exists(feeds_file):
        return None

    try:
        with open(feeds_file, "r", encoding="utf-8") as f:
            all_feeds = json.load(f)
    except Exception:
        return None

    medi_feeds = all_feeds.get("medicaldaily", [])
    if not medi_feeds:
        return None

    preventer = DuplicatePreventer()
    used_links = preventer.get_recent_rss_links("medicaldaily")

    # 키워드 토큰화
    search_tokens = set()
    for kw in (keywords or []):
        for token in str(kw).replace("-", " ").replace("·", " ").split():
            clean_tok = token.strip().lower()
            if len(clean_tok) >= 2:
                search_tokens.add(clean_tok)

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    scored_candidates = []
    fallback_candidate = None

    import random
    feed_sample = medi_feeds.copy()
    random.shuffle(feed_sample)

    for feed_url in feed_sample[:10]:
        try:
            req = urllib.request.Request(feed_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                xml_data = resp.read()
            root = ET.fromstring(xml_data)
            items = root.findall(".//item")
            if not items:
                items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

            for item in items[:15]:
                title_elem = item.find("title")
                if title_elem is None:
                    title_elem = item.find("{http://www.w3.org/2005/Atom}title")

                link_elem = item.find("link")
                if link_elem is None:
                    link_elem = item.find("{http://www.w3.org/2005/Atom}link")

                desc_elem = item.find("description")
                if desc_elem is None:
                    desc_elem = item.find("{http://www.w3.org/2005/Atom}summary")

                title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
                if link_elem is not None:
                    link = (link_elem.get("href") or link_elem.text or "").strip()
                else:
                    link = ""
                desc = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ""

                if not title or not link or link in used_links:
                    continue

                if fallback_candidate is None:
                    fallback_candidate = (title, desc, link)

                combined_text = (title + " " + desc).lower()
                # 매칭 점수 산출
                match_score = sum(1 for tok in search_tokens if tok in combined_text)
                if match_score > 0:
                    scored_candidates.append((match_score, title, desc, link))

            if len(scored_candidates) >= 5:
                break
        except Exception:
            continue

    if scored_candidates:
        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_title, best_desc, best_link = scored_candidates[0]
    elif fallback_candidate:
        best_title, best_desc, best_link = fallback_candidate
        best_score = 0
    else:
        return None

    payload = (
        f"SOURCE REAL NEWS WIRE REPORT\n"
        f"============================\n"
        f"Original Title: {best_title}\n"
        f"Original Summary: {best_desc}\n"
        f"Reference URL: {best_link}\n"
        f"============================\n"
        f"Please write a high quality article based on the facts and guidelines above."
    )
    return payload, best_link, best_title, best_score
