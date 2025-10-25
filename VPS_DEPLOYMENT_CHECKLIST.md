# 📋 VPS 배포 체크리스트

## 🎯 배포 전 준비사항

### 1. VPS 정보 확인
- [ ] VPS IP 주소 확인
- [ ] SSH root 접근 권한 확인
- [ ] VPS 운영체제 확인 (Ubuntu 20.04+ 권장)

### 2. 로컬 환경 준비
- [ ] GitHub 저장소 준비 (https://github.com/helloyeop/LighterBot.git)
- [ ] Lighter API 키/시크릿 준비
- [ ] 계정 인덱스 확인 (account_index, api_key_index)

## 🚀 배포 단계

### 1. 시스템 설정
```bash
# VPS 접속
ssh root@YOUR_VPS_IP
# 만약 접속 안될 시 (Host key verification failed) ssh-keygen -R YOUR_VPS_IP

# 시스템 업데이트
apt update && apt upgrade -y

# 필수 패키지 설치
apt install -y python3 python3-pip python3-venv git nginx ufw
```
- [ ] 시스템 업데이트 완료
- [ ] 필수 패키지 설치 완료

### 2. 애플리케이션 설치
```bash
# 작업 디렉토리 생성
mkdir -p /opt/lighter_api
cd /opt/lighter_api

# Git 클론
git clone https://github.com/helloyeop/LighterBot.git .

# 가상환경 설정
python3 -m venv venv
source venv/bin/activate

# 의존성 설치
pip install -r requirements.txt
```
- [ ] Git 클론 성공
- [ ] 가상환경 생성 완료
- [ ] 의존성 설치 완료

### 3. 환경 설정
```bash
# .env 파일 생성
cat > .env << 'EOF'
LIGHTER_API_KEY=your_api_key_here
LIGHTER_API_SECRET=your_api_secret_here
LIGHTER_NETWORK=mainnet
LIGHTER_ENDPOINT=https://mainnet.zklighter.elliot.ai
LIGHTER_ACCOUNT_INDEX=143145
LIGHTER_API_KEY_INDEX=3
TRADINGVIEW_SECRET_TOKEN=lighter_to_the_moon_2918
PORT=8000
HOST=0.0.0.0
TRADINGVIEW_ALLOWED_IPS=0.0.0.0
EOF

chmod 600 .env
```
- [ ] API 키/시크릿 입력
- [ ] 계정 인덱스 설정
- [ ] HOST=0.0.0.0 설정 (외부 접근 허용)
- [ ] IP 제한 해제 설정 (TRADINGVIEW_ALLOWED_IPS=0.0.0.0)
- [ ] .env 권한 설정 (600)

### 4. 계정 설정
```bash
# accounts.json 확인
cat config/accounts.json

# 필요시 수정
nano config/accounts.json
```
- [ ] 계정 정보 확인
- [ ] API 키 입력
- [ ] 허용 심볼 설정 (BTC, ETH, BNB, SOL)

### 5. Nginx 설정 (포트 80)
```bash
# 기존 설정 제거
rm -f /etc/nginx/sites-enabled/*

# Nginx 설정 파일 생성
cat > /etc/nginx/sites-available/lighter-api << 'EOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    # 타임아웃 설정
    proxy_read_timeout 300s;
    proxy_connect_timeout 300s;
    proxy_send_timeout 300s;

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

# 설정 활성화
ln -sf /etc/nginx/sites-available/lighter-api /etc/nginx/sites-enabled/lighter-api

# Nginx 테스트 및 재시작
nginx -t && systemctl restart nginx
```
- [ ] Nginx 설정 파일 생성
- [ ] 기존 설정 제거
- [ ] 새 설정 활성화
- [ ] Nginx 테스트 통과
- [ ] Nginx 재시작 성공

### 6. 방화벽 설정
```bash
# UFW 설정
ufw --force enable
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP
ufw status
```
- [ ] 방화벽 활성화
- [ ] SSH 포트 허용
- [ ] HTTP 포트 허용
- [ ] 방화벽 상태 확인

### 7. 시스템 서비스 설정
```bash
# systemd 서비스 생성
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
systemctl status lighter-api
```
- [ ] 서비스 파일 생성
- [ ] 서비스 등록
- [ ] 서비스 자동 시작 설정
- [ ] 서비스 시작 성공

## ✅ 배포 검증

### 1. 헬스 체크
```bash
# 로컬 테스트
curl http://localhost:8000/health

# 외부 접근 테스트
curl http://YOUR_VPS_IP/webhook/health
```
- [ ] 로컬 헬스체크 성공
- [ ] 외부 접근 성공

### 2. API 테스트
```bash
# 계정 정보 확인
curl http://YOUR_VPS_IP/api/accounts/

# 포지션 확인
curl http://YOUR_VPS_IP/api/positions
```
- [ ] 계정 정보 조회 성공
- [ ] 포지션 조회 성공

### 3. 웹훅 테스트
```bash
# 웹훅 시그널 테스트
curl -X POST http://YOUR_VPS_IP/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTC","sale":"long","leverage":1,"secret":"lighter_to_the_moon_2918"}'
```
- [ ] 웹훅 인증 성공
- [ ] 시그널 처리 성공

### 4. 로그 확인
```bash
# 서비스 로그
journalctl -u lighter-api -f

# Nginx 로그
tail -f /var/log/nginx/access.log
```
- [ ] 애플리케이션 로그 정상
- [ ] Nginx 로그 정상

## 📡 TradingView 설정

### 웹훅 URL 설정
- **모든 계정**: `http://YOUR_VPS_IP/webhook/tradingview`
- **특정 계정**: `http://YOUR_VPS_IP/webhook/tradingview/account/143145`

### 웹훅 메시지 형식
```json
{
  "symbol": "{{ticker}}",
  "sale": "long",
  "leverage": 1,
  "secret": "lighter_to_the_moon_2918"
}
```
- [ ] TradingView 알림 생성
- [ ] 웹훅 URL 입력
- [ ] 메시지 형식 설정
- [ ] 실제 시그널 테스트

## 🔧 트러블슈팅

### 문제 발생 시 확인사항
1. **서비스 상태**: `systemctl status lighter-api`
2. **포트 확인**: `netstat -tulpn | grep :80`
3. **방화벽 확인**: `ufw status`
4. **환경 변수 확인**: `grep TRADINGVIEW /opt/lighter_api/.env`
5. **로그 확인**: `journalctl -u lighter-api --no-pager`

## 📝 최종 확인

- [ ] 모든 서비스 실행 중
- [ ] 외부에서 접근 가능
- [ ] 웹훅 테스트 성공
- [ ] TradingView 연동 완료
- [ ] 실제 거래 시작

## 🎉 배포 완료!

**중요 정보 기록**
- VPS IP: ___________________
- 웹훅 URL: `http://___________________/webhook/tradingview`
- 시크릿 토큰: `lighter_to_the_moon_2918`
- 계정 인덱스: ___________________

---

배포 완료 시간: ___________________
담당자: ___________________