#!/bin/bash

# 🚀 빠른 VPS 배포 스크립트
# 사용법: ./quick_deploy.sh [VPS_IP]

VPS_IP="${1:-YOUR_VPS_IP}"

if [ "$VPS_IP" = "YOUR_VPS_IP" ]; then
    echo "❌ VPS IP를 입력하세요: ./quick_deploy.sh 45.76.210.218"
    exit 1
fi

echo "🚀 VPS 빠른 배포 시작"
echo "📍 VPS IP: $VPS_IP"
echo "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "="

cat << EOF

다음 명령어를 VPS에서 순서대로 실행하세요:

📋 1. 시스템 설정 및 패키지 설치
===============================
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv git nginx certbot python3-certbot-nginx ufw

📋 2. 애플리케이션 배포
==================
mkdir -p /opt/lighter_api && cd /opt/lighter_api
git clone https://github.com/helloyeop/LighterBot.git .
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

📋 3. 환경 설정
=============
cat > .env << 'ENVEOF'
LIGHTER_API_KEY=your_api_key
LIGHTER_API_SECRET=your_api_secret
LIGHTER_ACCOUNT_INDEX=143145
LIGHTER_API_KEY_INDEX=3
TRADINGVIEW_SECRET_TOKEN=lighter_to_the_moon_2918
PORT=8000
HOST=127.0.0.1
TRADINGVIEW_ALLOWED_IPS=0.0.0.0
ENVEOF

chmod 600 .env

📋 4. Nginx 설정 (포트 80)
=======================
cat > /etc/nginx/sites-available/lighter-api-ip << 'NGINXEOF'
server {
    listen 80 default_server;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /webhook/ {
        proxy_pass http://127.0.0.1:8000/webhook/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
NGINXEOF

rm -f /etc/nginx/sites-enabled/*
ln -sf /etc/nginx/sites-available/lighter-api-ip /etc/nginx/sites-enabled/lighter-api-ip
nginx -t && systemctl restart nginx

📋 5. 시스템 서비스 설정
===================
cp systemd/lighter-api.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable lighter-api
systemctl start lighter-api

📋 6. 방화벽 설정
===============
ufw --force enable
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp

📋 7. 배포 확인
=============
systemctl status lighter-api
curl http://localhost:8000/health
curl http://${VPS_IP}/webhook/health

📋 8. 웹훅 테스트
===============
curl -X POST http://${VPS_IP}/webhook/tradingview \\
  -H "Content-Type: application/json" \\
  -d '{"symbol":"BTC","sale":"long","leverage":1,"secret":"lighter_to_the_moon_2918"}'

🎯 트레이딩뷰 웹훅 URL:
=====================
모든 계정: http://${VPS_IP}/webhook/tradingview
특정 계정: http://${VPS_IP}/webhook/tradingview/account/143145

📝 웹훅 메시지 형식:
================
{
  "symbol": "{{ticker}}",
  "sale": "long",
  "leverage": 1,
  "secret": "lighter_to_the_moon_2918"
}

✅ 완료되면 이 스크립트로 테스트:
==============================
./test_vps_deployment.sh ${VPS_IP}

EOF

echo ""
echo "🎉 배포 명령어가 준비되었습니다!"
echo "📋 위 명령어들을 VPS에서 순서대로 실행하세요."