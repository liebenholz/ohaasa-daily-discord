from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import requests
import os
from datetime import datetime

# 매핑 데이터 관리 (별도의 데이터 구조로 분리)
SIGN_CONFIG = {
    "weekday": {
        "url": "https://www.asahi.co.jp/ohaasa/week/horoscope/",
        "selector": "ul.oa_horoscope_list li",
        "map": {
            "aries": "양자리", "taurus": "황소자리", "gemini": "쌍둥이자리",
            "cancer": "게자리", "leo": "사자자리", "virgo": "처녀자리",
            "libra": "천칭자리", "scorpio": "전갈자리", "sagittarius": "사수자리",
            "capricorn": "염소자리", "aquarius": "물병자리", "pisces": "물고기자리"
        }
    },
    "weekend": {
        "url": "https://www.tv-asahi.co.jp/goodmorning/uranai/",
        "selector": ".rank-box li",
        "map": {
            "ohitsuji": "양자리", "ousi": "황소자리", "futago": "쌍둥이자리",
            "kani": "게자리", "sisi": "사자자리", "otome": "처녀자리",
            "tenbin": "천칭자리", "sasori": "전갈자리", "ite": "사수자리",
            "yagi": "염소자리", "mizugame": "물병자리", "uo": "물고기자리"
        }
    }
}

# 브라우저 제어 로직
def fetch_html(url, selector, timeout=20000):
    """Playwright를 사용하여 HTML 소스를 가져오는 단일 함수"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0")
        page = context.new_page()
        try:
            # 주말 사이트의 'networkidle' 이슈를 고려하여 domcontentloaded 사용
            page.goto(url, wait_until="domcontentloaded", timeout=40000)
            page.wait_for_selector(selector, timeout=timeout)
            return page.content()
        finally:
            browser.close()

# 데이터 파싱 로직
def parse_horoscope_data(html, mode):
    """HTML에서 별자리 키워드를 추출하는 로직"""
    soup = BeautifulSoup(html, 'html.parser')
    config = SIGN_CONFIG[mode]
    results = []

    if mode == "weekday":
        items = soup.select(config["selector"])
        for item in items:
            classes = item.get('class', [])
            sign_key = next((c for c in classes if c in config["map"]), "unknown")
            results.append(sign_key)
    else:
        # 주말 사이트는 a 태그의 data-label 사용
        items = soup.select(f"{config['selector']} a")
        for item in items:
            sign_key = item.get('data-label', '').strip().lower()
            results.append(sign_key)
    
    return results

# 메시지 구성 로직(인터페이스 통일)
def format_message(sign_keys, mode):
    """추출된 키를 한글 메시지로 변환"""
    if not sign_keys:
        return "❌ 데이터를 찾지 못했습니다. 사이트 구조가 변경되었을 수 있습니다."

    config = SIGN_CONFIG[mode]
    msg_lines = ["✨ **오늘의 오하아사 별자리 순위** ✨\n"]
    
    for rank, key in enumerate(sign_keys, start=1):
        korean_sign = config["map"].get(key, f"알 수 없음({key})")
        
        if rank == 1: emoji = "🥇"
        elif rank == 2: emoji = "🥈"
        elif rank == 3: emoji = "🥉"
        else: emoji = "🔹"
        
        msg_lines.append(f"{emoji} **{rank}위**: {korean_sign}")
    
    return "\n".join(msg_lines)

# 실행 메인 함수
def get_horoscope_ranking(mode):
    try:
        config = SIGN_CONFIG[mode]
        html = fetch_html(config["url"], config["selector"])
        sign_keys = parse_horoscope_data(html, mode)
        return format_message(sign_keys, mode)
    except Exception as e:
        return f"❌ 크롤링 중 에러 발생 ({mode}): {e}"

def send_discord(message):
    webhook_url = os.environ.get('DISCORD_WEBHOOK')
    if not webhook_url:
        print(message)
        return
        
    payload = {
        "username": "아침별점 요정",
        "avatar_url": "https://drive.google.com/uc?export=view&id=1EdVoWwvz-GxAJ9ihau06RYILyIx_mrrY",
        "content": message
    }
    requests.post(webhook_url, json=payload)
    
    # avatar_path = os.path.join("src", "ohaasa-profile.png")

    # payload = {
    #     "username": "아침별점 요정",
    #     "content": message
    # }

    # try:
    #     with open(avatar_path, "rb") as f:
    #         files = {
    #             "avatar": (os.path.basename(avatar_path), f, "image/png")
    #         }
    #         requests.post(webhook_url, data=payload, files=files)
    # except FileNotFoundError:
    #     requests.post(webhook_url, json=payload)
    # except requests.exceptions.RequestException as e:
    #     print(f"❌ 메세지 전송 중 에러 발생: {e}")
    
if __name__ == "__main__":
    weekday = datetime.now().weekday()
    mode = "weekend" if weekday in [4, 5] else "weekday"
    
    result_message = get_horoscope_ranking(mode)
    send_discord(result_message)