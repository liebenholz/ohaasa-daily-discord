from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import requests
import os
import json
import re
import time
import glob
from datetime import datetime, timedelta

from notifier import send_embed_to_channels
# ⭐ 3단계: 웹훅 제거 — 아래 import/상수는 웹훅 중복 발송 방지용이라 함께 주석 처리
# from channels import get_sent_guild_ids, mark_sent

# WEBHOOK_SENT_MARKER = "__webhook__"

DEBUG = os.environ.get("CRAWLER_DEBUG", "0") == "1"

# 데이터 신선도 폴링
MAX_RETRIES = 12          # 최대 12회
RETRY_INTERVAL = 300      # 5분 간격 → 최대 약 1시간 대기

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
        # <div class="oa_horoscope_date"><h4><span>8</span>月<span>7</span>日（金）の運勢
        "date_selectors": ["div.oa_horoscope_date h4", "div.oa_horoscope_date"],
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
        # <p class="ttl-area">7月4日（Sat）の占い</p>
        "date_selectors": ["div.rank-area p.ttl-area", "p.ttl-area"],
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

def _normalize_digits(text: str) -> str:
    """전각 숫자 → 반각"""
    return text.translate(str.maketrans("０１２３４５６７８９", "0123456789"))

def extract_page_date(html: str, mode: str):
    """모드별 날짜 영역에서 (월, 일) 추출. 못 찾으면 None

    평일은 숫자가 <span>으로 분리되어 텍스트 추출 시 공백이 끼므로
    (예: '8 月 7 日') 정규식에 \\s* 를 허용한다.
    """
    soup = BeautifulSoup(html, "html.parser")
    for sel in SIGN_CONFIG[mode].get("date_selectors", []):
        el = soup.select_one(sel)
        if not el:
            continue
        text = _normalize_digits(el.get_text(" ", strip=True))
        m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None

def is_fresh(html: str, mode: str, prev_contents: dict) -> bool:
    """1차: 모드별 날짜 영역 검사 / 2차: 어제 본문 비교 / 판별 불가 시 통과"""
    jst = datetime.utcnow() + timedelta(hours=9)

    # ── 1차: 날짜 영역 (평일·주말 모두 확인된 셀렉터로 여기서 판별됨)
    page_date = extract_page_date(html, mode)
    if page_date is not None:
        fresh = page_date == (jst.month, jst.day)
        print(f"🔎 날짜 영역 검사: 페이지={page_date[0]}月{page_date[1]}日 "
              f"→ {'오늘' if fresh else '갱신 전'}")
        return fresh

    # ── 2차: 내용 비교 폴백 (사이트 개편 대비 보험)
    if not prev_contents:
        print("🔎 판별 불가 (날짜 영역·이전 데이터 없음) — 검사 생략, 통과")
        return True
    detail = parse_horoscope_detail(html, mode)
    if not detail:
        return False  # 파싱 실패 → 재시도
    same = sum(1 for k, v in detail.items()
               if v.get("content_ja") and v.get("content_ja") == prev_contents.get(k))
    fresh = same < max(1, len(detail) // 2)
    print(f"🔎 내용 비교: 어제와 동일 {same}/{len(detail)}건 "
          f"→ {'오늘' if fresh else '갱신 전'}")
    return fresh


def fetch_with_wait(url: str, selector: str, mode: str, today_iso: str) -> str:
    """오늘 데이터가 올라올 때까지 폴링하며 크롤"""
    prev_contents = load_previous_contents(today_iso)

    for attempt in range(1, MAX_RETRIES + 1):
        html = fetch_html(url, selector)
        if is_fresh(html, mode, prev_contents):
            print(f"✅ 오늘 데이터 확인 (시도 {attempt}회)")
            return html
        print(f"⏳ 아직 갱신 전 (시도 {attempt}/{MAX_RETRIES}) — {RETRY_INTERVAL}초 대기")
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_INTERVAL)

    raise RuntimeError(
        f"제한 시간({MAX_RETRIES * RETRY_INTERVAL // 60}분) 내에 오늘 데이터가 갱신되지 않음"
    )

def load_previous_contents(today_iso: str) -> dict:
    """오늘 이전 가장 최근 파일의 {별자리: content_ja} (2차 폴백용)"""
    for path in sorted(glob.glob("data/horoscope_*.json"), reverse=True):
        d = os.path.basename(path)[10:20]
        if d < today_iso:
            try:
                with open(path, encoding="utf-8") as f:
                    prev = json.load(f)
                return {k: v.get("content_ja", "")
                        for k, v in prev.get("signs", {}).items()}
            except Exception:
                return {}
    return {}

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

def load_previous_ranks(today_iso: str) -> dict:
    """오늘 이전의 가장 최근 데이터에서 {별자리: 순위} 맵을 로드.

    파일이 없으면(첫 실행 등) 빈 dict 반환 → 변동 표시 없이 동작.
    """
    candidates = sorted(glob.glob("data/horoscope_*.json"))
    prev_path = None
    for path in reversed(candidates):
        date_part = os.path.basename(path)[10:20]  # horoscope_YYYY-MM-DD.json
        if date_part < today_iso:
            prev_path = path
            break

    if not prev_path:
        print("ℹ️  이전 데이터 없음 — 순위 변동 표시 생략")
        return {}

    try:
        with open(prev_path, encoding="utf-8") as f:
            prev = json.load(f)
        prev_ranks = {
            sign_kr: entry.get("rank", 0)
            for sign_kr, entry in prev.get("signs", {}).items()
            if entry.get("rank")
        }
        print(f"📊 순위 비교 기준: {os.path.basename(prev_path)}")
        return prev_ranks
    except Exception as e:
        print(f"⚠️  이전 데이터 로드 실패 ({e}) — 변동 표시 생략")
        return {}

# ─────────────────────────────────────────────
# 디스코드 알림 (생략 — 이전과 동일)
# ─────────────────────────────────────────────
def format_ranking_message(detail, prev_ranks=None):
    if not detail:
        return "❌ 데이터를 찾지 못했습니다."

    prev_ranks = prev_ranks or {}
    sorted_signs = sorted(detail.values(), key=lambda x: x["rank"])
    lines = []

    for s in sorted_signs:
        rank = s["rank"]
        sign_kr = s["sign_kr"]
        emoji = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, "🔹")

        # 순위 변동 계산 (숫자가 작아지면 상승)
        change = ""
        if sign_kr in prev_ranks:
            diff = prev_ranks[sign_kr] - rank
            if diff > 0:
                change = f" (▲{diff})"
            elif diff < 0:
                change = f" (▼{abs(diff)})"
            else:
                change = " (-)"

        lines.append(f"{emoji} **{rank}위**: {sign_kr}{change}")

    return "\n".join(lines)


def get_date_display():
    kst = datetime.utcnow() + timedelta(hours=9)
    wd = ["월", "화", "수", "목", "금", "토", "일"][kst.weekday()]
    return kst.strftime(f"%Y-%m-%d ({wd})")


def get_date_iso():
    return (datetime.utcnow() + timedelta(hours=9)).strftime("%Y-%m-%d")


def send_discord(message, mode, run_key=None):
    embed = {
        "title": "✨ **오늘의 오하아사 별자리 순위** ✨\n",
        "description": message,
        "color": 0x9B59B6,
        "url": "https://x.com/Hi_Ohaasa",
        "footer": {"text": f"{get_date_display()} · {'평일' if mode == 'weekday' else '주말'} 기준"},
    }

    # ⭐ 3단계: 웹훅 제거 — 아래 블록 전체 주석 처리 (삭제 아님, 복원 가능)
    # # 예비 cron 재시도 패스에서 크롤 데이터를 재사용해도, 웹훅은 하루 1번만
    # # 나가도록 run_key(오늘 날짜) 기준 발송 이력을 확인한다.
    # webhook_url = os.environ.get("DISCORD_WEBHOOK")
    # webhook_already_sent = False
    # if webhook_url and run_key:
    #     try:
    #         webhook_already_sent = WEBHOOK_SENT_MARKER in get_sent_guild_ids(run_key)
    #     except Exception as e:
    #         print(f"⚠️  웹훅 발송 이력 조회 실패 — 발송 진행: {e}")
    #
    # if webhook_url and not webhook_already_sent:
    #     payload = {
    #         "username": "아침별점 요정",
    #         "avatar_url": "https://drive.google.com/uc?export=view&id=1EdVoWwvz-GxAJ9ihau06RYILyIx_mrrY",
    #         "embeds": [embed],
    #     }
    #     requests.post(webhook_url, json=payload, timeout=10)
    #     if run_key:
    #         try:
    #             mark_sent(run_key, WEBHOOK_SENT_MARKER)
    #         except Exception as e:
    #             print(f"⚠️  웹훅 발송 이력 기록 실패: {e}")
    # elif webhook_already_sent:
    #     print("ℹ️  오늘 웹훅은 이미 발송됨 — 스킵")
    # else:
    #     print(message)

    send_embed_to_channels(embed, run_key=run_key)


# ─────────────────────────────────────────────
# 진입점
# ─────────────────────────────────────────────
if __name__ == "__main__":
    today = datetime.utcnow() + timedelta(hours=3)
    mode = "weekday" if today.weekday() < 5 else "weekend"
    date_iso = get_date_iso()

    # 수동 실행(workflow_dispatch)이면 항상 새로 크롤링
    is_manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    existing_path = f"data/horoscope_{date_iso}.json"
    reuse_existing = (not is_manual) and os.path.exists(existing_path)

    try:
        if reuse_existing:
            # ⭐ 예비 cron 재시도 패스 — 오늘 데이터는 이미 있으니 크롤링은
            # 건너뛰고, 아직 발송 성공하지 못한 채널에만 재발송을 시도한다.
            print(f"✅ 오늘({date_iso}) 데이터 이미 존재 — 크롤링 생략, 미발송 채널만 재시도")
            with open(existing_path, encoding="utf-8") as f:
                detail = json.load(f).get("signs", {})
        else:
            config = SIGN_CONFIG[mode]
            html = fetch_with_wait(config["url"], config["selector"], mode, date_iso)

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

        # ⭐ 오늘 이전의 가장 최근 순위와 비교
        prev_ranks = load_previous_ranks(date_iso)
        send_discord(format_ranking_message(detail, prev_ranks), mode, run_key=date_iso)

    except Exception as e:
        send_discord(f"❌ 크롤링 중 에러 발생 ({mode}): {e}", mode, run_key=date_iso)
        raise
