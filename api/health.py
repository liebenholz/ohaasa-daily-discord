"""기준 사이트 접속 점검 엔드포인트 (Vercel) — Upstash QStash가 15분마다 호출한다.

QStash 서명(Upstash-Signature)이 유효한 POST만 처리한다. 점검 로직과 알림은
source_health.py에 있다. 서명 검증 실패 시 401, 점검 중 예외는 500을 돌려줘서
QStash 로그에서 실패를 바로 확인할 수 있게 한다.
"""
import json
from http.server import BaseHTTPRequestHandler

from qstash_verify import verify_qstash_signature
from source_health import run_health_check


class handler(BaseHTTPRequestHandler):
    def _reply(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        ok, reason = verify_qstash_signature(self.headers.get("Upstash-Signature", ""), body)
        if not ok:
            print(f"⛔ 서명 검증 실패: {reason}")
            self._reply(401, {"error": reason})
            return

        try:
            result = run_health_check()
        except Exception as e:
            print(f"❌ 헬스체크 실행 실패: {e}")
            self._reply(500, {"error": str(e)})
            return

        print(f"🩺 헬스체크: {result}")
        self._reply(200, result)

    def do_GET(self):
        # 브라우저 확인용 — 점검은 서명된 POST에서만 실행된다.
        msg = b"ohaasa health endpoint: OK (signed POST only)"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(msg)))
        self.end_headers()
        self.wfile.write(msg)
