"""
번역 결과 미리보기 — 테스트 웹후크로 순위대로 임베드 전송

data/latest.json을 읽어 rank 오름차순(1위 → 12위)으로
테스트 채널에 임베드를 자동 전송합니다.

필요한 환경변수:
  TEST_DISCORD_WEBHOOK: 테스트 채널의 웹후크 URL
"""

import os
import sys
import json
import time
import requests

# 프로젝트 루트를 파이썬 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from interactions.handler import build_embed


TEST_WEBHOOK = os.environ.get("TEST_DISCORD_WEBHOOK")
LATEST_PATH = "data/latest.json"
SEND_DELAY = 0.6   # 웹후크 rate limit 대비 (초)


def load_latest() -> dict:
    if not os.path.exists(LATEST_PATH):
        print(f"❌ {LATEST_PATH} 파일이 없습니다. main.py를 먼저 실행해주세요.")
        sys.exit(1)

    with open(LATEST_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"📂 로드 완료: {LATEST_PATH}")
    print(f"   date={data.get('date')}, mode={data.get('mode')}, "
          f"별자리={len(data.get('signs', {}))}개")
    return data


def send_preview(sign_kr: str, data: dict, index: int, total: int):
    embed = build_embed(sign_kr, data)

    # 프리뷰임을 표시
    embed["title"] = f"🧪 [PREVIEW] {embed.get('title', '')}"

    # footer에 진행 표시 + 일본어 원문 대조
    original_footer = embed.get("footer", {}).get("text", "")
    sign = data.get("signs", {}).get(sign_kr, {})
    ja_content = sign.get("content_ja", "")
    ja_item = sign.get("lucky_item_ja", "")
    ja_color = sign.get("lucky_color_ja", "")

    debug_lines = [f"[{index}/{total}] {original_footer}"]
    if ja_content:
        debug_lines.append(f"🇯🇵 {ja_content}")
        extras = []
        if ja_color:
            extras.append(f"색: {ja_color}")
        if ja_item:
            extras.append(f"아이템: {ja_item}")
        if extras:
            debug_lines.append(" | ".join(extras))

    embed["footer"] = {"text": "\n".join(debug_lines)[:2000]}

    payload = {
        "username": "🧪 오하아사 프리뷰",
        "embeds": [embed],
    }

    r = requests.post(TEST_WEBHOOK, json=payload, timeout=10)
    if r.status_code not in (200, 204):
        print(f"  ⚠️  {sign_kr} 전송 실패: {r.status_code} {r.text[:200]}")
        return False
    print(f"  ✅ [{index}/{total}] {sign_kr}")
    return True


def main():
    if not TEST_WEBHOOK:
        print("❌ 환경변수 TEST_DISCORD_WEBHOOK 이 설정되지 않았습니다.")
        sys.exit(1)

    data = load_latest()
    signs_dict = data.get("signs", {})

    if not signs_dict:
        print("❌ 데이터에 별자리 정보가 없습니다.")
        sys.exit(1)

    # ⭐ rank 오름차순 정렬 (1위 → 12위)
    sorted_signs = sorted(
        signs_dict.items(),
        key=lambda kv: kv[1].get("rank", 999),
    )
    total = len(sorted_signs)

    print(f"\n📤 순위대로 {total}개 별자리를 테스트 웹후크로 전송합니다...\n")

    success_count = 0
    for i, (sign_kr, _) in enumerate(sorted_signs, start=1):
        if send_preview(sign_kr, data, i, total):
            success_count += 1
        if i < total:
            time.sleep(SEND_DELAY)

    print(f"\n✨ 완료: {success_count}/{total} 성공")
    if success_count < total:
        sys.exit(1)


if __name__ == "__main__":
    main()