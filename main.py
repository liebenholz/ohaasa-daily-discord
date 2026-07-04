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
        "rank_selector": "ul.rank-box li a",      # 순위 (문서 순서 = 순위)
        "detail_selector": "div.seiza-box",       # 별자리별 상세 박스 (id로 매칭)
        # 대기용 셀렉터 (fetch_html에 전달)
        "selector": "div.seiza-box .read-area p.read",
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

def split_lucky_item(content_ja: str, max_item_len: int = 20) -> tuple[str, str]:
    """마지막 공백 뒤의 짧은 토큰을 행운의 아이템으로 분리.

    오하아사 평일 데이터는 항상 다음 패턴을 따름:
      '문장1 문장2 아이템'
      → 마지막 공백 뒤가 아이템.

    문장 종결 방식(종결어미/특수문자/동사 활용)에 관계없이
    공백 위치만으로 안정적으로 분리 가능.

    Returns: (본문, 행운의_아이템)
    """
    if not content_ja:
        return "", ""

    # 전각 공백을 반각으로 통일 후 좌우 공백 제거
    text = content_ja.replace("\u3000", " ").strip()

    # 마지막 공백 위치
    last_space = text.rfind(" ")

    if last_space == -1:
        # 공백이 없음 → 아이템이 없는 형태로 간주
        return text, ""

    candidate_main = text[:last_space].strip()
    candidate_item = text[last_space + 1:].strip()

    # 방어 필터
    #  1) 아이템 후보가 비었거나 너무 길면 분리 실패 처리
    #  2) 본문이 비어있으면 (전체가 단일 토큰) 분리 실패 처리
    if not candidate_item or len(candidate_item) > max_item_len:
        return text, ""
    if not candidate_main:
        return text, ""

    return candidate_main, candidate_item

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

        # ⭐ 원본 텍스트에서 본문과 행운의 아이템 분리
        raw_content = first_text(item, config["content_selectors"])
        content_ja, lucky_item_ja = split_lucky_item(raw_content)

        detail[meta["kr"]] = {
            "rank": rank,
            "sign_kr": meta["kr"],
            "sign_ja": meta["ja"],
            "sign_key": sign_key,
            "content_ja": content_ja,
            "lucky_item_ja": lucky_item_ja,   # ← 새 필드
        }
    return detail


def _extract_labeled_text(read_area, label_class):
    """<span class="...">라벨</span>"：값" 패턴에서 값 추출

    예: <span class="lucky-color-txt">ラッキーカラー</span>"：黄色" → "黄色"
    """
    span = read_area.select_one(f"span.{label_class}")
    if not span:
        return ""
    # span 바로 뒤의 텍스트 노드
    sibling = span.next_sibling
    while sibling is not None:
        if isinstance(sibling, str):
            text = sibling.strip()
            if text:
                # 전각/반각 콜론 제거
                return text.lstrip("：:").strip()
        elif getattr(sibling, "name", None) == "br":
            break  # 줄바꿈 넘어가면 다음 항목이므로 중단
        sibling = sibling.next_sibling
    return ""


# 별점 카테고리: li 클래스 → (JSON 키, 한글명)
WEEKEND_RATING_CATEGORIES = {
    "lucky-money":  ("money",  "금전운"),
    "lucky-love":   ("love",   "애정운"),
    "lucky-work":   ("work",   "일운"),
    "lucky-health": ("health", "건강운"),
}


def parse_weekend(soup, config):
    detail = {}

    # ① 순위: rank-box 안 a 태그의 문서 순서 = 순위
    rank_map = {}
    for rank, a in enumerate(soup.select(config["rank_selector"]), start=1):
        key = (a.get("data-label") or "").strip().lower()
        if key:
            rank_map[key] = rank

    if DEBUG:
        print(f"[DEBUG] weekend 순위: {rank_map}")

    # ② 상세: seiza-box를 id로 순회
    for box in soup.select(config["detail_selector"]):
        sign_key = (box.get("id") or "").strip().lower()
        if sign_key not in config["signs"]:
            continue
        meta = config["signs"][sign_key]

        # 본문
        read_area = box.select_one(".read-area")
        content_ja = ""
        lucky_color_ja = ""
        lucky_item_ja = ""
        if read_area:
            read_p = read_area.select_one("p.read")
            content_ja = normalize_text(read_p.get_text(strip=True)) if read_p else ""
            lucky_color_ja = _extract_labeled_text(read_area, "lucky-color-txt")
            lucky_item_ja  = _extract_labeled_text(read_area, "key-txt")

        # 별점: li.lucky-* 안의 p.lucky-box img 개수
        ratings = {}
        for li_class, (json_key, _) in WEEKEND_RATING_CATEGORIES.items():
            li = box.select_one(f"li.{li_class}")
            if li:
                icons = li.select("p.lucky-box img")
                ratings[json_key] = len(icons)

        detail[meta["kr"]] = {
            "rank": rank_map.get(sign_key, 0),
            "sign_kr": meta["kr"],
            "sign_ja": meta["ja"],
            "sign_key": sign_key,
            "content_ja": content_ja,
            "lucky_color_ja": lucky_color_ja,
            "lucky_item_ja": lucky_item_ja,
            "ratings": ratings,   # ⭐ 새 필드: {"money": 5, "love": 5, "work": 4, "health": 5}
        }

        if DEBUG and sign_key == "ohitsuji":
            print(f"[DEBUG] ohitsuji: content={content_ja[:50]}, "
                  f"color={lucky_color_ja}, item={lucky_item_ja}, ratings={ratings}")

    return detail


def parse_horoscope_detail(html, mode):
    soup = BeautifulSoup(html, "html.parser")
    config = SIGN_CONFIG[mode]
    return parse_weekday(soup, config) if mode == "weekday" else parse_weekend(soup, config)


# ─────────────────────────────────────────────
# ⭐ 번역 보강 — 평일/주말 모드별 다른 필드 처리
# ─────────────────────────────────────────────
def enrich_with_translation(detail: dict, mode: str, translator: Translator) -> dict:
    if not detail:
        return detail

    items_to_translate = []

    for sign_kr, entry in detail.items():
        items_to_translate.append((sign_kr, "content", entry.get("content_ja", "")))
        # ⭐ 평일/주말 공통: lucky_item 번역
        items_to_translate.append((sign_kr, "lucky_item", entry.get("lucky_item_ja", "")))
        # 주말만: lucky_color 추가
        if mode == "weekend":
            items_to_translate.append((sign_kr, "lucky_color", entry.get("lucky_color_ja", "")))

    texts = [t for _, _, t in items_to_translate]
    print(f"📝 번역 요청: {sum(1 for t in texts if t)}건 (빈 텍스트 제외)")

    try:
        translated = translator.translate_batch(texts)
    except Exception as e:
        print(f"⚠️  번역 실패 ({e}). 원문만 저장합니다.")
        translated = ["" for _ in texts]

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

        # 디버그 덤프 (유지 권장)
        os.makedirs("debug", exist_ok=True)
        with open(f"debug/raw_{mode}_{date_iso}.html", "w", encoding="utf-8") as f:
            f.write(html)
            
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