"""관리 페이지 - 브라우저(폰)에서 휴무일/일시정지/즉시발송/이력 확인

  python run.py --web            → http://서버IP:8080/?token=관리비밀번호
"""
from __future__ import annotations

import html
import json
import logging
import threading
import traceback
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

from .common import load_config, why_skip_today
from .state import State
from .store import SentLog

log = logging.getLogger("alimtalk.web")
_busy = threading.Lock()

CSS = """<style>
body{font-family:-apple-system,system-ui,'Malgun Gothic',sans-serif;max-width:820px;margin:0 auto;padding:16px;color:#222;background:#fafafa}
h2{margin:8px 0 4px} h3{margin:22px 0 8px;font-size:16px;border-top:1px solid #e5e5e5;padding-top:16px}
.card{background:#fff;border:1px solid #e5e5e5;border-radius:12px;padding:14px;margin:10px 0}
button{padding:12px 16px;margin:4px 4px 4px 0;border-radius:10px;border:1px solid #ccc;background:#f3f3f3;font-size:15px;cursor:pointer}
button.stop{background:#ffe3e3;border-color:#ea9999} button.go{background:#e3f0ff;border-color:#8fb8e8}
button.small{padding:5px 9px;font-size:13px}
.big{font-size:18px;font-weight:700} .ok{color:#1a7f37} .warn{color:#b42318}
table{border-collapse:collapse;width:100%;font-size:13px;margin-top:6px}
td,th{border:1px solid #e5e5e5;padding:5px 7px;text-align:left} th{background:#f6f6f6}
input,select{padding:10px;font-size:15px;border:1px solid #ccc;border-radius:8px}
details{margin:6px 0} summary{cursor:pointer;padding:6px 0}
.muted{color:#777;font-size:13px}
</style>"""


def _esc(s):
    return html.escape(str(s if s is not None else ""))


class Handler(BaseHTTPRequestHandler):
    cfg_path = "config.yaml"
    token = ""

    def _cfg(self):
        return load_config(self.cfg_path)

    def log_message(self, *a):
        pass

    # ------------------------------------------------------------ 공통
    def _auth(self, q) -> bool:
        return bool(self.token) and (q.get("token", [""])[0] == self.token)

    def _send(self, body: str, code=200, ctype="text/html; charset=utf-8"):
        b = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    # ------------------------------------------------------------ GET
    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if not self._auth(q):
            return self._send("<h3>주소가 올바르지 않습니다</h3>", 404)
        try:
            self._send(self.page(q))
        except Exception:
            self._send("<pre>" + _esc(traceback.format_exc()) + "</pre>", 500)

    # ------------------------------------------------------------ POST
    def do_POST(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if not self._auth(q):
            return self._send("<h3>주소가 올바르지 않습니다</h3>", 404)
        n = int(self.headers.get("Content-Length") or 0)
        form = parse_qs(self.rfile.read(n).decode("utf-8"))
        g = lambda k: (form.get(k) or [""])[0]
        action = g("action")
        cfg = self._cfg()
        st = State(cfg["_base_dir"])
        msg = ""
        try:
            if action == "pause":
                st.pause(g("reason")); msg = "일시정지했습니다. 다시 시작을 누를 때까지 발송하지 않습니다."
            elif action == "resume":
                st.resume(); msg = "다시 시작했습니다."
            elif action == "addhol":
                d1, d2 = g("date"), g("date2")
                if d1:
                    days = [d1]
                    if d2 and d2 > d1:
                        a, b = date.fromisoformat(d1), date.fromisoformat(d2)
                        days = [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]
                    for d in days:
                        st.add_holiday(d, g("note"))
                    msg = f"휴무일 {len(days)}일 추가했습니다."
            elif action == "delhol":
                st.del_holiday(g("day")); msg = "휴무일을 지웠습니다."
            elif action in ("run", "dry"):
                shop = g("shop")
                if not _busy.acquire(blocking=False):
                    msg = "이미 실행 중입니다. 잠시 후 다시 시도하세요."
                else:
                    try:
                        from .pipeline import run_shop
                        r = run_shop(cfg, shop, dry_run=(action == "dry"), force=True)
                        if r.get("skipped_day"):
                            msg = f"오늘은 발송하지 않는 날입니다 ({r['skipped_day']})"
                        else:
                            msg = (("[테스트] " if action == "dry" else "") +
                                   f"발송 {r.get('sent', 0)}건 / 건너뜀 {r.get('skipped', 0)}건")
                    finally:
                        _busy.release()
        except Exception as e:
            msg = "오류: " + str(e)
            log.exception("관리페이지 작업 실패")
        self.send_response(303)
        self.send_header("Location", f"/?token={quote(self.token)}&msg={quote(msg[:200])}")
        self.end_headers()

    # ------------------------------------------------------------ 화면
    def page(self, q) -> str:
        cfg = self._cfg()
        st = State(cfg["_base_dir"])
        st.cleanup_past()
        s = st.load()
        why = why_skip_today(cfg)
        t = self.token
        msg = (q.get("msg", [""])[0])

        head = f"<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>알림톡 자동발송</title>{CSS}<h2>배송 알림톡 자동발송</h2>"
        if msg:
            head += f"<div class='card' style='background:#fffbe6'>{_esc(msg)}</div>"

        # 상태
        if s.get("paused"):
            state_html = (f"<div class='big warn'>⏸ 일시정지 중</div>"
                          f"<div class='muted'>{_esc(s.get('paused_reason') or '')}</div>"
                          f"<form method=post action='/?token={t}'><input type=hidden name=action value=resume>"
                          f"<button class='go'>▶ 다시 시작</button></form>")
        else:
            state_html = (f"<div class='big ok'>▶ 정상 작동 중</div>"
                          f"<div class='muted'>오늘: {'발송 가능' if not why else _esc(why) + ' → 오늘은 발송하지 않습니다'}</div>"
                          f"<form method=post action='/?token={t}'><input type=hidden name=action value=pause>"
                          f"<input name=reason placeholder='이유 (예: 택배사 파업)' style='width:60%'> "
                          f"<button class='stop'>⏸ 발송 멈추기</button></form>")

        sched = "".join(
            f"<li>{_esc(v.get('display_name', k))} — 평일 {_esc(v.get('run_at', '-'))}</li>"
            for k, v in (cfg.get("shops") or {}).items())

        # 휴무일
        rows = ""
        for d in s.get("holidays") or []:
            note = (s.get("notes") or {}).get(d, "")
            wd = "월화수목금토일"[date.fromisoformat(d).weekday()]
            rows += (f"<tr><td>{_esc(d)} ({wd})</td><td>{_esc(note)}</td>"
                     f"<td><form method=post action='/?token={t}' style='margin:0'>"
                     f"<input type=hidden name=action value=delhol><input type=hidden name=day value='{_esc(d)}'>"
                     f"<button class='small'>지우기</button></form></td></tr>")
        hol = (f"<table><tr><th>날짜</th><th>메모</th><th></th></tr>{rows}</table>"
               if rows else "<p class='muted'>지정된 휴무일이 없습니다. (주말·공휴일은 자동으로 쉽니다)</p>")

        # 상점별 실행 버튼
        runs = ""
        for k, v in (cfg.get("shops") or {}).items():
            nm = _esc(v.get("display_name", k))
            runs += (f"<div style='margin:8px 0'><b>{nm}</b><br>"
                     f"<form method=post action='/?token={t}' style='display:inline'>"
                     f"<input type=hidden name=action value=dry><input type=hidden name=shop value='{_esc(k)}'>"
                     f"<button>테스트 (발송 안 함)</button></form>"
                     f"<form method=post action='/?token={t}' style='display:inline'>"
                     f"<input type=hidden name=action value=run><input type=hidden name=shop value='{_esc(k)}'>"
                     f"<button class='go'>지금 발송</button></form></div>")

        # 최근 이력
        try:
            recent = SentLog(f"{cfg['_base_dir']}/sent.db").recent(30)
        except Exception:
            recent = []
        hist = "".join(
            f"<tr><td>{_esc(r[0][5:16].replace('T', ' '))}</td><td>{_esc(r[1])}</td><td>{_esc(r[3])}</td>"
            f"<td>{_esc(r[4])}</td><td>{_esc(r[6])}</td><td>{_esc(r[7])}</td>"
            f"<td>{'테스트' if r[8] else ''}</td></tr>" for r in recent)
        hist = (f"<table><tr><th>시각</th><th>상점</th><th>주문번호</th><th>주문자</th><th>상품</th><th>운송장</th><th></th></tr>{hist}</table>"
                if hist else "<p class='muted'>아직 발송 이력이 없습니다.</p>")

        today = date.today().isoformat()
        return f"""{head}
<div class='card'>{state_html}<ul class='muted'>{sched}</ul></div>

<h3>배송 휴무일</h3>
<div class='card'>{hol}
<form method=post action='/?token={t}' style='margin-top:10px'>
  <input type=hidden name=action value=addhol>
  <div style='margin:6px 0'>날짜 <input type=date name=date value='{today}' required>
   ~ <input type=date name=date2> <span class='muted'>(하루만 쉬면 뒤쪽은 비워두세요)</span></div>
  <div style='margin:6px 0'><input name=note placeholder='메모 (예: 추석 택배 휴무)' style='width:60%'>
   <button class='go'>휴무일 추가</button></div>
</form></div>

<h3>지금 실행</h3>
<div class='card'>{runs}
<p class='muted'>‘테스트’는 알림톡을 보내지 않고 대상만 확인합니다. ‘지금 발송’은 휴무일이어도 실행되며, 이미 보낸 주문은 자동으로 제외됩니다.</p></div>

<h3>최근 발송 이력</h3>
<div class='card'>{hist}</div>
<p class='muted'>이 주소는 외부에 공유하지 마세요.</p>"""


def serve(cfg_path: str, token: str, port: int = 8080):
    Handler.cfg_path = cfg_path
    Handler.token = token
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    log.info("관리 페이지 실행: http://<서버주소>:%d/?token=%s", port, token)
    srv.serve_forever()
