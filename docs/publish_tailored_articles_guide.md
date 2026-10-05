# publish_tailored_articles.py (테마별 정기 기사) 목적 및 워크플로우 가이드

본 문서는 매일 크론탭 스케줄러를 통해 랜덤한 시간대에 자동 기동되는 **테마별 정기 기사 수집·생성·송출 코어 엔진**인 [`publish_tailored_articles.py`](file:///home/stock_trading_bot/publish_tailored_articles.py)의 개발 목적과 내부 구동 메커니즘을 상세히 정리한 공식 개발 문서입니다.

---

## 1. 개요 및 목적 (Purpose)

### 1) 매체 고유 아이덴티티 보호
14개 송출 매체는 각각 전용 오디언스와 에디토리얼 테마(Theme)를 가집니다. 동일 기사를 제목만 바꾸어 기계적으로 복제 송출(Replication)하는 행위를 원천 배제하고, 매체별 타겟 독자에게 진정으로 가치 있는 맞춤형 앵글의 기사만을 생산 및 제공하는 것이 핵심 목적입니다.

### 2) 동적 크론 스케줄링 (Anti-Bot Detection)
매일 동일한 정각 시간에 기사가 대량으로 올라올 경우 포털 및 유저에게 자동화 봇(Bot)으로 탐지될 우려가 있습니다. 이를 방지하기 위해 매 실행이 완료될 때마다 다음 날 기동할 크론 시간대를 무작위(UTC 13시~22시 사이의 무작위 분/시)로 크론탭에 동적 갱신 기재하여 불규칙한 사람의 발행 패턴을 자연스럽게 모사합니다.

### 3) 14개 매체 병렬 독립 처리
각 사이트를 동시 기동하여 병렬 통신 처리 속도를 최적화하는 동시에, 특정 매체 통신 장애가 타 매체에 영향을 미치지 않도록 스레딩(`threading.Thread`) 기법으로 완전 격리 처리합니다.

---

## 2. 핵심 아키텍처 및 워크플로우 (Workflow)

```mermaid
graph TD
    A[크론탭 스케줄러 자동 기동] --> B{STOP_PUBLISHING 플래그 검사}
    B -- True -- > C[즉시 안전 종료]
    B -- False --> D[14개 매체별 전용 스레드 스폰 및 백그라운드 지연 실행]
    D --> E[무작위 지연 대기 30초~45분 수행]
    E --> F[RSS 피드 수집 및 글로벌/로컬 중복 URL 필터링]
    F --> G{사용 가능한 RSS 시드가 존재하는가?}
    G -- Yes --> H[최신 RSS 시드 기사 선정]
    G -- No --> I[Gemini 활용 매체 테마에 맞춘 가상 Source Draft 자동 생성]
    H --> J[run_pipeline 위임 및 7대 기사 유형 및 AI 편집실 가드 검증]
    I --> J
    J --> K{AI 편집실 가드 통과 및 APPROVED 판정?}
    K -- Approved -- > L[어드민 API / Ingest API로 기사 최종 송출 완료]
    K -- Reject -- > M[차순위 시드로 Fallback 혹은 스킵]
    L --> N[다음 날 런을 위한 크론탭 무작위 시간대 업데이트 및 종료]
    M --> N
```

---

## 3. 세부 단계별 구동 프로세스

### STEP 1 — 동적 딜레이 실행 (Randomized Delay)
* 크론탭 기동 직후 14개 매체 스레드는 즉시 실행을 개시하지 않고, `random.randint(30, 2700)` 초(30초에서 45분) 동안 개별적으로 무작위 지연(time.sleep)을 수행합니다.
* 이는 14개 사이트 기사 송출의 시간 간격을 자연스럽게 떨어뜨려 불규칙한 분산 발행을 가능하게 하고, 어드민 서버의 순간 CPU/네트워크 부하 경합을 방지합니다.

### STEP 2 — 1차 소스 입수 (RSS Feed)
* 지정된 매체별 RSS 피드 리스트([`config/rss_feeds.json`](file:///home/stock_trading_bot/config/rss_feeds.json))로부터 최신 와이어 기사를 수집합니다.
* 이때 **글로벌 중복 필터링**(`DuplicatePreventer`)이 개입하여, 해당 시드 기사 링크가 최근 90일 내에 본 매체 혹은 타 매체군에서 이미 2개 이상 발행된 시드일 경우 강력하게 배제 처리하여 중복 수집을 원천 차단합니다.

### STEP 3 — 2차 소스 입수 (Gemini Fallback Generation)
* 만약 수집된 최신 RSS 피드가 모두 중복으로 배제되었거나, 외부 RSS 서버가 닫혀 입수가 불가한 경우 자동 Fallback 메커니즘이 기동됩니다.
* 이 단계에서 Gemini를 활용해 매체 고유 테마 가이드라인(`DOMAINS_THEME`)에 100% 맞춤화된 고유 가상 소스 텍스트(Source Draft)를 실시간 자동 생성하여 기사 재료로 공급합니다.

### STEP 4 — AI 편집실 가드 집행 (`run_pipeline`)
* 확보된 소스 텍스트를 기사 생성 파이프라인의 입구인 `run_pipeline`으로 위임하여 처리를 이식합니다.
* 이때 [`fact_checker.py`](file:///home/stock_trading_bot/fact_checker.py)의 **AI 편집실 가드**가 개입하여, 테마 우선 원칙을 위배하거나 24대 판정 규칙을 통과하지 못해 `REJECT` 판정이 난 후보는 즉각 탈락(Skip)시키고 통과된 정합 기사만 송출을 허가합니다.

### STEP 5 — 최종 송출 (Publish & Ingest API)
* **1~8번 매체**: 일반 `multipart/form-data` 스펙을 통해 기사 본문과 썸네일 바이너리 데이터를 직접 어드민으로 포스트(POST) 전송합니다.
* **9~14번 매체**: 고밀도 `Ingest API`를 호출하여 어드민에 JSON 데이터 형식으로 전송합니다. 
  - 이때 새로 탑재된 **기자명 맵핑 알고리즘**이 개입하여, 어드민 기자 풀 중 지정된 고유 기자(예: `Ed Stoddard`, `Ana Albiad` 등 매체별 2인)를 실시간 1:1 대조해 100% 정상적이고 고정된 리포터 ID로 강제 전송되도록 주입합니다.

### STEP 6 — 스케줄러 동적 업데이트
* 14개 매체 전송 스레드가 모두 종료되는 즉시 메인 프로세스는 시스템의 크론탭 스케줄 파일(`crontab -`)을 열어 `publish_tailored_articles.py` 의 예약 실행 시간대(`rand_minute rand_hour * * *`)를 불규칙한 다음 날 랜덤 시간대로 자동 치환한 뒤 안전하게 프로세스를 마칩니다.

---
> **주의**: 긴급 점검 등으로 기사 자동 생성을 중지해야 하는 경우, [`.env`](file:///home/stock_trading_bot/.env) 파일의 `STOP_PUBLISHING=True`를 마킹하거나 [`config/status.json`](file:///home/stock_trading_bot/config/status.json)에 `{"STOP_PUBLISHING": true}`를 기재해 두면 모든 동작이 즉각 우회 및 스킵 처리됩니다.
