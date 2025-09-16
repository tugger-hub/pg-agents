
# NEXT STEPS — 실행 체크리스트 (세부 버전 v2.0)

## 개요

본 체크리스트는 다음 문서에 기반합니다:
- `PG_Solo_Lite_AGENTS.md`
- `PG_Solo_Lite_Design_DB_v2.0.md`
- `basic_strategies_kr.md`

**목표**: 모노레포 초기화 → DB 코어 정합성 → 최소 에이전트 파이프라인 → 모의/페이퍼 검증 → 소액 실전 투입까지 **단계적으로 구축·검증**

## 사용 규약

| 표기 | 의미 |
|------|------|
| `[ ]` | 작업 미완료 |
| `[x]` | 작업 완료 |
| `[!]` | 블로킹 이슈 |

### 메타데이터 형식
- **Owner**: `@username`
- **ETA**: `YYYY-MM-DD`
- **Artifact**: `path/to/file`

### 수용 기준
각 섹션 마지막에 **검증 항목**을 명시합니다.

---

## M0. 리포지토리 & 환경 부트스트랩

### 작업 항목
- [ ] **모노레포 디렉터리 생성**
  - 디렉터리: `app/`, `db/`, `configs/`, `scripts/`, `docs/`
  - Owner: @you

- [ ] **Python 환경 설정**
  - Python 3.11+ 가상환경 구성
  - 필수 패키지 설치: `httpx`, `ccxt`, `pydantic`, `psycopg`/`sqlalchemy`, `apscheduler`, `python-telegram-bot`, `pytest`, `testcontainers`
  - Artifact: `requirements.txt`

- [ ] **환경 변수 템플릿 작성**
  - 파일: `.env.template`
  - 변수: `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `APP_ENV`, `DB_POOL_SIZE`, 전략 파라미터(위험 %, 지표 기간 등)
  - **주의**: 시크릿은 DB 저장 금지

- [ ] **실행 러너 구성** (택1)
  - `docker-compose.yml` 또는 `systemd` 유닛 파일
  - Artifact: `compose.yaml` / `pg-solo-lite.service`

### 수용 기준
- `make setup` 또는 `scripts/bootstrap.sh`로 로컬 환경이 재현됨
- `.env` 로드만으로 애플리케이션이 부팅(브로커 연결 제외)

---

## M1. DB 코어 구축 및 보호 레일

### 작업 항목
- [ ] **Postgres 기동 및 코어 DDL 적용**
  - orders 멱등/부분 유니크 설정
  - transactions append-only 설정
  - 알림 테이블/함수 구성
  - Artifact: `db/schema_core.sql`

- [ ] **주문 정규화 트리거 바인딩**
  - `normalize_price/size` 검증
  - `meets_min_notional` 검증

- [ ] **알림 채널 설치**
  - `telegram_chats` 테이블
  - `notification_outbox` 테이블
  - `enqueue_notification()` 함수

- [ ] **코어 무결성 쿼리 스모크 테스트 추가**
  - Artifact: `tests/db/test_core_integrity.py`

### 스모크 쿼리 예시

```sql
-- A. 정규화/최소 주문금액 확인
SELECT ei.exchange_symbol,
       normalize_price(ei.trading_rules, 123.456)  AS px_norm,
       normalize_size(ei.trading_rules, 0.987)     AS qty_norm,
       meets_min_notional(ei.trading_rules, 123.456, 0.987) AS ok_min_notional
FROM exchange_instruments ei LIMIT 1;

-- B. 활성 주문 중복 방지 인덱스 확인
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'orders' AND indexname LIKE 'ux_orders_%';
```

### 수용 기준
- "정규화/최소 주문금액 위반 시 즉시 예외"가 테스트로 증명됨
- 활성 상태에서 idempotency_key 중복 삽입이 차단됨
- transactions 테이블은 UPDATE/DELETE 시도 시 예외 발생(append-only) 

## M2. 에이전트 뼈대 & 오케스트레이션

### 작업 항목
- [ ] **모듈 스켈레톤 구성**
  - IngestionAgent
  - StrategyAgent
  - ExecutionAgent
  - RiskAgent
  - ReportAgent

- [ ] **공통 모델 정의**
  - TradingDecision(symbol, side, sl, tp, confidence)
  - MarketSnapshot
  - Artifact: `app/models.py`

- [ ] **스케줄러 루프 구현**
  - apscheduler 또는 asyncio.create_task 사용
  - 각 에이전트 주기 실행
  - Artifact: `app/scheduler.py`

- [ ] **구조화 로깅 설정**
  - JSON 형식
  - 민감정보 마스킹
  - Artifact: `app/logging.py`

### 수용 기준
- 로컬에서 "신호→주문→알림" 더미 경로 1회 선순환(모의 객체) 

## M3. Ingestion(최소 기능)

### 작업 항목
- [ ] **시장 데이터 수집**
  - 심볼 1–3개에 대해 1m 분봉 최근 N개 스냅샷 수집
  - 메모리 또는 candles 테이블 저장

- [ ] **에러 처리 및 복구**
  - 실패 시 지수 백오프 적용
  - 과거 과도 적재 금지(최근 윈도만)

- [ ] **브로커 규칙 캐시**
  - `exchange_instruments.trading_rules` 로컬 캐시화

### 수용 기준
- 네트워크 일시 장애에서 자동 복구(백오프)하고 스냅샷 윈도 크기 유지

## M4. 전략 파라미터 고정(가격·거래량·시간 프레임)

### 작업 항목
- [ ] **시간 프레임 매핑**
  - Trend: 1D/4H
  - Entry: 1H (기본값)

- [ ] **거래량 컨펌 설정**
  - 20MA 대비 ≥ 1.5x 시 돌파 컨펌

- [ ] **리테스트 성공 정의**
  - 돌파 후 S/R 재확인 + 캔들 마감 기준

- [ ] **손절/익절/트레일링 설정**
  - ATR 또는 % 기반
  - 무효화 지점 중심으로 손절 설정

- [ ] **기본 위험 비율**
  - 단일 거래 리스크 1–3% 룰 적용

- [ ] **신호 휴지기**
  - 신뢰도 임계치 미만은 폐기(StrategyAgent 정책)

### 수용 기준
- YAML/ENV로 전략 파라미터를 교체 가능, 변경 즉시 런타임 반영

## M5. Execution(멱등·정규화·최소 금액)

### 작업 항목
- [ ] **멱등키 부여**
  - TradingDecision→주문 변환 시 멱등키 부여
  - 전략/심볼/타임슬라이스 해시 사용

- [ ] **가격/수량 정규화**
  - 최소 주문 금액 사전 검증
  - 트리거 일관 적용

- [ ] **주문 제출 및 DB 기록**
  - 주문 제출 전후 DB 기록(원자성)
  - 재시도에도 활성 상태 중복 0 보장

### 수용 기준
- 재시도/재연결 시 "중복 주문 0"이 통합 테스트로 증명됨

## M6. Risk(관리·청산)

### 작업 항목
- [ ] **리스크 관리 룰 명문화**
  - 부분 익절/BE 이동/트레일링 스탑 룰을 구간표로 명문화
  - 예: +1R 25% 청산, +2R BE, +3R 트레일링

- [ ] **리스크 액션 기록**
  - 모든 리스크 액션은 원장 transactions에 append-only로 기록

- [ ] **중요 이벤트 알림**
  - 중요 이벤트는 텔레그램 알림 큐에 등록

### 수용 기준
- 백테스트 시나리오로 각 이벤트가 정확히 1회씩 기록/알림 처리됨

## M7. 알림(아웃박스 워커)

### 작업 항목
- [ ] **알림 큐잉 시스템**
  - `enqueue_notification()`으로 큐잉
  - 워커는 FOR UPDATE SKIP LOCKED 집계

- [ ] **중복 방지 및 재시도**
  - `dedupe_key`로 중복 방지
  - 백오프 재시도 및 DLQ 정책(옵션)

- [ ] **소음 억제**
  - `telegram_chats.min_severity` 정책으로 소음 억제

### 수용 기준
- 동일 dedupe_key 반복 전송 시 1회만 발송되고, 실패 시 지수 백오프 후 회복

## M8. KPI & 리포트

### 작업 항목
- [ ] **KPI 스냅샷 적재**
  - `ops_kpi_snapshots` 적재
  - 지연 p95/실패율/오픈 포지션 수 등

- [ ] **성과 요약 생성**
  - 일일/주간 성과 요약 생성
  - 텔레그램 전송(ReportAgent)

### 수용 기준
- 최근 KPI 1건을 조회하는 쿼리로 대시 값 확인 가능
- 리포트 메시지가 텔레그램으로 수신됨

## M9. 모의/페이퍼 검증

### 작업 항목
- [ ] **테스트넷/모의 브로커 검증**
  - "신호→주문→체결→리스크→알림" 경로 검증

- [ ] **모의 데이터 주입** (선택)
  - 수수료/펀딩/FX 스냅샷을 모의 값으로 주입

### 수용 기준
- 중복 주문 0, 알림/리스크 경로 정상, PnL 재현성(선택 항목) 확인

## M10. 소액 실전(가드레일)

### 작업 항목
- [ ] **전역 킬스위치**
  - `system_configuration` 1행 또는 ENV 플래그

- [ ] **손실 한도 규칙**
  - 일일 손실 한도/주간 정지 규칙 활성화
  - 위반 시 자동 CRITICAL 알림

- [ ] **백업/복구 리허설**
  - WAL 포함 백업/복구 리허설

### 수용 기준
- 킬스위치 ON 시 신규 주문 차단, 손실 한도 초과 시 자동 정지

## M11. 옵션 모듈(필요 시)

### 작업 항목
- [ ] **인바운드 디듀프 저장소**
  - `inbound_dedupe_keys`, `mark_idem_seen()` 연결

- [ ] **정산 SoT**
  - `exchange_fee_schedules`, `funding_rates`, `fx_rate_snapshots`

- [ ] **시계열 확장**
  - TimescaleDB 하이퍼테이블/연속 집계 또는 네이티브 파티션

- [ ] **DLQ 규약 수립**
  - 모니터링 룰 설정

### 수용 기준
- 모듈별 테이블/함수가 설치되고 최소 1건의 데이터가 관측됨

## M12. Pine Script(Webhook) 통합(옵션)

### 작업 항목
- [ ] **HTTP 엔드포인트 구성**
  - 경량 HTTP 엔드포인트로 TradingView alert() 수신
  - 공유 토큰 + IP 화이트리스트

- [ ] **원문 보존 상자**
  - `inbound_alerts(payload, dedupe_key)` 저장

- [ ] **StrategyAdapter 구현**
  - 유효성 검증(pydantic) → 내부 TradingDecision 변환

### 수용 기준
- 동일 idempotency_key 알림은 1회만 주문/처리를 유발

## M13. 테스트 전략

### 작업 항목
- [ ] **Unit 테스트**
  - 전략/리스크 순수 함수(목표 커버리지 80%+)

- [ ] **Integration 테스트**
  - Postgres 포함 testcontainers로 DB 상호작용 검증

- [ ] **E2E 테스트(경량)**
  - 더미 신호→주문→알림 경로 1–2 케이스 자동화

### 수용 기준
- CI에서 모든 테스트가 통과하고, 실패 시 원인이 구조화 로그로 재현됨

## M14. 운영 런북(요약)

### 작업 항목
- [ ] **가동/중지**
  - `docker-compose up -d` 또는 systemd 1개 서비스

- [ ] **알림 워커**
  - FOR UPDATE SKIP LOCKED 집계 → 전송/재시도/실패 격리

- [ ] **백업**
  - 일 1회 전체 백업 + WAL 보관
  - 장애 시 PENDING 알림은 멱등 재전송 허용

### 수용 기준
- 장애 주입(텔레그램/브로커/API) 시 자동 복구 및 중복 없는 재처리 확인

---

## 부록 A. 전략 기본 원칙(요약)

### 핵심 원칙
- 거래는 계획 후 실행(진입/목표/무효화 지점 선정)
- 손실은 짧게, 추세는 길게
- 원금 보존, 단순함, 기록 학습, 현물 우선

### 주의사항
- 다이버전스는 힌트이며 트리거 아님 → S/R 플립이나 가격 확인을 기다릴 것

### 8단계 체크리스트
Top-Down, S/R, 거래량, 컨펌, 손절, 사이징, 관리 순으로 진행

---

## 문서 정보
- **버전**: v2.0
- **최종 수정일**: 2024년
- **기반 문서**: `PG_Solo_Lite_AGENTS.md`, `PG_Solo_Lite_Design_DB_v2.0.md`, `basic_strategies_kr.md` 