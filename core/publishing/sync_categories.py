import os
import re
import json
import time
import urllib.request
import urllib.error
import ssl
from datetime import datetime

# ==============================================================================
# 1. 견고한 .env 파일 파서 (외부 패키지 의존성 제거)
# ==============================================================================
def load_env(env_path=".env"):
    if not os.path.exists(env_path):
        print(f"[Warning] {env_path} file not found.")
        return {}
    
    env_vars = {}
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # 주석 및 빈 줄 스킵
            if not line or line.startswith("#"):
                continue
            # KEY=VALUE 매칭
            match = re.match(r"^([^=]+)=(.*)$", line)
            if match:
                key = match.group(1).strip()
                val = match.group(2).strip()
                # 따옴표 제거
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                env_vars[key] = val
                os.environ[key] = val
    return env_vars

# ==============================================================================
# 2. API 호출 유틸리티 (재시도 및 지수 백오프 탑재)
# ==============================================================================
def fetch_categories_with_retry(base_url, api_key, max_retries=3, backoff_factor=2):
    # Base URL의 trailing slash 정합성 체크
    if not base_url.endswith("/"):
        base_url += "/"
    target_url = f"{base_url}categories.php"
    
    # SSL 검증 우회 (인증서 오류 대비)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    req = urllib.request.Request(target_url)
    req.add_header("X-API-Key", api_key)
    req.add_header("User-Agent", "AI-Article-Publisher/1.0")
    
    retry_delay = 1.0
    for attempt in range(1, max_retries + 1):
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
                if response.status == 200:
                    body = response.read().decode("utf-8")
                    data = json.loads(body)
                    return data.get("categories", []), None
                else:
                    return None, f"HTTP status {response.status}"
        except urllib.error.HTTPError as e:
            status_code = e.code
            try:
                error_body = e.read().decode('utf-8')
                error_json = json.loads(error_body)
                error_msg = error_json.get("error", "unknown_api_error")
            except:
                error_msg = e.reason
            
            # 429(Rate Limit) 또는 5xx(서버 오류)일 때만 재시도 진행
            if status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                print(f"  [Attempt {attempt}] Retrying in {retry_delay}s due to error: {status_code} ({error_msg})")
                time.sleep(retry_delay)
                retry_delay *= backoff_factor
                continue
            else:
                return None, f"HTTP {status_code} ({error_msg})"
        except Exception as e:
            if attempt < max_retries:
                print(f"  [Attempt {attempt}] Connection error: {str(e)}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay *= backoff_factor
                continue
            else:
                return None, f"Connection failed: {str(e)}"
    
    return None, "Max retries exceeded"

fetch_categories_for_site = fetch_categories_with_retry

# ==============================================================================
# 3. 메인 실행 함수
# ==============================================================================
def main():
    print("[Info] Starting category synchronization...")
    
    # 1. env 환경 변수 로드
    env = load_env()
    
    # 2. 8개 사이트 맵핑 매트릭스 구성
    sites_config = []
    # 1번부터 8번까지 순서대로 파싱
    for i in range(1, 9):
        url_key = f"ARTICLES_API_BASE_URL_{i}"
        key_key = f"ARTICLES_API_KEY_{i}"
        
        url = env.get(url_key)
        api_key = env.get(key_key)
        
        if url and api_key:
            # 도메인명 추출 (로깅 및 캐싱 키용)
            domain = "unknown"
            match = re.search(r"https?://admin\.([^/]+)", url)
            if match:
                domain = match.group(1).split(".")[0]  # 예: scienceworldreport
            
            sites_config.append({
                "index": i,
                "domain_key": domain,
                "url": url,
                "api_key": api_key
            })
    
    if not sites_config:
        print("[Error] No active site configurations found in .env. Please check the environment variables.")
        return

    print(f"[Info] Found {len(sites_config)} active sites in configuration.")
    
    # 3. 사이트별 카테고리 수집
    all_categories = {}
    success_count = 0
    total_categories_count = 0
    
    for site in sites_config:
        print(f"-> Processing [{site['index']}/8] {site['domain_key']}...")
        
        # API 호출 및 카테고리 fetch
        categories, err = fetch_categories_with_retry(site["url"], site["api_key"])
        
        if err is None:
            all_categories[site["domain_key"]] = categories
            success_count += 1
            total_categories_count += len(categories)
            print(f"   [SUCCESS] Collected {len(categories)} categories.")
        else:
            print(f"   [FAILED] Error: {err}")
            all_categories[site["domain_key"]] = []
            
        # 연속 호출 시 레이트 리밋 예방을 위해 0.5초 대기
        time.sleep(0.5)
        
    # JobsnHire 정적 카테고리 정보 강제 병합 (API 호출 없이 로컬 저장 전용)
    jobsnhire_categories = [
        {"id": 1, "name": "Business", "slug": "business", "title": "Business"},
        {"id": 2, "name": "Retail", "slug": "retail", "title": "Retail"},
        {"id": 3, "name": "Tech", "slug": "tech", "title": "Tech"},
        {"id": 4, "name": "Autos", "slug": "autos", "title": "Autos"},
        {"id": 5, "name": "Energy", "slug": "energy", "title": "Energy"},
        {"id": 6, "name": "Food", "slug": "food", "title": "Food"},
        {"id": 7, "name": "Pharma& Health care", "slug": "pharma-health-care", "title": "Pharma& Health care"},
        {"id": 8, "name": "Media", "slug": "media", "title": "Media"},
        {"id": 9, "name": "Education", "slug": "education", "title": "Education"},
        {"id": 10, "name": "Entrepreneurs", "slug": "entrepreneurs", "title": "Entrepreneurs"},
        {"id": 11, "name": "Taxes and Law", "slug": "taxes-and-law", "title": "Taxes and Law"},
        {"id": 12, "name": "Finance", "slug": "finance", "title": "Finance"},
        {"id": 13, "name": "Small business", "slug": "small-business", "title": "Small business"},
        {"id": 14, "name": "Leadership", "slug": "leadership", "title": "Leadership"},
        {"id": 15, "name": "Leaders", "slug": "leaders", "title": "Leaders"},
        {"id": 16, "name": "Management", "slug": "management", "title": "Management"},
        {"id": 17, "name": "Lifestyle", "slug": "lifestyle", "title": "Lifestyle"},
        {"id": 18, "name": "Entertainment", "slug": "entertainment", "title": "Entertainment"},
        {"id": 19, "name": "Sports", "slug": "sports", "title": "Sports"},
        {"id": 20, "name": "Travel", "slug": "travel", "title": "Travel"},
        {"id": 21, "name": "Graduates", "slug": "graduates", "title": "Graduates"},
        {"id": 22, "name": "Technology", "slug": "technology", "title": "Technology"},
        {"id": 23, "name": "Games", "slug": "games", "title": "Games"},
        {"id": 24, "name": "Gear", "slug": "gear", "title": "Gear"},
        {"id": 25, "name": "Mobile", "slug": "mobile", "title": "Mobile"},
        {"id": 26, "name": "Security", "slug": "security", "title": "Security"},
        {"id": 27, "name": "Social Media", "slug": "social-media", "title": "Social Media"},
        {"id": 28, "name": "Events", "slug": "events", "title": "Events"},
        {"id": 29, "name": "NASA", "slug": "nasa", "title": "NASA"},
        {"id": 30, "name": "Biology", "slug": "biology", "title": "Biology"},
        {"id": 31, "name": "Chemist", "slug": "chemist", "title": "Chemist"},
        {"id": 32, "name": "Global Warming", "slug": "global-warming", "title": "Global Warming"},
        {"id": 33, "name": "News", "slug": "news", "title": "News"}
    ]
    all_categories["jobsnhire"] = jobsnhire_categories
    total_categories_count += len(jobsnhire_categories)
    print(f"-> Injected static cache for jobsnhire: Added {len(jobsnhire_categories)} categories.")

    # 1) FranchiseHerald 카테고리 정보 강제 병합
    franchise_categories = [
        {"id": 1, "name": "Franchise News", "slug": "franchise-news", "title": "Franchise News"},
        {"id": 2, "name": "Product", "slug": "product", "title": "Product"},
        {"id": 3, "name": "Best Deals", "slug": "best-deals", "title": "Best Deals"},
        {"id": 4, "name": "Misc", "slug": "misc", "title": "Misc"},
        {"id": 5, "name": "Featured Franchise", "slug": "featured-franchise", "title": "Featured Franchise"},
        {"id": 6, "name": "Best Alibaba Suppliers", "slug": "best-alibaba-suppliers", "title": "Best Alibaba Suppliers"},
        {"id": 7, "name": "Coupons", "slug": "coupons", "title": "Coupons"},
        {"id": 8, "name": "Franchise Directory", "slug": "franchise-directory", "title": "Franchise Directory"},
        {"id": 9, "name": "Guide", "slug": "guide", "title": "Guide"},
        {"id": 10, "name": "Marketing", "slug": "marketing", "title": "Marketing"},
        {"id": 11, "name": "Franchise Review", "slug": "franchise-review", "title": "Franchise Review"},
        {"id": 12, "name": "Biz/Tech", "slug": "biz-tech", "title": "Biz/Tech"},
        {"id": 13, "name": "Life", "slug": "life", "title": "Life"},
        {"id": 14, "name": "Trending News", "slug": "trending-news", "title": "Trending News"}
    ]
    all_categories["franchiseherald"] = franchise_categories
    total_categories_count += len(franchise_categories)
    print(f"-> Injected static cache for franchiseherald: Added {len(franchise_categories)} categories.")

    # 2) MobileNApps 카테고리 정보 강제 병합
    mobile_categories = [
        {"id": 1, "name": "RECOMMEND APPS & GAMES", "slug": "recommend-apps-games", "title": "RECOMMEND APPS & GAMES"},
        {"id": 2, "name": "APPS/GAMES ON SALE", "slug": "apps-games-on-sale", "title": "APPS/GAMES ON SALE"},
        {"id": 3, "name": "RECOMMEND GAMES", "slug": "recommend-games", "title": "RECOMMEND GAMES"},
        {"id": 4, "name": "RECOMMEND APPS", "slug": "recommend-apps", "title": "RECOMMEND APPS"},
        {"id": 5, "name": "News", "slug": "news", "title": "News"},
        {"id": 6, "name": "Mobile", "slug": "mobile", "title": "Mobile"},
        {"id": 7, "name": "Tablet", "slug": "tablet", "title": "Tablet"},
        {"id": 8, "name": "PC", "slug": "pc", "title": "PC"},
        {"id": 9, "name": "Wearables", "slug": "wearables", "title": "Wearables"},
        {"id": 10, "name": "Accessories", "slug": "accessories", "title": "Accessories"},
        {"id": 11, "name": "What's App", "slug": "whats-app", "title": "What's App"},
        {"id": 12, "name": "Business", "slug": "business", "title": "Business"},
        {"id": 13, "name": "Security", "slug": "security", "title": "Security"},
        {"id": 14, "name": "Camera", "slug": "camera", "title": "Camera"},
        {"id": 15, "name": "Games", "slug": "games", "title": "Games"},
        {"id": 16, "name": "Mobile Games", "slug": "mobile-games", "title": "Mobile Games"},
        {"id": 17, "name": "PC Games", "slug": "pc-games", "title": "PC Games"},
        {"id": 18, "name": "XBOX", "slug": "xbox", "title": "XBOX"},
        {"id": 19, "name": "NINTENDO", "slug": "nintendo", "title": "NINTENDO"},
        {"id": 20, "name": "PS4", "slug": "ps4", "title": "PS4"},
        {"id": 21, "name": "Reviews", "slug": "reviews", "title": "Reviews"},
        {"id": 22, "name": "Gadgets", "slug": "gadgets", "title": "Gadgets"},
        {"id": 23, "name": "APPS", "slug": "apps", "title": "APPS"},
        {"id": 24, "name": "How To", "slug": "how-to", "title": "How To"},
        {"id": 25, "name": "Culture", "slug": "culture", "title": "Culture"},
        {"id": 26, "name": "TV Shows", "slug": "tv-shows", "title": "TV Shows"},
        {"id": 27, "name": "Movies", "slug": "movies", "title": "Movies"},
        {"id": 28, "name": "Celebrities", "slug": "celebrities", "title": "Celebrities"},
        {"id": 29, "name": "Sports", "slug": "sports", "title": "Sports"},
        {"id": 30, "name": "Trending News", "slug": "trending-news", "title": "Trending News"}
    ]
    all_categories["mobilenapps"] = mobile_categories
    total_categories_count += len(mobile_categories)
    print(f"-> Injected static cache for mobilenapps: Added {len(mobile_categories)} categories.")

    # 3) ParentHerald 카테고리 정보 강제 병합
    parent_categories = [
        {"id": 1, "name": "Trending News", "slug": "trending-news", "title": "Trending News"},
        {"id": 2, "name": "News", "slug": "news", "title": "News"},
        {"id": 3, "name": "Product Review", "slug": "product-review", "title": "Product Review"},
        {"id": 4, "name": "Resources", "slug": "resources", "title": "Resources"},
        {"id": 5, "name": "Parenting", "slug": "parenting", "title": "Parenting"},
        {"id": 6, "name": "Health/Nutrition", "slug": "health-nutrition", "title": "Health/Nutrition"},
        {"id": 7, "name": "School", "slug": "school", "title": "School"},
        {"id": 8, "name": "Family Life", "slug": "family-life", "title": "Family Life"},
        {"id": 9, "name": "Moms", "slug": "moms", "title": "Moms"},
        {"id": 10, "name": "Pregnancy", "slug": "pregnancy", "title": "Pregnancy"},
        {"id": 11, "name": "Celebrity Moms", "slug": "celebrity-moms", "title": "Celebrity Moms"},
        {"id": 12, "name": "Dads", "slug": "dads", "title": "Dads"},
        {"id": 13, "name": "New Dad", "slug": "new-dad", "title": "New Dad"},
        {"id": 14, "name": "Expectant Dad", "slug": "expectant-dad", "title": "Expectant Dad"},
        {"id": 15, "name": "Celebrity Dads", "slug": "celebrity-dads", "title": "Celebrity Dads"},
        {"id": 16, "name": "Children", "slug": "children", "title": "Children"},
        {"id": 17, "name": "Infant", "slug": "infant", "title": "Infant"},
        {"id": 18, "name": "Toddler", "slug": "toddler", "title": "Toddler"},
        {"id": 19, "name": "School Age", "slug": "school-age", "title": "School Age"},
        {"id": 20, "name": "Teens/Young Adults", "slug": "teens-young-adults", "title": "Teens/Young Adults"},
        {"id": 21, "name": "Issues", "slug": "issues", "title": "Issues"},
        {"id": 22, "name": "SPED Kids", "slug": "sped-kids", "title": "SPED Kids"},
        {"id": 23, "name": "Adoption", "slug": "adoption", "title": "Adoption"},
        {"id": 24, "name": "Marriage and Relationship", "slug": "marriage-relationship", "title": "Marriage and Relationship"},
        {"id": 25, "name": "Child Abuse", "slug": "child-abuse", "title": "Child Abuse"},
        {"id": 26, "name": "Parent Buzz", "slug": "parent-buzz", "title": "Parent Buzz"}
    ]
    all_categories["parentherald"] = parent_categories
    total_categories_count += len(parent_categories)
    print(f"-> Injected static cache for parentherald: Added {len(parent_categories)} categories.")

    # 4) BooksNReview 카테고리 정보 강제 병합
    books_categories = [
        {"id": 1, "name": "Book News", "slug": "book-news", "title": "Book News"},
        {"id": 2, "name": "Book Reviews", "slug": "book-reviews", "title": "Book Reviews"},
        {"id": 3, "name": "Biography / Memoir", "slug": "biography-memoir", "title": "Biography / Memoir"},
        {"id": 4, "name": "Romance", "slug": "romance", "title": "Romance"},
        {"id": 5, "name": "Mystery / Thriller", "slug": "mystery-thriller", "title": "Mystery / Thriller"},
        {"id": 6, "name": "Gardening", "slug": "gardening", "title": "Gardening"},
        {"id": 7, "name": "Science Fiction", "slug": "science-fiction", "title": "Science Fiction"},
        {"id": 8, "name": "Fantasy", "slug": "fantasy", "title": "Fantasy"},
        {"id": 9, "name": "History", "slug": "history", "title": "History"},
        {"id": 10, "name": "Cooking", "slug": "cooking", "title": "Cooking"},
        {"id": 11, "name": "Young Adult", "slug": "young-adult", "title": "Young Adult"},
        {"id": 12, "name": "Juvenile", "slug": "juvenile", "title": "Juvenile"},
        {"id": 13, "name": "Sports", "slug": "sports", "title": "Sports"},
        {"id": 14, "name": "Art / Architecture", "slug": "art-architecture", "title": "Art / Architecture"},
        {"id": 15, "name": "Health / Fitness", "slug": "health-fitness", "title": "Health / Fitness"},
        {"id": 16, "name": "Science", "slug": "science", "title": "Science"},
        {"id": 17, "name": "Historical Fiction", "slug": "historical-fiction", "title": "Historical Fiction"},
        {"id": 18, "name": "Poetry", "slug": "poetry", "title": "Poetry"},
        {"id": 19, "name": "Juvenile Fiction", "slug": "juvenile-fiction", "title": "Juvenile Fiction"},
        {"id": 20, "name": "Fiction", "slug": "fiction", "title": "Fiction"},
        {"id": 21, "name": "Political Science", "slug": "political-science", "title": "Political Science"},
        {"id": 22, "name": "Juvenile Nonfiction", "slug": "juvenile-nonfiction", "title": "Juvenile Nonfiction"},
        {"id": 23, "name": "Nature", "slug": "nature", "title": "Nature"},
        {"id": 24, "name": "YA Sci Fi / Fantasy", "slug": "ya-sci-fi-fantasy", "title": "YA Sci Fi / Fantasy"},
        {"id": 25, "name": "Comics / Graphic Novels", "slug": "comics-graphic-novels", "title": "Comics / Graphic Novels"},
        {"id": 26, "name": "YA Romance", "slug": "ya-romance", "title": "YA Romance"},
        {"id": 27, "name": "Humor", "slug": "humor", "title": "Humor"},
        {"id": 28, "name": "Horror", "slug": "horror", "title": "Horror"},
        {"id": 29, "name": "Christian", "slug": "christian", "title": "Christian"},
        {"id": 30, "name": "Religion / Spirituality", "slug": "religion-spirituality", "title": "Religion / Spirituality"},
        {"id": 31, "name": "Nonfiction", "slug": "nonfiction", "title": "Nonfiction"},
        {"id": 32, "name": "Crafts / Hobbies", "slug": "crafts-hobbies", "title": "Crafts / Hobbies"},
        {"id": 33, "name": "Misc", "slug": "misc", "title": "Misc"},
        {"id": 34, "name": "Books", "slug": "books", "title": "Books"},
        {"id": 35, "name": "Authors", "slug": "authors", "title": "Authors"}
    ]
    all_categories["booksnreview"] = books_categories
    total_categories_count += len(books_categories)
    print(f"-> Injected static cache for booksnreview: Added {len(books_categories)} categories.")

    # 5) FoodWorldNews 카테고리 정보 강제 병합
    food_categories = [
        {"id": 1, "name": "Top Stories", "slug": "top-stories", "title": "Top Stories"},
        {"id": 2, "name": "Celebrities", "slug": "celebrities", "title": "Celebrities"},
        {"id": 3, "name": "Safety", "slug": "safety", "title": "Safety"},
        {"id": 4, "name": "Shopping", "slug": "shopping", "title": "Shopping"},
        {"id": 5, "name": "HOW-TO'S", "slug": "how-tos", "title": "HOW-TO'S"},
        {"id": 6, "name": "People In Food", "slug": "people-in-food", "title": "People In Food"},
        {"id": 7, "name": "Celebrity Eats", "slug": "celebrity-eats", "title": "Celebrity Eats"},
        {"id": 8, "name": "Food Recalls", "slug": "food-recalls", "title": "Food Recalls"},
        {"id": 9, "name": "Equipment Recalls", "slug": "equipment-recalls", "title": "Equipment Recalls"},
        {"id": 10, "name": "New Food Items", "slug": "new-food-items", "title": "New Food Items"},
        {"id": 11, "name": "New Cookbooks", "slug": "new-cookbooks", "title": "New Cookbooks"},
        {"id": 12, "name": "Recipe", "slug": "recipe", "title": "Recipe"},
        {"id": 13, "name": "Tips", "slug": "tips", "title": "Tips"}
    ]
    all_categories["foodworldnews"] = food_categories
    total_categories_count += len(food_categories)
    print(f"-> Injected static cache for foodworldnews: Added {len(food_categories)} categories.")
    
    # 4. JSON 파일 저장
    output_data = {
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "sites": all_categories
    }
    
    cache_file_path = "data/categories_cache.json"
    os.makedirs(os.path.dirname(cache_file_path), exist_ok=True)
    
    with open(cache_file_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
        
    print("\n==================================================")
    print(" Synchronization Completed!")
    print(f" - Target File: {cache_file_path}")
    print(f" - Success: {success_count} / {len(sites_config)} sites")
    print(f" - Total Categories Cached: {total_categories_count}")
    print("==================================================")

sync_all_categories = main

if __name__ == "__main__":
    main()
