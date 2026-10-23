"""기준 사이트 접속 점검 — 오늘 크롤링해야 하는 사이트가 열리는지 확인한다.

Upstash QStash가 15분마다 api/health.py를 호출하면 run_health_check()가 실행된다.
GitHub Actions의 cron은 지연이 커서 실시간 점검에 맞지 않아 이 방식을 쓴다.

  - 점검 대상: KST 요일 기준 평일(월~금) → 평일 사이트, 주말 → 주말 사이트
  - 정상: HTTP 2xx. 페이지 본문은 JS로 채워져서 상태코드만 본다.
  - 실패: 한 번의 실행 안에서 ATTEMPTS회 재시도한 뒤에도 실패하면 장애로 본다.
  - 알림은 TEST_DISCORD_WEBHOOK(모니터링 채널)으로만 보내고, 정상일 땐 아무것도 보내지 않는다.
  - 장애가 이어져도 15분마다 알림이 쌓이지 않도록 Redis(health:{site})에 상태를 저장해
    "최초 감지 시 1회 + REMIND_INTERVAL마다 리마인드"만 보낸다.
"""
import time
from datetime import datetime, timedelta, timezone

import requests

from channels import get_health_state, set_health_state, clear_health_state
from notifier import notify_source_down, notify_source_recovered

KST = timezone(timedelta(hours=9))

# main.py SIGN_CONFIG의 URL과 같은 값. main.py는 playwright에 의존하고 Vercel 배포에서
# 제외(.vercelignore)돼 있어 import하지 않고 여기에 둔다.
SITES = {
    "weekday": {"label": "평일", "url": "https://www.asahi.co.jp/ohaasa/week/horoscope/"},
    "weekend": {"label": "주말", "url": "https://www.tv-asahi.co.jp/goodmorning/uranai/"},
}

ATTEMPTS = 3            # 한 번 실행 안에서의 시도 횟수 (일시적 오류로 인한 오탐 방지)
TIMEOUT = (3, 4)        # (연결, 응답) 초 — QStash 응답 제한 안에 끝나도록 짧게
RETRY_DELAY = 1         # 재시도 사이 대기(초)
REMIND_INTERVAL = 60 * 60       # 장애가 이어질 때 리마인드 간격(초)
STATE_TTL = 2 * REMIND_INTERVAL  # 상태 키 수명 — 리마인드 때마다 갱신된다
NOTIFY_RECOVERY = False  # True면 복구 시 "복구됨" 메시지도 보낸다 (기본: 정상일 땐 무음)

# 크롤러(main.py fetch_html)와 같은 UA에 브라우저형 헤더를 더한다.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja-JP,ja;q=0.9",
}


def today_mode(now: datetime) -> str:
    """KST 요일 기준으로 오늘 크롤링할 사이트를 고른다."""
    return "weekday" if now.astimezone(KST).weekday() < 5 else "weekend"


def check_url(url: str) -> dict:
    """GET으로 접속 여부 확인. 반환: {ok, status, detail, attempts}"""
    last = {"ok": False, "status": None, "detail": "알 수 없음"}
    for attempt in range(1, ATTEMPTS + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
            if 200 <= r.status_code < 300:
                return {"ok": True, "status": r.status_code, "detail": f"HTTP {r.status_code}", "attempts": attempt}
            last = {"ok": False, "status": r.status_code, "detail": f"HTTP {r.status_code}"}
        except requests.RequestException as e:
            last = {"ok": False, "status": None, "detail": type(e).__name__}
        if attempt < ATTEMPTS:
            time.sleep(RETRY_DELAY)
    return {**last, "attempts": ATTEMPTS}


def _safe(fn, *args, default=None):
    """Redis 상태 접근 실패가 점검/알림 자체를 막지 않게 한다 (알림이 중복되는 편이 침묵보다 낫다)."""
    try:
        return fn(*args)
    except Exception as e:
        print(f"⚠️  상태 저장소 오류 ({fn.__name__}): {e}")
        return default


def run_health_check(now: datetime | None = None) -> dict:
    now = now or datetime.now(KST)
    mode = today_mode(now)
    site = SITES[mode]
    result = check_url(site["url"])
    ts = int(now.timestamp())
    detected_at = now.astimezone(KST).strftime("%Y-%m-%d %H:%M KST")

    state = _safe(get_health_state, mode)

    if result["ok"]:
        if not state:
            action = "ok"
        else:
            _safe(clear_health_state, mode)
            action = "recovered"
            if NOTIFY_RECOVERY:
                notify_source_recovered(site["label"], site["url"], max(0, (ts - state.get("since", ts)) // 60))
    elif not state:
        notify_source_down(site["label"], site["url"], result["detail"], result["attempts"], detected_at)
        _safe(set_health_state, mode, {"since": ts, "last_alert": ts}, STATE_TTL)
        action = "alerted"
    elif ts - state.get("last_alert", 0) >= REMIND_INTERVAL:
        notify_source_down(
            site["label"], site["url"], result["detail"], result["attempts"], detected_at,
            down_minutes=max(0, (ts - state.get("since", ts)) // 60),
        )
        _safe(set_health_state, mode, {"since": state.get("since", ts), "last_alert": ts}, STATE_TTL)
        action = "reminded"
    else:
        action = "suppressed"  # 이미 알렸고 리마인드 시간이 안 됨

    return {
        "site": mode, "url": site["url"], "ok": result["ok"],
        "status": result["status"], "attempts": result["attempts"], "action": action,
    }
