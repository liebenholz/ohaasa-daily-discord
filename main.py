from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import requests
import os
from datetime import datetime
import pytz

# 별자리 영문-한글 or 일본어-한글 매핑 테이블
WEEKDAY_SIGN_MAP = {
    "aries": "양자리", "taurus": "황소자리", "gemini": "쌍둥이자리",
    "cancer": "게자리", "leo": "사자자리", "virgo": "처녀자리",
    "libra": "천칭자리", "scorpio": "전갈자리", "sagittarius": "사수자리",
    "capricorn": "염소자리", "aquarius": "물병자리", "pisces": "물고기자리"
}

# 주말 사이트 전용 data-label 매핑 테이블
WEEKEND_SIGN_MAP = {
        "ohitsuji": "양자리", "ousi": "황소자리", "futago": "쌍둥이자리",
        "kani": "게자리", "sisi": "사자자리", "otome": "처녀자리",
        "tenbin": "천칭자리", "sasori": "전갈자리", "ite": "사수자리",
        "yagi": "염소자리", "mizugame": "물병자리", "uo": "물고기자리"
    }

def get_weekday_ranking():
    url = "https://www.asahi.co.jp/ohaasa/week/horoscope/"
    
    try:
        with sync_playwright() as p:
            # GitHub Actions 서버 환경을 위한 브라우저 설정
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            page.goto(url)
            # 서버 환경을 고려해 15초로 여유 있게 설정
            page.wait_for_selector('ul.oa_horoscope_list li', timeout=15000)
            
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
            english_sign = next((c for c in classes if c in WEEKDAY_SIGN_MAP), "unknown")
            korean_sign = WEEKDAY_SIGN_MAP.get(english_sign, english_sign)
            
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
    

def get_weekend_ranking():
    url = "https://www.tv-asahi.co.jp/goodmorning/uranai/"
    
    try:
        with sync_playwright() as p:
            # GitHub Actions 및 로컬 환경을 위한 브라우저 설정
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            page.goto(url, wait_until="networkidle", timeout=60000)
            # 이미지에서 확인한 rank-box 내부의 li 태그가 나타날 때까지 대기
            page.wait_for_selector('.rank-box li', timeout=20000)

            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, 'html.parser')
        rank_items = soup.select('.rank-box li a')
        
        if not rank_items:
            return "❌ 데이터를 찾지 못했습니다. 사이트 구조가 변경되었을 수 있습니다."

        msg_lines = ["✨ **오늘의 오하아사 별자리 순위** ✨\n"]
        
        for index, item in enumerate(rank_items, start=1):
            # <a> 태그의 data-label 속성값 가져오기 (예: sisi, ite...)
            label = item.get('data-label', '').strip().lower()
            
            # 주말 전용 매핑 테이블에서 한글 이름 찾기
            korean_sign = WEEKEND_SIGN_MAP.get(label, f"알 수 없음({label})")
            
            rank_val = index
            if rank_val == 1: emoji = "🥇"
            elif rank_val == 2: emoji = "🥈"
            elif rank_val == 3: emoji = "🥉"
            else: emoji = "🔹"
            
            msg_lines.append(f"{emoji} **{rank_val}위**: {korean_sign}")
            
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

    now = datetime.now()
    weekday = now.weekday() # 0:월 ~ 4:금, 5:토, 6:일

    if weekday < 5:
        result_message = get_weekday_ranking()
    else:
        result_message = get_weekend_ranking()

    send_discord(result_message)
