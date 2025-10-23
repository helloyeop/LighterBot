#!/bin/bash

# VPS 배포 테스트 스크립트
# 사용법: ./test_vps_deployment.sh [VPS_IP]

VPS_IP="${1:-45.76.210.218}"
BASE_URL="http://${VPS_IP}"

echo "🚀 VPS 배포 테스트 시작"
echo "📍 VPS IP: ${VPS_IP}"
echo "🌐 Base URL: ${BASE_URL}"
echo "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "="

# 색상 코드
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 테스트 결과 추적
TESTS_PASSED=0
TESTS_FAILED=0

# 테스트 함수
test_endpoint() {
    local name="$1"
    local url="$2"
    local expected_status="$3"
    local method="${4:-GET}"
    local data="$5"

    echo -e "${BLUE}🧪 테스트: $name${NC}"
    echo "   URL: $url"

    if [ "$method" = "POST" ] && [ -n "$data" ]; then
        response=$(curl -s -w "HTTPSTATUS:%{http_code}" -X POST \
                   -H "Content-Type: application/json" \
                   -d "$data" "$url" 2>/dev/null)
    else
        response=$(curl -s -w "HTTPSTATUS:%{http_code}" "$url" 2>/dev/null)
    fi

    if [ $? -ne 0 ]; then
        echo -e "   ${RED}❌ 연결 실패${NC}"
        ((TESTS_FAILED++))
        return 1
    fi

    body=$(echo "$response" | sed -E 's/HTTPSTATUS\:[0-9]{3}$//')
    status=$(echo "$response" | tr -d '\n' | sed -E 's/.*HTTPSTATUS:([0-9]{3})$/\1/')

    if [ "$status" = "$expected_status" ]; then
        echo -e "   ${GREEN}✅ 성공 (HTTP $status)${NC}"
        if [ -n "$body" ] && [ "$body" != "null" ]; then
            echo "   응답: $(echo "$body" | head -c 100)..."
        fi
        ((TESTS_PASSED++))
        return 0
    else
        echo -e "   ${RED}❌ 실패 (예상: $expected_status, 실제: $status)${NC}"
        if [ -n "$body" ]; then
            echo "   응답: $(echo "$body" | head -c 200)..."
        fi
        ((TESTS_FAILED++))
        return 1
    fi
}

echo "📋 1. 기본 헬스체크 테스트"
echo "------------------------------"
test_endpoint "애플리케이션 헬스체크" "${BASE_URL}/health" "200"
test_endpoint "웹훅 헬스체크" "${BASE_URL}/webhook/health" "200"

echo ""
echo "📋 2. API 엔드포인트 테스트"
echo "------------------------------"
test_endpoint "계정 목록 조회" "${BASE_URL}/api/accounts/" "200"
test_endpoint "포지션 조회" "${BASE_URL}/api/positions" "200"

echo ""
echo "📋 3. 웹훅 엔드포인트 테스트"
echo "------------------------------"

# TradingView 시그널 테스트 데이터 (시크릿 토큰 포함)
LONG_SIGNAL='{"symbol":"BTC","sale":"long","leverage":1,"secret":"lighter_to_the_moon_2918"}'
SHORT_SIGNAL='{"symbol":"ETH","sale":"short","leverage":1,"secret":"lighter_to_the_moon_2918"}'
CLOSE_SIGNAL='{"symbol":"BTC","sale":"close","leverage":1,"secret":"lighter_to_the_moon_2918"}'

test_endpoint "전체 계정 LONG 시그널" "${BASE_URL}/webhook/tradingview" "200" "POST" "$LONG_SIGNAL"
test_endpoint "특정 계정 SHORT 시그널" "${BASE_URL}/webhook/tradingview/account/143145" "200" "POST" "$SHORT_SIGNAL"
test_endpoint "전체 계정 CLOSE 시그널" "${BASE_URL}/webhook/tradingview" "200" "POST" "$CLOSE_SIGNAL"

echo ""
echo "📋 4. 잘못된 요청 테스트"
echo "------------------------------"
test_endpoint "존재하지 않는 엔드포인트" "${BASE_URL}/nonexistent" "404"
test_endpoint "잘못된 웹훅 데이터" "${BASE_URL}/webhook/tradingview" "401" "POST" '{"invalid":"data"}'

echo ""
echo "📋 5. 서비스 상태 테스트"
echo "------------------------------"

# SSH를 통한 서비스 상태 확인 (VPS에서 실행시에만)
if [ "$VPS_IP" = "localhost" ] || [ "$VPS_IP" = "127.0.0.1" ]; then
    echo -e "${BLUE}🔍 로컬 서비스 상태 확인${NC}"

    # systemd 서비스 상태
    if systemctl is-active --quiet lighter-api; then
        echo -e "   ${GREEN}✅ lighter-api 서비스 실행 중${NC}"
        ((TESTS_PASSED++))
    else
        echo -e "   ${RED}❌ lighter-api 서비스 중지됨${NC}"
        ((TESTS_FAILED++))
    fi

    if systemctl is-active --quiet nginx; then
        echo -e "   ${GREEN}✅ nginx 서비스 실행 중${NC}"
        ((TESTS_PASSED++))
    else
        echo -e "   ${RED}❌ nginx 서비스 중지됨${NC}"
        ((TESTS_FAILED++))
    fi

    # 포트 확인
    if netstat -tulpn | grep -q ":8000"; then
        echo -e "   ${GREEN}✅ 포트 8000 리스닝 중${NC}"
        ((TESTS_PASSED++))
    else
        echo -e "   ${RED}❌ 포트 8000 리스닝 안됨${NC}"
        ((TESTS_FAILED++))
    fi

    if netstat -tulpn | grep -q ":80"; then
        echo -e "   ${GREEN}✅ 포트 80 리스닝 중${NC}"
        ((TESTS_PASSED++))
    else
        echo -e "   ${RED}❌ 포트 80 리스닝 안됨${NC}"
        ((TESTS_FAILED++))
    fi
else
    echo -e "${YELLOW}⚠️  원격 VPS이므로 서비스 상태 확인 생략${NC}"
fi

echo ""
echo "📋 6. 성능 테스트"
echo "------------------------------"

echo -e "${BLUE}🏃 응답 시간 측정${NC}"
for i in {1..3}; do
    start_time=$(date +%s%3N)
    curl -s "${BASE_URL}/health" > /dev/null
    end_time=$(date +%s%3N)
    response_time=$((end_time - start_time))
    echo "   테스트 $i: ${response_time}ms"
done

echo ""
echo "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "="
echo "📊 테스트 결과 요약"
echo "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "=" "="

TOTAL_TESTS=$((TESTS_PASSED + TESTS_FAILED))
SUCCESS_RATE=$((TESTS_PASSED * 100 / TOTAL_TESTS))

echo -e "✅ 통과: ${GREEN}$TESTS_PASSED${NC}"
echo -e "❌ 실패: ${RED}$TESTS_FAILED${NC}"
echo -e "📊 성공률: ${GREEN}$SUCCESS_RATE%${NC}"

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "\n🎉 ${GREEN}모든 테스트 통과! 배포가 성공적으로 완료되었습니다.${NC}"
    echo ""
    echo "🎯 트레이딩뷰 웹훅 URL:"
    echo "   전체 계정: ${BASE_URL}/webhook/tradingview"
    echo "   특정 계정: ${BASE_URL}/webhook/tradingview/account/143145"
    exit 0
else
    echo -e "\n⚠️  ${YELLOW}일부 테스트가 실패했습니다. 로그를 확인하세요.${NC}"
    echo ""
    echo "🔍 문제 해결 명령어:"
    echo "   journalctl -u lighter-api -f"
    echo "   systemctl status nginx"
    echo "   curl http://localhost:8000/health"
    exit 1
fi