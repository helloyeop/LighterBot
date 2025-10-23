# 🚀 VPS 배포 가이드 (Git 사용)

## 📋 사전 준비

### VPS 정보
- **IP**: 45.76.210.218
- **사용자**: root
- **도메인**: ypab5.com
- **포트**: 8000 (애플리케이션), 80/443 (웹훅)

## 🔧 1단계: VPS 기본 설정

```bash
# VPS 접속
ssh root@45.76.210.218

# 시스템 업데이트
apt update && apt upgrade -y

# 필수 패키지 설치
apt install -y python3 python3-pip python3-venv git nginx certbot python3-certbot-nginx ufw

# Git 설정 (선택사항)
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"
```

## 🗂️ 2단계: 애플리케이션 배포

```bash
# 작업 디렉토리 생성
mkdir -p /opt/lighter_api
cd /opt/lighter_api

# Git에서 최신 코드 클론
git clone https://github.com/helloyeop/LighterBot.git .

# 가상환경 생성 및 활성화
python3 -m venv venv
source venv/bin/activate

# 의존성 설치
pip install -r requirements.txt
```

## ⚙️ 3단계: 환경 설정

```bash
# .env 파일 생성
cat > .env << 'EOF'
LIGHTER_API_KEY=your_api_key
LIGHTER_API_SECRET=your_api_secret
LIGHTER_ACCOUNT_INDEX=143145
LIGHTER_API_KEY_INDEX=3
TRADINGVIEW_SECRET_TOKEN=lighter_to_the_moon_2918
PORT=8000
HOST=127.0.0.1

# 웹훅 IP 제한 해제 (모든 IP 허용)
TRADINGVIEW_ALLOWED_IPS=0.0.0.0
EOF

# .env 파일 권한 설정
chmod 600 .env
```

## 🔄 4단계: 계정 설정 (멀티 계정)

```bash
# 계정 설정 파일 확인 및 수정
nano config/accounts.json

# 또는 마이그레이션 도구 사용
python3 migrate_to_multi_account.py
```

## 🌐 5단계: Nginx 웹훅 설정 (포트 80)

```bash
# IP 기반 Nginx 설정 생성 (도메인 없이)
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

# Nginx 설정 테스트
nginx -t

# Nginx 재시작
systemctl restart nginx
```

## 🔥 6단계: 방화벽 설정

```bash
# UFW 활성화 및 규칙 추가
ufw --force enable
ufw allow 22/tcp      # SSH
ufw allow 80/tcp      # HTTP
ufw allow 443/tcp     # HTTPS
ufw allow 8000/tcp    # 애플리케이션 (선택사항)

# 상태 확인
ufw status
```

## ⚡ 7단계: 시스템 서비스 생성

```bash
# systemd 서비스 파일 생성
cat > /etc/systemd/system/lighter-api.service << 'EOF'
[Unit]
Description=Lighter API Trading Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/lighter_api
Environment=PATH=/opt/lighter_api/venv/bin
ExecStart=/opt/lighter_api/venv/bin/python /opt/lighter_api/main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# 서비스 등록 및 시작
systemctl daemon-reload
systemctl enable lighter-api
systemctl start lighter-api

# 서비스 상태 확인
systemctl status lighter-api
```

## 🧪 8단계: 배포 확인

```bash
# 로컬 애플리케이션 테스트
curl http://localhost:8000/health

# 외부 웹훅 엔드포인트 테스트 (포트 80)
curl http://45.76.210.218/webhook/health

# 계정 정보 확인
curl http://45.76.210.218/api/accounts/

# 웹훅 시그널 테스트 (중요!)
curl -X POST http://45.76.210.218/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTC","sale":"long","leverage":1,"secret":"lighter_to_the_moon_2918"}'

# 특정 계정 웹훅 테스트
curl -X POST http://45.76.210.218/webhook/tradingview/account/143145 \
  -H "Content-Type: application/json" \
  -d '{"symbol":"ETH","sale":"long","leverage":1,"secret":"lighter_to_the_moon_2918"}'

# 로그 확인
journalctl -u lighter-api -f
```

## 🔄 업데이트 스크립트

```bash
# 편리한 업데이트를 위한 스크립트 생성
cat > /opt/lighter_api/update.sh << 'EOF'
#!/bin/bash
echo "🔄 Updating Lighter API..."

# 서비스 중지
systemctl stop lighter-api

# 최신 코드 풀
git pull origin main

# 의존성 업데이트 (필요시)
source venv/bin/activate
pip install -r requirements.txt

# 서비스 재시작
systemctl start lighter-api

# 상태 확인
systemctl status lighter-api --no-pager

echo "✅ Update completed!"
EOF

chmod +x /opt/lighter_api/update.sh
```

## 📊 모니터링 명령어

```bash
# 실시간 로그 확인
journalctl -u lighter-api -f

# 시스템 리소스 확인
htop

# 웹훅 로그 확인
tail -f /var/log/nginx/webhook_access.log

# 디스크 사용량 확인
df -h

# 네트워크 연결 확인
netstat -tulpn | grep :8000
```

## 🎯 TradingView 설정

**웹훅 URL (IP 기반):**
- **모든 계정**: `http://YOUR_VPS_IP/webhook/tradingview`
- **특정 계정**: `http://YOUR_VPS_IP/webhook/tradingview/account/143145`

**예시 (IP: 45.76.210.218):**
- **모든 계정**: `http://45.76.210.218/webhook/tradingview`
- **특정 계정**: `http://45.76.210.218/webhook/tradingview/account/143145`

**웹훅 메시지 형식 (JSON):**
```json
{
  "symbol": "{{ticker}}",
  "sale": "long",
  "leverage": 1,
  "secret": "lighter_to_the_moon_2918"
}
```

**중요 사항:**
- 반드시 JSON 본문에 `"secret": "lighter_to_the_moon_2918"` 포함 필요
- 트레이딩뷰는 포트 80만 지원하므로 HTTP 사용
- IP 제한이 해제되어 모든 IP에서 접근 가능

## 🚨 트러블슈팅

### 1. 서비스가 시작되지 않는 경우

```bash
# 로그 확인
journalctl -u lighter-api --no-pager

# 수동 실행으로 에러 확인
cd /opt/lighter_api
source venv/bin/activate
python3 main.py
```

### 2. 웹훅이 도달하지 않는 경우

```bash
# Nginx 상태 확인
systemctl status nginx

# SSL 인증서 확인
certbot certificates

# 방화벽 확인
ufw status
```

### 3. Git 권한 문제

```bash
# SSH 키 설정 (선택사항)
ssh-keygen -t rsa -b 4096 -C "your.email@example.com"

# 또는 HTTPS 사용 시 Personal Access Token 설정
git config --global credential.helper store
```

## 🔧 유지보수

### 정기 업데이트

```bash
# 매주 실행 권장
cd /opt/lighter_api
./update.sh
```

### 로그 정리

```bash
# 오래된 로그 정리 (월 1회)
journalctl --rotate
journalctl --vacuum-time=30d
```

### SSL 인증서 갱신

```bash
# 자동 갱신 확인 (certbot이 자동으로 설정함)
certbot renew --dry-run
```

## ✅ 배포 완료 체크리스트

- [ ] VPS에 필수 패키지 설치
- [ ] Git에서 코드 클론
- [ ] 가상환경 및 의존성 설치
- [ ] .env 파일 설정
- [ ] accounts.json 설정
- [ ] Nginx 리버스 프록시 설정
- [ ] SSL 인증서 발급
- [ ] 방화벽 설정
- [ ] systemd 서비스 등록
- [ ] 웹훅 엔드포인트 테스트
- [ ] TradingView 연동 확인

## 🎉 완료!

이제 멀티 계정 거래 시스템이 VPS에서 실행되고 있습니다!

**웹훅 URL**: https://ypab5.com/webhook/tradingview
**관리 API**: https://ypab5.com/api/accounts/