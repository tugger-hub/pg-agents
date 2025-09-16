# PostgreSQL Solo‑Lite DB 설계 명세서 (v2.0)

- 대상: 1인 개발, 동시 사용자 1–5명
- 문서 출처: 본 문서는 `PG_Solo_Lite_Design_DB_v1.0.md`의 코어 설계를 유지하되, `anb_b1_gp.txt(보완판 vB1.1)`에서 누락되거나 스킵된 항목을 옵션 모듈(Opt‑in)로 재정렬·병합함

---

## 0. 프로파일(Profiles): Lite(기본) vs Plus(옵션)
| 영역 | Lite(기본) | Plus(옵션) |
|---|---|---|
| DB 백엔드 | 순수 PostgreSQL 단일 인스턴스 | TimescaleDB 선택적 적용 또는 네이티브 파티션 스크립트 |
| 시계열 테이블 | 일반 테이블(분봉만 `candles`) | Timescale 하이퍼테이블 + 연속 집계(1m→1h/1d) |
| 메시지 안정성 | 주문/체결 멱등(부분 유니크) | 인바운드 디듀프 저장소(`inbound_dedupe_keys`) 추가 |
| 정산/평가 | 최소한의 거래 파이프라인 | 수수료/펀딩/FX 스냅샷 |
| 데이터 거버넌스 | 기본 로깅 | 심볼/기업행위 이벤트, KPI 스냅샷 |
| 추적성(Explain) | 주문/체결/원장 기본 추적 | LLM/의사결정 추적 확장 |

> 권장: Lite로 시작하고, 병목/요구 발생 시 섹션 5의 모듈을 개별적으로 활성화하세요.

---

## 1. 범위 및 전제
- 데이터베이스: PostgreSQL 단일 인스턴스(외부 OLAP/대시보드 의존 없음)
- 워크로드: 초당 수십 행 수준의 삽입(주문/체결), 대용량 시계열은 초기 미적용
- 핵심 파이프라인: 주문 → 체결 → 포지션 → 거래 원장(append‑only)
- 알림 채널: 텔레그램 매핑 + 아웃박스 큐(워커 전송)
- 보안: 토큰/시크릿은 DB가 아닌 환경 변수/시크릿 스토어로 관리

---

## 2. v2.0의 주요 변경 사항
### 2.1 유지/강화(Lite 코어)
- `exchange_instruments.trading_rules`(JSONB) 기반 가격/수량 정규화 + 최소 주문 금액 검사 트리거 유지
- 활성 상태 부분 유니크 인덱스(멱등성 키 포함)로 재시도/중복 내성 유지
- `transactions` append‑only 트리거로 원장 불변성 강제

### 2.2 복원/병합(Plus 모듈 재도입)
- 메시지 안정성 확장: `inbound_dedupe_keys`, Upsert 헬퍼(`mark_idem_seen`)
- 평가·정산 SoT: `exchange_fee_schedules`, `funding_rates`, `fx_rate_snapshots`
- 심볼/상장 이벤트: `corporate_actions`, `symbol_events`
- 운영 KPI 스냅샷: `ops_kpi_snapshots`
- LLM/의사결정 추적성 확장: 프롬프트 해시/모델 버전/데이터 스냅샷 키
- 시계열 백엔드 옵션: TimescaleDB 선택 적용 + 연속 집계 예시 문서화

---

## 3. 아키텍처 개요
```
[Application Service]
├─ 거래/리스크 로직(규칙 평가 포함)
├─ 주문 정규화 호출(가격·수량·최소 주문 금액 검증)
├─ 알림 큐잉: DB.enqueue_notification()
└─ 텔레그램 워커: notification_outbox → 전송 → 상태 갱신

[PostgreSQL]
Core(Lite): users, api_keys, exchanges, instruments,
            exchange_instruments(trading_rules), orders, executions,
            positions, transactions(append-only), candles(분봉),
            system_logs, alerts(telegram_chats, notification_outbox)
Plus(옵션): inbound_dedupe_keys, exchange_fee_schedules, funding_rates,
            fx_rate_snapshots, corporate_actions, symbol_events,
            ops_kpi_snapshots, LLM 추적 확장, Timescale 하이퍼테이블/연속 집계
```

---

## 4. 스키마 — Lite 코어(정제/수정)

### 4.1 주문/체결 핵심 무결성
#### orders: 멱등성 및 활성 상태 중복 방지
```sql
ALTER TABLE orders
  ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(120);

-- 활성 상태에서만 중복을 막는 부분 유니크
CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_idem_active
  ON orders(account_id, idempotency_key)
  WHERE status IN ('NEW','PARTIALLY_FILLED');

CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_exoid_active
  ON orders(exchange_order_id)
  WHERE status IN ('NEW','PARTIALLY_FILLED');
```

#### transactions: Append‑Only(갱신/삭제 차단)
```sql
CREATE OR REPLACE FUNCTION trg_transactions_block_ud()
RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'transactions is append-only';
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tr_transactions_block_update ON transactions;
CREATE TRIGGER tr_transactions_block_update
  BEFORE UPDATE OR DELETE ON transactions
  FOR EACH ROW EXECUTE FUNCTION trg_transactions_block_ud();
```

### 4.2 주문 정규화 트리거(가격·수량·최소 금액)
```sql
CREATE OR REPLACE FUNCTION trg_orders_normalize()
RETURNS trigger AS $$
BEGIN
  NEW.price := normalize_price(NEW.exchange_instrument_id, NEW.price);
  NEW.quantity := normalize_size(NEW.exchange_instrument_id, NEW.quantity);
  IF NOT meets_min_notional(NEW.exchange_instrument_id, NEW.price, NEW.quantity) THEN
    RAISE EXCEPTION 'min notional violation';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tr_orders_normalize ON orders;
CREATE TRIGGER tr_orders_normalize
  BEFORE INSERT OR UPDATE ON orders
  FOR EACH ROW EXECUTE FUNCTION trg_orders_normalize();
```
설명: 정규화 함수는 기존 설계를 재사용하며, 본 문서는 트리거 바인딩만 포함합니다.

### 4.3 텔레그램 연동(매핑/아웃박스/헬퍼)
```sql
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'alert_severity') THEN
    CREATE TYPE alert_severity AS ENUM ('INFO','WARN','CRITICAL');
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS telegram_chats (
  id SERIAL PRIMARY KEY,
  user_id INT REFERENCES users(id),
  chat_id BIGINT NOT NULL UNIQUE,
  description TEXT,
  min_severity alert_severity NOT NULL DEFAULT 'WARN',
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS notification_outbox (
  id BIGSERIAL PRIMARY KEY,
  channel VARCHAR(20) NOT NULL DEFAULT 'TELEGRAM',
  chat_id BIGINT NOT NULL,
  severity alert_severity NOT NULL,
  title TEXT NOT NULL,
  message TEXT NOT NULL,
  dedupe_key VARCHAR(120),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  send_after TIMESTAMPTZ,
  sent_at TIMESTAMPTZ,
  fail_count INT NOT NULL DEFAULT 0,
  status VARCHAR(20) NOT NULL DEFAULT 'PENDING'  -- PENDING|SENT|FAILED
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_notification_outbox_dedupe
  ON notification_outbox(dedupe_key) WHERE dedupe_key IS NOT NULL;

CREATE OR REPLACE FUNCTION enqueue_notification(
  p_chat_id BIGINT,
  p_sev alert_severity,
  p_title TEXT,
  p_msg TEXT,
  p_dedupe TEXT DEFAULT NULL
) RETURNS BIGINT AS $$
DECLARE v_id BIGINT;
BEGIN
  IF p_dedupe IS NOT NULL THEN
    INSERT INTO notification_outbox(chat_id, severity, title, message, dedupe_key)
    VALUES (p_chat_id, p_sev, p_title, p_msg, p_dedupe)
    ON CONFLICT (dedupe_key) DO NOTHING
    RETURNING id INTO v_id;
    RETURN COALESCE(v_id, 0);
  ELSE
    INSERT INTO notification_outbox(chat_id, severity, title, message)
    VALUES (p_chat_id, p_sev, p_title, p_msg)
    RETURNING id INTO v_id;
    RETURN v_id;
  END IF;
END; $$ LANGUAGE plpgsql;
```

---

## 5. Plus 옵션 모듈(스위치 온/오프 가능)

### 5.1 메시지 안정성 확장(인바운드 디듀프)
```sql
CREATE TABLE IF NOT EXISTS inbound_dedupe_keys (
  id BIGSERIAL PRIMARY KEY,
  idempotency_key VARCHAR(200) UNIQUE NOT NULL,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  source VARCHAR(50) NOT NULL,
  payload_hash VARCHAR(64) NOT NULL,
  processed BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE OR REPLACE FUNCTION mark_idem_seen(p_key text, p_hash text, p_src text)
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO inbound_dedupe_keys(idempotency_key, payload_hash, source)
  VALUES (p_key, p_hash, p_src)
  ON CONFLICT (idempotency_key) DO
    UPDATE SET last_seen_at = NOW();
END $$;
```
설명: 수신 핸들러는 (1) `mark_idem_seen` 호출 후, (2) 동일 키 재수신 시 본문 해시 비교로 무시/보류합니다. DB 레벨에서는 `orders`/`executions`의 부분 유니크가 2차 방어를 수행합니다.

### 5.2 수수료·펀딩·환율 스냅샷(평가/정산 SoT)
```sql
CREATE TABLE IF NOT EXISTS exchange_fee_schedules (
  id SERIAL PRIMARY KEY,
  exchange_id INT NOT NULL REFERENCES exchanges(id),
  effective_from TIMESTAMPTZ NOT NULL,
  effective_to   TIMESTAMPTZ,
  fee_schema JSONB NOT NULL,
  UNIQUE(exchange_id, effective_from)
);

CREATE TABLE IF NOT EXISTS funding_rates (
  id BIGSERIAL PRIMARY KEY,
  exchange_instrument_id INT NOT NULL REFERENCES exchange_instruments(id),
  funding_time TIMESTAMPTZ NOT NULL,
  funding_rate NUMERIC NOT NULL,
  collected BOOLEAN NOT NULL DEFAULT FALSE,
  UNIQUE(exchange_instrument_id, funding_time)
);

CREATE TABLE IF NOT EXISTS fx_rate_snapshots (
  ts TIMESTAMPTZ NOT NULL,
  base_ccy VARCHAR(10) NOT NULL,
  quote_ccy VARCHAR(10) NOT NULL,
  rate NUMERIC NOT NULL,
  PRIMARY KEY (ts, base_ccy, quote_ccy)
);
```
설명: 영구선물 펀딩(`funding_rates`), 수수료 스케줄(`exchange_fee_schedules`), 포트폴리오 USD 환산(`fx_rate_snapshots`)을 단일 진실 원천(SoT)으로 별도 관리합니다.

### 5.3 심볼/상장 이벤트
```sql
CREATE TABLE IF NOT EXISTS corporate_actions (
  id SERIAL PRIMARY KEY,
  instrument_id INT NOT NULL REFERENCES instruments(id),
  event_time TIMESTAMPTZ NOT NULL,
  action_type VARCHAR(40) NOT NULL, -- 'SPLIT','REVERSE_SPLIT','MERGER','SYMBOL_CHANGE','DELIST','LIST'
  details JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS symbol_events (
  id SERIAL PRIMARY KEY,
  exchange_id INT NOT NULL REFERENCES exchanges(id),
  instrument_id INT NOT NULL REFERENCES instruments(id),
  event_time TIMESTAMPTZ NOT NULL,
  event_type VARCHAR(40) NOT NULL,  -- 'SYMBOL_LISTED','SYMBOL_DELISTED','LOT_SIZE_CHANGE', ...
  details JSONB NOT NULL
);
```
가이드: 글로벌 SoT는 `instruments`, 거래소별 규칙은 `exchange_instruments`가 보유하며, 이벤트 발생 시 매핑/규칙 갱신 및 영향 범위 백필 절차를 문서화합니다.

### 5.4 KPI 스냅샷(운영/가시성)
```sql
CREATE TABLE IF NOT EXISTS ops_kpi_snapshots (
  ts TIMESTAMPTZ PRIMARY KEY DEFAULT NOW(),
  order_latency_p50_ms INT,
  order_latency_p95_ms INT,
  order_failure_rate NUMERIC,
  order_retry_rate NUMERIC,
  position_gross_exposure_usd NUMERIC,
  open_positions_count INT
);
```

### 5.5 LLM/의사결정 추적성 확장
```sql
ALTER TABLE llm_prompts
  ADD COLUMN IF NOT EXISTS prompt_hash VARCHAR(64);

ALTER TABLE llm_responses
  ADD COLUMN IF NOT EXISTS data_snapshot_key VARCHAR(128);

ALTER TABLE llm_insights
  ADD COLUMN IF NOT EXISTS model_version VARCHAR(50);

ALTER TABLE decision_logs
  ADD COLUMN IF NOT EXISTS prompt_hash VARCHAR(64),
  ADD COLUMN IF NOT EXISTS data_snapshot_key VARCHAR(128),
  ADD COLUMN IF NOT EXISTS model_name VARCHAR(100),
  ADD COLUMN IF NOT EXISTS model_version VARCHAR(50),
  ADD COLUMN IF NOT EXISTS parameters JSONB;
```
설명: 프롬프트 해시 + 데이터 스냅샷 키 + 모델 버전/파라미터로 재현성을 강화합니다.

### 5.6 시계열 백엔드 옵션(Timescale / 네이티브 파티션)
- Timescale(권장‑옵션): 하이퍼테이블 + 1m→1h/1d 연속 집계 MV
- 네이티브 파티션(대안): 월별 RANGE 파티션 스크립트로 분리 배포

전략: Lite에서는 일반 테이블로 시작하고, 데이터 볼륨/질의 유형에 따라 단계적으로 옵션을 활성화합니다.

### 5.7 Pine Script 알림 수신(옵션)
```sql
-- 외부(Pine/TradingView) 알림 원문 보존 상자(감사/재처리 용도)
CREATE TABLE IF NOT EXISTS inbound_alerts (
  id BIGSERIAL PRIMARY KEY,
  source VARCHAR(50) NOT NULL DEFAULT 'tradingview',
  received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  dedupe_key VARCHAR(200),                         -- alert의 idempotency_key 매핑(있을 경우)
  payload JSONB NOT NULL,                          -- alert_message 원문
  parsed BOOLEAN NOT NULL DEFAULT FALSE,           -- 어댑터 처리 여부
  error TEXT                                       -- 검증/처리 오류 메시지
);

-- 필요 시 dedupe 인덱스(널 제외)
CREATE UNIQUE INDEX IF NOT EXISTS ux_inbound_alerts_dedupe
  ON inbound_alerts(dedupe_key) WHERE dedupe_key IS NOT NULL;

-- 기존 인바운드 키 저장소 재사용(중복 차단/관측)
-- see: inbound_dedupe_keys, mark_idem_seen(p_key, p_hash, p_src)
```
가이드:
- 알림 수신 시 `inbound_alerts(payload, dedupe_key, source)`에 원문 저장 후, `mark_idem_seen()`으로 중복 관리를 수행합니다.
- 어댑터가 스키마 검증/매핑 성공 시 `parsed=true`로 갱신하고, 실패 시 `error`에 사유를 남깁니다.

---

## 6. 운영 런북(요약)
- 알림 처리: 워커가 `notification_outbox`에서 `status='PENDING'` 건을 `FOR UPDATE SKIP LOCKED`로 집계 → 전송 성공 시 `SENT`, 실패 시 `fail_count` 증가 + 백오프(`send_after`)
- 재시도 정책: 1m → 2m → 5m → 15m → 30m, 5회 이상 실패 시 `FAILED` 전환 및 자체 경고
- 백업/복구: 일 1회 전체 백업 + WAL 보관. PENDING 아웃박스는 멱등 전송 허용

---

## 7. 마이그레이션 가이드(v1.0 → v2.0)
1) 백업 생성 및 쓰기 트래픽 정지(읽기 전용 전환)
2) 코어 보강: `orders` 부분 유니크 2종, `transactions` append‑only 트리거, 알림 테이블/함수 설치(이미 v1.0에 포함된 경우 확인만)
3) 옵션 모듈 선택 적용:
   - 메시지 안정성(5.1) → 외부 수신 핸들러 연동
   - 수수료/펀딩/FX(5.2) → 수집 파이프라인/정산 로직 연결
   - 심볼/CA(5.3) → 규칙 갱신/백필 절차 확립
   - KPI(5.4) → 대시보드/알람 룰 연계
   - LLM 추적(5.5) → 주문/결정 로그에 컬럼 연계
   - Timescale(5.6) → 하이퍼테이블/연속 집계 생성(대안: 네이티브 파티션 스크립트)
4) 롤백 계획: 신규 오브젝트 제거 및 `zz_` 프리픽스 백업 테이블 복구 스크립트 준비

---

## 8. 수용 기준(체크리스트)
- 주문 생성/수정 시 정규화 일관 적용, 최소 주문 금액 미충족 시 즉시 거절
- 동일 `idempotency_key` 활성 상태에서 중복 주문 방지
- 텔레그램 알림이 `min_severity` 정책에 따라 전송/재시도/중복 방지 동작
- `transactions`는 갱신/삭제 불가(append‑only)
- (Plus 적용 시) 펀딩/수수료/FX, 심볼 이벤트, KPI, LLM 추적 컬럼/테이블 정합성 만족

---

## 9. 대표 쿼리(실전 예시)
### A. 주문 준비: 규칙 정규화 결과 확인
```sql
SELECT
  ei.exchange_symbol,
  normalize_price(ei.trading_rules, $1::numeric)  AS px_norm,
  normalize_size(ei.trading_rules, $2::numeric)   AS qty_norm,
  meets_min_notional(ei.trading_rules, $1, $2)    AS ok_min_notional
FROM exchange_instruments ei
WHERE ei.id = $3;
```

### B. 활성 주문 페이징(중복 안전)
```sql
SELECT id, client_order_id, exchange_order_id, status, created_at
FROM orders
WHERE account_id = $1
  AND status IN ('NEW','PARTIALLY_FILLED')
ORDER BY created_at DESC
LIMIT 100;
```

### C. 최근 펀딩 정산 내역(Plus)
```sql
SELECT t.timestamp, ei.exchange_symbol, t.amount
FROM transactions t
JOIN positions p ON p.id = t.related_position_id
JOIN exchange_instruments ei ON ei.id = p.exchange_instrument_id
WHERE t.transaction_type = 'FUNDING_FEE'
  AND t.account_id = $1
ORDER BY t.timestamp DESC
LIMIT 200;
```

### D. KPI 최신값(Plus)
```sql
SELECT *
FROM ops_kpi_snapshots
ORDER BY ts DESC
LIMIT 1;
```

---

## 10. 보안/권한
- 봇 토큰/시크릿: 환경 변수로 공급, DB 저장 금지. 필요 시 `system_configuration` 1행으로 대체
- 워커 권한: `notification_outbox`에 `SELECT FOR UPDATE SKIP LOCKED`, `UPDATE`만 부여
- PII 최소화: `telegram_chats`는 최소 식별자만 저장, 필요 시 `users` FK만 보유

---

## 11. 환경 변수(권장)
- `TELEGRAM_BOT_TOKEN`: 텔레그램 봇 토큰(필수)
- `APP_ENV`: 환경 구분(`local`|`staging`|`prod`)
- `DB_POOL_SIZE`, `DB_STATEMENT_TIMEOUT`: 커넥션/타임아웃 파라미터

---

## 부록: 시계열 옵션 DDL 힌트(Plus)
### TimescaleDB 예시
```sql
SELECT create_hypertable('candles', 'time', if_not_exists => TRUE);
-- 1m → 1h 연속 집계 MV 예시(개략)
-- CREATE MATERIALIZED VIEW candles_1h WITH (timescaledb.continuous) AS
--   SELECT time_bucket('1 hour', time) AS bucket,
--          instrument_id,
--          first(open, time)  AS open,
--          max(high)          AS high,
--          min(low)           AS low,
--          last(close, time)  AS close,
--          sum(volume)        AS volume
--   FROM candles
--   GROUP BY bucket, instrument_id;
```

### 네이티브 파티션 예시
```sql
-- 월별 RANGE 파티션 스크립트를 별도 파일(e.g., candles_native_partition.sql)로 관리/배포
```
