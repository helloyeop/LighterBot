# 🔗 TradingView 웹훅 설정 가이드 (IP 기반)

## 🎯 핵심 포인트

TradingView 웹훅은 **포트 80(HTTP) 또는 443(HTTPS)에서만** 작동합니다.
현재 시스템은 포트 8000에서 실행되므로 **Nginx 리버스 프록시**가 필요합니다.

**도메인이 필요 없습니다!** VPS IP 주소를 직접 사용합니다.

## 🛠️ 설정 방법

### 1. VPS에 IP 기반 Nginx 설정

```bash
# IP 기반 Nginx 설정 (도메인 불필요)
cat > /etc/nginx/sites-available/lighter-api-ip << 'EOF'
server {
    listen 80 default_server;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /webhook/ {
        proxy_pass http://127.0.0.1:8000/webhook/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

# 기존 설정 제거하고 새 설정 활성화
rm -f /etc/nginx/sites-enabled/*
ln -sf /etc/nginx/sites-available/lighter-api-ip /etc/nginx/sites-enabled/lighter-api-ip

# Nginx 재시작
nginx -t && systemctl restart nginx

# 방화벽 설정
ufw allow 80/tcp
```

### 2. IP 제한 해제 설정 (중요!)

```bash
# 환경 변수에 IP 제한 해제 추가
echo "TRADINGVIEW_ALLOWED_IPS=0.0.0.0" >> /opt/lighter_api/.env

# 애플리케이션 재시작
systemctl restart lighter-api
```

### 3. 배포 확인

```bash
# 로컬 테스트
curl http://localhost:8000/health

# 외부 접근 테스트 (YOUR_VPS_IP를 실제 IP로 변경)
curl http://YOUR_VPS_IP/webhook/health

# 웹훅 시그널 테스트
curl -X POST http://YOUR_VPS_IP/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTC","sale":"long","leverage":1,"secret":"lighter_to_the_moon_2918"}'
```

## 📡 TradingView 웹훅 URL (IP 기반)

### ✅ 실제 사용할 URL들

**YOUR_VPS_IP를 실제 VPS IP로 변경하세요!**

#### 🎯 특정 계정 (권장)
```
http://YOUR_VPS_IP/webhook/tradingview/account/143145
```
**예시:** `http://YOUR_VPS_IP/webhook/tradingview/account/143145`

#### 🎯 모든 계정
```
http://YOUR_VPS_IP/webhook/tradingview
```
**예시:** `http://YOUR_VPS_IP/webhook/tradingview`

#### 🔍 헬스 체크
```
http://YOUR_VPS_IP/webhook/health
```
**예시:** `http://YOUR_VPS_IP/webhook/health`

## 🧪 TradingView 알림 설정

### Pine Script 예시

```pine
//@version=5
strategy("Multi-Account Signal", overlay=true)

// 매수 조건
buy_condition = ta.crossover(ta.sma(close, 10), ta.sma(close, 20))

// 매도 조건
sell_condition = ta.crossunder(ta.sma(close, 10), ta.sma(close, 20))

if buy_condition
    strategy.entry("Long", strategy.long)

if sell_condition
    strategy.close("Long")

// 알림 설정
alertcondition(buy_condition, title="Buy Signal", message='{"secret": "lighter_to_the_moon_2918", "action": "buy", "symbol": "{{ticker}}", "leverage": 1}')

alertcondition(sell_condition, title="Sell Signal", message='{"secret": "lighter_to_the_moon_2918", "action": "sell", "symbol": "{{ticker}}", "leverage": 1}')
```

### 🎯 웹훅 메시지 템플릿 (올바른 형식)

#### 🔹 LONG 시그널 (모든 계정)
```json
{
  "symbol": "{{ticker}}",
  "sale": "long",
  "leverage": 1,
  "secret": "lighter_to_the_moon_2918"
}
```

#### 🔹 SHORT 시그널 (모든 계정)
```json
{
  "symbol": "{{ticker}}",
  "sale": "short",
  "leverage": 1,
  "secret": "lighter_to_the_moon_2918"
}
```

#### 🔹 포지션 종료 (모든 계정)
```json
{
  "symbol": "{{ticker}}",
  "sale": "close",
  "leverage": 1,
  "secret": "lighter_to_the_moon_2918"
}
```

## 🔧 트러블슈팅

### 1. 웹훅이 도달하지 않는 경우

```bash
# Nginx 로그 확인
ssh root@YOUR_VPS_IP 'tail -f /var/log/nginx/webhook_access.log'

# 애플리케이션 로그 확인
ssh root@YOUR_VPS_IP 'journalctl -u lighter-api -f'

# 방화벽 상태 확인
ssh root@YOUR_VPS_IP 'ufw status'
```

### 2. IP 접근 문제

```bash
# IP 직접 테스트
curl http://YOUR_VPS_IP/webhook/health

# 포트 확인
ssh root@YOUR_VPS_IP 'netstat -tulpn | grep :80'

# Nginx 상태 확인
ssh root@YOUR_VPS_IP 'systemctl status nginx'
```

### 3. 웹훅 인증 실패 (401 에러)

```bash
# 시크릿 토큰 확인
ssh root@YOUR_VPS_IP 'grep TRADINGVIEW_SECRET_TOKEN /opt/lighter_api/.env'

# IP 제한 확인
ssh root@YOUR_VPS_IP 'grep TRADINGVIEW_ALLOWED_IPS /opt/lighter_api/.env'

# 올바른 웹훅 테스트
curl -X POST http://YOUR_VPS_IP/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTC","sale":"long","leverage":1,"secret":"lighter_to_the_moon_2918"}'
```

## 📊 모니터링

### 실시간 웹훅 모니터링

```bash
# 웹훅 요청 로그
ssh root@YOUR_VPS_IP 'tail -f /var/log/nginx/webhook_access.log'

# 애플리케이션 로그
ssh root@YOUR_VPS_IP 'journalctl -u lighter-api -f --no-pager'

# 시스템 리소스
ssh root@YOUR_VPS_IP 'htop'
```

### 웹훅 테스트 (IP 기반)

```bash
# 수동 웹훅 테스트 (YOUR_VPS_IP를 실제 IP로 변경)
curl -X POST http://YOUR_VPS_IP/webhook/tradingview/account/143145 \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTC",
    "sale": "long",
    "leverage": 1,
    "secret": "lighter_to_the_moon_2918"
  }'

# 모든 계정 테스트
curl -X POST http://YOUR_VPS_IP/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTC",
    "sale": "long",
    "leverage": 1,
    "secret": "lighter_to_the_moon_2918"
  }'
```

## 🎯 최종 요약

### ✅ 핵심 설정사항

1. **웹훅 URL**: `http://YOUR_VPS_IP/webhook/tradingview`
2. **메시지 형식**: JSON에 `"secret": "lighter_to_the_moon_2918"` 필수
3. **IP 제한**: `TRADINGVIEW_ALLOWED_IPS=0.0.0.0` (모든 IP 허용)
4. **포트 설정**: Nginx 포트 80 → 애플리케이션 포트 8000

### 🔧 핵심 명령어

```bash
# IP 제한 해제
echo "TRADINGVIEW_ALLOWED_IPS=0.0.0.0" >> /opt/lighter_api/.env
systemctl restart lighter-api

# 웹훅 테스트
curl -X POST http://YOUR_VPS_IP/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTC","sale":"long","leverage":1,"secret":"lighter_to_the_moon_2918"}'
```

### 📋 체크리스트

- [ ] VPS IP 주소 확인
- [ ] Nginx 포트 80 설정 완료
- [ ] IP 제한 해제 설정
- [ ] 웹훅 테스트 성공
- [ ] 트레이딩뷰 알림 설정 완료

**도메인이 필요 없습니다! IP 주소만 있으면 됩니다.**

### 📊 시스템 흐름

```
TradingView → 포트 80 (HTTP) → Nginx → 포트 8000 (애플리케이션)
             http://VPS_IP       ↓     http://localhost:8000
                                리버스 프록시
```

**🎉 설정 완료! 이제 트레이딩뷰에서 웹훅을 사용할 수 있습니다.**
