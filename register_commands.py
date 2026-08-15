import os
import requests

APP_ID    = os.environ["DISCORD_APP_ID"]
BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
GUILD_ID  = os.environ.get("DISCORD_GUILD_ID")  # 있으면 길드 한정 = 즉시 반영

PERMISSION_MANAGE_GUILD = 0x20

SIGNS = [
    "양자리", "황소자리", "쌍둥이자리", "게자리",
    "사자자리", "처녀자리", "천칭자리", "전갈자리",
    "사수자리", "염소자리", "물병자리", "물고기자리",
]

horoscope_command = {
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

settings_command = {
    "name": "오하아사설정",
    "description": "오하아사 알림 채널을 관리합니다 (서버 관리자 전용)",
    "default_member_permissions": str(PERMISSION_MANAGE_GUILD),
    "options": [
        {
            "name": "알림설정",
            "description": "알림을 받을 채널을 등록하거나 변경합니다",
            "type": 1,  # SUB_COMMAND
            "options": [{
                "name": "채널",
                "description": "알림을 받을 채널",
                "type": 7,  # CHANNEL
                "required": True,
            }],
        },
        {
            "name": "알림확인",
            "description": "현재 설정된 알림 채널을 확인합니다",
            "type": 1,  # SUB_COMMAND
        },
        {
            "name": "알림해제",
            "description": "알림 채널 설정을 해제합니다",
            "type": 1,  # SUB_COMMAND
        },
    ],
}

url = (
    f"https://discord.com/api/v10/applications/{APP_ID}/guilds/{GUILD_ID}/commands"
    if GUILD_ID
    else f"https://discord.com/api/v10/applications/{APP_ID}/commands"
)

for command in (horoscope_command, settings_command):
    r = requests.post(url, headers={"Authorization": f"Bot {BOT_TOKEN}"}, json=command, timeout=10)
    print(command["name"], r.status_code, r.text)
    r.raise_for_status()