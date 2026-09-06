"""연간 오하아사 순위 리포트 — 채널 요약 메시지 + 쓰레드 형태로 발송

채널에 연간(또는 테스트용 기간) 요약 임베드를 올리고, 그 메시지에 쓰레드를 만들어
별자리별 개별 리포트(월별 평균 꺾은선그래프 포함)를 12위→1위 순으로 발송한다.

사용법:
  python annual_stats.py <시작일 YYYY-MM-DD> <종료일 YYYY-MM-DD>
  예) python annual_stats.py 2026-01-01 2026-08-31

발송 대상은 아래 TARGET_MODE 상수로 전환한다 (기본은 테스트 채널만).
"""
import os
import sys
import json
import time
import urllib.parse
from collections import Counter

from stats import load_period, aggregate
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


# ─────────────────────────────────────────────
# 통계 산출 — stats.py의 load_period/aggregate 재사용, 여기선 월별 분해와
# 최빈 등수만 새로 계산한다.
# ─────────────────────────────────────────────
def _months_present(days: list[dict]) -> list[int]:
    """days에 실제로 존재하는 월(1~12) 목록, 오름차순. 데이터가 있는 달만 반환한다."""
    return sorted({int(day["date"][5:7]) for day in days})


def aggregate_by_month(days: list[dict], months: list[int]) -> dict[str, dict[int, float]]:
    """별자리별 {월: 평균 순위} — 그래프용."""
    per_sign_month: dict[str, dict[int, list[int]]] = {}
    for day in days:
        month = int(day["date"][5:7])
        if month not in months:
            continue
        for sign, rank in day["ranks"].items():
            per_sign_month.setdefault(sign, {}).setdefault(month, []).append(rank)

    return {
        sign: {m: round(sum(rs) / len(rs), 2) for m, rs in by_month.items()}
        for sign, by_month in per_sign_month.items()
    }


def _pick_mode_rank(ranks: list[int]) -> tuple[int, int]:
    """최빈 등수 계산.

    최다 빈도 등수가 여럿이면(동점) 평균 순위가 더 좋을수록(등수 숫자가 작을수록)
    우선한다 — 후보 자체가 서로 다른 등수 숫자이므로 이는 '더 낮은(좋은) 등수
    우선'과 동일하다. 그래도 같으면 표준편차가 작은 쪽을 우선하기로 했지만,
    정수 후보가 서로 다른 이상 이 단계까지 내려갈 일은 실질적으로 없다.
    """
    counts = Counter(ranks)
    max_count = max(counts.values())
    best = min(r for r, c in counts.items() if c == max_count)
    return best, max_count


def build_yearly_stats(days: list[dict], months: list[int]) -> list[dict]:
    """12개 별자리의 실데이터 통계를 만들고, 평균 순위 기준으로 1~12위를 매긴다."""
    agg = aggregate(days)  # {sign: {avg, stdev, first, last, days}}
    monthly_by_sign = aggregate_by_month(days, months)

    per_sign_ranks: dict[str, list[int]] = {}
    for day in days:
        for sign, rank in day["ranks"].items():
            per_sign_ranks.setdefault(sign, []).append(rank)

    ranked_signs = sorted(agg.items(), key=lambda kv: kv[1]["avg"])

    stats = []
    for i, (sign_kr, a) in enumerate(ranked_signs):
        mode_rank, mode_days = _pick_mode_rank(per_sign_ranks[sign_kr])
        monthly_values = [monthly_by_sign[sign_kr][m] for m in months]
        stats.append({
            "rank": i + 1,
            "sign_kr": sign_kr,
            "avg": a["avg"],
            "first_count": a["first"],
            "last_count": a["last"],
            "stdev": a["stdev"],
            "monthly": monthly_values,
            "mode_rank": mode_rank,
            "mode_days": mode_days,
        })
    return stats


# ─────────────────────────────────────────────
# 임베드 구성 (test/test_thread.py에서 승인받은 형식 재현 — 실데이터용으로 별도 작성)
# ─────────────────────────────────────────────
def build_monthly_chart_url(months: list[int], monthly_values: list[float]) -> str:
    """월별 평균 순위 꺾은선그래프 — QuickChart 이미지 URL.

    y축은 1위가 위로 오도록 반전. 데이터가 있는 달만 그린다(예: 1~8월 테스트 시
    9~12월은 그래프에 그리지 않는다).
    """
    config = {
        "type": "line",
        "data": {
            "labels": [f"{m}월" for m in months],
            "datasets": [{
                "label": "월별 평균 순위",
                "data": monthly_values,
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


def build_summary_embed(stats: list[dict], period_label: str, day_count: int, year: int) -> dict:
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
        "title": f"🧪 [TEST] {year}년 오하아사 연간 리포트",
        "description": "\n".join(lines),
        "color": 0xF1C40F,  # 골드
        "footer": {"text": f"{period_label} · 집계 {day_count}일 · 테스트 발송"},
    }


def build_sign_embed(s: dict, months: list[int]) -> dict:
    """② 쓰레드 내부 개별 리포트 — 별자리 1개"""
    emoji = RANK_EMOJI.get(s["rank"], "🔹")
    color = RANK_COLOR.get(s["rank"], 0x9B59B6)

    monthly_values = s["monthly"]
    best_idx = min(range(len(monthly_values)), key=lambda i: monthly_values[i])
    worst_idx = max(range(len(monthly_values)), key=lambda i: monthly_values[i])
    best_month, worst_month = months[best_idx], months[worst_idx]

    description = (
        f"연간 평균 {s['avg']:.2f}위\n\n"
        f"👑 1위 {s['first_count']}회 · 🌧️ 12위 {s['last_count']}회\n"
        f"🎯 최다 등수: {s['mode_rank']}위 ({s['mode_days']}일)\n"
        f"📊 변동성: 표준편차 {s['stdev']:.2f}\n"
        f"🌸 최고의 달: {best_month}월 (평균 {monthly_values[best_idx]:.2f}위)\n"
        f"🍂 최악의 달: {worst_month}월 (평균 {monthly_values[worst_idx]:.2f}위)"
    )

    return {
        "title": f"{emoji} {s['rank']}위 — {s['sign_kr']}",
        "description": description,
        "color": color,
        "image": {"url": build_monthly_chart_url(months, monthly_values)},
    }


# ─────────────────────────────────────────────
# 발송
# ─────────────────────────────────────────────
def send_annual_report(
    guild_id: str, channel_id: str, stats: list[dict], months: list[int],
    period_label: str, day_count: int, year: int,
) -> bool:
    headers = bot_headers()
    if not headers:
        print("❌ DISCORD_BOT_TOKEN 미설정 — 발송 불가")
        return False

    summary_embed = build_summary_embed(stats, period_label, day_count, year)
    result = send_with_retry(channel_id, summary_embed, headers)
    if result["outcome"] != "success":
        print(f"❌ [{guild_id}] 요약 메시지 발송 실패: {result}")
        return False
    message_id = result["body"]["id"]
    print(f"✅ [{guild_id}] 요약 메시지 발송 (message_id={message_id})")

    thread_name = f"🧪 [TEST] {year}년 별자리별 연간 결산"
    thread_result = create_thread(channel_id, message_id, thread_name, headers)
    if thread_result["outcome"] != "success":
        print(f"❌ [{guild_id}] 쓰레드 생성 실패: {thread_result}")
        return False
    thread_id = thread_result["body"]["id"]
    print(f"✅ [{guild_id}] 쓰레드 생성 (thread_id={thread_id})")

    by_rank_desc = sorted(stats, key=lambda s: -s["rank"])  # 12위 → 1위, 마지막이 챔피언
    ok = 0
    for i, s in enumerate(by_rank_desc):
        embed = build_sign_embed(s, months)
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


def main():
    if len(sys.argv) != 3:
        print("사용법: python annual_stats.py <시작일 YYYY-MM-DD> <종료일 YYYY-MM-DD>")
        sys.exit(1)

    start_iso, end_iso = sys.argv[1], sys.argv[2]
    year = int(start_iso[:4])

    days = load_period(start_iso, end_iso)
    if not days:
        print(f"❌ {start_iso} ~ {end_iso} 기간에 데이터가 없습니다.")
        sys.exit(1)

    months = _months_present(days)
    stats = build_yearly_stats(days, months)
    period_label = f"{start_iso} ~ {end_iso}"

    print(f"📊 집계 완료 — {len(days)}일, {len(months)}개월({months[0]}~{months[-1]}월)")

    entries = _resolve_targets()
    if not entries:
        print("❌ 발송 대상이 없습니다.")
        sys.exit(1)

    total_ok = 0
    for guild_id, channel_id in entries:
        if send_annual_report(guild_id, channel_id, stats, months, period_label, len(days), year):
            total_ok += 1

    print(f"\n{'=' * 50}\n 전체 결과: {total_ok}/{len(entries)}개 서버 성공\n{'=' * 50}")


if __name__ == "__main__":
    main()
