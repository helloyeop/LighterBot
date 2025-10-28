# 📚 VPS 배포 완벽 가이드

이 가이드는 Lighter API Trading Bot을 새로운 VPS에 배포하는 완전한 과정을 안내합니다.

## 📋 목차
1. [시스템 요구사항](#-시스템-요구사항)
2. [사전 준비사항](#-사전-준비사항)
3. [Step-by-Step 배포](#-step-by-step-배포)
4. [멀티 계정 설정](#-멀티-계정-설정)
5. [검증 및 테스트](#-검증-및-테스트)
6. [트러블슈팅](#-트러블슈팅)
7. [유지보수](#-유지보수)

---

## 💻 시스템 요구사항

### 최소 사양
- **CPU**: 1 vCPU
- **RAM**: 1GB
- **Storage**: 25GB SSD
- **OS**: Ubuntu 20.04+ / Debian 10+
- **Network**: 고정 IP 주소

### 권장 사양
- **CPU**: 2+ vCPU
- **RAM**: 2GB+
- **Storage**: 50GB+ SSD
- **OS**: Ubuntu 22.04 LTS

### 지원 VPS 제공업체
- ✅ Vultr
- ✅ DigitalOcean
- ✅ Linode
- ✅ AWS EC2
- ✅ Google Cloud
- ✅ Azure

---

## 📝 사전 준비사항

### 1. Lighter DEX 계정 정보
각 거래 계정별로 다음 정보가 필요합니다:

```
□ Account Index (예: 143145)
□ API Key Index (예: 3)
□ API Key
□ API Secret
```

### 2. 로컬 준비물
```
□ SSH 클라이언트 (Terminal, PuTTY 등)
□ VPS root 접근 권한
□ GitHub 계정 (선택사항)
```

### 3. TradingView 설정
```
□ TradingView Pro 계정
□ Alert 생성 권한
□ Webhook URL 설정 가능
```

---

## 🚀 Step-by-Step 배포

### Step 1: VPS 초기 설정

```bash
# 1.1 VPS 접속
ssh root@YOUR_VPS_IP

# SSH 키 문제 발생 시
ssh-keygen -R YOUR_VPS_IP
ssh root@YOUR_VPS_IP

# 1.2 시스템 업데이트
apt update && apt upgrade -y

# 1.3 필수 패키지 설치
apt install -y \
    python3 python3-pip python3-venv \
    git curl wget \
    nginx \
    ufw \
    htop \
    supervisor  # 선택사항: systemd 대신 사용 가능

# 1.4 시간대 설정 (선택사항)
timedatectl set-timezone Asia/Seoul  # 또는 원하는 시간대
```

### Step 2: 애플리케이션 설치

```bash
# 2.1 작업 디렉토리 생성
mkdir -p /opt/lighter_api
cd /opt/lighter_api

# 2.2 소스코드 다운로드
git clone https://github.com/helloyeop/LighterBot.git .

# 2.3 Python 가상환경 생성
python3 -m venv venv

# 2.4 가상환경 활성화
source venv/bin/activate

# 2.5 의존성 설치
pip install --upgrade pip
pip install -r requirements.txt

# 2.6 설치 확인
python -c "import lighter_api; print('✅ Lighter API 설치 완료')"
```

### Step 3: 환경 설정

#### 3.1 기본 환경변수 (.env)

```bash
cat > /opt/lighter_api/.env << 'EOF'
# Lighter DEX Configuration
LIGHTER_API_KEY=YOUR_API_KEY_HERE
LIGHTER_API_SECRET=YOUR_API_SECRET_HERE
LIGHTER_NETWORK=mainnet
LIGHTER_ENDPOINT=https://mainnet.zklighter.elliot.ai
LIGHTER_ACCOUNT_INDEX=YOUR_ACCOUNT_INDEX
LIGHTER_API_KEY_INDEX=YOUR_API_KEY_INDEX

# Webhook Security
TRADINGVIEW_SECRET_TOKEN=your_custom_secret_token_here
TRADINGVIEW_ALLOWED_IPS=0.0.0.0

# Server Configuration
PORT=8000
HOST=0.0.0.0
WORKERS=1

# Logging
LOG_LEVEL=INFO
EOF

# 3.2 파일 권한 설정 (보안)
chmod 600 /opt/lighter_api/.env
```

#### 3.2 단일 계정 설정 (간단한 경우)

위의 .env 파일만 설정하면 단일 계정으로 작동합니다.

#### 3.3 멀티 계정 설정 (고급)

```bash
cat > /opt/lighter_api/config/accounts.json << 'EOF'
{
  "accounts": [
    {
      "account_index": 143145,
      "api_key_index": 3,
      "api_key": "YOUR_API_KEY_1",
      "api_secret": "YOUR_API_SECRET_1",
      "name": "Main Account",
      "active": true,
      "allowed_symbols": ["BTC", "ETH", "BNB", "SOL"]
    },
    {
      "account_index": 267180,
      "api_key_index": 5,
      "api_key": "YOUR_API_KEY_2",
      "api_secret": "YOUR_API_SECRET_2",
      "name": "Secondary Account",
      "active": true,
      "allowed_symbols": ["BTC", "ETH"]
    }
  ],
  "default_account_index": 143145
}
EOF

chmod 600 /opt/lighter_api/config/accounts.json
```

### Step 4: Nginx 리버스 프록시 설정

```bash
# 4.1 기존 설정 백업
mkdir -p /etc/nginx/backup
mv /etc/nginx/sites-enabled/* /etc/nginx/backup/ 2>/dev/null

# 4.2 새 설정 생성
cat > /etc/nginx/sites-available/lighter-api << 'EOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    client_max_body_size 10M;

    # 타임아웃 설정
    proxy_connect_timeout 300s;
    proxy_send_timeout 300s;
    proxy_read_timeout 300s;

    # 로깅
    access_log /var/log/nginx/lighter-api-access.log;
    error_log /var/log/nginx/lighter-api-error.log;

    # 메인 프록시
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }

    # Webhook 엔드포인트
    location /webhook/ {
        proxy_pass http://127.0.0.1:8000/webhook/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # API 엔드포인트
    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

# 4.3 설정 활성화
ln -sf /etc/nginx/sites-available/lighter-api /etc/nginx/sites-enabled/

# 4.4 Nginx 테스트 및 재시작
nginx -t
systemctl restart nginx
systemctl enable nginx
```

### Step 5: 방화벽 설정

```bash
# 5.1 UFW 방화벽 설정
ufw --force enable
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP
ufw allow 443/tcp   # HTTPS (SSL 사용 시)

# 5.2 상태 확인
ufw status verbose
```

### Step 6: Systemd 서비스 설정

```bash
# 6.1 서비스 파일 생성
cat > /etc/systemd/system/lighter-api.service << 'EOF'
[Unit]
Description=Lighter API Trading Bot
After=network.target nginx.service

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/opt/lighter_api
Environment="PATH=/opt/lighter_api/venv/bin"
ExecStart=/opt/lighter_api/venv/bin/python /opt/lighter_api/main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# 리소스 제한 (1GB RAM VPS용)
MemoryMax=800M
CPUQuota=80%

[Install]
WantedBy=multi-user.target
EOF

# 6.2 서비스 활성화 및 시작
systemctl daemon-reload
systemctl enable lighter-api
systemctl start lighter-api

# 6.3 상태 확인
systemctl status lighter-api
```

---

## 🔧 멀티 계정 설정

### 계정별 웹훅 URL

각 계정별로 개별 웹훅 URL을 사용할 수 있습니다:

```
계정 1: http://YOUR_VPS_IP/webhook/tradingview/account/143145
계정 2: http://YOUR_VPS_IP/webhook/tradingview/account/267180
계정 3: http://YOUR_VPS_IP/webhook/tradingview/account/267219
계정 4: http://YOUR_VPS_IP/webhook/tradingview/account/267221
모든 계정: http://YOUR_VPS_IP/webhook/tradingview
```

### TradingView 메시지 형식

```json
{
  "secret": "your_custom_secret_token_here",
  "sale": "long",     // "long", "short", "close"
  "symbol": "BTC",    // "BTC", "ETH", "BNB", "SOL"
  "leverage": 5,      // 1-20
  "quantity": 0.001   // 선택사항
}
```

**대체 필드 지원:**
- `"sale"` → `"buy"` (long으로 변환) 또는 `"sell"` (short으로 변환)
- `"sale"` → `"action"` 필드로도 사용 가능

---

## ✅ 검증 및 테스트

### 1단계: 서비스 확인

```bash
# 서비스 상태
systemctl status lighter-api

# 포트 확인
netstat -tulpn | grep -E ":80|:8000"

# 프로세스 확인
ps aux | grep python
```

### 2단계: 헬스체크

```bash
# 로컬 테스트
curl http://localhost:8000/health

# 외부 접근 테스트 (다른 터미널에서)
curl http://YOUR_VPS_IP/health
curl http://YOUR_VPS_IP/webhook/health
```

### 3단계: 웹훅 테스트

```bash
# 테스트 웹훅 전송
curl -X POST http://YOUR_VPS_IP/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{
    "secret": "your_custom_secret_token_here",
    "sale": "long",
    "symbol": "BTC",
    "leverage": 1,
    "quantity": 0.0001
  }'

# 응답 확인
# 성공: {"status":"success","message":"Signal received and queued for processing"}
```

### 4단계: 로그 확인

```bash
# 실시간 로그 모니터링
journalctl -u lighter-api -f

# 최근 100줄 로그
journalctl -u lighter-api -n 100

# 에러만 확인
journalctl -u lighter-api -p err -n 50

# Nginx 로그
tail -f /var/log/nginx/lighter-api-access.log
tail -f /var/log/nginx/lighter-api-error.log
```

---

## 🔴 트러블슈팅

### 문제 1: 403 Forbidden
**원인**: IP 제한
**해결**:
```bash
# .env 파일에서 확인
grep TRADINGVIEW_ALLOWED_IPS /opt/lighter_api/.env
# TRADINGVIEW_ALLOWED_IPS=0.0.0.0 으로 설정
```

### 문제 2: Invalid Signature
**원인**: 잘못된 API 키/시크릿
**해결**:
```bash
# accounts.json 확인
cat /opt/lighter_api/config/accounts.json | grep -E "api_key|api_secret"
# API 키와 시크릿이 올바른지 확인
```

### 문제 3: Invalid Nonce
**원인**: Nonce 동기화 문제
**해결**: 시스템이 자동으로 재시도 (로그 확인)

### 문제 4: Connection Refused
**원인**: 서비스 미실행
**해결**:
```bash
systemctl restart lighter-api
systemctl status lighter-api
```

### 문제 5: 504 Gateway Timeout
**원인**: 애플리케이션 응답 없음
**해결**:
```bash
# 프로세스 확인
ps aux | grep python
# 서비스 재시작
systemctl restart lighter-api
# CPU/메모리 확인
htop
```

---

## 🛠️ 유지보수

### 일일 점검사항
```bash
# 1. 서비스 상태
systemctl status lighter-api

# 2. 디스크 사용량
df -h

# 3. 메모리 사용량
free -h

# 4. 로그 크기
du -sh /var/log/nginx/*.log
journalctl --disk-usage
```

### 업데이트 절차
```bash
cd /opt/lighter_api

# 1. 백업
cp .env .env.backup
cp config/accounts.json config/accounts.json.backup

# 2. 코드 업데이트
git pull origin main

# 3. 의존성 업데이트
source venv/bin/activate
pip install -r requirements.txt

# 4. 서비스 재시작
systemctl restart lighter-api

# 5. 확인
systemctl status lighter-api
journalctl -u lighter-api -f
```

### 로그 관리
```bash
# journalctl 로그 정리 (1주일 이상 된 로그 삭제)
journalctl --vacuum-time=7d

# Nginx 로그 로테이션 설정
cat > /etc/logrotate.d/lighter-api << 'EOF'
/var/log/nginx/lighter-api-*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 www-data adm
    sharedscripts
    prerotate
        if [ -d /etc/logrotate.d/httpd-prerotate ]; then \
            run-parts /etc/logrotate.d/httpd-prerotate; \
        fi
    endscript
    postrotate
        invoke-rc.d nginx rotate >/dev/null 2>&1
    endscript
}
EOF
```

### 백업 스크립트
```bash
# 백업 스크립트 생성
cat > /opt/lighter_api/backup.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/opt/backups/lighter_api"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

# 설정 파일 백업
tar -czf $BACKUP_DIR/config_$DATE.tar.gz \
    /opt/lighter_api/.env \
    /opt/lighter_api/config/

echo "✅ 백업 완료: $BACKUP_DIR/config_$DATE.tar.gz"

# 7일 이상 된 백업 삭제
find $BACKUP_DIR -name "*.tar.gz" -mtime +7 -delete
EOF

chmod +x /opt/lighter_api/backup.sh

# Cron 등록 (매일 새벽 3시 백업)
(crontab -l 2>/dev/null; echo "0 3 * * * /opt/lighter_api/backup.sh") | crontab -
```

---

## 📊 성능 모니터링

### 리소스 모니터링
```bash
# htop 설치 및 실행
apt install -y htop
htop

# 네트워크 모니터링
apt install -y iftop
iftop

# 디스크 I/O 모니터링
apt install -y iotop
iotop
```

### 거래 모니터링
```bash
# 최근 거래 로그
journalctl -u lighter-api | grep "order" | tail -20

# 에러 발생 빈도
journalctl -u lighter-api --since "1 hour ago" | grep -c ERROR

# 웹훅 수신 횟수
grep "webhook" /var/log/nginx/lighter-api-access.log | wc -l
```

---

## 📝 체크리스트

배포 완료 후 확인사항:

- [ ] VPS 접속 가능
- [ ] 시스템 업데이트 완료
- [ ] Python 및 의존성 설치
- [ ] .env 파일 설정
- [ ] accounts.json 설정 (멀티 계정)
- [ ] Nginx 설정 및 실행
- [ ] 방화벽 규칙 설정
- [ ] Systemd 서비스 실행
- [ ] 헬스체크 성공
- [ ] 웹훅 테스트 성공
- [ ] TradingView 연동
- [ ] 실제 거래 테스트
- [ ] 백업 설정
- [ ] 모니터링 설정

---

## 🎯 Quick Deploy Script

빠른 배포를 위한 원클릭 스크립트:

```bash
#!/bin/bash
# quick-deploy.sh

echo "🚀 Lighter API Trading Bot 빠른 배포 시작..."

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# VPS IP 입력
read -p "VPS IP 주소: " VPS_IP
read -p "API Key: " API_KEY
read -s -p "API Secret: " API_SECRET
echo
read -p "Account Index: " ACCOUNT_INDEX
read -p "API Key Index: " API_KEY_INDEX

# 배포 시작
echo -e "${GREEN}✅ 시스템 업데이트...${NC}"
apt update && apt upgrade -y

echo -e "${GREEN}✅ 패키지 설치...${NC}"
apt install -y python3 python3-pip python3-venv git nginx ufw

echo -e "${GREEN}✅ 애플리케이션 설치...${NC}"
cd /opt
git clone https://github.com/helloyeop/LighterBot.git lighter_api
cd lighter_api

echo -e "${GREEN}✅ Python 환경 설정...${NC}"
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

echo -e "${GREEN}✅ 환경 변수 설정...${NC}"
cat > .env << EOF
LIGHTER_API_KEY=$API_KEY
LIGHTER_API_SECRET=$API_SECRET
LIGHTER_NETWORK=mainnet
LIGHTER_ENDPOINT=https://mainnet.zklighter.elliot.ai
LIGHTER_ACCOUNT_INDEX=$ACCOUNT_INDEX
LIGHTER_API_KEY_INDEX=$API_KEY_INDEX
TRADINGVIEW_SECRET_TOKEN=lighter_to_the_moon_2918
TRADINGVIEW_ALLOWED_IPS=0.0.0.0
PORT=8000
HOST=0.0.0.0
EOF

echo -e "${GREEN}✅ 서비스 설정...${NC}"
# ... (나머지 설정 계속)

echo -e "${GREEN}🎉 배포 완료!${NC}"
echo "웹훅 URL: http://$VPS_IP/webhook/tradingview"
```

---

## 📞 지원 및 문의

- **GitHub Issues**: https://github.com/helloyeop/LighterBot/issues
- **로그 위치**: `/var/log/`, `journalctl`
- **설정 위치**: `/opt/lighter_api/`

---

**마지막 업데이트**: 2024년 10월
**버전**: 2.0.0