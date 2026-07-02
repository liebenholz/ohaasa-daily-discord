from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import requests
import os
import json
import re
import time
from datetime import datetime, timedelta

DEBUG = os.environ.get("CRAWLER_DEBUG", "0") == "1"

# ─────────────────────────────────────────────
# 사이트별 매핑 설정 (이전 코드 동일, 생략 없이 유지)
# ─────────────────────────────────────────────
SIGN_CONFIG = {
    "weekday": {
        "url": "https://www.asahi.co.jp/ohaasa/week/horoscope/",
        "selector": "ul.oa_horoscope_list li",
        "content_selectors": [
            "p.txt", "p.text", ".comment", ".description", "dd", "p"
        ],
        "signs": {
            "aries":       {"kr": "양자리",     "ja": "おひつじ座"},
            "taurus":      {"kr": "황소자리",   "ja": "おうし座"},
            "gemini":      {"kr": "쌍둥이자리", "ja": "ふたご座"},
            "cancer":      {"kr": "게자리",     "ja": "かに座"},
            "leo":         {"kr": "사자자리",   "ja": "しし座"},
            "virgo":       {"kr": "처녀자리",   "ja": "おとめ座"},
            "libra":       {"kr": "천칭자리",   "ja": "てんびん座"},
            "scorpio":     {"kr": "전갈자리",   "ja": "さそり座"},
            "sagittarius": {"kr": "사수자리",   "ja": "いて座"},
            "capricorn":   {"kr": "염소자리",   "ja": "やぎ座"},
            "aquarius":    {"kr": "물병자리",   "ja": "みずがめ座"},
            "pisces":      {"kr": "물고기자리", "ja": "うお座"},
        },
    },
    "weekend": {
        "url": "https://www.tv-asahi.co.jp/goodmorning/uranai/",
        "selector": ".rank-box li",
        "content_selectors": [
            ".comment", "p.text", "p.txt", ".description", "dd", "p"
        ],
        "lucky_color_selectors": [
            ".color", ".lucky-color", ".lucky_color",
            "dt:-soup-contains('ラッキーカラー') + dd",
            "th:-soup-contains('ラッキーカラー') + td",
        ],
        "lucky_item_selectors": [
            ".item", ".lucky-item", ".lucky_item",
            "dt:-soup-contains('ラッキーアイテム') + dd",
            "th:-soup-contains('ラッキーアイテム') + td",
        ],
        "signs": {
            "ohitsuji": {"kr": "양자리",     "ja": "おひつじ座"},
            "ousi":     {"kr": "황소자리",   "ja": "おうし座"},
            "futago":   {"kr": "쌍둥이자리", "ja": "ふたご座"},
            "kani":     {"kr": "게자리",     "ja": "かに座"},
            "sisi":     {"kr": "사자자리",   "ja": "しし座"},
            "otome":    {"kr": "처녀자리",   "ja": "おとめ座"},
            "tenbin":   {"kr": "천칭자리",   "ja": "てんびん座"},
            "sasori":   {"kr": "전갈자리",   "ja": "さそり座"},
            "ite":      {"kr": "사수자리",   "ja": "いて座"},
            "yagi":     {"kr": "염소자리",   "ja": "やぎ座"},
            "mizugame": {"kr": "물병자리",   "ja": "みずがめ座"},
            "uo":       {"kr": "물고기자리", "ja": "うお座"},
        },
    },
}


# ─────────────────────────────────────────────
# 번역기 추상화 (DeepL 기본 / 다른 API로 교체 가능)
# ─────────────────────────────────────────────
class Translator:
    """공통 인터페이스"""
    def translate_batch(self, texts: list[str]) -> list[str]:
        raise NotImplementedError


class DeepLTranslator(Translator):
    def __init__(self, api_key: str):
        self.api_key = api_key
        # Free 플랜은 :fx로 끝남
        self.endpoint = (
            "https://api-free.deepl.com/v2/translate"
            if api_key.endswith(":fx")
            else "https://api.deepl.com/v2/translate"
        )

    def translate_batch(self, texts: list[str]) -> list[str]:
        # 빈 문자열은 번역 호출 없이 그대로 통과
        clean_texts = [t for t in texts if t]
        if not clean_texts:
            return ["" for _ in texts]

        # DeepL은 한 요청에 여러 text 필드를 받을 수 있음
        data = [("source_lang", "JA"), ("target_lang", "KO")]
        for t in clean_texts:
            data.append(("text", t))

        for attempt in range(3):
            try:
                r = requests.post(
                    self.endpoint,
                    data=data,
                    headers={"Authorization": f"DeepL-Auth-Key {self.api_key}"},
                    timeout=15,
                )
                r.raise_for_status()
                translations = [item["text"] for item in r.json()["translations"]]
                # 빈 문자열 위치 복원
                result, idx = [], 0
                for t in texts:
                    if t:
                        result.append(translations[idx])
                        idx += 1
                    else:
                        result.append("")
                return result
            except requests.HTTPError as e:
                if r.status_code == 429:  # rate limit
                    time.sleep(2 ** attempt)
                    continue
                raise
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)


class PapagoTranslator(Translator):
    """대안: 네이버 Papago — 환경변수 PAPAGO_CLIENT_ID / PAPAGO_CLIENT_SECRET 필요"""
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.endpoint = "https://naveropenapi.apigw.ntruss.com/nmt/v1/translation"

    def translate_batch(self, texts: list[str]) -> list[str]:
        results = []
        for text in texts:
            if not text:
                results.append("")
                continue
            r = requests.post(
                self.endpoint,
                data={"source": "ja", "target": "ko", "text": text},
                headers={
                    "X-NCP-APIGW-API-KEY-ID": self.client_id,
                    "X-NCP-APIGW-API-KEY": self.client_secret,
                },
                timeout=10,
            )
            r.raise_for_status()
            results.append(r.json()["message"]["result"]["translatedText"])
        return results


class NoopTranslator(Translator):
    """번역기 비활성화 시 폴백 — 원문을 그대로 반환"""
    def translate_batch(self, texts: list[str]) -> list[str]:
        return list(texts)


def build_translator() -> Translator:
    if os.environ.get("DEEPL_API_KEY"):
        return DeepLTranslator(os.environ["DEEPL_API_KEY"])
    if os.environ.get("PAPAGO_CLIENT_ID") and os.environ.get("PAPAGO_CLIENT_SECRET"):
        return PapagoTranslator(
            os.environ["PAPAGO_CLIENT_ID"],
            os.environ["PAPAGO_CLIENT_SECRET"],
        )
    print("⚠️  번역 API 키가 없습니다. 원문만 저장합니다.")
    return NoopTranslator()


# ─────────────────────────────────────────────
# HTML 가져오기 / 텍스트 정리 (이전과 동일)
# ─────────────────────────────────────────────
def fetch_html(url, selector, timeout=20000):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="ja-JP",
        )
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=40000)
            page.wait_for_selector(selector, timeout=timeout)
            return page.content()
        finally:
            browser.close()


def normalize_text(text):
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    text = text.replace("\u3000", " ")
    return text.strip()


def first_text(item, selectors):
    for sel in selectors:
        try:
            el = item.select_one(sel)
        except Exception:
            continue
        if el:
            txt = normalize_text(el.get_text(separator=" ", strip=True))
            if txt:
                return txt
    return ""


# ─────────────────────────────────────────────
# 파싱 (이전과 동일)
# ─────────────────────────────────────────────
def parse_weekday(soup, config):
    detail = {}
    items = soup.select(config["selector"])
    if DEBUG and items:
        print(f"[DEBUG] weekday: {len(items)}개 li 발견")
        print(f"[DEBUG] 첫 li 원본:\n{items[0].prettify()[:1500]}")

    for rank, item in enumerate(items, start=1):
        classes = item.get("class", [])
        sign_key = next((c for c in classes if c in config["signs"]), None)
        if not sign_key:
            continue
        meta = config["signs"][sign_key]
        detail[meta["kr"]] = {
            "rank": rank,
            "sign_kr": meta["kr"],
            "sign_ja": meta["ja"],
            "sign_key": sign_key,
            "content_ja": first_text(item, config["content_selectors"]),
        }
    return detail


def parse_weekend(soup, config):
    detail = {}
    items = soup.select(config["selector"])
    if DEBUG and items:
        print(f"[DEBUG] weekend: {len(items)}개 li 발견")
        print(f"[DEBUG] 첫 li 원본:\n{items[0].prettify()[:1500]}")

    for rank, item in enumerate(items, start=1):
        anchor = item.select_one("a")
        sign_key = (anchor.get("data-label") or "").strip().lower() if anchor else ""
        if sign_key not in config["signs"]:
            continue
        meta = config["signs"][sign_key]
        detail[meta["kr"]] = {
            "rank": rank,
            "sign_kr": meta["kr"],
            "sign_ja": meta["ja"],
            "sign_key": sign_key,
            "content_ja":     first_text(item, config["content_selectors"]),
            "lucky_color_ja": first_text(item, config["lucky_color_selectors"]),
            "lucky_item_ja":  first_text(item, config["lucky_item_selectors"]),
        }
    return detail


def parse_horoscope_detail(html, mode):
    soup = BeautifulSoup(html, "html.parser")
    config = SIGN_CONFIG[mode]
    return parse_weekday(soup, config) if mode == "weekday" else parse_weekend(soup, config)


# ─────────────────────────────────────────────
# ⭐ 번역 보강 — 평일/주말 모드별 다른 필드 처리
# ─────────────────────────────────────────────
def enrich_with_translation(detail: dict, mode: str, translator: Translator) -> dict:
    """detail의 일본어 필드들을 번역해서 한국어 필드를 추가"""
    if not detail:
        return detail

    # 번역할 텍스트들을 (별자리키, 필드명, 텍스트)의 평탄한 리스트로 모음
    items_to_translate = []  # [(sign_kr, field_name, text)]

    for sign_kr, entry in detail.items():
        items_to_translate.append((sign_kr, "content", entry.get("content_ja", "")))
        if mode == "weekend":
            items_to_translate.append((sign_kr, "lucky_color", entry.get("lucky_color_ja", "")))
            items_to_translate.append((sign_kr, "lucky_item",  entry.get("lucky_item_ja",  "")))

    texts = [t for _, _, t in items_to_translate]
    print(f"📝 번역 요청: {sum(1 for t in texts if t)}건 (빈 텍스트 제외)")

    try:
        translated = translator.translate_batch(texts)
    except Exception as e:
        print(f"⚠️  번역 실패 ({e}). 원문만 저장합니다.")
        # 번역 실패해도 ko 필드는 비워서 저장 (출력 시 fallback)
        translated = ["" for _ in texts]

    # 결과를 detail에 다시 매핑
    for (sign_kr, field, _), ko_text in zip(items_to_translate, translated):
        detail[sign_kr][f"{field}_ko"] = ko_text

    return detail


# ─────────────────────────────────────────────
# JSON 저장
# ─────────────────────────────────────────────
def save_json(detail, mode, date_iso):
    os.makedirs("data", exist_ok=True)
    payload = {
        "date": date_iso,
        "mode": mode,
        "source_url": SIGN_CONFIG[mode]["url"],
        "updated_at_kst": (datetime.utcnow() + timedelta(hours=9))
                              .isoformat(timespec="seconds"),
        "signs": detail,
    }
    for path in (f"data/horoscope_{date_iso}.json", "data/latest.json"):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"✅ 저장 완료: data/horoscope_{date_iso}.json, data/latest.json")
    return payload


# ─────────────────────────────────────────────
# 디스코드 알림 (생략 — 이전과 동일)
# ─────────────────────────────────────────────
def format_ranking_message(detail):
    if not detail:
        return "❌ 데이터를 찾지 못했습니다."
    sorted_signs = sorted(detail.values(), key=lambda x: x["rank"])
    lines = []
    for s in sorted_signs:
        emoji = {1: "🥇", 2: "🥈", 3: "🥉"}.get(s["rank"], "🔹")
        lines.append(f"{emoji} **{s['rank']}위**: {s['sign_kr']}")
    return "\n".join(lines)


def get_date_display():
    kst = datetime.utcnow() + timedelta(hours=9)
    wd = ["월", "화", "수", "목", "금", "토", "일"][kst.weekday()]
    return kst.strftime(f"%Y-%m-%d ({wd})")


def get_date_iso():
    return (datetime.utcnow() + timedelta(hours=9)).strftime("%Y-%m-%d")


def send_discord(message, mode):
    webhook_url = os.environ.get("DISCORD_WEBHOOK")
    if not webhook_url:
        print(message)
        return
    embed = {
        "title": "✨ **오늘의 오하아사 별자리 순위** ✨\n",
        "description": message,
        "color": 0x9B59B6,
        "url": "https://x.com/Hi_Ohaasa",
        "footer": {"text": f"{get_date_display()} · {'평일' if mode == 'weekday' else '주말'} 기준"},
    }
    payload = {
        "username": "아침별점 요정",
        "avatar_url": "https://drive.google.com/uc?export=view&id=1EdVoWwvz-GxAJ9ihau06RYILyIx_mrrY",
        "embeds": [embed],
    }
    requests.post(webhook_url, json=payload, timeout=10)


# ─────────────────────────────────────────────
# 진입점
# ─────────────────────────────────────────────
if __name__ == "__main__":
    today = datetime.utcnow() + timedelta(hours=3)
    mode = "weekday" if today.weekday() < 5 else "weekend"
    date_iso = get_date_iso()

    try:
        config = SIGN_CONFIG[mode]
        html = fetch_html(config["url"], config["selector"])
        detail = parse_horoscope_detail(html, mode)

        if not detail:
            raise RuntimeError("파싱 결과가 비어 있음 (셀렉터 확인 필요)")

        # ⭐ 번역 보강
        translator = build_translator()
        detail = enrich_with_translation(detail, mode, translator)

        save_json(detail, mode, date_iso)
        send_discord(format_ranking_message(detail), mode)

    except Exception as e:
        send_discord(f"❌ 크롤링 중 에러 발생 ({mode}): {e}", mode)
        raise