# 🚀 Lighter API Trading Bot

TradingView 신호를 받아 Lighter DEX에서 자동으로 거래를 실행하는 전문적인 멀티 계정 자동 거래 시스템입니다.

## 🎯 주요 특징

- **멀티 계정 지원**: 최대 4개 계정 동시 거래
- **TradingView 통합**: 웹훅을 통한 실시간 신호 처리
- **자동 재시도**: Nonce 에러 자동 복구
- **VPS 최적화**: 1 vCPU / 1GB RAM 환경 최적화
- **배치 처리**: 리소스 효율적인 2개씩 계정 처리

## 🚀 빠른 시작

### 1. 설치 및 실행
```bash
# 저장소 클론
git clone https://github.com/helloyeop/LighterBot.git
cd LighterBot

# 가상환경 설정
python3 -m venv venv
source venv/bin/activate

# 의존성 설치
pip install -r requirements.txt

# 환경변수 설정
cp .env.example .env
nano .env  # API 키 입력

# 실행
python main.py
```

### 2. 환경 설정 (.env)
```bash
# Lighter DEX 설정
LIGHTER_API_KEY=your_api_key_here
LIGHTER_API_SECRET=your_api_secret_here
LIGHTER_NETWORK=mainnet
LIGHTER_ENDPOINT=https://mainnet.zklighter.elliot.ai
LIGHTER_ACCOUNT_INDEX=143145
LIGHTER_API_KEY_INDEX=3

# 웹훅 설정
TRADINGVIEW_SECRET_TOKEN=lighter_to_the_moon_2918
TRADINGVIEW_ALLOWED_IPS=0.0.0.0  # 모든 IP 허용

# 서버 설정
PORT=8000
HOST=0.0.0.0  # 외부 접근 필수
```

### 3. 멀티 계정 설정 (config/accounts.json)
```json
{
  "accounts": [
    {
      "account_index": 143145,
      "api_key_index": 3,
      "api_key": "your_api_key",
      "api_secret": "your_api_secret",
      "name": "Account 1",
      "active": true,
      "allowed_symbols": ["BTC", "ETH", "BNB", "SOL"]
    },
    {
      "account_index": 267180,
      "api_key_index": 5,
      "api_key": "your_api_key_2",
      "api_secret": "your_api_secret_2",
      "name": "Account 2",
      "active": true,
      "allowed_symbols": ["BTC", "ETH"]
    }
  ],
  "default_account_index": 143145
}
```

## 📊 주요 기능

- ✅ **멀티 계정 거래**: 최대 4개 계정 동시 관리
- ✅ **TradingView 웹훅**: 실시간 신호 수신 및 처리
- ✅ **자동 시장가 주문**: 빠른 체결
- ✅ **Nonce 자동 관리**: SignerClient 내부 nonce 처리
- ✅ **자동 재시도**: 에러 발생 시 자동 복구
- ✅ **배치 처리**: 2개씩 계정 처리로 리소스 최적화
- ✅ **IP 제한 우회**: 0.0.0.0 설정으로 모든 IP 허용
- ✅ **실시간 로깅**: 상세한 거래 로그

## 🔗 API 엔드포인트

실행 후 브라우저에서 확인:
- **API 문서**: http://127.0.0.1:8000/docs
- **시스템 상태**: http://127.0.0.1:8000/health
- **리스크 상태**: http://127.0.0.1:8000/api/risk/status

## 📱 TradingView 웹훅 설정

### 웹훅 URL
- **모든 계정**: `http://YOUR_VPS_IP/webhook/tradingview`
- **특정 계정**: `http://YOUR_VPS_IP/webhook/tradingview/account/143145`

### 메시지 형식
```json
{
  "secret": "lighter_to_the_moon_2918",
  "sale": "long",  // "short", "close" 가능
  "symbol": "BTC",  // "ETH", "BNB", "SOL" 가능
  "leverage": 5,    // 최대: 20
  "quantity": 0.001 // 선택사항
}
```

### 대체 필드 지원
- `"sale"` 대신 `"buy"` (long으로 변환) 또는 `"sell"` (short으로 변환) 사용 가능
- `"sale"` 대신 `"action"` 필드 사용 가능

## 🚀 VPS 배포

### 빠른 배포 (Ubuntu)
```bash
# VPS 접속
ssh root@YOUR_VPS_IP

# 시스템 업데이트
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv git nginx ufw

# 애플리케이션 설치
cd /opt
git clone https://github.com/helloyeop/LighterBot.git lighter_api
cd lighter_api

# 가상환경 및 의존성
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 환경 설정
cp .env.example .env
nano .env  # API 키 입력

# 계정 설정
cp config/accounts.example.json config/accounts.json
nano config/accounts.json  # 계정 정보 입력

# systemd 서비스 설정
sudo systemctl enable lighter-api
sudo systemctl start lighter-api

# Nginx 설정
sudo systemctl restart nginx

# 방화벽 설정
ufw allow 80/tcp
ufw allow 22/tcp
ufw --force enable
```

자세한 내용은 [VPS_DEPLOYMENT_CHECKLIST.md](VPS_DEPLOYMENT_CHECKLIST.md) 참조

## 🛡️ 모니터링 및 디버깅

### 로그 확인
```bash
# 실시간 로그
journalctl -u lighter-api -f

# 최근 에러
journalctl -u lighter-api --since "10 minutes ago" | grep ERROR

# 특정 계정 로그
journalctl -u lighter-api -f | grep 143145
```

### 서비스 관리
```bash
# 상태 확인
systemctl status lighter-api

# 재시작
systemctl restart lighter-api

# 중지
systemctl stop lighter-api
```

### 테스트 웹훅
```bash
curl -X POST http://localhost:8000/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{"secret":"lighter_to_the_moon_2918","sale":"long","symbol":"BTC","leverage":1}'
```

## 📁 프로젝트 구조

```
lighter_api/
├── src/
│   ├── api/              # API 엔드포인트
│   │   ├── webhook.py    # TradingView 웹훅 처리
│   │   └── routes.py     # API 라우트
│   ├── core/             # 핵심 모듈
│   │   ├── account_manager_v2.py  # 멀티 계정 관리
│   │   └── lighter_client.py      # Lighter DEX 클라이언트
│   └── services/         # 서비스 레이어
│       └── multi_account_signal_service.py  # 신호 처리
├── config/
│   ├── accounts.json     # 멀티 계정 설정
│   └── performance.json  # 성능 최적화 설정
├── .env                  # 환경변수
├── main.py               # 메인 애플리케이션
└── VPS_DEPLOYMENT_CHECKLIST.md  # 배포 가이드
```

## 🔧 문제 해결

### 1. Invalid Signature 에러
- **원인**: 잘못된 API 키/시크릿 또는 api_key_index
- **해결**: accounts.json의 자격 증명 확인

### 2. Invalid Nonce 에러
- **원인**: Nonce 동기화 문제
- **해결**: 시스템이 자동으로 SignerClient 재설정 및 재시도

### 3. 403 Forbidden
- **원인**: IP 제한
- **해결**: `TRADINGVIEW_ALLOWED_IPS=0.0.0.0` 설정

### 4. Leverage 에러
- **원인**: 레버리지가 최대값(20) 초과
- **해결**: TradingView 알림에서 레버리지 감소

## ⚙️ 성능 최적화

### 제한된 VPS 리소스 (1 vCPU, 1GB RAM)

시스템은 리소스 제약 환경에 최적화되어 있습니다:
- **배치 처리**: 2개 계정씩 동시 처리
- **연결 타임아웃**: 5초로 단축
- **자동 재시도**: 일시적 에러 자동 복구
- **메모리 관리**: 효율적인 리소스 활용

### 성능 튜닝 (config/performance.json)
```json
{
  "multi_account": {
    "batch_size": 2,
    "batch_delay_seconds": 0.5,
    "connection_timeout_seconds": 5
  }
}
```

## ⚠️ 주의사항

1. **메인넷 거래**: 실제 자금이 사용됩니다
2. **API 키 보안**: 안전한 보관 필수
3. **테스트 우선**: 소액으로 충분한 테스트 후 운영
4. **모니터링**: 정기적인 로그 확인 권장
5. **백업**: accounts.json 및 .env 파일 백업

## 📈 최근 업데이트

### v2.0.0 (2024년 10월)
- ✅ 멀티 계정 지원 (최대 4개 계정)
- ✅ Nonce 관리 개선 및 자동 재시도
- ✅ 리소스 최적화를 위한 배치 처리
- ✅ IP 제한 우회 (0.0.0.0 지원)
- ✅ TradingView 웹훅 필드 유연성 (sale/buy/sell)
- ✅ 에러 처리 및 로깅 개선
- ✅ VPS 배포 최적화

## 📞 지원

- **GitHub Issues**: [버그 리포트 및 기능 요청](https://github.com/helloyeop/LighterBot/issues)
- **배포 가이드**: [VPS_DEPLOYMENT_CHECKLIST.md](VPS_DEPLOYMENT_CHECKLIST.md)
- **로그 확인**: `journalctl -u lighter-api -f`

---

**현재 배포**: VPS IP 45.76.210.218 | 상태: 🟢 운영 중
