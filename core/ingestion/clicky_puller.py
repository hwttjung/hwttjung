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
