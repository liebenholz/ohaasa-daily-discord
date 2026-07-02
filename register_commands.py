import os
import requests

APP_ID    = os.environ["DISCORD_APP_ID"]
BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
GUILD_ID  = os.environ.get("DISCORD_GUILD_ID")  # 있으면 길드 한정 = 즉시 반영

SIGNS = [
    "양자리", "황소자리", "쌍둥이자리", "게자리",
    "사자자리", "처녀자리", "천칭자리", "전갈자리",
    "사수자리", "염소자리", "물병자리", "물고기자리",
]

command = {
    "name": "오하아사",
    "description": "오늘의 오하아사 별자리 운세를 확인합니다",
    "options": [{
        "name": "별자리",
        "description": "조회할 별자리",
        "type": 3,           # STRING
        "required": True,
        "choices": [{"name": s, "value": s} for s in SIGNS],
    }],
}

url = (
    f"https://discord.com/api/v10/applications/{APP_ID}/guilds/{GUILD_ID}/commands"
    if GUILD_ID
    else f"https://discord.com/api/v10/applications/{APP_ID}/commands"
)
r = requests.post(url, headers={"Authorization": f"Bot {BOT_TOKEN}"}, json=command, timeout=10)
print(r.status_code, r.text)
r.raise_for_status()