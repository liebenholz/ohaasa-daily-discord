"""주말 기준 사이트 도쿄 중계 — Vercel 도쿄 리전(hnd1)에서 대신 받아온다.

주말 사이트(tv-asahi.co.jp)는 일본 밖 IP에 406을 돌려준다. GitHub Actions 러너는 일본 밖이라 직접
크롤링할 수 없어서, 도쿄 리전에서 도는 /api/relay가 대신 GET해 HTML을 그대로 돌려주고 main.py가
그 HTML을 기존 파서로 처리한다 (페이지 데이터가 정적 HTML에 있어 JS 실행이 필요 없다).

⚠️ 아무나 쓰는 오픈 프록시가 되지 않도록:
  - 가져오는 URL은 주말 사이트 하나로 고정 (호출자가 URL을 줄 수 없다)
  - X-Relay-Token 헤더가 환경변수 RELAY_TOKEN과 일치해야만 동작
  - RELAY_TOKEN이 설정돼 있지 않으면 기능 자체가 꺼진다 (503)
"""
import os
import hmac
import json

import requests

from source_health import SITES, HEADERS

TARGET_URL = SITES["weekend"]["url"]
TIMEOUT = (3, 8)  # (연결, 응답) 초


def _json(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def handle_relay_request(token: str) -> tuple[int, str, bytes]:
    """(HTTP 상태코드, Content-Type, 본문)을 반환한다."""
    expected = os.environ.get("RELAY_TOKEN", "")
    if not expected:
        return 503, "application/json; charset=utf-8", _json({"error": "relay disabled (RELAY_TOKEN not set)"})
    if not token or not hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8")):
        return 401, "application/json; charset=utf-8", _json({"error": "invalid token"})

    try:
        r = requests.get(TARGET_URL, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException as e:
        return 502, "application/json; charset=utf-8", _json({"error": "upstream request failed", "detail": type(e).__name__})

    if r.status_code != 200:
        return 502, "application/json; charset=utf-8", _json({"error": "upstream error", "upstream_status": r.status_code})

    return 200, "text/html; charset=utf-8", r.content
