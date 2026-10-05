import os
import re
import json
import time
import urllib.request
import urllib.parse
import urllib.error
import ssl
import html
from datetime import datetime

# ==============================================================================
# Refactored Imports from core & common packages
# ==============================================================================
from common.logger_setup import get_domain_logger
from common.env_loader import EnvLoader, TelegramNotifier
from core.storage.duplicate_preventer import DuplicatePreventer
from core.generation.article_generator import ArticleGenerator
from core.media.image_searcher import ImageSearcher
from core.publishing.article_publisher import ArticlePublisher
from core.storage.history_archiver import HistoryArchiver

logger = get_domain_logger("general")
def clean_old_generated_articles(directory="data/generated_articles", days=10):
    logger = get_domain_logger("general")
    if not os.path.exists(directory):
        return
    import time
    now = time.time()
    threshold = now - (days * 24 * 3600)
    removed_count = 0
    
    for filename in os.listdir(directory):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(directory, filename)
        try:
            mtime = os.path.getmtime(filepath)
            if mtime < threshold:
                os.remove(filepath)
                removed_count += 1
        except Exception as e:
            logger.warning(f"[Warning] Failed to remove old generated article '{filename}': {e}")
            
    if removed_count > 0:
        logger.info(f"  [Auto Clean] Successfully removed {removed_count} old generated articles (older than {days} days) from {directory}.")

def run_pipeline(source_file_path, target_sites=None, mode="tailored"):
    logger = get_domain_logger("general")
    logger.info("==================================================")
    logger.info(" Starting AI Article Generation & Publishing Pipeline")
    logger.info("==================================================")
    
    # 1. Load configuration and environment
    env = EnvLoader.load_env()
    
    stop_publishing = env.get("STOP_PUBLISHING", "False").strip().lower() in ("true", "1", "yes")
    telegram_copy_mode = False
    
    status_file = "config/status.json"
    if os.path.exists(status_file):
        try:
            with open(status_file, "r", encoding="utf-8") as sf:
                status_data = json.load(sf)
                if status_data.get("STOP_PUBLISHING") is True:
                    stop_publishing = True
                if status_data.get("TELEGRAM_COPY_MODE") is True:
                    telegram_copy_mode = True
        except Exception as e:
            logger.warning(f"[Warning] Failed to read status file {status_file}: {e}")
            
    if stop_publishing:
        logger.warning("[Stop Publishing] STOP_PUBLISHING is active. Skipping the article generation & publishing pipeline.")
        return False
        
    sites = EnvLoader.get_sites_config(env)
    
    if not sites:
        logger.error("[Error] No active sites configured in .env.")
        return False
        
    # If specific targets are requested (for testing), filter them
    if target_sites:
        sites = [s for s in sites if s["domain_key"] in target_sites]
        
    logger.info(f"[Info] Target sites: {', '.join([s['domain_key'] for s in sites])}")
    
    # Read source file
    if not os.path.exists(source_file_path):
        logger.error(f"[Error] Source file not found: {source_file_path}")
        return False
        
    with open(source_file_path, "r", encoding="utf-8") as f:
        source_content = f.read().strip()
        
    if not source_content:
        logger.error("[Error] Source file content is empty.")
        return False

    # Initialize submodules
    generator = ArticleGenerator(env)
    searcher = ImageSearcher(env)
    publisher = ArticlePublisher()
    notifier = TelegramNotifier(env)
    dup_preventer = DuplicatePreventer()
    history_archiver = HistoryArchiver()
    
    any_success = False
    
    # 2. Iterate and process for each target site
    for site in sites:
        logger = get_domain_logger(site["domain_key"])
        logger.info(f"\n[Processing Site] {site['domain_key']} (Index: {site['index']})")
        
        # Ingest API 사용 매체 리스트 (1~8번의 External API 대신 HTTP Basic Auth Ingest API를 사용하는 9~14번 매체)
        INGEST_API_SITES = ["jobsnhire", "franchiseherald", "mobilenapps", "parentherald", "booksnreview", "foodworldnews"]
        LOCAL_ONLY_SITES = [] # 9~14번 매체의 실서버 승격 완료에 따라 로컬 전용 제한 제거

        from datetime import timedelta, timezone
        
        if site["domain_key"] in LOCAL_ONLY_SITES:
            with dup_preventer._lock():
                history = dup_preventer._load_history()
            site_history = history.get(site["domain_key"], [])
            
            kst = timezone(timedelta(hours=9))
            # datetime is imported globally
            today_kst = datetime.now(kst).strftime("%Y-%m-%d")
            
            today_published_count = sum(1 for item in site_history if item.get("date") == today_kst)
            if today_published_count >= 1:
                logger.warning(f"  [Skip Site] Skipping local-only site '{site['domain_key']}' because it already generated {today_published_count} article today KST (Daily Limit: 1).")
                continue
        
        # Get allowed categories for this site
        available_categories = publisher.get_categories_for_site(site["domain_key"])
        if not available_categories:
            logger.warning(f"  [Skip] No category cache found for {site['domain_key']}. Please run sync_categories.py first.")
            continue
            
        # 카테고리 제약조건(연속 방지 및 일일 최대 2개)이 반영된 허용 카테고리 필터링
        allowed_categories = dup_preventer.get_allowed_categories(site["domain_key"], available_categories)
        # 최근 7일 발행 빈도가 적은 카테고리를 앞쪽에 우선 배치하여 다양성 극대화
        allowed_categories = dup_preventer.sort_categories_by_stochastic_priority(site["domain_key"], allowed_categories)
        allowed_slugs = {c["slug"] for c in allowed_categories}
        
        # 확률적 역가중치(Stochastic Balanced Distribution) 기반 추천 타겟 카테고리 추첨
        recommended_category = dup_preventer.get_stochastically_weighted_category(site["domain_key"], allowed_categories)
        
        # [AI 편집실 가드] 14개 매체별 고유 테마 및 활성 카테고리 사전 검증 (Theme 우선 원칙)
        cand_title = site["domain_key"] + " Candidate Article"
        cand_desc = source_content
        cand_url = ""
        
        title_match = re.search(r"Original Title:\s*(.*)", source_content)
        if title_match:
            cand_title = title_match.group(1).strip()
        desc_match = re.search(r"Original Summary:\s*(.*)", source_content)
        if desc_match:
            cand_desc = desc_match.group(1).strip()
        url_match = re.search(r"Reference URL:\s*(.*)", source_content)
        if url_match:
            cand_url = url_match.group(1).strip()
            
        is_forced_bypass = "[SYSTEM_ALERT_FORCE_BYPASS=True]" in source_content
        
        if is_forced_bypass:
            logger.info("  [Forced Bypass Safety Net] Forced Editorial Bypass detected. Skipping pre-validation.")
            eval_res = {
                "suitability": "APPROVED",
                "decision": "CREATE",
                "reason": "Forced editorial bypass activated.",
                "story_id": None,
                "parent_article_id": None
            }
            suitability = eval_res["suitability"]
            decision = eval_res["decision"]
            reason = eval_res["reason"]
        else:
            from core.generation.fact_checker import evaluate_article_suitability
            eval_res = evaluate_article_suitability(
                env.get("GEMINI_API_KEY"),
                cand_title,
                cand_url,
                cand_desc,
                site["domain_key"],
                allowed_slugs
            )
            suitability = eval_res.get("suitability", "APPROVED")
            decision = eval_res.get("decision", "CREATE")
            reason = eval_res.get("reason", "")
        
        if suitability == "REJECT" or decision == "REJECT":
            logger.warning(f"  [Skip Site] Candidate article '{cand_title}' rejected by Editorial Guard: {reason}")
            continue
            
        logger.info(f"  [Editorial Guard APPROVED] Candidate '{cand_title}' suitability decision: {decision}. Reason: {reason}")

        # A. Generate AI Article (with duplicate prevention retry loop)
        logger.info("  Generating AI article content...")
        generated_article = None
        is_crossword = False
        
        # [Crossword Injection Logic]
        import random
        if site["domain_key"] == "boomsbeat" and random.random() < 0.15: # 15% chance
            logger.info("  [Crossword Mode] Generating a Crossword Puzzle instead of a normal article...")
            from core.generation import crossword_generator
            try:
                crossword_themes = ["Technology", "Science", "Space Exploration", "Popular Culture", "Internet History", "Gadgets", "Innovation"]
                chosen_theme = random.choice(crossword_themes)
                generated_article = crossword_generator.create_crossword_article(chosen_theme)
                if generated_article:
                    generated_article["search_keyword"] = "crossword puzzle abstract"
                    is_crossword = True
                    if allowed_categories:
                        generated_article["selected_category"] = random.choice(allowed_categories)["slug"]
            except Exception as e:
                logger.error(f"  [Crossword Error] Failed to generate crossword: {e}")
                
        max_retries = 3
        current_source_content = source_content
        
        if is_crossword and generated_article:
            logger.info(f"   [Gen SUCCESS] Crossword Title: '{generated_article.get('title')}'")
        else:
            for attempt in range(1, max_retries + 1):
                try:
                    # 필터링된 allowed_categories 를 전달하여 AI가 적절한 카테고리만 고르도록 강제
                    generated_article = generator.generate(
                        current_source_content,
                        site["domain_key"],
                        allowed_categories,
                        recommended_category=recommended_category
                    )
                    title = generated_article.get("title", "")
                    selected_cat = generated_article.get("selected_category", "")
                
                    # Check for duplicate title
                    is_dup_title = dup_preventer.is_duplicate(title, site["domain_key"])
                    
                    # Check for invalid category (LLM hallucinated or selected a restricted category)
                    is_invalid_cat = selected_cat not in allowed_slugs
                    
                    if is_dup_title or is_invalid_cat:
                        if is_dup_title:
                            logger.warning(f"   [Duplicate Warning - Attempt {attempt}/{max_retries}] Title '{title}' already similar to past posts.")
                        if is_invalid_cat:
                            logger.info(f"   [Category Restriction Warning - Attempt {attempt}/{max_retries}] Selected category '{selected_cat}' is not in allowed slugs.")
                            
                        if attempt < max_retries:
                            allowed_slugs_str = ", ".join([f"'{s}'" for s in allowed_slugs])
                            current_source_content = (
                                f"[IMPORTANT SYSTEM CONSTRAINTS FOR RETRY]\n"
                                f"- The previous news source content has been discarded entirely to avoid duplication.\n"
                                f"- You MUST write a completely new, factual news wire report on a different topic matching the site's theme ({site['domain_key']}).\n"
                                f"- Do NOT write about: '{title}'.\n"
                                f"- Do NOT use the category: '{selected_cat}'. You MUST select a category slug only from: [{allowed_slugs_str}].\n"
                                f"- Write the article based strictly on this new topic you choose, ensuring it is a single coherent topic and concludes with a clear ending."
                            )
                            continue
                    
                    # POST-VALIDATION: 1. 테마/카테고리 사후 검증 (Verify Theme & Differentiated Rewrite)
                    if "[SYSTEM_ALERT_REUSED_SEED=True]" in current_source_content and not is_forced_bypass:
                        from core.generation.fact_checker import verify_article_differentiated_rewrite
                        eval_res = verify_article_differentiated_rewrite(
                            env.get("GEMINI_API_KEY"),
                            generated_article.get("content", ""),
                            site["domain_key"],
                            selected_cat
                        )
                        if not eval_res.get("passed", True):
                            logger.warning(f"   [Post-Validation Failed - Attempt {attempt}/{max_retries}] Article failed theme rewrite test. Reason: {eval_res.get('reason')}")
                            if attempt < max_retries:
                                current_source_content = (
                                    f"[IMPORTANT SYSTEM CONSTRAINTS FOR RETRY]\n"
                                    f"- The previous generation was rejected because it did not differentiate from other sites. It was a plain summary.\n"
                                    f"- You MUST strictly rewrite this news around the target theme of '{site['domain_key'].upper()}' and category '{selected_cat}'. Create a highly unique narrative angle.\n"
                                    f"[SYSTEM_ALERT_REUSED_SEED=True]\n"
                                    f"Original Source:\n{source_content}"
                                )
                                continue
                            else:
                                generated_article = None
                                break

                    # POST-VALIDATION: 2. 최종 팩트 체크 검증
                    if is_forced_bypass:
                        is_valid_facts = True
                        logger.info("   [Forced Bypass Safety Net] Skipping fact-check validation.")
                    else:
                        from core.generation.fact_checker import verify_article_facts
                        content_to_check = generated_article.get("content", "")
                        is_valid_facts = verify_article_facts(env.get("GEMINI_API_KEY"), current_source_content, content_to_check, site["domain_key"])
                    
                    if not is_valid_facts:
                        logger.warning(f"   [Fact Check Failed - Attempt {attempt}/{max_retries}] Article distorted facts or hallucinated. Discarding...")
                        if attempt < max_retries:
                            current_source_content = (
                                f"[IMPORTANT SYSTEM CONSTRAINTS FOR RETRY]\n"
                                f"- The previous generation was rejected because it failed the strict fact-check (it introduced fabricated numbers, names, or distorted the event).\n"
                                  f"- You MUST write the article strictly based on the following original text without fabricating any facts to artificially fit the theme.\n"
                                f"Original Source:\n{source_content}"
                            )
                            # 만약 중복 시드 상태였다면 메타헤더도 복원 주입
                            if "[SYSTEM_ALERT_REUSED_SEED=True]" in source_content:
                                current_source_content = f"[SYSTEM_ALERT_REUSED_SEED=True]\n{current_source_content}"
                            continue
                        else:
                            generated_article = None
                            break
                            
                    logger.info(f"   [Gen SUCCESS] Title: '{title}'")
                    logger.info(f"   [Gen SUCCESS] Category Selected: '{selected_cat}'")
                    break
                except Exception as e:
                    logger.info(f"  [Gen Attempt {attempt} FAILED] Error: {e}")
                    if attempt == max_retries:
                        break
                        
        # 최종적으로 검증 통과했는지 체크
        if not generated_article:
            logger.warning(f"  [Skip Site] Skipping {site['domain_key']} due to generation failure after {max_retries} attempts.")
            continue
            
        final_title = generated_article.get("title", "")
        final_cat = generated_article.get("selected_category", "")
        if dup_preventer.is_duplicate(final_title, site["domain_key"]) or final_cat not in allowed_slugs:
            logger.warning(f"  [Skip Site] Skipping {site['domain_key']} due to unresolved duplicate titles or restricted categories after {max_retries} attempts.")
            continue
            
        # Extract Reference URL from source content if present
        source_rss_link = None
        match = re.search(r"Reference URL:\s*(https?://\S+)", source_content)
        if match:
            source_rss_link = match.group(1).strip()
            logger.info(f"   [Source RSS Link Extracted] {source_rss_link}")
            
        # B. Search Associated Image (with duplicate check filter & cascade queries)
        image_queries = generated_article.get("image_search_queries") or generated_article.get("search_keyword", "technology")
        exclude_img_urls = dup_preventer.get_recent_image_urls(site["domain_key"])
        img_data = searcher.search_image(
            image_queries,
            exclude_urls=exclude_img_urls,
            site_domain=site["domain_key"],
            article_summary=generated_article.get("summary", ""),
            article_title=generated_article.get("title", "")
        )
        logger.info(f"   [Image Found] URL: {img_data['url']} (Credit: {img_data['credit']})")
        
        # C. Publish Article (with Telegram Copy Mode Bypass check)
        if telegram_copy_mode:
            logger.info(f"   [Bypass API] TELEGRAM_COPY_MODE is active. Bypassing API publication for {site['domain_key']}.")
            # Generate a mock successful response with time-based ID
            mock_id = int(time.time()) + site["index"]
            pub_response = {
                "article_id": mock_id,
                "a_id": mock_id,
                "url": "https://telegram.copy.mode/bypass",
                "cms_url": "https://telegram.copy.mode/bypass",
                "status": "bypass"
            }
            err = None
        elif site["domain_key"] in INGEST_API_SITES:
            # Ingest API를 통해 기사를 원격 CMS 큐에 직접 송출합니다.
            pub_response, err = publisher.publish_to_ingest_api(
                site["domain_key"], generated_article, img_data, rss_link=source_rss_link
            )
            # Response 호환성 맞추기: Ingest API는 'a_id'와 'cms_url'을 반환하므로, 기존 article_id 및 url 파라미터로 매핑
            if err is None and pub_response:
                pub_response["article_id"] = pub_response.get("a_id")
                pub_response["url"] = pub_response.get("cms_url")
        else:
            pub_response, err = publisher.publish(site, generated_article, img_data)
        
        # D. Publish State Machine & Lineage 바인딩
        story_id = eval_res.get("story_id")
        parent_article_id = eval_res.get("parent_article_id")
        decision_type = eval_res.get("decision", "CREATE")

        if err is None:
            any_success = True
            logger.info(f"   [Publish SUCCESS] 어드민 등록 완료! Article ID: {pub_response.get('article_id')}")
            logger.info(f"   [Publish SUCCESS] status: {pub_response.get('status')}")
            logger.info(f"   [Publish SUCCESS] URL: {pub_response.get('url')}")
            
            # Archive generated article
            archive_data = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "site": site["domain_key"],
                "article_id": pub_response.get("article_id"),
                "status": "published",
                "url": pub_response.get("url"),
                "generated": generated_article,
                "image_url": img_data["url"],
                "image_credit": img_data["credit"],
                "story_id": story_id,
                "parent_article_id": parent_article_id,
                "article_type": decision_type
            }
            
            if site["domain_key"] in LOCAL_ONLY_SITES:
                archive_dir = "data/local_articles/unused"
            else:
                archive_dir = "data/generated_articles"
            os.makedirs(archive_dir, exist_ok=True)
            archive_file = os.path.join(archive_dir, f"{site['domain_key']}_{pub_response.get('article_id')}.json")
            
            with open(archive_file, "w", encoding="utf-8") as af:
                json.dump(archive_data, af, indent=2, ensure_ascii=False)
                
            logger.info(f"   [Archive Cached] Saved to {archive_file}")
            
            # Add to duplicate prevention history
            dup_preventer.add_to_history(
                generated_article["title"],
                site["domain_key"],
                generated_article["selected_category"],
                image_url=img_data.get("url"),
                rss_link=source_rss_link
            )
            
            # [이력 누적] 90일 보관 및 1:N Content/Publication 분리 저장 시스템 연동 (성공 케이스)
            try:
                article_hash = history_archiver.make_article_hash(generated_article.get("content", ""))
                content_payload = {
                    "article_id": str(pub_response.get("article_id")),
                    "headline": generated_article.get("title", ""),
                    "image_url": img_data.get("url"),
                    "seed_url": source_rss_link if source_rss_link else "",
                    "source_urls": [source_rss_link] if source_rss_link else [],
                    "fact_check_urls": [],
                    "article_hash": article_hash,
                    "category": generated_article.get("selected_category", ""),
                    "created_at": datetime.now().isoformat(),
                    "story_id": story_id,
                    "parent_article_id": parent_article_id,
                    "article_type": decision_type
                }
                
                history_archiver.save_content(content_payload)
                
                pub_payload = {
                    "article_id": str(pub_response.get("article_id")),
                    "site_id": site["domain_key"],
                    "status": "published",
                    "published_at": datetime.now().isoformat(),
                    "published_url": pub_response.get("url"),
                    "retry_count": 0,
                    "mode": mode,
                    "error": None
                }
                
                history_archiver.save_publication(pub_payload)
                history_archiver.clean_expired_archives()
                logger.info(f"   [HistoryArchiver] Successfully saved Content & Publication to 90-day archive.")
            except Exception as arch_ex:
                logger.error(f"   [HistoryArchiver-Error] Failed to save 90-day archive: {arch_ex}")
            
            # Send Telegram Success Notification
            pub_title = generated_article.get("title", "")
            pub_category = generated_article.get("selected_category", "")
            
            if telegram_copy_mode:
                pub_summary = generated_article.get("summary", "")
                pub_tags = generated_article.get("seo_tags", "")
                header_title = "[텔레그램 수동 복사 기사]"
                # 1. 정보(메타데이터) 메시지 전송
                meta_msg = (
                    f"<b>{header_title}</b>\n\n"
                    f"<b>■ 사이트명</b>\n"
                    f"<pre>{site['domain_key']}</pre>\n\n\n"
                    f"<b>■ Title</b>\n"
                    f"<pre>{pub_title}</pre>\n\n\n"
                    f"<b>■ CMS URL</b>\n"
                    f"<pre>{pub_response.get('url')}</pre>\n\n\n"
                    f"<b>■ Summary</b>\n"
                    f"<pre>{pub_summary}</pre>\n\n\n"
                    f"<b>■ 카테고리 (Category)</b>\n"
                    f"<pre>{pub_category}</pre>\n\n\n"
                    f"<b>■ 태그 (SEO Tags)</b>\n"
                    f"<pre>{pub_tags}</pre>"
                )
                notifier.send_notification(meta_msg)
                
                # 2. 본문(HTML Content) 메시지 분할 전송 (수동 복사 모드일 때만 본문 메시지 발송)
                if telegram_copy_mode:
                    raw_content = generated_article.get("content", "")
                    escaped_content = html.escape(raw_content)
                    
                    # 3800자 단위로 나누어 태그 깨짐 없이 텔레그램으로 송출
                    chunk_size = 3800
                    content_chunks = [escaped_content[i:i+chunk_size] for i in range(0, len(escaped_content), chunk_size)]
                    
                    for idx, chunk in enumerate(content_chunks):
                        part_info = f" (Part {idx+1}/{len(content_chunks)})" if len(content_chunks) > 1 else ""
                        content_msg = (
                            f"<b>[수동 복사 본문]{part_info}</b>\n\n"
                            f"<pre><code>{chunk}</code></pre>"
                        )
                        notifier.send_notification(content_msg)
            else:
                tg_msg = (
                    f"<b>[송출 성공]</b>\n"
                    f"• 사이트명: {site['domain_key']}\n"
                    f"• 기사명: {pub_title}\n"
                    f"• 카테고리: {pub_category}"
                )
                notifier.send_notification(tg_msg)
        else:
            logger.info(f"   [Publish FAILED] Error: {err}")
            
            # [이력 누적] 90일 보관 및 1:N Content/Publication 분리 저장 시스템 연동 (실패 케이스)
            try:
                article_hash = history_archiver.make_article_hash(generated_article.get("content", ""))
                import random
                failed_mock_id = f"fail_{int(time.time())}_{random.randint(1,999)}"
                content_payload = {
                    "article_id": failed_mock_id,
                    "headline": generated_article.get("title", ""),
                    "image_url": img_data.get("url"),
                    "seed_url": source_rss_link if source_rss_link else "",
                    "source_urls": [source_rss_link] if source_rss_link else [],
                    "fact_check_urls": [],
                    "article_hash": article_hash,
                    "category": generated_article.get("selected_category", ""),
                    "created_at": datetime.now().isoformat(),
                    "story_id": story_id,
                    "parent_article_id": parent_article_id,
                    "article_type": decision_type
                }
                
                history_archiver.save_content(content_payload)
                
                pub_payload = {
                    "article_id": failed_mock_id,
                    "site_id": site["domain_key"],
                    "status": "publish_failed",
                    "published_at": datetime.now().isoformat(),
                    "published_url": None,
                    "retry_count": 3,
                    "mode": mode,
                    "error": str(err)
                }
                
                history_archiver.save_publication(pub_payload)
                logger.info(f"   [HistoryArchiver] Successfully recorded FAILED status to 90-day archive.")
            except Exception as arch_ex:
                logger.error(f"   [HistoryArchiver-Error] Failed to save 90-day failed archive: {arch_ex}")
            
            # Send Telegram Failure Notification
            pub_title = generated_article.get("title") if 'generated_article' in locals() else "N/A"
            pub_category = generated_article.get("selected_category") if 'generated_article' in locals() else "N/A"
            tg_msg = (
                f"<b>[송출 실패]</b>\n"
                f"• 사이트명: {site['domain_key']}\n"
                f"• 기사명: {pub_title}\n"
                f"• 카테고리: {pub_category}\n"
                f"• 에러: <code>{err}</code>"
            )
            notifier.send_notification(tg_msg)
            
    # 10일 지난 송출 완료 기사 캐시 자동 청소 실행
    clean_old_generated_articles(directory="data/generated_articles", days=10)

    logger.info("\n==================================================")
    logger.info(" Pipeline execution finished!")
    logger.info("==================================================")
    return any_success

if __name__ == "__main__":
    # Test script runner fallback
    import sys
    source = "data/article_sources/sample_source.txt"
    targets = None
    
    # Allow passing arguments (e.g. python3 main.py <source_path> <site_domain>)
    if len(sys.argv) > 1:
        source = sys.argv[1]
    if len(sys.argv) > 2:
        targets = [sys.argv[2]]
        
    run_pipeline(source, targets)
