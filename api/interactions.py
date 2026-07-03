import os
import json
import urllib.request
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

GH_USER    = os.environ.get("GH_USER", "liebenholz")
GH_REPO    = os.environ.get("GH_REPO", "ohaasa-daily-discord")
GH_BRANCH  = os.environ.get("GH_BRANCH", "main")

LATEST_URL = (
    f"https://raw.githubusercontent.com/{GH_USER}/{GH_REPO}/{GH_BRANCH}/data/latest.json"
)

TYPE_PONG               = 1
TYPE_CHANNEL_MESSAGE    = 4
FLAG_EPHEMERAL          = 64

def _get_public_key():
    return os.environ["DISCORD_PUBLIC_KEY"]

def _get_app_id():
    return os.environ["DISCORD_APP_ID"]


def verify_signature(signature_hex, timestamp, body):
    try:
        VerifyKey(bytes.fromhex(_get_public_key())).verify(
            f"{timestamp}{body}".encode(), bytes.fromhex(signature_hex)
        )
        return True
    except (BadSignatureError, ValueError):
        return False


def fetch_latest():
    req = urllib.request.Request(LATEST_URL, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=2) as r:
        return json.loads(r.read())


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

    # 본문 (한국어만; 번역 실패 시 안내 문구)
    content_ko = sign.get("content_ko") or "(번역 데이터가 준비되지 않았습니다)"
    lines = [content_ko]

    # 럭키 정보 (한국어만 표시)
    lucky_color_ko = sign.get("lucky_color_ko")
    lucky_item_ko  = sign.get("lucky_item_ko")

    if lucky_color_ko or lucky_item_ko:
        lines.append("")  # 본문과 럭키 정보 사이 빈 줄
        if lucky_color_ko:
            lines.append(f"🎨 {lucky_color_ko}")
        if lucky_item_ko:
            lines.append(f"🍀 {lucky_item_ko}")

    return {
        "title": f"✨ 오늘의 {sign_kr} 운세 ✨",
        "description": "\n".join(lines),
        "color": 0x9B59B6,
        "fields": [
            {"name": "순위", "value": f"{emoji} {rank}위", "inline": True},
        ],
        "footer": {
            "text": f"{data.get('date', '')} · {'평일' if mode == 'weekday' else '주말'} 기준"
        },
    }


def handle_interaction(interaction: dict) -> dict:
    # PING (엔드포인트 등록 검증)
    if interaction.get("type") == 1:
        return {"type": TYPE_PONG}

    # APPLICATION_COMMAND
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
                    "data": {
                        "content": f"❌ 운세 조회 실패: {e}",
                        "flags": FLAG_EPHEMERAL,  # 본인에게만 보임
                    },
                }

    return {
        "type": TYPE_CHANNEL_MESSAGE,
        "data": {"content": "지원하지 않는 명령입니다.", "flags": FLAG_EPHEMERAL},
    }


# AWS Lambda 진입점 (API Gateway HTTP API 기준)
def lambda_handler(event, context):
    body = event.get("body", "") or ""
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    signature = headers.get("x-signature-ed25519", "")
    timestamp = headers.get("x-signature-timestamp", "")

    if not verify_signature(signature, timestamp, body):
        return {"statusCode": 401, "body": "invalid request signature"}

    response = handle_interaction(json.loads(body))
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json; charset=utf-8"},
        "body": json.dumps(response, ensure_ascii=False),
    }