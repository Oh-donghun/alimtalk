#!/usr/bin/env python3
"""
배송 알림톡 자동발송 실행기

  python run.py --shop ojingeo_mom            # 오징어엄마 지금 즉시 실행(API 수집 → 알리고 발송)
  python run.py --shop donggwang --dry-run    # 발송은 안 하고 결과/엑셀만 확인
  python run.py --daemon                      # 켜두면 각 상점의 run_at 시각에 자동 실행
  python run.py --web                         # 자동실행 + 관리 페이지(휴무일/일시정지) 동시 실행
  python run.py --shop ojingeo_mom --coupang-excel DeliveryList.xlsx --excel-only
                                              # 쿠팡 엑셀 → 알리고 업로드용 엑셀 변환만
  python run.py --shop donggwang --naver-excel 주문.xlsx --password 1234
                                              # 네이버 엑셀(비밀번호) → 발송
  python run.py --history                     # 최근 발송 이력 보기
  python run.py --shop ojingeo_mom --check    # 알리고 템플릿/포인트, API 연결 점검
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from alimtalk_auto.common import load_config, setup_logging, why_skip_today  # noqa: E402
from alimtalk_auto.pipeline import run_shop  # noqa: E402
import logging  # noqa: E402

log = logging.getLogger("alimtalk")


def main():
    ap = argparse.ArgumentParser(description="배송 알림톡 자동발송")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--shop", help="상점 키 (config.yaml 의 shops 아래 이름). 생략하면 전체")
    ap.add_argument("--dry-run", action="store_true", help="발송하지 않고 대상만 확인 + 엑셀 저장")
    ap.add_argument("--excel-only", action="store_true", help="알리고 업로드용 엑셀만 생성 (발송 X)")
    ap.add_argument("--force", action="store_true", help="휴무일/PAUSE 무시하고 실행")
    ap.add_argument("--ignore-sent", action="store_true", help="이미 보낸 주문도 다시 대상에 포함")
    ap.add_argument("--naver-excel", help="네이버 발주발송관리 엑셀 파일 경로 (API 대신 사용)")
    ap.add_argument("--coupang-excel", help="쿠팡 DeliveryList 엑셀 파일 경로 (API 대신 사용)")
    ap.add_argument("--password", help="네이버 엑셀 비밀번호")
    ap.add_argument("--daemon", action="store_true", help="상주하며 run_at 시각에 자동 실행")
    ap.add_argument("--history", action="store_true", help="최근 발송 이력 출력")
    ap.add_argument("--check", action="store_true", help="설정/연결 점검")
    ap.add_argument("--web", action="store_true", help="관리 페이지 실행 (휴무일/일시정지/즉시발송)")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg["_base_dir"], args.verbose)

    if args.history:
        from alimtalk_auto.store import SentLog
        for row in SentLog(Path(cfg["_base_dir"], "sent.db")).recent(50):
            print(" | ".join(str(x) for x in row))
        return

    if args.check:
        return check(cfg, args.shop)

    if args.web:
        from alimtalk_auto.web import serve
        tok = (cfg.get("web") or {}).get("token")
        if not tok:
            raise SystemExit("config.yaml 에 web.token 을 정하세요 (관리 페이지 비밀번호)")
        port = (cfg.get("web") or {}).get("port", args.port)
        import threading
        threading.Thread(target=daemon, args=(cfg,), daemon=True).start()
        return serve(args.config, tok, int(port))

    if args.daemon:
        return daemon(cfg)

    shops = [args.shop] if args.shop else list(cfg["shops"].keys())
    for k in shops:
        if k not in cfg["shops"]:
            raise SystemExit(f"상점 키 '{k}' 가 config.yaml 에 없습니다. 가능: {list(cfg['shops'])}")
        r = run_shop(cfg, k, dry_run=args.dry_run, force=args.force,
                     excel_only=args.excel_only, naver_excel=args.naver_excel,
                     coupang_excel=args.coupang_excel, password=args.password,
                     ignore_sent=args.ignore_sent)
        log.info("[%s] 결과: %s", k, r)


def check(cfg, shop_key):
    from alimtalk_auto.aligo import Aligo
    print("오늘 발송 여부:", why_skip_today(cfg) or "발송 가능일")
    keys = [shop_key] if shop_key else list(cfg["shops"])
    a = cfg["aligo"]
    for k in keys:
        s = cfg["shops"][k]
        print(f"\n=== {s.get('display_name', k)} ({k}) run_at={s.get('run_at')}")
        try:
            al = Aligo(a["userid"], a["apikey"], a["sender"], s["aligo"]["senderkey"],
                       s["aligo"]["tpl_code"], template_text=s["aligo"].get("template_text"))
            t = al.template()
            print("  알리고 템플릿:", t.get("templtName"), "/ 승인상태:", t.get("inspStatus"))
            print("  변수:", al.variables)
            print("  본문:\n    " + (t.get("templtContent") or "").replace("\r\n", "\n").replace("\n", "\n    "))
            print("  잔여:", al.remaining())
        except Exception as e:
            print("  알리고 오류:", e)
        ch = s.get("channels", {})
        if ch.get("naver", {}).get("enabled"):
            from alimtalk_auto.naver import NaverCommerce
            try:
                NaverCommerce(ch["naver"]["client_id"], ch["naver"]["client_secret"]).token()
                print("  네이버 커머스API 인증: OK")
            except Exception as e:
                print("  네이버 커머스API 인증 실패:", e)
        if ch.get("coupang", {}).get("enabled"):
            from alimtalk_auto.coupang import Coupang
            c = ch["coupang"]
            try:
                n = len(Coupang(c["vendor_id"], c["access_key"], c["secret_key"],
                                c.get("api_version", "v4")).ordersheets(c.get("status", "DEPARTURE"), 1))
                print(f"  쿠팡 API: OK (최근 1일 {c.get('status','DEPARTURE')} {n}건)")
            except Exception as e:
                print("  쿠팡 API 실패:", e)


def daemon(cfg):
    import schedule
    for k, s in cfg["shops"].items():
        at = s.get("run_at")
        if not at:
            continue
        schedule.every().day.at(at).do(_safe_run, cfg, k)
        log.info("예약: %s → 매일 %s", s.get("display_name", k), at)
    log.info("대기 중... (창을 닫으면 멈춥니다. Ctrl+C 로 종료)")
    while True:
        schedule.run_pending()
        time.sleep(20)


def _safe_run(cfg, k):
    try:
        cfg2 = load_config(Path(cfg["_base_dir"], "config.yaml"))  # 매번 다시 읽음(휴무일 수정 반영)
        r = run_shop(cfg2, k)
        log.info("[%s] 결과: %s", k, r)
    except Exception as e:
        log.exception("[%s] 실행 중 오류: %s", k, e)


if __name__ == "__main__":
    main()
