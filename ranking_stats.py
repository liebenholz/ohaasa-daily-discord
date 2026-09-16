"""순위 데이터 집계 공용 함수 — data/horoscope_*.json 기반.

monthly_stats.py/annual_stats.py가 공용으로 쓴다. stats.py는 10월 1일부터
monthly_stats.py로 대체될 예정이라, 새 리포트 스크립트들이 stats.py에 의존하지
않도록 여기로 분리했다 (stats.py 자체는 9월 30일까지 그대로 운영되므로 건드리지
않는다 — 이 모듈에는 stats.py와 동일한 로직의 사본이 들어있다).

발송(임베드 구성/전송)은 각 리포트 스크립트가 담당하고, 여기는 순수 집계 함수만.
"""
import os
import glob
import json
import calendar
import statistics
from collections import Counter, defaultdict


def month_range(y: int, m: int) -> tuple[str, str]:
    last_day = calendar.monthrange(y, m)[1]
    return f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{last_day:02d}"


def load_period(start_iso: str, end_iso: str) -> list[dict]:
    """기간 내 파일에서 {별자리: 순위} 맵 목록을 추출.

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


def pick_mode_rank(ranks: list[int]) -> tuple[int, int]:
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
