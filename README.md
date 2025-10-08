# LighterBot

TradingView 신호를 받아 Lighter DEX에서 자동으로 거래를 실행하는 간단한 시스템입니다.

## 🚀 빠른 시작

### 1. 설치 및 실행
```bash
# 환경변수 설정
cp .env.example .env
# .env 파일을 열어 API 키 입력

# 봇 실행 (의존성 자동 설치)
python run.py
```

### 2. .env 파일 설정 (필수)
```bash
# Lighter DEX API 키 (필수)
LIGHTER_API_KEY=your_api_key_here
LIGHTER_API_SECRET=your_api_secret_here

# TradingView Webhook 시크릿 (필수)
TRADINGVIEW_SECRET_TOKEN=your_webhook_secret_here

# Telegram 알림 (선택사항)
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

## 📊 주요 기능

- ✅ **TradingView Webhook 수신**
- ✅ **자동 시장가/지정가 주문**
- ✅ **Stop Loss / Take Profit 지원**
- ✅ **리스크 관리** (포지션 크기, 일일 손실, 거래 빈도 제한)
- ✅ **Kill Switch** (긴급 정지)
- ✅ **SQLite 로컬 데이터베이스**
- ✅ **Telegram 알림** (선택사항)

## 🔗 API 엔드포인트

실행 후 브라우저에서 확인:
- **API 문서**: http://127.0.0.1:8000/docs
- **시스템 상태**: http://127.0.0.1:8000/health
- **리스크 상태**: http://127.0.0.1:8000/api/risk/status

## 📱 TradingView 설정

1. TradingView에서 Alert 생성
2. Webhook URL: `http://your-server:8000/webhook/tradingview`
3. Message 형식:

```json
{
  "secret": "your_secret_token",
  "action": "buy",
  "symbol": "BTC-USD",
  "orderType": "market",
  "quantity": 0.1,
  "leverage": 5,
  "stopLoss": 50000,
  "takeProfit": 60000,
  "strategy": "my_strategy"
}
```

## ⚙️ 리스크 설정 (기본값)

- **최대 포지션**: $100
- **최대 레버리지**: 5x
- **일일 손실 한도**: 5%
- **분당 최대 거래**: 3회

`.env` 파일에서 수정 가능:
```bash
MAX_POSITION_SIZE_USD=100
MAX_LEVERAGE=5
MAX_DAILY_LOSS_PCT=5
MAX_TRADES_PER_MINUTE=3
```

## 🛡️ 안전 기능

### Kill Switch
```bash
# 긴급 정지 (모든 거래 중단)
curl -X POST http://127.0.0.1:8000/api/risk/kill-switch/activate

# 재개
curl -X POST http://127.0.0.1:8000/api/risk/kill-switch/deactivate
```

### 모든 포지션 청산
```bash
curl -X POST http://127.0.0.1:8000/api/positions/close-all
```

## 📁 파일 구조

```
lighter_api/
├── data/                  # SQLite DB, 상태 파일
├── src/                   # 소스 코드
├── config/                # 설정
├── .env                   # 환경변수 (직접 생성)
├── run.py                 # 실행 스크립트
└── main.py                # 메인 애플리케이션
```

## 🔧 문제 해결

### 연결 오류
- Lighter API 키 확인
- 네트워크 연결 확인

### 권한 오류
```bash
chmod +x run.py
```

### 포트 충돌
`.env` 파일에서 PORT 변경:
```bash
PORT=8001
```

## ⚠️ 주의사항

1. **메인넷 거래**: 실제 자금이 사용됩니다
2. **보수적 시작**: 극소액으로 테스트 후 점진적 증가
3. **모니터링**: Telegram 알림 설정 권장
4. **백업**: 중요한 설정은 별도 보관

## 📞 지원

- GitHub Issues: 버그 리포트 및 기능 요청
- Logs: `logs/` 디렉토리에서 상세 로그 확인
