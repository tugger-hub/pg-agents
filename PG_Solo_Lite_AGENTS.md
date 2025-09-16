# PG Solo‑Lite Agents 설계 명세서(최소 복잡도, 1인 운영)

## 1. 목적 및 범위
- 목적: 1인 개발자가 소규모(1–5명)로 안정적으로 운영할 수 있는 최소 복잡도 자동매매 시스템 정의
- 범위: 단일 프로세스(필요 시 단일 컨테이너) Python 서비스 + PostgreSQL(단일 인스턴스). 외부 브로커는 `ccxt`로 추상화
- 제외: Django/DRF, Celery, RabbitMQ, TimescaleDB, Prometheus/Grafana/Loki(관측 스택), 복잡한 대시보드. 대신 텔레그램 알림 + 간단한 CLI/옵션형 경량 HTTP만 사용

## 2. 핵심 원칙(보안/확장성/속도/운영/복잡성 최소)
1) 보안: 시크릿은 환경 변수, 최소 권한 DB 롤, PII 저장 최소화, 구조화 로그에 민감정보 마스킹
2) 확장성: 초기에는 수직 확장(단일 프로세스 멀티 태스크) → 필요 시에만 큐/워커 분리(옵션)
3) 성능: 필수 인덱스만, 배치 I/O, 연결 재사용, 멱등 처리로 재시도 비용 최소화
4) 1인 개발 친화: 단일 리포지토리, 저의존성, 읽기 쉬운 구조, 자동화된 테스트/포맷터
5) 소규모 운영: docker-compose 또는 systemd로 간단 가동/중지, 일 1회 백업, 텔레그램 알림
6) 복잡성 최소: 필요한 것만 채택, 고급 기능은 모두 Opt‑in

## 3. 전체 아키텍처(요약)
```
[pg-solo-lite (Python, 단일 프로세스)]
├─ Scheduler (주기 실행; asyncio/apscheduler)
├─ Agents
│  ├─ Ingestion → 시장 데이터 수집(필요 시 분봉 저장)
│  ├─ Strategy  → 신호 산출(경량 지표 계산)
│  ├─ Execution → 주문 제출(멱등/정규화)
│  ├─ Risk      → 포지션 모니터링/청산 규칙
│  └─ Report    → 일일/주간 성과 요약
├─ Notify Worker → DB 아웃박스 → Telegram
└─ (선택) 경량 HTTP API(FastAPI) / CLI

[PostgreSQL Solo‑Lite]
├─ Core/Trading 테이블 + Alert 아웃박스
└─ 최소 인덱스 & 트리거(append‑only, 정규화)
```

- 이벤트 버스/브로커 없음: 에이전트 간 전달은 메모리(함수 호출/Queue) 또는 DB 상태 폴링으로 대체
- 관측: 파일/STDOUT 로그 + 간단한 카운터 로그(예: 처리 건수)

## 4. 최소 Tech Stack
- **Python 3.11+**, `httpx`, `ccxt`, `pydantic`, `sqlalchemy`(또는 `psycopg`), `apscheduler`(또는 `asyncio`), `python-telegram-bot`
- **옵션**: FastAPI(경량 API), Alembic(DB 마이그레이션), `pandas`/`pandas-ta`(간단 지표)

## 5. 에이전트 카탈로그(경량화)
### 5.1 IngestionAgent
- **역할:** 브로커 API에서 필요한 심볼의 최신 캔들/틱 요약을 **저부하 주기**(예: 1m)로 가져온다.
- **입력:** 심볼 목록, 기간 설정
- **출력:** 메모리 내 `MarketSnapshot` 또는 최소 `candles` 테이블(분봉) 업데이트
- **정책:** 실패 시 지수 백오프. 과도한 과거데이터 적재 금지(최근 N개 윈도우만).

### 5.2 StrategyAgent
- **역할:** 최근 스냅샷/분봉으로 단순 규칙(RSI/EMA 교차 등)을 계산, `TradingDecision` 생성.
- **입력:** `MarketSnapshot`/`candles`
- **출력:** `TradingDecision(symbol, action, sl/tp, confidence)`
- **정책:** **신뢰도 임계치** 미만은 폐기. 계산 비용이 큰 지표는 캐시/윈도우 업데이트.

### 5.3 ExecutionAgent
- **역할:** `TradingDecision`을 멱등키와 함께 주문으로 변환해 제출, DB에 기록.
- **정책(핵심):** 가격/수량 정규화 및 최소 주문 금액 검증, 활성 상태 부분 유니크 인덱스로 중복 차단, 거래 원장은 append‑only. 자세한 DB 제약/트리거는 “Solo‑Lite DB 설계”를 따른다. 

### 5.4 RiskAgent
- **역할:** 활성 포지션을 주기 점검하여 트레일링 스탑/부분익절/손절을 집행.
- **정책:** 모든 리스크 액션은 DB에 원자적으로 기록 후 실행. 중요 이벤트는 텔레그램 큐에 등록.

### 5.5 ReportAgent
- **역할:** 일일/주간 성과(수익률, 승률 등) 요약 생성, 알림으로 링크 전송.
- **정책:** 생성 시점 스냅샷 보존(재현성).

## 6. 실행/오케스트레이션 모델(브로커 없는 설계)
- **스케줄러:** `apscheduler` 또는 `asyncio.create_task`로 각 에이전트 루프 실행.
- **데이터 전달:** 메모리 큐(`asyncio.Queue`) 또는 DB 상태 기반 폴링(간단).
- **백오프 & 멱등:** 모든 외부 호출은 재시도 시 멱등키 사용. 주문/알림은 DB 레벨에서 중복 방지.

## 7. 데이터베이스 설계(요약 · Solo‑Lite 우선)
> 세부 스키마/트리거/인덱스/함수는 `PG_Solo_Lite_Design_DB_v2.0.md` 문서를 우선 참조합니다.

- **Core:** `users`, `api_keys`, `exchanges`, `instruments`, `exchange_instruments(trading_rules JSONB)`
- **Trading:** `orders(idempotency_key + 활성 상태 부분 유니크)`, `executions`, `positions`, `transactions(append‑only 트리거로 갱신/삭제 차단)`
- **Rules/정규화:** `normalize_price/size`, `meets_min_notional` 트리거로 사전 검증
- **Alerts:** `telegram_chats(min_severity)`, `notification_outbox(dedupe_key 유니크, 상태/재시도 필드)`, `enqueue_notification()`
- **성능 인덱스(최소):** `orders(idempotency_key WHERE status IN ...)`, `orders(exchange_order_id WHERE ...)`, `notification_outbox(status, created_at)`
- **운영:** 아웃박스 워커는 `SELECT ... FOR UPDATE SKIP LOCKED`로 안전 집계. 봇 토큰은 환경 변수로만 관리 

## 8. 설정 및 환경 변수(예시)
- `DATABASE_URL`, `BROKER_API_KEY/SECRET`, `TELEGRAM_BOT_TOKEN`, `APP_ENV`, `DB_POOL_SIZE`, 전략 파라미터(기본 위험 %, 지표 기간 등). **토큰/시크릿은 파일/DB 저장 금지.** 

## 9. 운영 Runbook(소규모)
1. **가동/중지:** `docker-compose up -d` 또는 `systemd` 서비스 1개.
2. **알림:** 운영자 텔레그램 chat_id 등록 → 아웃박스 워커 상시 실행.
3. **백업:** 일 1회 전체 백업 + WAL 보관. 장애 시 PENDING 알림은 재전송 허용(멱등). 
4. **장애 대처:** 외부 API 장애 시 백오프, 내부 예외는 알림(WARN/CRITICAL).

## 10. 보안 지침
- **DB 권한 분리:** 앱/워커 역할 분리, 아웃박스 워커는 필요한 최소 권한만.
- **네트워크:** DB 접근 IP 제한, 브로커 API 키 출금권한/화이트리스트 적용.
- **로그:** 구조화(JSON) + 민감정보 마스킹, PII는 DB에 저장 최소화. 

## 11. 성능/최적화(필요한 만큼만)
- **I/O:** 배치 쓰기(가능 시), 연결 풀/HTTP 세션 재사용.
- **DB:** 필수 인덱스만 유지, 순차 로그성 테이블은 BRIN(옵션). 
- **전략:** 윈도우 업데이트 방식(증분 계산), 과도한 히스토리 로드 금지.

## 12. 테스트 전략(경량)
- **Unit:** 전략/리스크 순수 함수 테스트(목표 커버리지 80%+).
- **Integration:** Postgres 포함 `testcontainers`로 DB 상호작용 검증.
- **E2E(경량):** “신호 → 주문 → 알림” 최소 경로 1~2 케이스 자동화.

## 13. 마이그레이션(v4.3 → v5)
- **DB 이전:** `orders.idempotency_key`, 부분 유니크 인덱스, `transactions` append-only 트리거, `telegram_chats/notification_outbox/enqueue_notification()` 생성. 
- **옵스:** 관측 스택 비활성화(로그만), 비핵심 테이블은 즉시 DROP 대신 `zz_`로 RENAME 후 유예 드랍. 

## 14. 향후 확장(Opt‑in)
- 데이터 증가 시 Celery/RabbitMQ 도입, TimescaleDB/연속집계, Prometheus/Grafana, 대시보드(Next.js) 추가 가능.
- 전략/심볼 증가 시 에이전트 프로세스 분리(수평 확장).

## 15. 수용 기준(Acceptance)
- 주문은 **정규화/최소 주문금액**을 통과하지 못하면 즉시 거절되고, 멱등키로 활성 상태 중복이 차단된다. 
- 알림은 `telegram_chats.min_severity` 정책에 맞춰 중복 방지(dedupe_key)와 재시도 로직으로 전송된다. 
- `transactions`는 업데이트/삭제가 불가(append-only)하여 원장 무결성이 유지된다. 

---

## 16. Pine Script 통합(옵션)
- 목적: 외부(예: TradingView) Pine Script 알림을 간단·안전·멱등하게 수신하여 내부 `TradingDecision`으로 변환
- 방식:
  - Webhook(권장): 경량 HTTP 엔드포인트로 Pine `alert()` 메시지 수신
  - 파일 임포트: CSV/JSON(백필·리플레이용) → CLI로 적재
  - Pull(대안): 정적 URL/S3/Gist 주기 조회(ETag/If-Modified-Since)
- 보안: `X-Auth-Token` 헤더의 공유 토큰 + IP 허용 목록(선택)
- 멱등/감사: `idempotency_key`를 포함하고, DB의 `inbound_dedupe_keys`/`inbound_alerts`로 중복 차단 및 원문 보존

예시 alert_message(JSON)
```json
{
  "symbol": "BINANCE:BTCUSDT",
  "side": "buy",
  "qty": 0.01,
  "price": 25123.5,
  "ts": "2025-09-15T12:34:56Z",
  "strategy": "rsi_ema_cross_v1",
  "idempotency_key": "tv:abc123:1694777696"
}
```

StrategyAdapter(개념)
- 입력: 위 JSON → 스키마 검증(pydantic)
- 매핑: `strategy` → 내부 심볼/리스크 파라미터 매핑 적용
- 출력: `TradingDecision(symbol, action, sl/tp, confidence)` 생성
- 실패 처리: 오류는 `inbound_alerts.error`에 기록, 알림 WARN 발송(옵션)

FastAPI(옵션) 엔드포인트 예시
```http
POST /alerts/pine  (Headers: X-Auth-Token: <token>)
Body: alert_message JSON
동작: (1) 토큰 검증 → (2) inbound_alerts 저장(+idempotency_key) → (3) StrategyAdapter → (4) ExecutionAgent 큐 투입
```

CSV 임포트(백필)
- 컬럼: `ts,symbol,side,qty,price,strategy,idempotency_key`
- CLI: `python -m tools.import_pine_csv path/to/file.csv --source=tradingview`

수용 기준(추가)
- 동일 `idempotency_key` 알림은 중복 처리/주문 중복을 유발하지 않는다.
- 스키마 검증 실패 시 안전하게 격리되고 운영자에게 WARN 알림이 전송된다.
- 유효 알림은 정규화/최소 주문 금액 검증을 거쳐 ExecutionAgent로 전달된다.

---

## 17. 참조 다이어그램
- 아키텍처 및 ER: `diagrams/PG_Solo_Lite_Mermaid.md`
- 에이전트 파이프라인/오케스트레이션/알림: `diagrams/PG_Solo_Lite_AGENTS_Mermaid.md`
