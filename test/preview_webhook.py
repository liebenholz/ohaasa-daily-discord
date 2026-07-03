"""
번역 결과 미리보기 — 테스트 웹후크로 임베드 전송

사용법:
  # 기본: data/latest.json의 모든 별자리를 테스트 웹후크로 전송
  python tests/preview_webhook.py

  # 특정 별자리만 확인
  python tests/preview_webhook.py --sign 처녀자리 --sign 쌍둥이자리

  # 저장된 JSON이 아니라 지금 즉시 크롤+번역해서 프리뷰
  python tests/preview_webhook.py --live

  # 특정 날짜의 저장 파일 확인
  python tests/preview_webhook.py --date 2026-07-04
"""

import os
import sys
import json
import time
import argparse
import requests
from datetime import datetime, timedelta

# 프로젝트 루트를 파이썬 경로에 추가 (tests/ 하위에서 실행 시)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.interactions import build_embed  # 실제 봇 응답과 동일한 렌더러

# ─────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────
TEST_WEBHOOK = os.environ.get("TEST_DISCORD_WEBHOOK")
DEFAULT_SIGNS = [
    "양자리", "황소자리", "쌍둥이자리", "게자리",
    "사자자리", "처녀자리", "천칭자리", "전갈자리",
    "사수자리", "염소자리", "물병자리", "물고기자리",
]

# ─────────────────────────────────────────────
# 데이터 로드 (파일 또는 라이브)
# ─────────────────────────────────────────────
def load_from_file(date: str | None) -> dict:
    if date:
        path = f"data/horoscope_{date}.json"
    else:
        path = "data/latest.json"

    if not os.path.exists(path):
        raise FileNotFoundError(
            f"❌ {path} 파일이 없습니다. 먼저 main.py를 실행해 데이터를 만들어주세요."
        )

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"📂 로드 완료: {path} (date={data.get('date')}, mode={data.get('mode')})")
    return data


def load_live() -> dict:
    """크롤+번역을 즉시 실행 (저장은 하지 않음)"""
    from main import (
        SIGN_CONFIG, fetch_html, parse_horoscope_detail,
        enrich_with_translation, build_translator,
    )

    today = datetime.utcnow() + timedelta(hours=3)
    mode = "weekday" if today.weekday() < 5 else "weekend"
    date_iso = (datetime.utcnow() + timedelta(hours=9)).strftime("%Y-%m-%d")

    print(f"🌐 라이브 크롤링 시작 (mode={mode}, date={date_iso})")

    config = SIGN_CONFIG[mode]
    html = fetch_html(config["url"], config["selector"])
    detail = parse_horoscope_detail(html, mode)

    if not detail:
        raise RuntimeError("파싱 결과가 비어 있음 (셀렉터 확인 필요)")

    print(f"📝 번역 시작 ({len(detail)}개 별자리)")
    translator = build_translator()
    detail = enrich_with_translation(detail, mode, translator)

    return {
        "date": date_iso,
        "mode": mode,
        "source_url": config["url"],
        "updated_at_kst": (datetime.utcnow() + timedelta(hours=9))
                              .isoformat(timespec="seconds"),
        "signs": detail,
    }


# ─────────────────────────────────────────────
# 웹후크 전송 (봇 응답 형식과 동일한 embed)
# ─────────────────────────────────────────────
def send_preview(sign_kr: str, data: dict, index: int, total: int):
    """봇의 build_embed 결과를 그대로 웹후크로 전송"""
    embed = build_embed(sign_kr, data)

    # 프리뷰임을 알리는 표시를 제목 앞에 붙임
    embed["title"] = f"🧪 [PREVIEW] {embed.get('title', '')}"

    # footer에 진행 상황 및 원문 대조 정보 추가
    original_footer = embed.get("footer", {}).get("text", "")
    sign = data.get("signs", {}).get(sign_kr, {})
    ja_content = sign.get("content_ja", "")
    ja_item = sign.get("lucky_item_ja", "")
    ja_color = sign.get("lucky_color_ja", "")

    debug_footer = f"[{index}/{total}] {original_footer}"
    if ja_content:
        # 원문 확인용 - preview에서만 노출, 실제 봇 응답에는 없음
        debug_footer += f"\n🇯🇵 {ja_content}"
        if ja_color:
            debug_footer += f" | 색: {ja_color}"
        if ja_item:
            debug_footer += f" | 아이템: {ja_item}"

    embed["footer"] = {"text": debug_footer[:2000]}  # Discord 제한

    payload = {
        "username": "🧪 오하아사 프리뷰",
        "embeds": [embed],
    }

    r = requests.post(TEST_WEBHOOK, json=payload, timeout=10)
    if r.status_code not in (200, 204):
        print(f"  ⚠️  {sign_kr} 전송 실패: {r.status_code} {r.text}")
    else:
        print(f"  ✅ {sign_kr}")


# ─────────────────────────────────────────────
# 진입점
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="번역 결과 미리보기 웹후크 전송")
    parser.add_argument("--sign", action="append", default=None,
                        help="특정 별자리만 전송 (여러 번 지정 가능)")
    parser.add_argument("--date", default=None,
                        help="특정 날짜의 저장 파일 사용 (예: 2026-07-04)")
    parser.add_argument("--live", action="store_true",
                        help="저장된 파일 대신 즉시 크롤+번역")
    parser.add_argument("--delay", type=float, default=0.5,
                        help="별자리 간 전송 간격(초). 웹후크 rate limit 대비")
    args = parser.parse_args()

    if not TEST_WEBHOOK:
        print("❌ 환경변수 TEST_DISCORD_WEBHOOK 이 설정되지 않았습니다.")
        print("   예: export TEST_DISCORD_WEBHOOK='https://discord.com/api/webhooks/...'")
        sys.exit(1)

    # 데이터 로드
    if args.live:
        data = load_live()
    else:
        data = load_from_file(args.date)

    # 대상 별자리 결정
    available = list(data.get("signs", {}).keys())
    if args.sign:
        targets = [s for s in args.sign if s in available]
        missing = [s for s in args.sign if s not in available]
        if missing:
            print(f"⚠️  데이터에 없는 별자리: {missing}")
    else:
        # 기본 순서(정통 12별자리 순)로 정렬
        targets = [s for s in DEFAULT_SIGNS if s in available]

    if not targets:
        print("❌ 전송할 별자리가 없습니다.")
        sys.exit(1)

    print(f"\n📤 {len(targets)}개 별자리를 테스트 웹후크로 전송합니다...\n")

    for i, sign_kr in enumerate(targets, start=1):
        send_preview(sign_kr, data, i, len(targets))
        if i < len(targets):
            time.sleep(args.delay)

    print(f"\n✨ 프리뷰 완료: 테스트 채널을 확인해주세요.")


if __name__ == "__main__":
    main()