"""월간/분기 오하아사 순위 통계 리포트 (기존 data/horoscope_*.json 활용)

사용법:
  python stats.py                    # 자동: 말일이면 월간, 분기 말이면 분기까지
  python stats.py month 2026-07      # 특정 월 수동 실행
  python stats.py quarter 2026-Q3    # 특정 분기 수동 실행
"""
import os
import sys
import glob
import json
import calendar
import statistics
import requests
from collections import defaultdict
from datetime import datetime, timedelta, date


# ─────────────────────────────────────────────
# 기간 계산
# ─────────────────────────────────────────────
def kst_today() -> date:
    return (datetime.utcnow() + timedelta(hours=9)).date()


def month_range(y: int, m: int) -> tuple[str, str]:
    last_day = calendar.monthrange(y, m)[1]
    return f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{last_day:02d}"


def quarter_range(y: int, q: int) -> tuple[str, str]:
    start_m = 3 * (q - 1) + 1
    end_m = start_m + 2
    last_day = calendar.monthrange(y, end_m)[1]
    return f"{y:04d}-{start_m:02d}-01", f"{y:04d}-{end_m:02d}-{last_day:02d}"


# ─────────────────────────────────────────────
# ⭐ 기존 horoscope_*.json 로더
# ─────────────────────────────────────────────
def load_period(start_iso: str, end_iso: str) -> list[dict]:
    """기간 내 파일에서 {별자리: 순위} 맵 목록을 추출

    반환: [{"date": "...", "ranks": {"양자리": 1, ...}}, ...]
    """
    days = []
    for path in sorted(glob.glob("data/horoscope_*.json")):
        d = os.path.basename(path)[10:20]  # horoscope_YYYY-MM-DD.json
        if not (start_iso <= d <= end_iso):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            ranks = {
                sign_kr: entry["rank"]
                for sign_kr, entry in raw.get("signs", {}).items()
                if entry.get("rank")
            }
            if ranks:
                days.append({"date": raw.get("date", d), "ranks": ranks})
            else:
                print(f"⚠️  {path}: 순위 데이터 없음 — 제외")
        except Exception as e:
            print(f"⚠️  {path} 로드 실패: {e} — 제외")
    return days


# ─────────────────────────────────────────────
# 집계
# ─────────────────────────────────────────────
def aggregate(days: list[dict]) -> dict:
    per_sign = defaultdict(list)
    for day in days:
        for sign, rank in day["ranks"].items():
            per_sign[sign].append(rank)

    stats = {}
    for sign, ranks in per_sign.items():
        stats[sign] = {
            "avg": round(statistics.mean(ranks), 2),
            "stdev": round(statistics.stdev(ranks), 2) if len(ranks) >= 2 else 0.0,
            "first": ranks.count(1),
            "last": ranks.count(12),
            "days": len(ranks),
        }
    return stats


# ─────────────────────────────────────────────
# 수상자 선정 (동점 시 타이브레이크)
# ─────────────────────────────────────────────
def pick_awards(stats: dict) -> dict:
    signs = list(stats.items())
    eligible = [kv for kv in signs if kv[1]["days"] >= 2]

    return {
        # 최다 1위 — 동점이면 평균 순위가 좋은 쪽
        "most_first": max(signs, key=lambda kv: (kv[1]["first"], -kv[1]["avg"])),
        # 최다 12위 — 동점이면 평균 순위가 나쁜 쪽
        "most_last": max(signs, key=lambda kv: (kv[1]["last"], kv[1]["avg"])),
        # 표준편차 최소/최대
        "stable": min(eligible, key=lambda kv: (kv[1]["stdev"], kv[1]["avg"])) if eligible else None,
        "chaotic": max(eligible, key=lambda kv: (kv[1]["stdev"],)) if eligible else None,
    }


# ─────────────────────────────────────────────
# 메시지 조립 및 전송
# ─────────────────────────────────────────────
def build_description(stats: dict, awards: dict, kind: str) -> str:
    lines = ["**📈 평균 순위**"]
    ranked = sorted(stats.items(), key=lambda kv: kv[1]["avg"])
    for i, (sign, s) in enumerate(ranked, start=1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, "🔹")
        lines.append(f"{medal} {i}위 {sign} (평균 {s['avg']}위)")

    lines.append("")
    lines.append("**🏆 이달의 수상**" if kind == "month" else "**🏆 분기의 수상**")

    mf_sign, mf = awards["most_first"]
    lines.append(f"👑 최다 1위: {mf_sign} ({mf['first']}회)")

    ml_sign, ml = awards["most_last"]
    lines.append(f"🌧️ 최다 12위: {ml_sign} ({ml['last']}회)")

    if awards["stable"]:
        st_sign, st = awards["stable"]
        lines.append(f"🧘 안정형 상: {st_sign} (표준편차 {st['stdev']})")
    if awards["chaotic"]:
        ch_sign, ch = awards["chaotic"]
        lines.append(f"🎢 멘헤라 상: {ch_sign} (표준편차 {ch['stdev']})")

    return "\n".join(lines)


def send_report(title: str, description: str, day_count: int, period_label: str):
    webhook = os.environ.get("DISCORD_WEBHOOK")
    payload = {
        "username": "아침별점 요정",
        "avatar_url": "https://drive.google.com/uc?export=view&id=1EdVoWwvz-GxAJ9ihau06RYILyIx_mrrY",
        "embeds": [{
            "title": title,
            "description": description,
            "color": 0xF1C40F,
            "footer": {"text": f"{period_label} · 집계 {day_count}일"},
        }],
    }
    if not webhook:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    r = requests.post(webhook, json=payload, timeout=10)
    print(f"📤 전송: {r.status_code}")


def run_report(kind: str, start_iso: str, end_iso: str, label: str):
    days = load_period(start_iso, end_iso)
    if not days:
        print(f"❌ {label} 기간에 데이터가 없습니다 ({start_iso} ~ {end_iso})")
        return

    stats = aggregate(days)
    awards = pick_awards(stats)
    title = f"📊 {label} 오하아사 {'월간' if kind == 'month' else '분기'} 리포트"
    send_report(title, build_description(stats, awards, kind),
                len(days), f"{start_iso} ~ {end_iso}")


def main():
    args = sys.argv[1:]

    # ── 수동 모드
    if len(args) == 2:
        kind, target = args
        if kind == "month":
            y, m = map(int, target.split("-"))
            s, e = month_range(y, m)
            run_report("month", s, e, f"{y}년 {m}월")
        elif kind == "quarter":
            y, q = target.split("-Q")
            y, q = int(y), int(q)
            s, e = quarter_range(y, q)
            run_report("quarter", s, e, f"{y}년 {q}분기")
        else:
            print("사용법: python stats.py [month 2026-07 | quarter 2026-Q3]")
            sys.exit(1)
        return

    # ── 자동 모드: 오늘(KST)이 말일인지 검사
    today = kst_today()
    if (today + timedelta(days=1)).day != 1:
        print(f"오늘({today})은 말일이 아님 — 리포트 생략")
        return

    s, e = month_range(today.year, today.month)
    run_report("month", s, e, f"{today.year}년 {today.month}월")

    if today.month in (3, 6, 9, 12):
        q = today.month // 3
        s, e = quarter_range(today.year, q)
        run_report("quarter", s, e, f"{today.year}년 {q}분기")


if __name__ == "__main__":
    main()