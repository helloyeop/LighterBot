# 🔗 TradingView 웹훅 설정 가이드

## 🎯 핵심 포인트

TradingView 웹훅은 **포트 80(HTTP) 또는 443(HTTPS)에서만** 작동합니다.
현재 시스템은 포트 8000에서 실행되므로 **Nginx 리버스 프록시**가 필요합니다.

## 🛠️ 설정 방법

### 1. VPS에 Nginx 설정

```bash
# 자동 설정 스크립트 실행
./setup_port80_webhook.sh
```

또는 수동 설정:

```bash
# 1. Nginx 설정 파일 업로드
scp nginx/lighter-api.conf root@45.76.210.218:/etc/nginx/sites-available/lighter-api

# 2. 사이트 활성화
ssh root@45.76.210.218 'ln -sf /etc/nginx/sites-available/lighter-api /etc/nginx/sites-enabled/'

# 3. Nginx 재시작
ssh root@45.76.210.218 'nginx -t && systemctl restart nginx'

# 4. 방화벽 설정
ssh root@45.76.210.218 'ufw allow 80/tcp && ufw allow 443/tcp'
```

### 2. SSL 인증서 설정 (HTTPS 필수)

```bash
# Certbot 설치
ssh root@45.76.210.218 'apt install -y certbot python3-certbot-nginx'

# SSL 인증서 발급
ssh root@45.76.210.218 'certbot --nginx -d ypab5.com'
```

### 3. 애플리케이션 실행 확인

```bash
# 서비스 상태 확인
ssh root@45.76.210.218 'systemctl status lighter-api'

# 포트 8000에서 실행 확인
ssh root@45.76.210.218 'curl http://localhost:8000/health'
```

## 📡 TradingView 웹훅 URL

### ✅ 사용할 URL들

#### 🎯 특정 계정 (권장)
```
https://ypab5.com/webhook/tradingview/account/143145
```

#### 🎯 모든 계정
```
https://ypab5.com/webhook/tradingview
```

#### 🔍 헬스 체크
```
https://ypab5.com/webhook/health
```

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

### 알림 메시지 템플릿

#### 🔹 특정 계정 (account_index 143145)
```json
{
  "secret": "lighter_to_the_moon_2918",
  "action": "{{strategy.order.action}}",
  "symbol": "{{ticker}}",
  "leverage": 1,
  "account_index": 143145
}
```

#### 🔹 모든 계정
```json
{
  "secret": "lighter_to_the_moon_2918",
  "action": "{{strategy.order.action}}",
  "symbol": "{{ticker}}",
  "leverage": 1
}
```

#### 🔹 포지션 종료
```json
{
  "secret": "lighter_to_the_moon_2918",
  "action": "close",
  "symbol": "{{ticker}}",
  "leverage": 1
}
```

## 🔧 트러블슈팅

### 1. 웹훅이 도달하지 않는 경우

```bash
# Nginx 로그 확인
ssh root@45.76.210.218 'tail -f /var/log/nginx/webhook_access.log'

# 애플리케이션 로그 확인
ssh root@45.76.210.218 'journalctl -u lighter-api -f'

# 방화벽 상태 확인
ssh root@45.76.210.218 'ufw status'
```

### 2. SSL 인증서 문제

```bash
# 인증서 상태 확인
ssh root@45.76.210.218 'certbot certificates'

# 인증서 갱신
ssh root@45.76.210.218 'certbot renew'
```

### 3. 도메인 연결 확인

```bash
# DNS 확인
nslookup ypab5.com

# 도메인 접근 테스트
curl -I https://ypab5.com/webhook/health
```

## 📊 모니터링

### 실시간 웹훅 모니터링

```bash
# 웹훅 요청 로그
ssh root@45.76.210.218 'tail -f /var/log/nginx/webhook_access.log'

# 애플리케이션 로그
ssh root@45.76.210.218 'journalctl -u lighter-api -f --no-pager'

# 시스템 리소스
ssh root@45.76.210.218 'htop'
```

### 웹훅 테스트

```bash
# 수동 웹훅 테스트
curl -X POST https://ypab5.com/webhook/tradingview/account/143145 \
  -H "Content-Type: application/json" \
  -d '{
    "secret": "lighter_to_the_moon_2918",
    "action": "buy",
    "symbol": "BTC",
    "leverage": 1
  }'
```

## 🎯 시스템 구조

```
TradingView → 포트 443 (HTTPS) → Nginx → 포트 8000 (애플리케이션)
             https://ypab5.com      ↓     http://localhost:8000
                                   리버스 프록시
```

## ⚡ 성능 최적화

### Nginx 설정 튜닝

```nginx
# /etc/nginx/nginx.conf에 추가
worker_processes auto;
worker_connections 1024;

# keepalive 설정
keepalive_timeout 30;
keepalive_requests 100;

# gzip 압축
gzip on;
gzip_types application/json text/plain;
```

### 로그 로테이션

```bash
# 로그 로테이션 설정
ssh root@45.76.210.218 'cat > /etc/logrotate.d/lighter-webhook << EOF
/var/log/nginx/webhook_*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    postrotate
        systemctl reload nginx
    endscript
}
EOF'
```

## 🔐 보안 설정

### IP 화이트리스트 (선택사항)

```nginx
# Nginx 설정에 추가
location /webhook/ {
    # TradingView IP 범위
    allow 52.89.214.238;
    allow 34.212.75.30;
    allow 52.32.178.7;
    allow 54.218.53.128;
    allow 52.36.31.181;
    deny all;

    proxy_pass http://127.0.0.1:8000/webhook/;
    # ... 기타 설정
}
```

## ✅ 설정 완료 체크리스트

- [ ] Nginx 설치 및 설정
- [ ] SSL 인증서 설정
- [ ] 방화벽 포트 80/443 허용
- [ ] 애플리케이션 포트 8000에서 실행
- [ ] 도메인 DNS 연결 확인
- [ ] 웹훅 URL 테스트 성공
- [ ] TradingView 알림 설정 완료
- [ ] 로그 모니터링 설정

이제 TradingView에서 https://ypab5.com/webhook/tradingview 로 웹훅을 보낼 수 있습니다!