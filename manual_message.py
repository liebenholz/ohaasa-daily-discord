"""수동 메시지 발송 — 자동 크롤링이 불가능한 날, 직접 작성/복사한 내용을 임베드로 보낸다.

기준 사이트 접속 장애 등으로 일일 알림을 만들 수 없을 때 쓴다. 본문은 두 가지 중 하나로 준다.
  1) 워크플로 입력(message) — 한 줄. 줄바꿈은 글자 그대로 \\n 으로 적는다.
  2) 저장소의 manual_message.txt — 여러 줄 본문을 그대로 붙여넣을 때 (입력이 비어 있으면 이 파일을 읽는다)

발송 대상은 --target 으로 고른다 (기본 test).
  test : TEST_CHANNEL_ID 채널 하나로만 (미리보기)
  all  : Redis에 등록된 모든 서버 채널

사용법 (보통은 GitHub Actions의 Manual Message 워크플로로 실행한다)
  python manual_message.py --target test
  python manual_message.py --target all --title "제목" --message "1위 처녀자리\\n2위 게자리"
  python manual_message.py --dry-run      # 발송 없이 임베드 미리보기만
"""
import os
import sys
import argparse
from datetime import datetime, timedelta

from channels import list_channel_entries
from notifier import send_embed_to_channels, bot_headers

DEFAULT_TITLE = "✨ 오늘의 별자리 운세 ✨"
MESSAGE_FILE = "manual_message.txt"
EMBED_COLOR = 0x9B59B6
TITLE_LIMIT = 256          # Discord 임베드 제목 최대 길이
DESCRIPTION_LIMIT = 4096   # Discord 임베드 본문 최대 길이


def fail(msg: str):
    print(f"❌ {msg}")
    sys.exit(1)


def get_date_display() -> str:
    kst = datetime.utcnow() + timedelta(hours=9)
    wd = ["월", "화", "수", "목", "금", "토", "일"][kst.weekday()]
    return kst.strftime(f"%Y-%m-%d ({wd})")


def load_message(input_value: str) -> str:
    """입력값이 있으면 그것을(\\n → 줄바꿈), 없으면 manual_message.txt를 읽는다."""
    if input_value and input_value.strip():
        return input_value.replace("\\n", "\n").strip()
    if os.path.exists(MESSAGE_FILE):
        with open(MESSAGE_FILE, encoding="utf-8") as f:
            return f.read().strip()
    return ""


def build_embed(title: str, message: str) -> dict:
    return {
        "title": title,
        "description": message,
        "color": EMBED_COLOR,
        "footer": {"text": f"{get_date_display()} · 수동 발송"},
    }


def resolve_entries(target: str) -> list[tuple[str, str]]:
    if target == "all":
        try:
            entries = list_channel_entries()
        except Exception as e:
            fail(f"등록 채널 목록 조회 실패: {e}")
        if not entries:
            fail("등록된 알림 채널이 없습니다.")
        print(f"🌐 전체 발송 — 등록된 {len(entries)}개 서버 대상")
        return entries

    channel_id = os.environ.get("TEST_CHANNEL_ID")
    if not channel_id:
        fail("TEST_CHANNEL_ID 환경변수가 없습니다.")
    guild_id = os.environ.get("TEST_GUILD_ID", "test")
    print(f"🧪 테스트 발송 — 채널 {channel_id} 하나로만")
    return [(guild_id, channel_id)]


def main():
    p = argparse.ArgumentParser(description="수동 메시지 발송")
    p.add_argument("--target", choices=["test", "all"], default=os.environ.get("TARGET") or "test")
    p.add_argument("--title", default=os.environ.get("TITLE") or DEFAULT_TITLE)
    p.add_argument("--message", default=os.environ.get("MESSAGE", ""))
    p.add_argument("--dry-run", action="store_true", help="발송하지 않고 임베드 미리보기만")
    args = p.parse_args()

    message = load_message(args.message)
    if not message:
        fail(f"본문이 비어 있습니다 — message 입력 또는 {MESSAGE_FILE}에 내용을 넣어주세요.")
    if len(args.title) > TITLE_LIMIT:
        fail(f"제목이 너무 깁니다 ({len(args.title)}자 / 최대 {TITLE_LIMIT}자)")
    if len(message) > DESCRIPTION_LIMIT:
        fail(f"본문이 너무 깁니다 ({len(message)}자 / 최대 {DESCRIPTION_LIMIT}자)")

    embed = build_embed(args.title, message)
    print("─" * 50)
    print(f"[제목] {embed['title']}")
    print(embed["description"])
    print(f"[푸터] {embed['footer']['text']}")
    print("─" * 50)

    if args.dry_run:
        print("ℹ️  --dry-run — 발송하지 않고 종료")
        return

    # 설정 누락으로 아무것도 안 나가는데 성공으로 끝나는 일을 막는다
    if not bot_headers():
        fail("DISCORD_BOT_TOKEN 미설정 — 발송 불가")

    entries = resolve_entries(args.target)
    send_embed_to_channels(embed, entries=entries)


if __name__ == "__main__":
    main()
