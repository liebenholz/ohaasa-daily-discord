"""연간 리포트(4단계) 사전 검증 — 쓰레드 생성 테스트

기존 코드를 전혀 import하지 않는 독립 실행 스크립트입니다.
연간 리포트가 실제로 하게 될 3단계 흐름을 그대로 예행합니다.

    ① 채널에 요약 메시지 발송        → message_id 확보
    ② 그 메시지에 쓰레드 생성         → thread_id 확보
    ③ 쓰레드 안에 개별 리포트 N개 발송

필요한 환경변수
    DISCORD_BOT_TOKEN     봇 토큰 (필수)
    TEST_CHANNEL_ID       테스트 채널 ID (필수)
    TEST_GUILD_ID         테스트 서버 ID (선택 — 채널 소속 검증용)

GitHub Actions용 환경변수 (CLI 플래그와 동일 효과)
    THREAD_TEST_COUNT     쓰레드 메시지 수 (기본 3, 최대 12)
    THREAD_TEST_CHECK_ONLY  "true"이면 권한 확인만 (발송 안 함)
    THREAD_TEST_CLEANUP     "true"이면 테스트 후 쓰레드 삭제

사용법
    python test/test_thread.py                 # 전체 흐름 테스트 (메시지 3개)
    python test/test_thread.py --count 12      # 실제 연간 리포트와 동일하게 12개
    python test/test_thread.py --check-only    # 권한만 확인, 메시지 발송 안 함
    python test/test_thread.py --cleanup       # 테스트로 만든 쓰레드 삭제 시도
"""

import os
import sys
import time
import json
import math
import argparse
import urllib.request
import urllib.error
import urllib.parse

API = "https://discord.com/api/v10"

BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
CHANNEL_ID = os.environ.get("TEST_CHANNEL_ID")
GUILD_ID = os.environ.get("TEST_GUILD_ID")

# 쓰레드 관련 권한 비트
PERM_VIEW_CHANNEL           = 1 << 10   # 1024
PERM_SEND_MESSAGES          = 1 << 11   # 2048
PERM_EMBED_LINKS            = 1 << 14   # 16384
PERM_CREATE_PUBLIC_THREADS  = 1 << 35   # 34359738368
PERM_SEND_MESSAGES_IN_THREADS = 1 << 38 # 274877906944

REQUIRED_PERMS = [
    (PERM_VIEW_CHANNEL,             "채널 보기"),
    (PERM_SEND_MESSAGES,            "메시지 보내기"),
    (PERM_EMBED_LINKS,              "링크 첨부"),
    (PERM_CREATE_PUBLIC_THREADS,    "공개 스레드 만들기"),
    (PERM_SEND_MESSAGES_IN_THREADS, "스레드에서 메시지 보내기"),
]


# ─────────────────────────────────────────────
# HTTP 유틸
# ─────────────────────────────────────────────
def call(method, path, payload=None):
    """Discord API 호출. (status, body_dict) 반환"""
    url = API + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bot {BOT_TOKEN}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "OhaasaThreadTest/1.0")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            body = json.loads(raw)
        except Exception:
            body = {"raw": raw}
        return e.code, body
    except Exception as e:
        return 0, {"error": str(e)}


def explain_error(status, body):
    """자주 나오는 에러를 사람 말로 풀어줌"""
    code = body.get("code")
    msg = body.get("message", "")
    hints = {
        50001: "봇이 이 채널을 볼 수 없습니다. 채널 권한에 봇(또는 봇 역할)을 추가하고 '채널 보기'를 허용하세요.",
        50013: "권한이 부족합니다. 아래 권한 확인 결과를 참고해 누락된 항목을 부여하세요.",
        10003: "채널을 찾을 수 없습니다. TEST_CHANNEL_ID가 올바른지 확인하세요.",
        10008: "메시지를 찾을 수 없습니다. 이미 삭제되었을 수 있습니다.",
        160004: "이 메시지에는 이미 스레드가 있습니다.",
        50024: "이 채널에서는 스레드를 만들 수 없습니다 (포럼/음성 채널 등).",
    }
    line = f"   status={status} code={code} message={msg}"
    if code in hints:
        line += f"\n   → {hints[code]}"
    return line


# ─────────────────────────────────────────────
# 사전 점검
# ─────────────────────────────────────────────
def check_env():
    missing = []
    if not BOT_TOKEN:
        missing.append("DISCORD_BOT_TOKEN")
    if not CHANNEL_ID:
        missing.append("TEST_CHANNEL_ID")
    if missing:
        print(f"❌ 환경변수 누락: {', '.join(missing)}")
        print("\n   설정 예시 (macOS/Linux):")
        print('     export DISCORD_BOT_TOKEN="..."')
        print('     export TEST_CHANNEL_ID="1234567890123456789"')
        print('     export TEST_GUILD_ID="9876543210987654321"   # 선택')
        sys.exit(1)

    for name, val in (("TEST_CHANNEL_ID", CHANNEL_ID), ("TEST_GUILD_ID", GUILD_ID)):
        if val and not (val.isdigit() and 17 <= len(val) <= 20):
            print(f"⚠️  {name}={val} 형식이 이상합니다 (숫자 17~20자리여야 함)")


def check_bot_identity():
    status, body = call("GET", "/users/@me")
    if status != 200:
        print("❌ 봇 토큰 확인 실패")
        print(explain_error(status, body))
        sys.exit(1)
    print(f"🤖 봇: {body.get('username')}#{body.get('discriminator')} (id={body.get('id')})")
    return body.get("id")


def check_channel():
    status, body = call("GET", f"/channels/{CHANNEL_ID}")
    if status != 200:
        print("❌ 채널 조회 실패")
        print(explain_error(status, body))
        sys.exit(1)

    ch_type = body.get("type")
    type_names = {0: "텍스트", 5: "공지", 15: "포럼", 2: "음성"}
    print(f"📺 채널: #{body.get('name')} (type={ch_type} {type_names.get(ch_type, '기타')})")

    if ch_type not in (0, 5):
        print(f"⚠️  이 채널 타입에서는 메시지 기반 스레드 생성이 제한될 수 있습니다.")

    guild = body.get("guild_id")
    print(f"🏠 소속 서버(guild): {guild}")
    if GUILD_ID and guild != GUILD_ID:
        print(f"⚠️  TEST_GUILD_ID({GUILD_ID})와 채널의 실제 guild({guild})가 다릅니다!")
    return guild


def check_permissions(bot_id, guild_id):
    """봇의 해당 채널 실효 권한을 확인"""
    if not guild_id:
        print("⚠️  guild_id를 알 수 없어 권한 확인을 건너뜁니다.")
        return

    status, member = call("GET", f"/guilds/{guild_id}/members/{bot_id}")
    if status != 200:
        print("⚠️  봇 멤버 정보 조회 실패 — 권한 확인 생략")
        print(explain_error(status, member))
        return

    # 역할 권한 합산 (채널 오버라이드는 반영되지 않는 근사치)
    status, roles = call("GET", f"/guilds/{guild_id}/roles")
    if status != 200:
        print("⚠️  역할 조회 실패 — 권한 확인 생략")
        return

    role_map = {r["id"]: int(r["permissions"]) for r in roles}
    perms = 0
    for rid in member.get("roles", []):
        perms |= role_map.get(rid, 0)
    # @everyone 역할(= guild_id와 동일한 id)도 포함
    perms |= role_map.get(guild_id, 0)

    ADMINISTRATOR = 1 << 3
    if perms & ADMINISTRATOR:
        print("🔑 권한: Administrator (모든 권한 보유)")
        return

    print("🔑 역할 기준 권한 확인 (채널별 오버라이드는 미반영):")
    missing = []
    for bit, name in REQUIRED_PERMS:
        ok = bool(perms & bit)
        print(f"   {'✅' if ok else '❌'} {name}")
        if not ok:
            missing.append(name)

    if missing:
        print(f"\n   ⚠️  누락 가능: {', '.join(missing)}")
        print("   서버 설정 → 역할 → 봇 역할, 또는 채널 편집 → 권한에서 부여하세요.")
        print("   (채널별 오버라이드로 이미 허용했다면 실제 발송은 성공할 수 있습니다)")


# ─────────────────────────────────────────────
# 더미 데이터 — 연간 리포트 UI 시안 재현용
# (연간 순위 1~12위 순서. index 0 = 1위 ... index 11 = 12위)
# ─────────────────────────────────────────────
SIGNS_RANKED = [
    ("처녀자리", "おとめ座"),
    ("게자리",   "かに座"),
    ("물고기자리", "うお座"),
    ("황소자리", "おうし座"),
    ("사자자리", "しし座"),
    ("쌍둥이자리", "ふたご座"),
    ("양자리",   "おひつじ座"),
    ("천칭자리", "てんびん座"),
    ("사수자리", "いて座"),
    ("염소자리", "やぎ座"),
    ("물병자리", "みずがめ座"),
    ("전갈자리", "さそり座"),
]

RANK_EMOJI = {1: "👑", 2: "🥈", 3: "🥉"}
RANK_COLOR = {1: 0xF1C40F, 2: 0xBEC2CB, 3: 0xCD7F32}  # 1~3위 전용 색상 (금/은/동) — 유지 대상

# 별자리(연간 순위 index)별 표준편차 더미값 — 전부 다른 값이어야 안정형/기복형 상이
# 한쪽으로 쏠리지 않는다.
STDEV_POOL = [2.89, 4.50, 3.60, 3.35, 3.10, 2.95, 2.92, 2.40, 2.10, 1.75, 1.40, 3.87]


def build_dummy_yearly_stats():
    """12개 별자리의 더미 연간 통계를 결정론적으로 생성한다 (매 실행 동일 결과).

    실제 데이터가 아니라 UI 시안(전체 랭킹표 + 수상 4종 + 개별 리포트 통계)을
    재현하기 위한 값이며, 매번 같은 값이 나와야 디버깅이 쉬워서 random을 쓰지 않는다.
    """
    stats = []
    for i, (sign_kr, sign_ja) in enumerate(SIGNS_RANKED):
        rank = i + 1
        avg = round(4.0 + i * 0.42, 2)                     # 1위일수록 낮은(좋은) 평균
        first_count = max(1, 60 - i * 5)                     # 1위일수록 1위 횟수 많음
        last_count = max(1, 3 + i * 4)                       # 12위일수록 12위 횟수 많음
        stdev = STDEV_POOL[i]
        monthly = [
            round(min(12.0, max(1.0, avg + 2.2 * math.sin((m + i) / 1.8))), 2)
            for m in range(12)
        ]
        mode_rank = max(1, min(12, round(avg)))
        mode_days = 30 + (i % 4) * 8

        stats.append({
            "rank": rank, "sign_kr": sign_kr, "sign_ja": sign_ja,
            "avg": avg, "first_count": first_count, "last_count": last_count,
            "monthly": monthly, "stdev": stdev,
            "mode_rank": mode_rank, "mode_days": mode_days,
        })

    return stats


def build_monthly_chart_url(monthly: list) -> str:
    """월별 평균 순위 꺾은선그래프 — QuickChart 이미지 URL. y축은 1위가 위로 오도록 반전."""
    config = {
        "type": "line",
        "data": {
            "labels": [f"{m}월" for m in range(1, 13)],
            "datasets": [{
                "label": "월별 평균 순위",
                "data": monthly,
                "borderColor": "#9B59B6",
                "backgroundColor": "rgba(155, 89, 182, 0.15)",
                "fill": True,
                "tension": 0.35,
                "pointRadius": 3,
            }],
        },
        "options": {
            "legend": {"display": False},
            "scales": {
                "yAxes": [{"ticks": {"min": 1, "max": 12, "stepSize": 1, "reverse": True}}],
            },
        },
    }
    encoded = urllib.parse.quote(json.dumps(config))
    return f"https://quickchart.io/chart?w=520&h=220&bkg=white&c={encoded}"


def build_summary_embed(stats: list) -> dict:
    """① 채널 메인 메시지 — 연간 요약 (골드 컬러, 전체 랭킹 + 수상 4종)"""
    lines = ["**📈 연간 평균 순위**"]
    for s in stats:
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(s["rank"], "🔹")
        lines.append(f"{medal} {s['rank']}위 {s['sign_kr']} (평균 {s['avg']:.2f}위)")

    most_first = max(stats, key=lambda s: s["first_count"])
    most_last = max(stats, key=lambda s: s["last_count"])
    stable = min(stats, key=lambda s: s["stdev"])
    chaotic = max(stats, key=lambda s: s["stdev"])

    lines += [
        "",
        "**🏆 올해의 수상**",
        f"👑 최다 1위: {most_first['sign_kr']} ({most_first['first_count']}회)",
        f"🌧️ 최다 12위: {most_last['sign_kr']} ({most_last['last_count']}회)",
        f"🧘 안정형 상: {stable['sign_kr']} (표준편차 {stable['stdev']:.2f})",
        f"🎢 기복형 상: {chaotic['sign_kr']} (표준편차 {chaotic['stdev']:.2f})",
    ]

    return {
        "title": "🧪 [TEST] 2026년 오하아사 연간 리포트",
        "description": "\n".join(lines),
        "color": 0xF1C40F,   # 골드
        "footer": {"text": "2026-01-01 ~ 2026-12-31 · 집계 365일 · 쓰레드 생성 테스트용 더미 데이터"},
    }


def build_sign_embed(s: dict) -> dict:
    """② 쓰레드 내부 개별 리포트 — 별자리 1개"""
    emoji = RANK_EMOJI.get(s["rank"], "🔹")
    color = RANK_COLOR.get(s["rank"], 0x9B59B6)   # 1~3위 전용 색상 유지, 그 외는 기본 보라
    best_month = min(range(12), key=lambda m: s["monthly"][m]) + 1
    worst_month = max(range(12), key=lambda m: s["monthly"][m]) + 1

    description = (
        f"연간 평균 {s['avg']:.2f}위\n\n"
        f"👑 1위 {s['first_count']}회 · 🌧️ 12위 {s['last_count']}회\n"
        f"🎯 최다 등수: {s['mode_rank']}위 ({s['mode_days']}일)\n"
        f"📊 변동성: 표준편차 {s['stdev']:.2f}\n"
        f"🌸 최고의 달: {best_month}월 (평균 {min(s['monthly']):.2f}위)\n"
        f"🍂 최악의 달: {worst_month}월 (평균 {max(s['monthly']):.2f}위)\n\n"
        "_더미 데이터입니다._"
    )

    return {
        "title": f"{emoji} {s['rank']}위 — {s['sign_kr']}",
        "description": description,
        "color": color,
        "image": {"url": build_monthly_chart_url(s["monthly"])},
    }


# ─────────────────────────────────────────────
# 실제 흐름 테스트
# ─────────────────────────────────────────────
def post_summary(stats):
    """① 요약 메시지 발송 (연간 랭킹 1~12위 전체 + 수상 4종)"""
    embed = build_summary_embed(stats)
    status, body = call("POST", f"/channels/{CHANNEL_ID}/messages", {"embeds": [embed]})
    if status not in (200, 201):
        print("❌ ① 요약 메시지 발송 실패")
        print(explain_error(status, body))
        return None
    msg_id = body["id"]
    print(f"✅ ① 요약 메시지 발송 성공 (message_id={msg_id})")
    return msg_id


def create_thread(message_id):
    """② 메시지에 쓰레드 생성"""
    payload = {
        "name": "🧪 [TEST] 2026 별자리별 연간 결산",
        "auto_archive_duration": 1440,   # 24시간 후 자동 보관
    }
    status, body = call(
        "POST", f"/channels/{CHANNEL_ID}/messages/{message_id}/threads", payload
    )
    if status not in (200, 201):
        print("❌ ② 쓰레드 생성 실패")
        print(explain_error(status, body))
        return None
    thread_id = body["id"]
    print(f"✅ ② 쓰레드 생성 성공 (thread_id={thread_id}, name={body.get('name')})")
    return thread_id


def post_to_thread(thread_id, stats, count, delay):
    """③ 쓰레드에 개별 리포트 발송 (12위 → 1위 순서 예행, 마지막이 챔피언)"""
    by_rank_desc = sorted(stats, key=lambda s: -s["rank"])  # 12위 ... 1위
    selected = by_rank_desc[:min(count, len(by_rank_desc))]
    n = len(selected)
    ok_count = 0

    for i, s in enumerate(selected):
        embed = build_sign_embed(s)
        status, body = call("POST", f"/channels/{thread_id}/messages", {"embeds": [embed]})
        if status in (200, 201):
            ok_count += 1
            print(f"   ✅ [{i+1}/{n}] {s['rank']}위 {s['sign_kr']}")
        else:
            print(f"   ❌ [{i+1}/{n}] {s['rank']}위 {s['sign_kr']} 실패")
            print(explain_error(status, body))
            if status == 429:
                retry = body.get("retry_after", 1)
                print(f"      rate limit — {retry}s 대기 후 계속")
                time.sleep(retry)
        if i < n - 1:
            time.sleep(delay)

    print(f"✅ ③ 쓰레드 발송 완료: {ok_count}/{n} 성공")
    return ok_count == n


def cleanup_thread(thread_id):
    status, body = call("DELETE", f"/channels/{thread_id}")
    if status in (200, 204):
        print(f"🧹 쓰레드 삭제 완료 ({thread_id})")
    else:
        print(f"⚠️  쓰레드 삭제 실패 — 수동으로 지워주세요 ({thread_id})")
        print(explain_error(status, body))


# ─────────────────────────────────────────────
# 진입점
# ─────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="연간 리포트 쓰레드 생성 테스트")
    p.add_argument("--count", type=int, default=3, help="쓰레드에 보낼 개별 리포트 수 (기본 3, 최대 12)")
    p.add_argument("--delay", type=float, default=0.7, help="메시지 간 간격(초)")
    p.add_argument("--check-only", action="store_true", help="권한 확인만 하고 발송하지 않음")
    p.add_argument("--cleanup", action="store_true", help="테스트 후 쓰레드 삭제 시도")
    args = p.parse_args()

    # GitHub Actions 환경변수로 CLI 플래그를 오버라이드
    # (workflow_dispatch inputs → env로 전달한 값이 우선됨)
    env_count = os.environ.get("THREAD_TEST_COUNT")
    if env_count and env_count.isdigit():
        args.count = int(env_count)
    if os.environ.get("THREAD_TEST_CHECK_ONLY", "").lower() == "true":
        args.check_only = True
    if os.environ.get("THREAD_TEST_CLEANUP", "").lower() == "true":
        args.cleanup = True

    print("=" * 56)
    print(" 연간 리포트 쓰레드 생성 테스트")
    print("=" * 56)

    check_env()
    bot_id = check_bot_identity()
    guild_id = check_channel()
    check_permissions(bot_id, guild_id)

    if args.check_only:
        print("\n✅ 사전 점검 완료 (--check-only 이므로 발송하지 않음)")
        return

    print("\n" + "-" * 56)
    print(" 실제 흐름 예행")
    print("-" * 56)

    stats = build_dummy_yearly_stats()

    msg_id = post_summary(stats)
    if not msg_id:
        sys.exit(1)

    thread_id = create_thread(msg_id)
    if not thread_id:
        print("\n💡 쓰레드 생성만 실패했다면 '공개 스레드 만들기' 권한을 확인하세요.")
        sys.exit(1)

    all_ok = post_to_thread(thread_id, stats, args.count, args.delay)

    if args.cleanup:
        print()
        cleanup_thread(thread_id)

    print("\n" + "=" * 56)
    if all_ok:
        print(" ✅ 전체 흐름 성공 — 연간 리포트 구현 가능")
    else:
        print(" ⚠️  일부 단계 실패 — 위 로그 확인 필요")
    print("=" * 56)


if __name__ == "__main__":
    main()
