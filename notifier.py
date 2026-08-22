"""디스코드 알림 발송 (Bot API, 멀티 채널)

main.py / stats.py가 공용으로 사용한다. 채널 하나가 실패해도 나머지는 계속
발송하며, 등록된 채널이 없거나 필요한 환경변수가 없으면 조용히 종료한다.

⚠️ 발송 경로는 채널 목록 조회에 읽기 전용(SMEMBERS + GET)만 사용한다.
등록 해제는 오직 /오하아사설정 알림해제 커맨드(api/index.py)를 통해서만
일어나야 하며, 발송 실패(403/429/timeout 등)를 이유로 이 모듈이 스스로
등록을 지우지 않는다 — 일시적 실패로 정상 등록이 사라지는 사고를 막기 위함.
"""
import os
import time
import requests

from channels import list_channel_entries, get_sent_guild_ids, mark_sent

DISCORD_API = "https://discord.com/api/v10"
SEND_DELAY = 0.5     # 채널 간 순차 발송 간격 (rate limit 대비)
MAX_ATTEMPTS = 3      # 채널당 재시도 횟수
BASE_BACKOFF = 1.0     # 지수 백오프 기준(초): 1s, 2s, 4s ...

# 재시도해도 의미 없는 Discord 오류 코드 — 영구 실패로 분류
PERMANENT_ERROR_CODES = {50001, 50013, 10003}  # Missing Access / Missing Permissions / Unknown Channel

TEST_EMBED = {
    "title": "✅ 오하아사 알림 채널 연결 테스트",
    "description": "이 메시지가 보이면 알림 채널 설정이 정상입니다.",
    "color": 0x2ECC71,
}


def _classify_response(r: requests.Response) -> dict:
    """단일 응답을 outcome으로 분류한다.

    outcome: "success" | "retry"(429/5xx/응답 파싱 불가) | "permanent"(403/404 등) | "abort"(401)
    """
    if r.status_code < 400:
        return {"outcome": "success", "status_code": r.status_code}

    try:
        body = r.json()
    except ValueError:
        body = {}
    error_code = body.get("code") if isinstance(body, dict) else None
    message = body.get("message") if isinstance(body, dict) else r.text[:200]
    retry_after = body.get("retry_after") if isinstance(body, dict) else None

    result = {"status_code": r.status_code, "error_code": error_code, "message": message}

    if r.status_code == 401:
        result["outcome"] = "abort"
    elif r.status_code == 429 or r.status_code >= 500:
        result["outcome"] = "retry"
        result["retry_after"] = retry_after
    elif r.status_code in (403, 404) or error_code in PERMANENT_ERROR_CODES:
        result["outcome"] = "permanent"
    else:
        # 기타 4xx — 재시도해도 결과가 바뀌지 않으므로 영구 실패로 취급
        result["outcome"] = "permanent"
    return result


def send_once(channel_id: str, embed: dict, headers: dict) -> dict:
    """단일 시도. 네트워크 예외/타임아웃은 재시도 대상으로 분류한다."""
    try:
        r = requests.post(
            f"{DISCORD_API}/channels/{channel_id}/messages",
            headers=headers,
            json={"embeds": [embed]},
            timeout=10,
        )
    except requests.Timeout:
        return {"outcome": "retry", "status_code": None, "error_code": None, "message": "timeout"}
    except requests.RequestException as e:
        return {"outcome": "retry", "status_code": None, "error_code": None, "message": str(e)}

    return _classify_response(r)


def send_with_retry(channel_id: str, embed: dict, headers: dict) -> dict:
    """지수 백오프로 최대 MAX_ATTEMPTS회 시도. 성공/영구실패/중단은 즉시 반환."""
    result = None
    for attempt in range(MAX_ATTEMPTS):
        result = send_once(channel_id, embed, headers)
        if result["outcome"] != "retry":
            return result

        if attempt < MAX_ATTEMPTS - 1:
            wait = result.get("retry_after") or BASE_BACKOFF * (2 ** attempt)
            print(f"  ↻ 채널 {channel_id} 재시도 {attempt + 1}/{MAX_ATTEMPTS} "
                  f"({result.get('status_code')} {result.get('message')}) — {wait:.1f}s 대기")
            time.sleep(wait)

    result["outcome"] = "retries_exhausted"
    return result


def send_test_message(channel_id: str) -> dict:
    """등록 직후 즉시 1회 테스트 발송 (재시도 없음 — 인터랙션 응답 지연 최소화)."""
    bot_token = os.environ.get("DISCORD_BOT_TOKEN")
    if not bot_token:
        return {"outcome": "retry", "status_code": None, "error_code": None, "message": "DISCORD_BOT_TOKEN 미설정"}
    headers = {"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"}
    return send_once(channel_id, TEST_EMBED, headers)


def _post_to_test_webhook(payload: dict) -> None:
    """TEST_DISCORD_WEBHOOK으로 운영 알림을 보낸다. 미설정/실패는 조용히 무시한다."""
    webhook = os.environ.get("TEST_DISCORD_WEBHOOK")
    if not webhook:
        return
    try:
        requests.post(webhook, json=payload, timeout=10)
    except requests.RequestException as e:
        print(f"⚠️  TEST_DISCORD_WEBHOOK 전송 실패: {e}")


def _send_failure_summary(failures: list[dict], registered_count: int, success_count: int) -> None:
    if not failures:
        return

    lines = [f"등록 {registered_count}건 · 성공 {success_count}건 · 실패 {len(failures)}건", ""]
    for f in failures:
        lines.append(
            f"- 채널 `{f['channel_id']}` (길드 `{f['guild_id']}`): {f['outcome']} "
            f"status={f.get('status_code')} code={f.get('error_code')} {f.get('message') or ''}"
        )

    payload = {
        "username": "오하아사 발송 모니터",
        "embeds": [{
            "title": "⚠️ 알림 발송 실패 요약",
            "description": "\n".join(lines)[:4000],
            "color": 0xE74C3C,
        }],
    }
    _post_to_test_webhook(payload)


EVENT_TITLES = {
    "register": "🆕 신규 알림 채널 등록",
    "change":   "🔁 알림 채널 변경",
    "remove":   "🗑️ 알림 채널 해제",
}


def notify_channel_event(
    event: str,
    guild_id: str,
    channel_id: str,
    actor: str,
    *,
    previous_channel_id: str | None = None,
    test_result: dict | None = None,
) -> None:
    """채널 등록/변경/해제 이벤트를 TEST_DISCORD_WEBHOOK으로 알린다.

    event: "register" | "change" | "remove"
    test_result가 있으면(register/change) 테스트 발송 성공/실패를 같이 표시한다.
    remove는 테스트 발송이 없으므로 test_result 없이 호출한다.
    """
    if event == "change" and previous_channel_id:
        target_line = f"길드 `{guild_id}` · 채널 `{previous_channel_id}` → `{channel_id}`"
    else:
        target_line = f"길드 `{guild_id}` · 채널 `{channel_id}`"

    actor_label = "실행자" if event == "remove" else "등록자"
    lines = [target_line, f"{actor_label}: {actor}"]

    color = 0x95A5A6  # remove 기본색
    if test_result is not None:
        if test_result.get("outcome") == "success":
            lines.append("✅ 테스트 발송 성공")
            color = 0x2ECC71
        else:
            lines.append(
                f"⚠️ 테스트 발송 실패 — {test_result.get('outcome')} "
                f"status={test_result.get('status_code')} code={test_result.get('error_code')} "
                f"{test_result.get('message') or ''}"
            )
            color = 0xE67E22

    payload = {
        "username": "오하아사 발송 모니터",
        "embeds": [{
            "title": EVENT_TITLES.get(event, "알림 채널 이벤트"),
            "description": "\n".join(lines),
            "color": color,
        }],
    }
    _post_to_test_webhook(payload)


def send_embed_to_channels(
    embed: dict,
    entries: list[tuple[str, str]] | None = None,
    run_key: str | None = None,
) -> None:
    """등록된 채널에 embed를 발송한다.

    run_key를 주면(main.py의 오늘 날짜 등) 이미 성공한 guild는
    channels.get_sent_guild_ids(run_key)로 걸러내고, 새로 성공한 guild는
    channels.mark_sent(run_key, ...)에 기록한다 — 같은 날 예비 cron이
    재실행돼도 이미 성공한 채널에는 중복 발송하지 않는다.
    """
    if entries is None:
        try:
            entries = list_channel_entries()
        except Exception as e:
            print(f"⚠️  등록 채널 목록 조회 실패 — Bot API 발송 생략: {e}")
            return

    registered_count = len(entries)
    if registered_count == 0:
        print("ℹ️  등록된 알림 채널이 없습니다 — Bot API 발송 생략")
        return

    if run_key:
        try:
            sent_guild_ids = get_sent_guild_ids(run_key)
        except Exception as e:
            print(f"⚠️  발송 이력 조회 실패 — 전체 대상으로 진행: {e}")
            sent_guild_ids = set()
        pending = [(g, c) for g, c in entries if g not in sent_guild_ids]
    else:
        pending = list(entries)

    already_sent = registered_count - len(pending)

    bot_token = os.environ.get("DISCORD_BOT_TOKEN")
    if not bot_token:
        print("⚠️  DISCORD_BOT_TOKEN 미설정 — Bot API 발송 생략")
        return

    headers = {"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"}

    print(f"📨 발송 시작 — 등록 {registered_count}건, 기존 성공 {already_sent}건, "
          f"이번 대상 {len(pending)}건")

    success = 0
    failures = []

    for i, (guild_id, channel_id) in enumerate(pending):
        result = send_with_retry(channel_id, embed, headers)

        if result["outcome"] == "success":
            success += 1
            print(f"✅ 채널 {channel_id} 발송 완료")
            if run_key:
                try:
                    mark_sent(run_key, guild_id)
                except Exception as e:
                    print(f"⚠️  발송 이력 기록 실패 (길드 {guild_id}): {e}")
        elif result["outcome"] == "abort":
            print(f"⛔ 채널 {channel_id} 401 Unauthorized — 봇 토큰 문제로 남은 발송 전체 중단")
            failures.append({"channel_id": channel_id, "guild_id": guild_id, **result})
            break
        else:
            print(f"⚠️  채널 {channel_id} 발송 실패 ({result['outcome']}): "
                  f"status={result.get('status_code')} code={result.get('error_code')} "
                  f"{result.get('message')}")
            failures.append({"channel_id": channel_id, "guild_id": guild_id, **result})

        if i < len(pending) - 1:
            time.sleep(SEND_DELAY)

    print(f"📬 발송 종료 — 대상 {len(pending)}건 중 성공 {success}건, 실패 {len(failures)}건 "
          f"(누적 성공 {already_sent + success}/{registered_count})")

    _send_failure_summary(failures, registered_count, already_sent + success)
