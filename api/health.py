"""기준 사이트 접속 점검 엔드포인트 (Vercel) — Upstash QStash가 15분마다 호출한다.

⚠️ 이 프로젝트에서는 /api/* 요청이 전부 api/index.py로 들어가므로, 실제 /api/health 처리는
api/index.py가 health_entry.handle_health_request로 분기해서 한다. 이 파일은 Vercel이 파일별로
경로를 연결하는 환경에서도 같은 동작을 하도록 같은 함수를 쓰는 얇은 래퍼다.
"""
import json
from http.server import BaseHTTPRequestHandler

from health_entry import handle_health_request


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        status, payload = handle_health_request(self.headers.get("Upstash-Signature", ""), body)

        out = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self):
        # 브라우저 확인용 — 점검은 서명된 POST에서만 실행된다.
        msg = b"ohaasa health endpoint: OK (signed POST only)"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(msg)))
        self.end_headers()
        self.wfile.write(msg)
