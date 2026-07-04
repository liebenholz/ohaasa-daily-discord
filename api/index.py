import os
import json
import urllib.request
from http.server import BaseHTTPRequestHandler
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

# ─────────────────────────────────────────────
# 환경변수 (lazy — import 시점에 읽지 않음)
# ─────────────────────────────────────────────
def _get_public_key():
    return os.environ["DISCORD_PUBLIC_KEY"]

GH_USER   = os.environ.get("GH_USER", "liebenholz")
GH_REPO   = os.environ.get("GH_REPO", "ohaasa-daily-discord")
GH_BRANCH = os.environ.get("GH_BRANCH", "main")

LATEST_URL = (
    f"https://raw.githubusercontent.com/{GH_USER}/{GH_REPO}/{GH_BRANCH}/data/latest.json"
)

TYPE_PONG            = 1
TYPE_CHANNEL_MESSAGE = 4
FLAG_EPHEMERAL       = 64

RATING_LABELS = {
    "money":  "💰 금전",
    "love":   "💕 애정",
    "work":   "💼 업무",
    "health": "🍎 건강",
}


# ─────────────────────────────────────────────
# 서명 검증
# ─────────────────────────────────────────────
def verify_signature(signature_hex, timestamp, body):
    try:
        VerifyKey(bytes.fromhex(_get_public_key())).verify(
            f"{timestamp}{body}".encode(), bytes.fromhex(signature_hex)
        )
        return True
    except (BadSignatureError, ValueError):
        return False


# ─────────────────────────────────────────────
# 데이터 조회
# ─────────────────────────────────────────────
def fetch_latest():
    req = urllib.request.Request(LATEST_URL, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


# ─────────────────────────────────────────────
# 임베드 생성 (한국어 전용, 컴팩트)
# ─────────────────────────────────────────────
def build_embed(sign_kr, data):
    mode = data.get("mode", "weekday")
    sign = (data.get("signs") or {}).get(sign_kr)

    if not sign:
        return {
            "title": f"❌ {sign_kr} 운세를 찾지 못했습니다",
            "description": "아직 오늘 데이터가 갱신되지 않았거나, 사이트 구조가 변경되었을 수 있습니다.",
            "color": 0xE74C3C,
        }

    rank = sign.get("rank", 0)
    emoji = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, "🔹")

    content_ko = sign.get("content_ko") or "(번역 데이터가 준비되지 않았습니다)"
    lines = [content_ko]

    lucky_color_ko = sign.get("lucky_color_ko")
    lucky_item_ko  = sign.get("lucky_item_ko")
    if lucky_color_ko or lucky_item_ko:
        lines.append("")
        if lucky_color_ko:
            lines.append(f"🎨 {lucky_color_ko}")
        if lucky_item_ko:
            lines.append(f"🍀 {lucky_item_ko}")

    lines.append("")
    lines.append(f"순위: {emoji} {rank}위")

    ratings = sign.get("ratings") or {}
    for key, label in RATING_LABELS.items():
        if key in ratings:
            count = ratings[key]
            stars = "⭐" * count if count > 0 else "—"
            lines.append(f"{label}: {stars}")

    return {
        "title": f"✨ 오늘의 {sign_kr} 운세 ✨",
        "description": "\n".join(lines),
        "color": 0x9B59B6,
        "footer": {
            "text": f"{data.get('date', '')} · {'평일' if mode == 'weekday' else '주말'} 기준"
        },
    }


# ─────────────────────────────────────────────
# 인터랙션 처리
# ─────────────────────────────────────────────
def handle_interaction(interaction):
    if interaction.get("type") == 1:
        return {"type": TYPE_PONG}

    if interaction.get("type") == 2:
        data = interaction.get("data", {})
        if data.get("name") == "오하아사":
            opts = {o["name"]: o["value"] for o in data.get("options", [])}
            sign_kr = opts.get("별자리")
            try:
                horoscope = fetch_latest()
                return {
                    "type": TYPE_CHANNEL_MESSAGE,
                    "data": {"embeds": [build_embed(sign_kr, horoscope)]},
                }
            except Exception as e:
                return {
                    "type": TYPE_CHANNEL_MESSAGE,
                    "data": {"content": f"❌ 운세 조회 실패: {e}", "flags": FLAG_EPHEMERAL},
                }

    return {
        "type": TYPE_CHANNEL_MESSAGE,
        "data": {"content": "지원하지 않는 명령입니다.", "flags": FLAG_EPHEMERAL},
    }


# ─────────────────────────────────────────────
# Vercel 엔트리포인트 — 반드시 소문자 'handler'
# ─────────────────────────────────────────────
class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")

        signature = self.headers.get("X-Signature-Ed25519", "")
        timestamp = self.headers.get("X-Signature-Timestamp", "")

        if not verify_signature(signature, timestamp, body):
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"invalid request signature")
            return

        response = handle_interaction(json.loads(body))
        body_bytes = json.dumps(response, ensure_ascii=False).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def do_GET(self):
        # 헬스체크용 (브라우저 확인 시)
        msg = b"ohaasa interactions endpoint: OK (POST only)"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(msg)))
        self.end_headers()
        self.wfile.write(msg)