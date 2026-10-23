"""Upstash QStash 요청 서명 검증 (표준 라이브러리만 사용)

QStash는 호출마다 `Upstash-Signature` 헤더에 HS256 JWT를 실어 보낸다. 이 토큰이
유효해야만 api/health.py가 동작하도록 해서, 아무나 URL을 두드려 점검/알림을
일으키지 못하게 막는다. 검증 규칙은 공식 SDK(qstash-py Receiver)와 같다:

  - 서명: 현재 키 → 실패하면 다음 키(키 로테이션 대비) 순으로 HMAC-SHA256 확인
  - 클레임: iss == "Upstash", sub/exp/nbf 필수, exp·nbf는 시계 오차 허용(leeway)
  - body: 요청 본문의 SHA-256을 urlsafe base64(패딩 제거)로 만든 값과 일치
  - sub(수신 URL)는 비교하지 않는다. 프록시/도메인 차이로 어긋나면 점검이 조용히
    죽기 때문이고, 서명 키를 가진 본인 QStash 계정이 만든 토큰만 통과하므로 위험이 낮다.
"""
import os
import hmac
import json
import time
import base64
import hashlib

LEEWAY_SECONDS = 60


def _b64url_decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def _signing_keys() -> list[str]:
    keys = (os.environ.get("QSTASH_CURRENT_SIGNING_KEY"), os.environ.get("QSTASH_NEXT_SIGNING_KEY"))
    return [k for k in keys if k]


def verify_qstash_signature(
    token: str, body: bytes, *, keys: list[str] | None = None, now: float | None = None,
) -> tuple[bool, str]:
    """(통과 여부, 사유)를 반환한다. 사유는 실패 시 로그/응답에 쓴다."""
    keys = _signing_keys() if keys is None else keys
    if not keys:
        return False, "signing key not configured"
    if not token:
        return False, "missing signature"

    parts = token.split(".")
    if len(parts) != 3:
        return False, "malformed token"

    try:
        header = json.loads(_b64url_decode(parts[0]))
        signature = _b64url_decode(parts[2])
    except (ValueError, json.JSONDecodeError):
        return False, "malformed token"
    if header.get("alg") != "HS256":
        return False, "unsupported algorithm"

    signing_input = f"{parts[0]}.{parts[1]}".encode()
    if not any(
        hmac.compare_digest(hmac.new(k.encode(), signing_input, hashlib.sha256).digest(), signature)
        for k in keys
    ):
        return False, "invalid signature"

    try:
        claims = json.loads(_b64url_decode(parts[1]))
    except (ValueError, json.JSONDecodeError):
        return False, "malformed token"

    if claims.get("iss") != "Upstash":
        return False, "invalid issuer"
    if any(c not in claims for c in ("sub", "exp", "nbf")):
        return False, "missing claims"

    now = time.time() if now is None else now
    if now > claims["exp"] + LEEWAY_SECONDS:
        return False, "signature expired"
    if now < claims["nbf"] - LEEWAY_SECONDS:
        return False, "signature not yet valid"

    body_hash = base64.urlsafe_b64encode(hashlib.sha256(body).digest()).decode().rstrip("=")
    if str(claims.get("body", "")).rstrip("=") != body_hash:
        return False, "body hash mismatch"

    return True, "ok"
