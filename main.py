from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import requests
import os

# 별자리 영문-한글 매핑 테이블
SIGN_MAP = {
    "aries": "양자리", "taurus": "황소자리", "gemini": "쌍둥이자리",
    "cancer": "게자리", "leo": "사자자리", "virgo": "처녀자리",
    "libra": "천칭자리", "scorpio": "전갈자리", "sagittarius": "사수자리",
    "capricorn": "염소자리", "aquarius": "물병자리", "pisces": "물고기자리"
}

def get_ohaasa_ranking():
    url = "https://www.asahi.co.jp/ohaasa/week/horoscope/"
    
    try:
        with sync_playwright() as p:
            # GitHub Actions 서버 환경을 위한 브라우저 설정
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            page.goto(url)
            page.wait_for_selector('ul.oa_horoscope_list li', timeout=15000) # 서버 환경을 고려해 15초로 여유 있게 설정
            
            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, 'html.parser')
        horoscope_ul = soup.select_one('ul.oa_horoscope_list')
        
        if not horoscope_ul:
            return "❌ 데이터를 찾지 못했습니다. 사이트 구조가 변경되었을 수 있습니다."

        items = horoscope_ul.select('li')
        msg_lines = ["✨ **오늘의 오하아사 별자리 순위** ✨\n"]
        
        for index, item in enumerate(items, start=1):
            classes = item.get('class', [])
            english_sign = next((c for c in classes if c in SIGN_MAP), "unknown")
            korean_sign = SIGN_MAP.get(english_sign, english_sign)
            
            # 4위부터 12위까지도 정상적으로 순위가 매겨지도록 index 활용
            rank_val = index
            rank_text = f"{rank_val}위"
            
            if rank_val == 1: emoji = "🥇"
            elif rank_val == 2: emoji = "🥈"
            elif rank_val == 3: emoji = "🥉"
            else: emoji = "🔹"
            
            msg_lines.append(f"{emoji} **{rank_text}**: {korean_sign}")
            
        return "\n".join(msg_lines)

    except Exception as e:
        return f"❌ 크롤링 중 에러 발생: {e}"

def send_discord(message):
    webhook_url = os.environ.get('DISCORD_WEBHOOK')
    if not webhook_url:
        print("Webhook URL이 설정되지 않았습니다. 결과만 출력합니다.")
        print(message)
        return
    
    # 디스코드 봇 프로필 설정 (선택 사항)
    payload = {
        "username": "아침별점 요정",
        "avatar_url": "https://pbs.twimg.com/card_img/2031288293040525312/XqIwveUV?format=jpg&name=360x360",
        "content": message
    }
    requests.post(webhook_url, json=payload)

if __name__ == "__main__":
    result_message = get_ohaasa_ranking()
    send_discord(result_message)
