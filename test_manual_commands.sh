#!/bin/bash

# 수동 테스트 명령어 모음
# VPS에서 복사해서 사용하세요

echo "🚀 VPS 배포 수동 테스트 명령어"
echo "==============================="

VPS_IP="YOUR_VPS_IP"  # 실제 VPS IP로 변경하세요 (예: 45.76.210.218)

echo ""
echo "📋 1. 기본 헬스체크"
echo "curl http://${VPS_IP}/health"
echo "curl http://${VPS_IP}/webhook/health"

echo ""
echo "📋 2. API 테스트"
echo "curl http://${VPS_IP}/api/accounts/"
echo "curl http://${VPS_IP}/api/positions"

echo ""
echo "📋 3. 웹훅 시그널 테스트 (시크릿 토큰 포함)"
echo "# LONG 시그널"
echo "curl -X POST http://${VPS_IP}/webhook/tradingview \\"
echo "  -H \"Content-Type: application/json\" \\"
echo "  -d '{\"symbol\":\"BTC\",\"sale\":\"long\",\"leverage\":1,\"secret\":\"lighter_to_the_moon_2918\"}'"

echo ""
echo "# SHORT 시그널"
echo "curl -X POST http://${VPS_IP}/webhook/tradingview \\"
echo "  -H \"Content-Type: application/json\" \\"
echo "  -d '{\"symbol\":\"ETH\",\"sale\":\"short\",\"leverage\":1,\"secret\":\"lighter_to_the_moon_2918\"}'"

echo ""
echo "# CLOSE 시그널"
echo "curl -X POST http://${VPS_IP}/webhook/tradingview \\"
echo "  -H \"Content-Type: application/json\" \\"
echo "  -d '{\"symbol\":\"BTC\",\"sale\":\"close\",\"leverage\":1,\"secret\":\"lighter_to_the_moon_2918\"}'"

echo ""
echo "📋 4. 특정 계정 웹훅 테스트"
echo "curl -X POST http://${VPS_IP}/webhook/tradingview/account/143145 \\"
echo "  -H \"Content-Type: application/json\" \\"
echo "  -d '{\"symbol\":\"SOL\",\"sale\":\"long\",\"leverage\":1,\"secret\":\"lighter_to_the_moon_2918\"}'"

echo ""
echo "📋 5. 서비스 상태 확인 (VPS에서)"
echo "systemctl status lighter-api"
echo "systemctl status nginx"
echo "journalctl -u lighter-api -f --no-pager"

echo ""
echo "📋 6. 포트 확인"
echo "netstat -tulpn | grep :8000"
echo "netstat -tulpn | grep :80"

echo ""
echo "📋 7. 로그 확인"
echo "tail -f /var/log/nginx/access.log"
echo "tail -f /var/log/nginx/error.log"

echo ""
echo "📋 8. 프로세스 확인"
echo "ps aux | grep python"
echo "ps aux | grep nginx"

echo ""
echo "🎯 트레이딩뷰 웹훅 URL:"
echo "   전체 계정: http://${VPS_IP}/webhook/tradingview"
echo "   특정 계정: http://${VPS_IP}/webhook/tradingview/account/143145"