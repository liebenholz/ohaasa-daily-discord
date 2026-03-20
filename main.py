import os
import requests
import re
from datetime import datetime
import pytz
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# 1. 별자리 매핑 테이블 (평일 클래스명 & 주말 ID명 통합)
SIGN_MAP = {
    "aries": "양자리", "ohitsuji": "양자리",
    "taurus": "황소자리", "ousi": "황소자리",
    "gemini": "쌍둥이자리", "futago": "쌍둥이자리",
    "cancer": "게자리", "kani": "게자리",
    "leo": "사자자리", "sisi": "사자자리",
    "virgo": "처녀자리", "otome": "처녀자리",
    "libra": "천칭자리", "tenbin": "천칭자리",
    "scorpio": "전갈자리", "sasori": "전갈자리",
    "sagittarius": "사수자리", "ite": "사수자리",
    "capricorn": "염소자리", "yagi": "염소자리",
    "aquarius": "물병자리", "mizugame": "물병자리",
    "pisces": "물고기자리", "uo": "물고기자리"
}

def get_weekday_ranking(page):
    """[평일] 오하아사(asahi.co.jp) 크롤링"""
    url = "https://www.asahi.co.jp/ohaasa/week/horoscope/"
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_selector('ul.oa_horoscope_list li', timeout=15000)
    
    soup = BeautifulSoup(page.content(), 'html.parser')
    items = soup.select('ul.oa_horoscope_list li')
    
    results = []
    for index, item in enumerate(items, start=1):
        classes = item.get('class', [])
        sign_key = next((c for c in classes if c in SIGN_MAP), "unknown")
        results.append({"rank": index, "sign": SIGN_MAP.get(sign_key, sign_key)})
    
    return "✨ **[평일] 오늘의 오하아사 별자리 순위** ✨", results

def get_weekend_ranking(page):
    """[주말] 굿모닝 우라나이(tv-asahi.co.jp) 크롤링 - 추출 로직 강화"""
    url = "https://www.tv-asahi.co.jp/goodmorning/uranai/"
    
    # 1. 접속 및 대기
    page.goto(url, wait_until="networkidle")
    # seiza-area가 나타나거나, 최소한 seiza-box가 보일 때까지 대기
    page.wait_for_selector('.seiza-box', timeout=15000)
    
    soup = BeautifulSoup(page.content(), 'html.parser')
    boxes = soup.select('.seiza-box')
    
    results = []
    for box in boxes:
        # ID로 별자리 판별
        box_id = box.get('id', '')
        korean_sign = SIGN_MAP.get(box_id, box_id)
        
        # [핵심 수정] 박스 내부의 모든 텍스트를 합쳐서 순위(숫자+位)를 찾음
        full_text = box.get_text(separator=' ', strip=True)
        # 정규표현식으로 '1位', '12位' 등을 찾음
        rank_match = re.search(r'(\d+)位', full_text)
        
        if rank_match:
            rank_val = int(rank_match.group(1))
            results.append({"rank": rank_val, "sign": korean_sign})
        else:
            # 만약 위 방법으로도 실패하면, 차선책으로 이미지 파일명이나 클래스를 뒤져봄
            # (일부 사이트는 숫자를 이미지로 넣기도 함)
            img_tag = box.select_one('img')
            if img_tag and 'src' in img_tag.attrs:
                img_src = img_tag['src']
                # 파일명에 숫자가 포함되어 있는지 확인 (예: rank01.png)
                img_rank = re.search(r'rank(?:_)?(\d+)', img_src)
                if img_rank:
                    results.append({"rank": int(img_rank.group(1)), "sign": korean_sign})

    # 중복 제거 및 정렬
    unique_results = {res['sign']: res for res in results}.values()
    final_results = sorted(unique_results, key=lambda x: x['rank'])
    
    return "☀️ **[주말] 고고 호로스코프 순위** ☀️", final_results

if __name__ == "__main__":
    # 한국 시간(KST) 기준 요일 계산
    tz_kst = pytz.timezone('Asia/Seoul')
    now_kst = datetime.now(tz_kst)
    weekday = now_kst.weekday() # 0:월 ~ 6:일

    with sync_playwright() as p:
        # 일반 브라우저처럼 보이게 하기 위한 헤더 설정
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.34 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.34"
        )
        page = context.new_page()
        
        try:
            if weekday < 7: # 월~금 (평일)
                title, results = get_weekday_ranking(page)
            else: # 토~일 (주말)
                title, results = get_weekend_ranking(page)
            
            send_discord(title, results)
        except Exception as e:
            print(f"❌ 실행 중 오류 발생: {e}")
        finally:
            browser.close()