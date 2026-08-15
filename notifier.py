"""디스코드 알림 발송 (Bot API, 멀티 채널)

main.py / stats.py가 공용으로 사용한다. 채널 하나가 실패해도 나머지는 계속
발송하며, 등록된 채널이 없거나 필요한 환경변수가 없으면 조용히 종료한다.
"""
import os
import time
import requests

from channels import list_channel_entries, remove_channel

DISCORD_API = "https://discord.com/api/v10"
SEND_DELAY = 0.5  # 채널 간 순차 발송 간격 (rate limit 대비)


def send_embed_to_channels(embed: dict, entries: list[tuple[str, str]] | None = None) -> None:
    if entries is None:
        try:
            entries = list_channel_entries()
        except Exception as e:
            print(f"⚠️  등록 채널 목록 조회 실패 — Bot API 발송 생략: {e}")
            return

    if not entries:
        print("ℹ️  등록된 알림 채널이 없습니다 — Bot API 발송 생략")
        return

    bot_token = os.environ.get("DISCORD_BOT_TOKEN")
    if not bot_token:
        print("⚠️  DISCORD_BOT_TOKEN 미설정 — Bot API 발송 생략")
        return

    headers = {"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"}

    for i, (guild_id, channel_id) in enumerate(entries):
        try:
            r = requests.post(
                f"{DISCORD_API}/channels/{channel_id}/messages",
                headers=headers,
                json={"embeds": [embed]},
                timeout=10,
            )
            if r.status_code == 403:
                print(f"⚠️  채널 {channel_id} 권한 없음(403) — 등록 해제")
                remove_channel(guild_id)
            elif r.status_code >= 400:
                print(f"⚠️  채널 {channel_id} 발송 실패: {r.status_code} {r.text[:200]}")
            else:
                print(f"✅ 채널 {channel_id} 발송 완료")
        except requests.RequestException as e:
            print(f"⚠️  채널 {channel_id} 발송 중 예외: {e}")

        if i < len(entries) - 1:
            time.sleep(SEND_DELAY)
