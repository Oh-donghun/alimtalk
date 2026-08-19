# 배송 알림톡 자동발송 (오징어엄마 · 동광수산)

매일 정해진 시각에 **네이버(커머스API) / 쿠팡(WING Open API)** 에서 송장이 등록된 주문을 가져와
**알리고 알림톡 API**로 배송 안내를 자동 발송합니다.

```
15:30  오징어엄마  ─ 네이버(발송처리 완료) + 쿠팡(배송지시)  →  알림톡
16:30  동광수산    ─ 네이버(발송처리 완료)                     →  알림톡 (옵션명 정리 후)
```

* 같은 주문에는 **절대 두 번 보내지 않습니다** (`sent.db` 에 이력 저장)
* 주말 · 공휴일 · 직접 지정한 휴무일 · `PAUSE` 파일이 있으면 자동으로 쉽니다
* 실행할 때마다 `out/` 폴더에 **발송 결과 엑셀 + 알리고 업로드용 엑셀**이 저장됩니다
* API 승인 전에는 **엑셀 파일 → 알림톡** 모드로도 쓸 수 있습니다 (쿠팡 수작업 붙여넣기 대체)

---

## 1. 준비물 (한 번만)

| 항목 | 어디서 |
|---|---|
| Python 3.10 이상 | https://www.python.org/downloads/ (설치 시 **Add python to PATH** 체크) |
| 알리고 API Key / userid | 알리고 사이트 → 문자API → API Key 발급. **발신 IP 등록** 필요 (자동발송할 PC 공인 IP) |
| 알리고 발신프로필키(senderkey), 템플릿코드(tpl_code) | 알리고 → 알림톡 → 카카오채널 관리 / 템플릿 관리 (오징어엄마, 동광수산 각각) |
| 네이버 커머스API 애플리케이션 ID/시크릿 | https://apicenter.commerce.naver.com → 애플리케이션 등록 (스토어별로 각각) → **주문 조회 권한** 신청. 승인까지 며칠 걸림 |
| 쿠팡 Open API Access/Secret Key, 업체코드(A000xxxxx) | WING → 판매자정보 → 추가판매정보 → Open API 키 발급 |

## 2. 설치

```bat
cd 이_폴더
pip install -r requirements.txt
copy config.example.yaml config.yaml
notepad config.yaml     ← 키값 채워넣기
```

## 3. 점검 → 테스트 → 실제 발송

```bat
python run.py --check                     # 알리고 템플릿/포인트, 네이버·쿠팡 API 연결 확인
python run.py --shop ojingeo_mom --dry-run  # 발송 없이 대상만 뽑아 out\ 에 엑셀 저장 + 첫 메시지 미리보기
python run.py --shop ojingeo_mom            # 실제 발송
```

`config.yaml` 의 `aligo.testmode: "Y"` 로 두면 알리고 테스트모드(실발송X)로 전체 흐름을 확인할 수 있습니다.

## 4. 자동 실행 (둘 중 하나)

**A. 켜두는 방식** – `start_daemon.bat` 더블클릭. 창이 떠 있는 동안 15:30 / 16:30 에 자동 실행.
(창을 닫으면 멈춤. 매일 아침 켜거나, 아래 B 방식 권장)

**B. Windows 작업 스케줄러 (권장)**
1. 시작 → "작업 스케줄러" → 기본 작업 만들기
2. 트리거: 매일 15:30 / 동작: 프로그램 시작 → `run_ojingeo_mom.bat` (시작 위치: 이 폴더)
3. 같은 방법으로 16:30 → `run_donggwang.bat`
4. "사용자가 로그온되어 있지 않아도 실행" 체크, "가장 높은 권한" 체크
   (PC가 꺼져 있으면 실행되지 않으니 자동발송 PC는 켜 두거나, 절전 해제)

## 5. 관리 페이지 (휴무일 · 일시정지 · 즉시발송)

`python run.py --web` 을 실행하면 자동발송 예약과 관리 페이지가 함께 뜹니다.
브라우저(휴대폰도 가능)에서 `http://서버주소:8080/?token=<config.yaml 의 web.token>` 을 열면:

* **⏸ 발송 멈추기 / ▶ 다시 시작** — 배송 사고 시 한 번에 정지
* **휴무일 추가** — 날짜 선택(기간도 가능) + 메모. 지나간 휴무일은 자동 정리
* **테스트 / 지금 발송** — 상점별로 즉시 실행
* **최근 발송 이력** — 누구에게 무엇을 보냈는지 확인

주말과 대한민국 공휴일은 등록하지 않아도 자동으로 쉽니다.

## 6. 알리고 잔액 부족 알림

`config.yaml` 의 `point_alert` 에서 설정합니다. 발송 직전에 잔여 알림톡 건수를 확인해서
`threshold` 이하이면 `admin_phones` 로 **문자 알림 + 충전 계좌 안내**를 보냅니다 (하루 1회).
계좌는 `bank_accounts` 에 상점별로 적어두세요.

## 7. 알리고 계정이 상점마다 다른 경우

각 상점의 `aligo:` 아래에 `userid` / `apikey` / `sender` / `senderkey` / `tpl_code` 를 각각 적으면 됩니다.
최상단 `aligo:` 는 공통 기본값(failover, testmode)만 두면 됩니다.

## 8. 쉬는 날 / 배송 문제 생겼을 때

* **오늘만 급히 멈추기**: 폴더에 `PAUSE` 라는 이름의 빈 파일 하나 만들어 두세요 (확장자 없이). 지우면 다시 발송.
* **미리 정한 휴무일**: `config.yaml` → `safety.extra_holidays` 에 날짜 추가. (다음 실행부터 반영)
* 주말 · 대한민국 공휴일은 기본으로 쉽니다 (`skip_weekends`, `skip_kr_holidays`).
* 다음 날 밀린 건까지 보내야 하면: `only_today: false` 로 바꾸거나 `python run.py --shop 동광수산 --force` 실행.
  (이미 보낸 주문은 이력 때문에 자동으로 제외됩니다)

## 6. 동광수산 옵션명 정리

`config.yaml` → `shops.donggwang.option_cleanup` 에서 정규식/치환 규칙을 조정합니다.
`python run.py --shop donggwang --dry-run` 으로 out\ 엑셀의 `#{주문상품명}` 열을 보면서 규칙을 다듬으세요.
같은 주문에 옵션이 여러 개면 `"첫옵션 외 2건"` 으로 합쳐집니다.

## 7. 엑셀 모드 (API 승인 전 / 비상시)

```bat
:: 쿠팡 WING 배송관리 엑셀 → 알림톡 바로 발송
python run.py --shop ojingeo_mom --coupang-excel DeliveryList_2026-08-19.xlsx
:: 알리고 사이트에 직접 업로드할 엑셀만 만들기 (발송 X)
python run.py --shop ojingeo_mom --coupang-excel DeliveryList_2026-08-19.xlsx --excel-only
:: 네이버 발주발송관리 엑셀(비밀번호 있음)
python run.py --shop donggwang --naver-excel 스마트스토어_발주발송.xlsx --password 1234
```

## 8. 기타

* `python run.py --history` : 최근 발송 이력 50건
* `logs\YYYY-MM.log` : 실행 로그
* 쿠팡 주문자 번호는 **안심번호(0502…)** 로 옵니다. 카카오톡은 안심번호로 직접 전달이 안 되므로
  `aligo.failover: "Y"` (실패 시 문자 대체) 를 켜 두어야 실제 고객에게 도달합니다. 지금 수동으로 보내던 방식과 동일합니다.
* 네이버는 "발송처리(송장 등록)된 주문" 을 가져옵니다. 발송처리 전(배송준비 상태)에는 송장번호가 API에 없어 알림톡을 만들 수 없습니다.

## 파일 구조

```
run.py                     실행기 (CLI)
config.example.yaml        설정 예시 → config.yaml 로 복사해서 사용
alimtalk_auto/
  aligo.py                 알리고 알림톡 API (템플릿 자동 로드, 500건 배치 발송)
  naver.py                 네이버 커머스API (토큰, 변경주문 조회, 상세 조회)
  coupang.py               쿠팡 Open API (HMAC 서명, 발주서 조회)
  excel_sources.py         엑셀 파일 입력 (쿠팡 DeliveryList / 네이버 발주발송관리)
  cleaner.py               옵션명 정리
  pipeline.py              수집→필터→발송→리포트
  store.py                 발송 이력(sqlite)
  common.py                설정/휴무일/공통
```

## 9. 클라우드 서버(리눅스)에서 돌리기 – PC 꺼져 있어도 발송

오라클 클라우드 Always Free 등 우분투 서버에 이 폴더를 올린 뒤:

```bash
bash setup_linux.sh          # 파이썬 설치, 크론(15:30/16:30 평일) 등록, 서버 IP 출력
nano config.yaml             # 키 입력
.venv/bin/python run.py --check
.venv/bin/python run.py --shop ojingeo_mom --dry-run
```
출력된 서버 IP를 알리고 "발신 IP" 에 등록하세요. 휴무일 조정은 서버의 config.yaml 을 고치거나 `touch PAUSE` / `rm PAUSE`.
