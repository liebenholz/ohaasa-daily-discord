"""월간 오하아사 순위 리포트 — 채널 요약 메시지 + 쓰레드로 별자리별 상세 정보 발송

stats.py의 후속 버전. 채널 요약 메시지의 문구/구성은 기존 stats.py(build_description)를
그대로 따르고, 그 메시지에 쓰레드를 만들어 별자리별 개별 리포트(일별 순위 꺾은선그래프
포함)를 12위→1위 순으로 추가 발송한다. 연간 리포트(annual_stats.py)의 쓰레드와 달리
'최고의 달/최악의 달'은 없다 — 한 달치 리포트에는 월간 비교 자체가 성립하지 않는다.
대신 그래프는 월 단위가 아니라 그 달의 일 단위로 그린다.

⚠️ 9월 30일까지는 기존 stats.py가 매달 말일 자동 발송을 계속 담당한다.
   10월 1일부터 이 스크립트로 대체할 예정이며, 그 전까지는 수동/테스트 실행만 한다.

사용법:
  python monthly_stats.py 2026-09      # 특정 월 수동 실행
  python monthly_stats.py              # 자동: 오늘(KST)이 말일이면 이번 달 리포트

발송 대상은 아래 TARGET_MODE 상수로 전환한다 (기본은 테스트 채널만).
"""
import os
import sys
import time
import urllib.parse
import json
from datetime import datetime, timedelta, date

from ranking_stats import load_period, aggregate, month_range, pick_mode_rank
from channels import list_channel_entries
from notifier import send_with_retry, create_thread, bot_headers

# ── 발송 대상 선택 ──────────────────────────────────────────────
# 기본: 테스트 길드/채널로만 발송 (안전). 아래 두 줄 중 하나만 활성화한다.
TARGET_MODE = "test"
# TARGET_MODE = "all"   # 전체 등록 길드로 실제 발송 — 위 줄을 주석 처리하고 이 줄을 활성화

SEND_DELAY = 0.7  # 쓰레드 내 메시지 간 간격 (rate limit 대비)

RANK_EMOJI = {1: "👑", 2: "🥈", 3: "🥉"}
RANK_COLOR = {1: 0xF1C40F, 2: 0xBEC2CB, 3: 0xCD7F32}  # 1~3위 전용 색상 (금/은/동) — 유지 대상


def _resolve_targets() -> list[tuple[str, str]]:
    if TARGET_MODE == "all":
        entries = list_channel_entries()
        print(f"🌐 전체 발송 모드 — 등록된 {len(entries)}개 서버 대상")
        return entries

    channel_id = os.environ.get("TEST_CHANNEL_ID")
    if not channel_id:
        print("❌ TEST_CHANNEL_ID 환경변수가 없습니다.")
        sys.exit(1)
    guild_id = os.environ.get("TEST_GUILD_ID", "test")
    print(f"🧪 테스트 모드 — 채널 {channel_id} 로만 발송")
    return [(guild_id, channel_id)]


def kst_today() -> date:
    return (datetime.utcnow() + timedelta(hours=9)).date()


# ─────────────────────────────────────────────
# 통계 산출 — ranking_stats.py의 load_period/aggregate/pick_mode_rank 재사용,
# 여기선 일별 순위 목록(그래프용)만 새로 만든다.
# ─────────────────────────────────────────────
def build_monthly_stats(days: list[dict]) -> list[dict]:
    """12개 별자리의 이달 통계를 만들고, 평균 순위 기준으로 1~12위를 매긴다."""
    agg = aggregate(days)  # {sign: {avg, stdev, first, last, days}}

    per_sign_ranks: dict[str, list[int]] = {}
    per_sign_daily: dict[str, list[tuple[str, int]]] = {}
    for day in sorted(days, key=lambda d: d["date"]):
        for sign, rank in day["ranks"].items():
            per_sign_ranks.setdefault(sign, []).append(rank)
            per_sign_daily.setdefault(sign, []).append((day["date"], rank))

    ranked_signs = sorted(agg.items(), key=lambda kv: kv[1]["avg"])

    stats = []
    for i, (sign_kr, a) in enumerate(ranked_signs):
        mode_rank, mode_days = pick_mode_rank(per_sign_ranks[sign_kr])
        stats.append({
            "rank": i + 1,
            "sign_kr": sign_kr,
            "avg": a["avg"],
            "first_count": a["first"],
            "last_count": a["last"],
            "stdev": a["stdev"],
            "daily": per_sign_daily[sign_kr],  # [(date_iso, rank), ...] 날짜 오름차순
            "mode_rank": mode_rank,
            "mode_days": mode_days,
        })
    return stats


# ─────────────────────────────────────────────
# 임베드 구성
# ─────────────────────────────────────────────
def build_daily_chart_url(daily: list[tuple[str, int]]) -> str:
    """일별 순위 꺾은선그래프 — QuickChart 이미지 URL. y축은 1위가 위로 오도록 반전.

    annual_stats.py는 월 단위(1월~8월 등)로 그리지만, 이건 하루 단위(1일~말일)로 그린다.
    """
    labels = [f"{int(date_iso[8:10])}일" for date_iso, _ in daily]
    values = [rank for _, rank in daily]

    config = {
        "type": "line",
        "data": {
            "labels": labels,
            "datasets": [{
                "label": "일별 순위",
                "data": values,
                "borderColor": "#9B59B6",
                "backgroundColor": "rgba(155, 89, 182, 0.15)",
                "fill": True,
                "tension": 0.3,
                "pointRadius": 2,
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
    return f"https://quickchart.io/chart?w=560&h=220&bkg=white&c={encoded}"


def build_summary_embed(stats: list[dict], period_label: str, day_count: int, label: str) -> dict:
    """① 채널 메인 메시지 — stats.py의 기존 문구(평균 순위 + 이달의 수상)를 그대로 재현."""
    lines = ["**📈 평균 순위**"]
    for s in stats:
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(s["rank"], "🔹")
        lines.append(f"{medal} {s['rank']}위 {s['sign_kr']} (평균 {s['avg']:.2f}위)")

    most_first = max(stats, key=lambda s: s["first_count"])
    most_last = max(stats, key=lambda s: s["last_count"])
    stable = min(stats, key=lambda s: s["stdev"])
    chaotic = max(stats, key=lambda s: s["stdev"])

    lines += [
        "",
        "**🏆 이달의 수상**",
        f"👑 최다 1위: {most_first['sign_kr']} ({most_first['first_count']}회)",
        f"🌧️ 최다 12위: {most_last['sign_kr']} ({most_last['last_count']}회)",
        f"🧘 안정형 상: {stable['sign_kr']} (표준편차 {stable['stdev']:.2f})",
        f"🎢 기복형 상: {chaotic['sign_kr']} (표준편차 {chaotic['stdev']:.2f})",
    ]

    return {
        "title": f"📊 {label} 오하아사 월간 리포트",
        "description": "\n".join(lines),
        "color": 0xF1C40F,
        "footer": {"text": f"{period_label} · 집계 {day_count}일"},
    }


def build_sign_embed(s: dict) -> dict:
    """② 쓰레드 내부 개별 리포트 — 별자리 1개. 연간판과 달리 최고/최악의 달 없음."""
    emoji = RANK_EMOJI.get(s["rank"], "🔹")
    color = RANK_COLOR.get(s["rank"], 0x9B59B6)

    description = (
        f"이달 평균 {s['avg']:.2f}위\n\n"
        f"👑 1위 {s['first_count']}회 · 🌧️ 12위 {s['last_count']}회\n"
        f"🎯 최다 등수: {s['mode_rank']}위 ({s['mode_days']}일)\n"
        f"📊 변동성: 표준편차 {s['stdev']:.2f}"
    )

    return {
        "title": f"{emoji} {s['rank']}위 — {s['sign_kr']}",
        "description": description,
        "color": color,
        "image": {"url": build_daily_chart_url(s["daily"])},
    }


# ─────────────────────────────────────────────
# 발송
# ─────────────────────────────────────────────
def send_monthly_report(
    guild_id: str, channel_id: str, stats: list[dict],
    period_label: str, day_count: int, label: str,
) -> bool:
    headers = bot_headers()
    if not headers:
        print("❌ DISCORD_BOT_TOKEN 미설정 — 발송 불가")
        return False

    summary_embed = build_summary_embed(stats, period_label, day_count, label)
    result = send_with_retry(channel_id, summary_embed, headers)
    if result["outcome"] != "success":
        print(f"❌ [{guild_id}] 요약 메시지 발송 실패: {result}")
        return False
    message_id = result["body"]["id"]
    print(f"✅ [{guild_id}] 요약 메시지 발송 (message_id={message_id})")

    thread_name = f"🧵 {label} 별자리별 상세"
    thread_result = create_thread(channel_id, message_id, thread_name, headers)
    if thread_result["outcome"] != "success":
        print(f"❌ [{guild_id}] 쓰레드 생성 실패: {thread_result}")
        return False
    thread_id = thread_result["body"]["id"]
    print(f"✅ [{guild_id}] 쓰레드 생성 (thread_id={thread_id})")

    by_rank_desc = sorted(stats, key=lambda s: -s["rank"])  # 12위 → 1위, 마지막이 챔피언
    ok = 0
    for i, s in enumerate(by_rank_desc):
        embed = build_sign_embed(s)
        r = send_with_retry(thread_id, embed, headers)
        if r["outcome"] == "success":
            ok += 1
            print(f"   ✅ [{i + 1}/{len(by_rank_desc)}] {s['rank']}위 {s['sign_kr']}")
        else:
            print(f"   ❌ [{i + 1}/{len(by_rank_desc)}] {s['rank']}위 {s['sign_kr']} 실패: {r}")
        if i < len(by_rank_desc) - 1:
            time.sleep(SEND_DELAY)

    print(f"📬 [{guild_id}] 쓰레드 발송 완료: {ok}/{len(by_rank_desc)} 성공")
    return ok == len(by_rank_desc)


def run_report(start_iso: str, end_iso: str, label: str):
    days = load_period(start_iso, end_iso)
    if not days:
        print(f"❌ {label} 기간에 데이터가 없습니다 ({start_iso} ~ {end_iso})")
        return

    stats = build_monthly_stats(days)
    period_label = f"{start_iso} ~ {end_iso}"

    entries = _resolve_targets()
    if not entries:
        print("❌ 발송 대상이 없습니다.")
        return

    total_ok = 0
    for guild_id, channel_id in entries:
        if send_monthly_report(guild_id, channel_id, stats, period_label, len(days), label):
            total_ok += 1

    print(f"\n{'=' * 50}\n 전체 결과: {total_ok}/{len(entries)}개 서버 성공\n{'=' * 50}")


def main():
    args = sys.argv[1:]

    # ── 수동 모드: python monthly_stats.py 2026-09
    if len(args) == 1:
        y, m = map(int, args[0].split("-"))
        s, e = month_range(y, m)
        run_report(s, e, f"{y}년 {m}월")
        return
    if args:
        print("사용법: python monthly_stats.py [2026-09]")
        sys.exit(1)

    # ── 자동 모드: 오늘(KST)이 말일이면 이번 달 리포트
    today = kst_today()
    if (today + timedelta(days=1)).day != 1:
        print(f"오늘({today})은 말일이 아님 — 리포트 생략")
        return

    s, e = month_range(today.year, today.month)
    run_report(s, e, f"{today.year}년 {today.month}월")


if __name__ == "__main__":
    main()
