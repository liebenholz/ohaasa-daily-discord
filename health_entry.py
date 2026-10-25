"""기준 사이트 점검 요청 처리 — QStash 서명 검증 + 점검 실행.

이 프로젝트의 Vercel 배포에서는 /api/* 요청이 모두 api/index.py로 들어간다(별도 api/*.py 파일은
자기 경로로 연결되지 않음). 그래서 api/index.py가 /api/health를 이 함수로 넘기고,
api/health.py도 같은 함수를 쓴다.
"""
from qstash_verify import verify_qstash_signature
from source_health import run_health_check


def handle_health_request(signature: str, body: bytes) -> tuple[int, dict]:
    """(HTTP 상태코드, JSON 응답)을 반환한다. 실패는 QStash 로그에서 바로 보이도록 401/500으로 돌려준다."""
    ok, reason = verify_qstash_signature(signature, body)
    if not ok:
        print(f"⛔ 서명 검증 실패: {reason}")
        return 401, {"error": reason}

    try:
        result = run_health_check()
    except Exception as e:
        print(f"❌ 헬스체크 실행 실패: {e}")
        return 500, {"error": str(e)}

    print(f"🩺 헬스체크: {result}")
    return 200, result
