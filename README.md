# AI 기사 작성 및 송출 시스템 - 초기 셋업 명세서

이 프로젝트는 AI를 통해 자동으로 기사를 생성하고, 외부 사이트의 어드민 API([external_articles_api.md](file:///home/stock_trading_bot/external_articles_api.md))를 호출하여 초안(Draft) 형태로 기사를 송출하는 시스템의 뼈대입니다.

---

## 1. 프로젝트 디렉토리 구조

```text
/home/stock_trading_bot
├── config/                      # 설정 및 템플릿 폴더
│   ├── settings.json            # 일반 실행 및 AI 모델 설정
│   └── prompt_templates.json    # AI 프롬프트 템플릿
├── data/                        # 데이터 캐시 및 생성 아카이브 폴더
│   ├── categories_cache.json    # 어드민 카테고리 캐시 목록
│   ├── article_sources/         # AI 기사 생성에 사용될 원본 소스 데이터 보관 폴더
│   └── generated_articles/      # AI가 생성 및 송출에 성공한 기사 기록 보관 폴더
├── logs/                        # 시스템 로그 폴더
│   └── app.log                  # 애플리케이션 실행 및 API 통신 오류 기록
├── .env.template                # 보안이 필요한 민감 설정 환경변수 템플릿
├── @MODIFICATION_LOG.md         # 프로젝트 코드 변경 이력 로그
└── README.md                    # 이 구조 설계서 및 가이드
```

---

## 2. 각 파일의 역할 및 데이터 스펙

### 2.1 `.env.template` (환경변수 설정 템플릿)
* **역할**: 외부 유출을 방지해야 하는 민감한 API Key 및 접속 경로를 설정하기 위한 템플릿입니다. 이 파일을 복사하여 `.env` 파일을 생성한 뒤 실제 키 값을 기입하여 사용하십시오.
* **주요 데이터 필드**:
  - `ARTICLES_API_BASE_URL`: 기사를 송출할 사이트의 어드민 API 주소입니다. (예: `https://admin.boomsbeat.com/api/v1/`)
  - `ARTICLES_API_KEY`: 어드민으로부터 발급받은 기사 등록 전용 X-API-Key 값입니다.
  - `OPENAI_API_KEY` / `GEMINI_API_KEY`: AI 기사 생성 시 사용할 LLM 서비스의 인증 토큰입니다.

### 2.2 `config/settings.json` (일반 설정 파일)
* **역할**: 보안이 필요하지 않으면서 프로그램 실행 시 동적으로 참고해야 하는 일반적인 옵션과 AI 생성 매개변수를 담고 있습니다.
* **주요 데이터 필드**:
  - `system.environment`: 실행 모드 (`development` / `production`)
  - `ai_model.provider`: 사용할 AI 서비스 제공자 (`gemini` / `openai` 등)
  - `ai_model.model_name`: 사용할 구체적인 LLM 모델 명칭 (예: `gemini-1.5-pro`, `gpt-4o`)
  - `ai_model.temperature`: AI 답변의 다양성 수준 조절 (기본값: `0.7`)
  - `scheduler.interval_minutes`: 기사 수집 및 작성 배치가 작동할 주기 분 단위 설정
  - `api_options`: API 연결 제한 초과(Rate Limit) 대처를 위한 재시도 횟수 및 딜레이 팩터

### 2.3 `config/prompt_templates.json` (AI 프롬프트 템플릿)
* **역할**: AI에게 줄 행동 지침, 기사 포맷 가이드라인, 제약 조건을 체계적으로 관리합니다.
* **주요 데이터 필드**:
  - `system_instruction`: AI에게 부여할 역할론 정의 (예: *"IT 전문 기자로서 글을 작성하십시오."*)
  - `format_rules`: 본문 기사의 마크업 제한 (예: *HTML `<p>`와 `<h2>` 사용*, *`<script>` 태그 차단*) 및 표현 톤 지정
  - `structure`: AI가 반환해야 하는 JSON 아웃풋 구조에 대한 가이드라인 (기사 제목, 요약, HTML 본문)

### 2.4 `data/categories_cache.json` (카테고리 캐시)
* **역할**: 송출 어드민 API가 허용하는 카테고리 슬러그 목록(`GET /api/v1/categories.json`)의 최신 캐시를 로컬에 보관하여, 기사를 송출할 때마다 API를 매번 중복 호출하지 않도록 방지합니다.
* **주요 데이터 필드**:
  - `site`: 대상 사이트 명칭
  - `updated_at`: 마지막으로 캐시를 업데이트한 시각 (ISO 8601 포맷)
  - `categories`: `id`, `slug`, `title`, `parent` 구조로 정렬된 카테고리 정보 배열

### 2.5 `data/article_sources/` (소스 데이터 디렉토리)
* **역할**: AI가 기사를 쓰기 위해 읽을 수집 원문 데이터들을 임시 혹은 영구 보관하는 폴더입니다.
* **추천 데이터 형식**: 크롤링한 원문 뉴스 데이터나 트렌드 분석용 JSON/텍스트 파일이 위치합니다.

### 2.6 `data/generated_articles/` (기사 아카이브 디렉토리)
* **역할**: AI가 작성을 마치고 API를 통해 최종적으로 송출(Draft)까지 마친 기사의 원본 결과물을 백업하는 아카이브 폴더입니다.
* **저장 데이터 구성**:
  - 생성된 기사 제목(`title`), 본문 HTML(`content`), 적용된 카테고리(`categories`), 썸네일 파일 경로 혹은 URL, 그리고 송출 성공 후 API가 응답한 `article_id` 및 송출 완료 일시.

---

## 3. 프로그램 개발 시 권장 작업 흐름

1. **설정 세팅**: `.env.template`을 바탕으로 `.env` 파일을 만들고 API 키를 채웁니다.
2. **카테고리 동기화**: `GET /api/v1/categories.json` API를 호출하여 받아온 결과를 `data/categories_cache.json`에 캐시 처리합니다.
3. **소스 로드 & AI 호출**: `data/article_sources/`에 소스를 로드하고 `config/`에 정의된 모델 및 프롬프트를 사용하여 AI 기사를 구성합니다.
4. **기사 송출**: `POST /api/v1/articles.php`를 활용해 기사를 송출한 뒤, 리턴된 `article_id`와 기사 본문을 `data/generated_articles/`에 영구 기록합니다.
