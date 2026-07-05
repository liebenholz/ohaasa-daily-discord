"""이메일 테스트 리포트 HTML 생성

data/latest.json을 읽어 순위 요약 + 별자리별 원문/번역 대조 리포트를
test/email_report.html 로 생성한다.
"""
import os
import json
import html
from datetime import datetime, timedelta

LATEST_PATH = "data/latest.json"
OUTPUT_PATH = "test/email_report.html"

RATING_LABELS = {
    "money":  "💰 금전",
    "love":   "💕 애정",
    "work":   "💼 업무",
    "health": "🍎 건강",
}


def esc(s):
    return html.escape(str(s or ""))


def kst_today() -> str:
    return (datetime.utcnow() + timedelta(hours=9)).strftime("%Y-%m-%d")


def build_ranking_table(signs_sorted: list[dict]) -> str:
    """상단 순위 요약 테이블"""
    rows = []
    for s in signs_sorted:
        rank = s.get("rank", 0)
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, "")
        rows.append(f"""
      <tr>
        <td style="padding:3px 10px; text-align:center;">{medal} {rank}위</td>
        <td style="padding:3px 10px;">{esc(s.get('sign_kr'))}
          <span style="color:#aaa; font-size:12px;">{esc(s.get('sign_ja'))}</span></td>
      </tr>""")
    return f"""
  <table style="border-collapse:collapse; font-size:14px; margin-bottom:20px;
                border:1px solid #e0e0e0; border-radius:8px;">
    {''.join(rows)}
  </table>"""


def build_sign_block(sign: dict) -> str:
    """별자리별 상세 카드 (원문/번역 대조)"""
    rank = sign.get("rank", 0)
    medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, "🔹")

    rows = [f"""
      <tr>
        <td style="padding:5px 10px; color:#888; white-space:nowrap; vertical-align:top; width:60px;">원문</td>
        <td style="padding:5px 10px; color:#555;">{esc(sign.get('content_ja')) or '<span style="color:#e74c3c;">(비어 있음)</span>'}</td>
      </tr>
      <tr>
        <td style="padding:5px 10px; color:#888; vertical-align:top;">번역</td>
        <td style="padding:5px 10px; font-weight:600;">{esc(sign.get('content_ko')) or '<span style="color:#e74c3c;">(비어 있음)</span>'}</td>
      </tr>"""]

    if sign.get("lucky_color_ja") or sign.get("lucky_color_ko"):
        rows.append(f"""
      <tr>
        <td style="padding:5px 10px; color:#888;">🎨 색</td>
        <td style="padding:5px 10px;">{esc(sign.get('lucky_color_ko'))}
          <span style="color:#aaa;">({esc(sign.get('lucky_color_ja'))})</span></td>
      </tr>""")

    if sign.get("lucky_item_ja") or sign.get("lucky_item_ko"):
        rows.append(f"""
      <tr>
        <td style="padding:5px 10px; color:#888;">🍀 아이템</td>
        <td style="padding:5px 10px;">{esc(sign.get('lucky_item_ko'))}
          <span style="color:#aaa;">({esc(sign.get('lucky_item_ja'))})</span></td>
      </tr>""")

    ratings = sign.get("ratings") or {}
    if ratings:
        stars_line = " &nbsp;&nbsp; ".join(
            f"{label}: {'⭐' * ratings[key]}"
            for key, label in RATING_LABELS.items() if key in ratings
        )
        rows.append(f"""
      <tr>
        <td style="padding:5px 10px; color:#888;">별점</td>
        <td style="padding:5px 10px;">{stars_line}</td>
      </tr>""")

    return f"""
  <div style="border:1px solid #e0e0e0; border-radius:8px; margin:14px 0; overflow:hidden;">
    <div style="background:#f5f0fa; padding:9px 14px; font-size:15px; font-weight:700;">
      {medal} {rank}위 &nbsp; {esc(sign.get('sign_kr'))}
      <span style="color:#999; font-weight:400; font-size:13px;">{esc(sign.get('sign_ja'))}</span>
    </div>
    <table style="width:100%; border-collapse:collapse; font-size:13px;">
      {''.join(rows)}
    </table>
  </div>"""


def build_error_page(message: str) -> str:
    return f"""
  <h2 style="margin:0 0 12px;">❌ 오하아사 테스트 리포트 — 데이터 이상</h2>
  <div style="background:#fdecea; border-radius:8px; padding:16px;">
    {esc(message)}
  </div>"""


def main():
    if not os.path.exists(LATEST_PATH):
        body = build_error_page("data/latest.json 이 존재하지 않습니다. 크롤러가 실행되지 않았을 수 있습니다.")
        date_str, mode_str, stale_warn = "?", "?", ""
    else:
        with open(LATEST_PATH, encoding="utf-8") as f:
            latest = json.load(f)

        date_str = latest.get("date", "?")
        mode_str = "평일" if latest.get("mode") == "weekday" else "주말"
        signs = sorted(
            latest.get("signs", {}).values(),
            key=lambda s: s.get("rank", 99),
        )

        # 데이터 신선도 검사 (오늘 데이터가 아니면 경고)
        stale_warn = ""
        if date_str != kst_today():
            stale_warn = f"""
  <div style="background:#fef5e7; border-radius:8px; padding:10px 14px; margin-bottom:14px;">
    ⚠️ 오늘({kst_today()}) 데이터가 아닙니다. latest.json 날짜: {esc(date_str)}
  </div>"""

        # 품질 경고 (원문/번역 누락)
        empty_ja = sum(1 for s in signs if not s.get("content_ja"))
        empty_ko = sum(1 for s in signs if not s.get("content_ko"))
        if empty_ja or empty_ko:
            items = []
            if empty_ja:
                items.append(f"원문 누락 {empty_ja}건")
            if empty_ko:
                items.append(f"번역 누락 {empty_ko}건")
            stale_warn += f"""
  <div style="background:#fef5e7; border-radius:8px; padding:10px 14px; margin-bottom:14px;">
    ⚠️ {' / '.join(items)}
  </div>"""

        if not signs:
            body = build_error_page("signs 데이터가 비어 있습니다. 파싱 실패 가능성이 있습니다.")
        else:
            body = f"""
  <h2 style="margin:0 0 4px;">✨ 오하아사 테스트 리포트</h2>
  <p style="margin:0 0 16px; color:#666;">{esc(date_str)} · {mode_str}</p>
  {stale_warn}
  <h3 style="margin:0 0 8px;">📊 오늘의 순위</h3>
  {build_ranking_table(signs)}
  <h3 style="margin:0 0 8px;">📖 상세 운세 (원문/번역 대조)</h3>
  {''.join(build_sign_block(s) for s in signs)}"""

    html_doc = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,'Segoe UI','Malgun Gothic',sans-serif;
             max-width:640px; margin:0 auto; padding:20px; color:#222;">
{body}
<p style="color:#bbb; font-size:11px; margin-top:24px;">
  자동 생성 테스트 리포트 · ohaasa-daily-discord</p>
</body></html>"""

    os.makedirs("test", exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html_doc)
    print(f"✅ 리포트 생성 완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()