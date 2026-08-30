# 아침별점 일일 알림 & 세부 운세 봇

## 설명

오하아사 순위와 세부 운세를 매일 아침 알려주는 디스코드 봇입니다.

- **일일 순위 알림 (Webhook 방식)**  
  특정 시간에 아사히 아침별점(おは朝星占い) 홈페이지를 크롤링하여 순위 메시지를 전달합니다.
  * 평일 : <https://www.asahi.co.jp/ohaasa/week/horoscope/>
  * 주말 : <https://www.tv-asahi.co.jp/goodmorning/uranai/>

- **세부 운세 조회 (슬래시 커맨드)**  
  디스코드에서 `/오하아사 별자리:처녀자리` 형태로 조회 시,
  일본어 원문을 한국어로 번역한 세부 운세와 행운의 아이템/색깔을 응답합니다.

- **[디스코드 서버에 봇 설정 링크](https://discord.com/oauth2/authorize?client_id=1485396590519910473&permissions=2147502080&integration_type=0&scope=bot+applications.commands)**

![](/src/ohaasa-discord-bot-01.png)

![](/src/ohaasa-discord-bot-02.png)

## 파일 구조
```
├── .github
│   └── workflows
│       ├── daily_bot.yml          # 매일 크롤 + 알림 발송 + 커밋&푸시 (GitHub Actions)
│       ├── register_commands.yml  # 슬래시 커맨드 등록 (수동 실행)
│       ├── stats_report.yml       # 월간 리포트 발송
│       ├── preview_only.yml       # 최신 데이터로 프리뷰 채널 발송 (수동 실행)
│       ├── preview_on_pr.yml      # 코드 변경 PR 시 자동 프리뷰
│       └── thread_test.yml        # 연간 리포트 쓰레드 발송 사전 검증
├── api
│   └── index.py                   # Discord Interactions 엔드포인트 — 운세 조회 + 알림 채널 설정 커맨드 (Vercel)
├── data
│   ├── horoscope_YYYY-MM-DD.json  # 날짜별 운세 데이터 (자동 생성)
│   └── latest.json                # 가장 최신 운세 (봇이 조회)
├── test
│   ├── preview_webhook.py         # 테스트 웹훅으로 번역 결과 프리뷰 발송
│   ├── build_email_report.py      # 일일 테스트 리포트 이메일 본문 생성
│   └── test_thread.py             # 연간 리포트 채널→쓰레드 발송 흐름 더미 테스트
├── src                            # README/랜딩 페이지용 이미지
├── channels.py                    # Upstash Redis 기반 서버별 알림 채널 저장소 (등록/조회/해제)
├── notifier.py                    # Bot API 멀티채널 발송 — 재시도/백오프/에러분류/실패요약 알림
├── main.py                        # 크롤링 + 번역 + JSON 저장 + 알림 발송(Bot API, 웹훅은 폴백으로 보존)
├── register_commands.py           # 슬래시 커맨드 1회성 등록 스크립트
├── requirements.txt
├── stats.py                       # 월간 리포트 생성 + 알림 발송
├── index.html                     # 프로젝트 소개 랜딩 페이지
└── vercel.json                    # Vercel 배포 리전 설정
```

## 전체 구조도

### 매일 아침 — 순위 알림 & 데이터 적재
```
┌─────────────────────────────────────────────────────────┐
  1. 스케줄러 & 실행 환경 (GitHub Actions - daily_bot.yml)
└─────────────────────────────────────────────────────────┘
│ - 매일 아침 특정 시간(cron) 또는 수동 실행
│ - Ubuntu 가상 서버 할당
│ - Python, Playwright, Chrome 브라우저 설치
▼
┌─────────────────────────────────────────────────────────┐
  2. 데이터 수집 / 크롤링 (main.py - Playwright)
└─────────────────────────────────────────────────────────┘
│ - 아사히 방송 오하아사 웹페이지 호출 (평일/주말 분기)
│ - Headless 크롬 브라우저 백그라운드 실행
│ - 자바스크립트가 데이터를 채울 때까지 대기 (최대 20초)
│ - 데이터가 모두 로딩된 최종 HTML 코드 확보
▼
┌─────────────────────────────────────────────────────────┐
  3. 데이터 가공 / 파싱 (main.py - BeautifulSoup)
└─────────────────────────────────────────────────────────┘
│ - HTML 내에서 별자리 순위/본문/행운 정보 추출 (12개)
│ - 평일: 클래스명(aries 등) + 마지막 공백 뒤 = 행운의 아이템
│ - 주말: a 태그의 data-label(ohitsuji 등) + 행운의 색/아이템
│ - 영문/일본어 키를 한글 별자리명으로 매핑
▼
┌─────────────────────────────────────────────────────────┐
  4. 번역 (main.py - DeepL API)
└─────────────────────────────────────────────────────────┘
│ - 일본어 원문(content_ja, lucky_item_ja, lucky_color_ja)을
│   DeepL API로 한 번에 배치 번역 (JA → KO)
│ - 번역 실패 시 원문만 저장하는 폴백 로직 포함
▼
┌─────────────────────────────────────────────────────────┐
  5. JSON 저장 (main.py - json)
└─────────────────────────────────────────────────────────┘
│ - 날짜별 파일: data/horoscope_YYYY-MM-DD.json
│ - 최신 파일: data/latest.json (봇 조회용)
│ - GitHub Actions가 자동으로 커밋 & 푸시
▼
┌─────────────────────────────────────────────────────────┐
  6. 알림 발송 (main.py → notifier.py, channels.py)
└─────────────────────────────────────────────────────────┘
│ - Upstash Redis에서 서버별로 등록된 알림 채널 목록 조회
│ - 채널마다 Discord Bot API로 순위 임베드 발송
│ - 실패 시 채널당 최대 3회 지수 백오프 재시도
│   (429/5xx/timeout → 재시도, 403/404 → 영구 실패, 401 → 전체 중단)
│ - 예비 cron이 같은 날 재실행돼도 이미 성공한 채널은 건너뜀
│   (Upstash의 sent:{date} 기록 기준)
│ - 남은 실패가 있으면 TEST_DISCORD_WEBHOOK으로 실패 요약 알림
│ - DISCORD_WEBHOOK(단일 채널 전송)은 현재 비활성화된 폴백 경로로 코드에 보존
│ - E-mail로 순위 및 번역 정보가 포함된 테스트 리포트 전달
│ - 어제 파일(data/horoscope_YYYY-MM-DD.json)과 순위 비교
▼
┌─────────────────────────────────────────────────────────┐
  7. 최종 목적지 (Discord App)
└─────────────────────────────────────────────────────────┘
등록된 각 서버 채널에 순위 메시지 도착!
```

### 유저 요청 시 — 세부 운세 응답
```
┌─────────────────────────────────────────────────────────┐
  1. 유저 입력 (Discord Client)
└─────────────────────────────────────────────────────────┘
│ - '/오하아사 별자리:처녀자리' 슬래시 커맨드 실행
▼
┌─────────────────────────────────────────────────────────┐
  2. 요청 라우팅 (Discord API)
└─────────────────────────────────────────────────────────┘
│ - Interactions Endpoint URL로 HTTP POST 전송
│ - 3초 응답 데드라인
▼
┌─────────────────────────────────────────────────────────┐
  3. 서명 검증 & 데이터 조회 (Vercel - api/index.py)
└─────────────────────────────────────────────────────────┘
│ - X-Signature-Ed25519 헤더 검증 (PyNaCl)
│ - PING(type=1) 응답 처리
│ - raw.githubusercontent.com에서 latest.json fetch (CDN 캐싱)
▼
┌─────────────────────────────────────────────────────────┐
  4. 임베드 응답 (Vercel - api/index.py)
└─────────────────────────────────────────────────────────┘
│ - 순위, 한국어 본문, 행운의 색/아이템으로 임베드 구성
│ - 평일/주말 모드에 따라 필드 자동 분기
│ - Discord에 type=4 응답 전송
▼
┌─────────────────────────────────────────────────────────┐
  5. 최종 목적지 (Discord App)
└─────────────────────────────────────────────────────────┘
유저 채널에 상세 운세 임베드 표시!
```

### 알림 채널 등록/변경/해제 — `/오하아사설정`
```
┌─────────────────────────────────────────────────────────┐
  1. 유저 입력 (Discord Client)
└─────────────────────────────────────────────────────────┘
│ - '/오하아사설정 알림설정 채널:#운세' 등 서브커맨드 실행
│ - Discord UI에서 '서버 관리(Manage Guild)' 권한자에게만 노출
▼
┌─────────────────────────────────────────────────────────┐
  2. 요청 라우팅 & 서명·권한 검증 (Vercel - api/index.py)
└─────────────────────────────────────────────────────────┘
│ - X-Signature-Ed25519 헤더 검증 (PyNaCl)
│ - member.permissions로 서버 관리 권한 서버단 재검증
▼
┌─────────────────────────────────────────────────────────┐
  3. 채널 등록/변경/해제 (Vercel - channels.py)
└─────────────────────────────────────────────────────────┘
│ - 알림설정: Upstash에 channels:{guild_id} SET + channels:index SADD
│ - 알림해제: DEL + SREM (등록 해제는 이 경로로만 발생 — 발송 실패로는 해제 안 됨)
│ - 알림확인: 현재 등록된 채널 조회
▼
┌─────────────────────────────────────────────────────────┐
  4. 즉시 테스트 발송 (Vercel - notifier.py)
└─────────────────────────────────────────────────────────┘
│ - 등록/변경 직후 Bot API로 해당 채널에 테스트 메시지 1회 발송
│ - 403 등 실패 시 권한 안내 메시지를 ephemeral로 응답
▼
┌─────────────────────────────────────────────────────────┐
  5. 운영 모니터링 알림 (Vercel - notifier.py)
└─────────────────────────────────────────────────────────┘
│ - 신규 등록/변경/해제 이벤트를 TEST_DISCORD_WEBHOOK으로 전송
│ - 실행자, 서버/채널, 테스트 발송 성공·실패 여부 포함
▼
┌─────────────────────────────────────────────────────────┐
  6. 최종 목적지 (Discord App)
└─────────────────────────────────────────────────────────┘
요청한 유저에게는 ephemeral 응답, 운영자에게는 모니터링 채널로 별도 알림!
```

## 데이터 스키마 (data/latest.json)

### 평일

```json
{
  "date": "2026-06-30",
  "mode": "weekday",
  "source_url": "https://www.asahi.co.jp/ohaasa/week/horoscope/",
  "updated_at_kst": "2026-06-30T07:01:23",
  "signs": {
    "처녀자리": {
      "rank": 1,
      "sign_kr": "처녀자리",
      "sign_ja": "おとめ座",
      "sign_key": "virgo",
      "content_ja": "周りに好印象を与えられます。挨拶や礼儀を大切にしましょう。",
      "content_ko": "주위에 좋은 인상을 남길 수 있어요. 인사와 예의를 중요시하면 좋아요.",
      "lucky_item_ja": "映画館",
      "lucky_item_ko": "영화관"
    }
  }
}
```

### 주말

```json
{
  "date": "2026-07-04",
  "mode": "weekend",
  "signs": {
    "처녀자리": {
      "rank": 3,
      "sign_kr": "처녀자리",
      "sign_ja": "おとめ座",
      "sign_key": "otome",
      "content_ja": "新しい出会いに恵まれる週末。素直な気持ちを伝えてみて。",
      "content_ko": "새로운 만남이 가득한 주말. 솔직한 마음을 전해보세요.",
      "lucky_color_ja": "ターコイズブルー",
      "lucky_color_ko": "터쿼이즈 블루",
      "lucky_item_ja": "シルバーのアクセサリー",
      "lucky_item_ko": "실버 액세서리"
    }
  }
}
```


## 필요한 환경 변수 (GitHub Secrets & Vercel)

### GitHub Secrets — 매일 크롤/알림 & 커맨드 등록

| Secret | 용도 | 발급처 |
|---|---|---|
| `DISCORD_WEBHOOK` | (현재 비활성화) 단일 채널 웹훅 전송 — 코드에 폴백용으로 주석 보존 | Discord 채널 → 연동 → 웹후크 |
| `TEST_DISCORD_WEBHOOK` | 프리뷰 채널 발송 + 알림 발송 실패/채널 등록 이벤트 모니터링 | Discord 채널 → 연동 → 웹후크 |
| `DISCORD_APP_ID` | 슬래시 커맨드 등록 | Developer Portal → General Information |
| `DISCORD_BOT_TOKEN` | 슬래시 커맨드 등록 인증 + Bot API 알림 발송 | Developer Portal → Bot → Reset Token |
| `DEEPL_API_KEY` | 일본어 → 한국어 운세 번역 | <https://www.deepl.com/pro-api> |
| `UPSTASH_REDIS_REST_URL` | 서버별 알림 채널 등록 정보 저장 | Upstash 콘솔 → REST API |
| `UPSTASH_REDIS_REST_TOKEN` | 위와 동일 | Upstash 콘솔 → REST API |

### Vercel Environment Variables — Interactions 엔드포인트(운세 조회 + 알림 채널 설정)용

| Variable | 용도 | 발급처 |
|---|---|---|
| `DISCORD_PUBLIC_KEY` | Interactions 요청 서명 검증 | Developer Portal → General Information |
| `DISCORD_APP_ID` | 팔로우업 응답 전송 | Developer Portal → General Information |
| `DISCORD_BOT_TOKEN` | 채널 등록 시 즉시 테스트 발송 | Developer Portal → Bot → Reset Token |
| `UPSTASH_REDIS_REST_URL` | 알림 채널 등록/조회/해제 | Upstash 콘솔 → REST API |
| `UPSTASH_REDIS_REST_TOKEN` | 위와 동일 | Upstash 콘솔 → REST API |
| `TEST_DISCORD_WEBHOOK` | 채널 등록/변경/해제 모니터링 알림 | Discord 채널 → 연동 → 웹후크 |


## 사용 스택

- **크롤링**: Python, Playwright, BeautifulSoup4
- **번역**: DeepL API (JA → KO)
- **스케줄링 & 데이터 저장**: GitHub Actions, Git 자동 커밋
- **알림 채널 저장소**: Upstash Redis (REST API)
- **서버리스 함수**: Vercel Python Runtime (`api/index.py`)
- **서명 검증**: PyNaCl (Ed25519)
- **디스코드 통신**: Discord Bot API (멀티채널 알림 발송, 재시도/백오프), Webhook (프리뷰·모니터링·폴백), Interactions (요청-응답)


## 버전

- 1.3.0(260831)
  - Bot 토큰 기반 채널 등록제 적용
  - GitHub Actions 실행 스케줄 개선
  - 오하아사 봇 웹페이지 개설
- 1.2.1(260731)
  - 일일 테스트 리포트 이메일로 전달
  - 월간 순위 리포트 웹후크를 이용하여 메세지 전달
    - 평균 순위 1~12위
    - 최다 1등, 최다 12등
    - 최저 표준편차(안정형 상), 최고 표준편차(기복형 상) 
- 1.2.0(260704)
  - 세부 운세 조회 슬래시 커맨드 추가 (`/오하아사 별자리:...`)
  - 일본어 원문 + DeepL 한국어 번역 병행 저장
  - 평일/주말 스키마 분기 (평일은 행운 아이템만, 주말은 행운 색/아이템 모두)
  - Vercel Interactions 엔드포인트 구축
  - 날짜별 JSON 아카이빙 (data/horoscope_YYYY-MM-DD.json)
  - 전날과 순위 비교 후 등락 표기
- 1.1.0(260402)
  - 평일/주말 기준 사이트 판별
  - 당일 별자리 순위 불러오기
  - 특정 시간 웹후크를 이용하여 메세지 전달
