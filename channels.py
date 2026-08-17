"""서버별 알림 채널 등록 저장소 (Upstash Redis REST API)

키 스키마:
  channels:{guild_id}  → channel_id (문자열)
  channels:index       → 등록된 guild_id들의 Set (전체 목록 조회용)

api/index.py의 설정 커맨드(/오하아사설정)와, 추후 발송 모듈(notifier.py)이
공용으로 사용한다.
"""
import os
import requests

INDEX_KEY = "channels:index"


def _upstash_url():
    return os.environ["UPSTASH_REDIS_REST_URL"].rstrip("/")


def _upstash_token():
    return os.environ["UPSTASH_REDIS_REST_TOKEN"]


def _upstash(*command) -> object:
    """단일 명령을 POST 본문(JSON 배열)으로 전송한다.

    URL 경로에 명령을 실어 보내는 방식(GET /sadd/key/member)은 콜론 등
    특수문자가 낀 키에서 게이트웨이/프록시 단에서 오동작할 여지가 있어,
    Upstash가 권장하는 POST + JSON 배열 방식으로 우회한다.
    """
    r = requests.post(
        _upstash_url(),
        headers={
            "Authorization": f"Bearer {_upstash_token()}",
            "Content-Type": "application/json",
        },
        json=[str(p) for p in command],
        timeout=5,
    )
    r.raise_for_status()
    body = r.json()
    if isinstance(body, dict) and body.get("error"):
        raise RuntimeError(f"Upstash 오류: {body['error']} (명령: {command})")
    return body.get("result")


def _channel_key(guild_id) -> str:
    return f"channels:{guild_id}"


def get_channel(guild_id) -> str | None:
    return _upstash("get", _channel_key(guild_id))


def set_channel(guild_id, channel_id) -> None:
    """등록/변경 — 기존 값을 덮어쓴다."""
    _upstash("set", _channel_key(guild_id), channel_id)
    _upstash("sadd", INDEX_KEY, guild_id)


def remove_channel(guild_id) -> None:
    _upstash("del", _channel_key(guild_id))
    _upstash("srem", INDEX_KEY, guild_id)


def list_channel_entries() -> list[tuple[str, str]]:
    """등록된 [(guild_id, channel_id), ...] 전체 목록 (발송 모듈용).

    발송 실패 시 guild_id로 등록을 해제해야 하므로 guild_id를 함께 반환한다.
    """
    guild_ids = _upstash("smembers", INDEX_KEY) or []
    entries = []
    for guild_id in guild_ids:
        channel_id = get_channel(guild_id)
        if channel_id:
            entries.append((guild_id, channel_id))
    return entries


# ─────────────────────────────────────────────
# 실행 간 발송 이력 (같은 날짜의 예비 cron 재시도가 이미 성공한
# guild를 건너뛸 수 있도록) — sent:{run_key} Set, 3일 TTL
# ─────────────────────────────────────────────
SENT_TTL_SECONDS = 3 * 24 * 3600


def _sent_key(run_key: str) -> str:
    return f"sent:{run_key}"


def get_sent_guild_ids(run_key: str) -> set[str]:
    result = _upstash("smembers", _sent_key(run_key)) or []
    return set(result)


def mark_sent(run_key: str, guild_id: str) -> None:
    key = _sent_key(run_key)
    _upstash("sadd", key, guild_id)
    _upstash("expire", key, SENT_TTL_SECONDS)
