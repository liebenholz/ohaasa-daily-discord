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


def _upstash(*parts) -> object:
    url = "/".join([_upstash_url(), *[str(p) for p in parts]])
    r = requests.get(
        url,
        headers={"Authorization": f"Bearer {_upstash_token()}"},
        timeout=5,
    )
    r.raise_for_status()
    return r.json().get("result")


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


def list_channels() -> list[str]:
    """등록된 모든 채널 id 목록 (발송 모듈용)."""
    guild_ids = _upstash("smembers", INDEX_KEY) or []
    channels = []
    for guild_id in guild_ids:
        channel_id = get_channel(guild_id)
        if channel_id:
            channels.append(channel_id)
    return channels
