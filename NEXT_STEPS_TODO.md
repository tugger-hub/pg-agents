# NEXT STEPS — 실행 체크리스트(포멀 버전)

> 본 체크리스트는 다음 문서에 기반합니다: `PG_Solo_Lite_AGENTS.md`, `PG_Solo_Lite_Design_DB_v2.0.md`, `basic_strategies_kr.md`.
> 목표는 MVP → 모의/페이퍼 → 소액 실전까지 단계적으로 구축·검증하는 것입니다.

## M0. 리포지토리 및 환경
- [ ] 모노레포 초기화: `app/`, `db/`, `configs/`, `scripts/`, `docs/`
- [ ] `.env` 템플릿: `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `APP_ENV`, 브로커 키 등(시크릿은 DB 저장 금지)
- [ ] Python 3.11+ 가상환경 및 필수 패키지 설치: `httpx`, `ccxt`, `pydantic`, `psycopg`, `sqlalchemy`, `apscheduler`, `python-telegram-bot`
- [ ] `docker-compose.yml` 또는 `systemd` 유닛 파일(선택)

## M1. DB 코어 구축
- [ ] Postgres 기동 및 `PG_Solo_Lite_Design_DB_v2.0.md` 코어 DDL 적용
- [ ] `orders` 활성 상태 부분 유니크(멱등/중복 주문 차단) 확인
- [ ] `transactions` append‑only 트리거(갱신/삭제 차단) 확인
- [ ] `telegram_chats`, `notification_outbox`, `enqueue_notification()` 설치

## M2. 에이전트 뼈대
- [ ] Scheduler + Ingestion/Strategy/Execution/Risk/Report 클래스 스켈레톤
- [ ] 공통 모델 정의: `TradingDecision`, `MarketSnapshot`
- [ ] 공통 로깅 인터페이스 및 구조화 로그 포맷

## M3. Ingestion(최소)
- [ ] 심볼 1–3개, 1m 분봉 최근 N개 수집(또는 메모리 스냅샷)
- [ ] 실패 시 지수 백오프, 과거 과도 적재 금지

## M4. 전략 파라미터 고정
- [ ] TF 매핑(예: Trend=1D/4H, Entry=1H), 거래량 컨펌(20MA 대비 ≥1.5x), 리테스트 성공 정의
- [ ] 손절/익절/트레일링(ATR 또는 %) 규칙 명문화
- [ ] 기본 위험 비율 1–3% 설정(종목/전략별 오버라이드 허용)

## M5. Execution(멱등/정규화)
- [ ] 신호→주문 변환 시 멱등키 부여, 가격/수량 정규화 및 최소 주문 금액 검증
- [ ] 주문 제출 전후 DB 기록(원자성), 재시도 시 중복 주문 0 확인

## M6. Risk(관리/청산)
- [ ] 부분 익절/BE 이동/트레일링 규칙 구현(구간표 기반)
- [ ] 모든 액션 로그 및 원장 기록(append‑only)

## M7. 알림(아웃박스)
- [ ] `enqueue_notification()` 사용, 워커는 `FOR UPDATE SKIP LOCKED` 집계
- [ ] `dedupe_key` 기반 중복 방지, 실패 시 백오프 재시도 및 DLQ(선택)

## M8. KPI 및 리포트
- [ ] `ops_kpi_snapshots` 집계(p95 지연, 실패율, 오픈 포지션)
- [ ] 일일/주간 성과 요약 생성 → 텔레그램 전송

## M9. 모의/페이퍼 검증
- [ ] 테스트넷/모의에서 “중복 주문 0”, 알림/리스크 경로 정상 동작 검증
- [ ] (선택) 수수료/펀딩/FX 스냅샷 적용 시 PnL 재현성 점검

## M10. 소액 실전(가드레일)
- [ ] 전역 킬스위치 플래그 준비(예: `system_configuration` 1행)
- [ ] 일일 손실 한도/주간 정지 규칙 활성화
- [ ] 백업 및 복구 리허설 수행(WAL 포함)

## M11. 옵션 모듈(필요 시 활성)
- [ ] 외부 알림/이벤트 중복 방지: `inbound_dedupe_keys`, `mark_idem_seen()`
- [ ] 정산 SoT: `exchange_fee_schedules`, `funding_rates`, `fx_rate_snapshots`
- [ ] 시계열 확장: TimescaleDB 또는 네이티브 파티션 전환 시나리오 준비
- [ ] DLQ 규약 수립(최종 실패 격리/경보)

---

## 수용 기준(DoD) 요약
- DB 코어: 정규화 트리거/부분 유니크/append‑only가 테스트로 증명됨
- Execution: 재시도/재연결 상황에서도 중복 주문 0 유지
- Risk: 부분익절/BE/트레일링 이벤트가 모두 원장에 남음
- 알림: `min_severity` 정책, dedupe, 백오프/재시도 로직이 동작

