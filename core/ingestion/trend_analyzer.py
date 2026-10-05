import os
import requests
import xml.etree.ElementTree as ET
from bingads.authorization import OAuthDesktopMobileAuthCodeGrant

import re
import urllib.request
import ssl
import json

# 어필리에이트/딜 기사 제외 및 뉴스 본문 크롤링 헬퍼
def fetch_trend_news_body(url, timeout=10):
    if not url:
        return ""
    try:
        req = urllib.request.Request(
            url, 
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        )
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as response:
            html = response.read().decode("utf-8", errors="ignore")
            paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', html, re.DOTALL)
            text_lines = []
            for p in paragraphs:
                cleaned = re.sub(r'<[^>]+>', '', p).strip()
                if len(cleaned) > 30 and not any(k in cleaned.lower() for k in ["cookie", "subscribe", "sign up", "privacy policy"]):
                    text_lines.append(cleaned)
            # 최대 2500자로 잘라서 팩트 소스로 반환
            return " ".join(text_lines)[:2500]
    except Exception as e:
        return ""

# 1. Google Trends RSS 상세 수집기 (https://trends.google.co.kr/trending/rss?geo=US)
def fetch_google_trends_detailed(geo="US", url=None, max_items=10):
    """
    구글 트렌드 RSS로부터 실시간 트렌드 검색어, 트래픽, 뉴스 아이템 목록을 상세 추출합니다.
    """
    import subprocess
    if url is None:
        url = f"https://trends.google.co.kr/trending/rss?geo={geo}"
        
    xml_content = ""
    try:
        res = subprocess.run(
            ["curl", "-s", "-m", "15", "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", url],
            capture_output=True,
            text=True
        )
        if res.returncode == 0 and res.stdout and "<rss" in res.stdout:
            xml_content = res.stdout
    except Exception as e:
        pass
        
    if not xml_content:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                xml_content = resp.text
        except Exception as e:
            print(f"[경고] Google Trends RSS 로드 실패: {e}")
            return []
            
    trends = []
    try:
        root = ET.fromstring(xml_content.encode("utf-8") if isinstance(xml_content, str) else xml_content)
        ns = {
            "ht": "https://trends.google.com/trending/rss",
            "atom": "http://www.w3.org/2005/Atom"
        }
        
        items = root.findall('.//item')
        for item in items[:max_items]:
            title_elem = item.find('title')
            query = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
            
            traffic_elem = item.find('ht:approx_traffic', ns)
            traffic = traffic_elem.text.strip() if traffic_elem is not None and traffic_elem.text else "N/A"
            
            pubdate_elem = item.find('pubDate')
            pub_date = pubdate_elem.text.strip() if pubdate_elem is not None and pubdate_elem.text else ""
            
            pic_elem = item.find('ht:picture', ns)
            picture = pic_elem.text.strip() if pic_elem is not None and pic_elem.text else ""
            
            pic_src_elem = item.find('ht:picture_source', ns)
            picture_source = pic_src_elem.text.strip() if pic_src_elem is not None and pic_src_elem.text else ""
            
            news_items = []
            for n_elem in item.findall('ht:news_item', ns):
                n_title = n_elem.find('ht:news_item_title', ns)
                n_url = n_elem.find('ht:news_item_url', ns)
                n_snippet = n_elem.find('ht:news_item_snippet', ns)
                n_source = n_elem.find('ht:news_item_source', ns)
                n_pic = n_elem.find('ht:news_item_picture', ns)
                
                news_title = n_title.text.strip() if n_title is not None and n_title.text else ""
                news_url = n_url.text.strip() if n_url is not None and n_url.text else ""
                news_snippet = n_snippet.text.strip() if n_snippet is not None and n_snippet.text else ""
                news_source = n_source.text.strip() if n_source is not None and n_source.text else ""
                news_pic = n_pic.text.strip() if n_pic is not None and n_pic.text else ""
                
                if news_title:
                    news_items.append({
                        "title": news_title,
                        "url": news_url,
                        "snippet": news_snippet,
                        "source": news_source,
                        "picture": news_pic
                    })
            
            if query:
                trends.append({
                    "query": query,
                    "traffic": traffic,
                    "pub_date": pub_date,
                    "picture": picture,
                    "picture_source": picture_source,
                    "news_items": news_items
                })
    except Exception as e:
        print(f"[경고] Google Trends RSS XML 파싱 실패: {e}")
        
    return trends

# 1-1. 기존 호환용 간소화 수집기
def get_google_trends():
    detailed = fetch_google_trends_detailed(max_items=10)
    trends = []
    for item in detailed:
        trends.append({
            "query": item["query"],
            "traffic": item["traffic"]
        })
    return trends

# 2. Pinterest Trends API 연동 (에러 복구 안전망 포함)
def get_pinterest_trends(seed_keyword, env):
    access_token = env.get("PINTEREST_ACCESS_TOKEN")
    if not access_token:
        # 아직 액세스 토큰이 미발급되었거나 없을 경우 에러 없이 빈 값 반환
        return {}
        
    url = f"https://api.pinterest.com/v5/trends?country=US&keywords={requests.utils.quote(seed_keyword)}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    try:
        # 아직 API 승인 전이므로 타임아웃을 짧게 주어 지연을 방지함
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        # Pinterest API 통신 및 권한 에러를 무시하고 무해한 Fallback 작동
        pass
    return {}

# 3. Microsoft Ads API (Bing Ads) GetKeywordIdeas 연동
def get_ms_ads_volume(seed_keyword, env):
    client_id = env.get("MS_CLIENT_ID")
    developer_token = env.get("MS_ADS_TOKEN") # .env에 등록된 MS_ADS_TOKEN이 Developer Token입니다.
    refresh_token = env.get("MS_REFRESH_TOKEN")
    customer_id = env.get("MS_CUSTOMER_ID")
    account_id = env.get("MS_ACCOUNT_ID")
    
    # 필수 크리덴셜 중 하나라도 누락되면 즉시 안전하게 스킵
    if not all([client_id, developer_token, refresh_token, customer_id, account_id]):
        return []
        
    try:
        # OAuth 2.0 Access Token 갱신
        authentication = OAuthDesktopMobileAuthCodeGrant(
            client_id=client_id
        )
        authentication.request_oauth_tokens_by_refresh_token(refresh_token)
        access_token = authentication.oauth_tokens.access_token
        
        # SOAP Envelope 구성 (ExpandIdeas: True로 아이디어 확장 유도)
        soap_payload = f"""<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
  <s:Header>
    <h:AuthenticationToken xmlns:h="https://bingads.microsoft.com/AdInsight/v13">{access_token}</h:AuthenticationToken>
    <h:DeveloperToken xmlns:h="https://bingads.microsoft.com/AdInsight/v13">{developer_token}</h:DeveloperToken>
    <h:CustomerId xmlns:h="https://bingads.microsoft.com/AdInsight/v13">{customer_id}</h:CustomerId>
    <h:CustomerAccountId xmlns:h="https://bingads.microsoft.com/AdInsight/v13">{account_id}</h:CustomerAccountId>
  </s:Header>
  <s:Body>
    <GetKeywordIdeasRequest xmlns="https://bingads.microsoft.com/AdInsight/v13">
      <ExpandIdeas>true</ExpandIdeas>
      <IdeaAttributes>
        <KeywordIdeaAttribute>Keyword</KeywordIdeaAttribute>
        <KeywordIdeaAttribute>SearchVolume</KeywordIdeaAttribute>
      </IdeaAttributes>
      <SearchParameters>
        <SearchParameter xmlns:i="http://www.w3.org/2001/XMLSchema-instance" i:type="QuerySearchParameter">
          <Queries xmlns:a="http://schemas.microsoft.com/2003/10/Serialization/Arrays">
            <a:string>{seed_keyword}</a:string>
          </Queries>
        </SearchParameter>
        <SearchParameter xmlns:i="http://www.w3.org/2001/XMLSchema-instance" i:type="LanguageSearchParameter">
          <Languages>
            <LanguageCriterion>
              <Language>English</Language>
            </LanguageCriterion>
          </Languages>
        </SearchParameter>
      </SearchParameters>
    </GetKeywordIdeasRequest>
  </s:Body>
</s:Envelope>"""

        url = "https://adinsight.api.bingads.microsoft.com/Api/Advertiser/AdInsight/v13/AdInsightService.svc"
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "GetKeywordIdeas"
        }
        
        response = requests.post(url, data=soap_payload.encode('utf-8'), headers=headers, timeout=10)
        
        results = []
        if response.status_code == 200:
            root = ET.fromstring(response.text)
            namespaces = {
                'a': 'https://bingads.microsoft.com/AdInsight/v13'
            }
            ideas = root.findall('.//a:KeywordIdea', namespaces)
            for idea in ideas:
                kw = idea.find('a:Keyword', namespaces)
                sv = idea.find('a:SearchVolume', namespaces)
                kw_val = kw.text if kw is not None else ""
                sv_val = int(sv.text) if (sv is not None and sv.text) else 0
                if kw_val:
                    results.append({
                        "keyword": kw_val,
                        "search_volume": sv_val
                    })
        # 검색량 기준 내림차순 정렬
        results.sort(key=lambda x: x["search_volume"], reverse=True)
        return results
        
    except Exception as e:
        # MS Ads API 연동 중 발생한 어떠한 오류도 무해하게 로깅 및 Fallback 반환
        print(f"[경고] Microsoft Ads API 호출 오류: {e}")
    return []

search_pinterest_trends = get_pinterest_trends
search_ms_ads_trends = get_ms_ads_volume

# 4. 하이브리드 트렌드 정보 집계 통합 메소드
def gather_trends(seed_keyword, env):
    trends_report = {
        "seed_keyword": seed_keyword,
        "google_trends": get_google_trends(),
        "pinterest_trends": get_pinterest_trends(seed_keyword, env),
        "ms_ads_keyword_ideas": get_ms_ads_volume(seed_keyword, env)
    }
    return trends_report

# 5. Gemini를 사용하여 최고 인기 기사로부터 구체적인 Core Seed Keyword 추출
def extract_core_seed_keyword(api_key, top_articles):
    if not top_articles:
        return "latest trends"
        
    target_article = top_articles[0]
    prompt = f"""
You are a professional SEO Specialist and Editor.
Analyze the title of our top popular article: "{target_article.get('title', '')}"
 
Your task is to extract exactly ONE highly specific 'Core Seed Keyword' (1-3 words) representing the concrete subject, technology, proper noun, or medical/business condition of this article.
This seed keyword will be used to look up search volume ideas and real-time trends.
 
CRITICAL RULES:
1. DO NOT extract broad, generic, or category-level words like "Scientific discovery", "Labor Market", "Business", "Sports", "Politics", "Technology", "Health", "Medicine", etc.
2. DO extract the highly specific, concrete core noun or term.
3. Output ONLY the clean keyword and nothing else. No quote marks, no bullet points, no explanations.
"""
    model_name = "gemini-3.1-flash-lite"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3}
    }
    
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, context=ctx, timeout=15) as response:
            body = response.read().decode("utf-8")
            res_json = json.loads(body)
            keyword = res_json['candidates'][0]['content']['parts'][0]['text'].strip()
            keyword = keyword.replace('"', '').replace("'", "").strip()
            return keyword
    except Exception as e:
        return "lifestyle trends"
