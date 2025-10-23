# Unified Trading System Guide

## 개요
**통합된 멀티 계정 시스템**으로 단일 계정과 다중 계정을 모두 지원합니다.
- **단일 계정**: `accounts.json`에 1개 계정만 설정
- **다중 계정**: `accounts.json`에 여러 계정 설정

> ⚠️ **중요**: 기존 `signal_trading_service.py`는 더 이상 사용되지 않습니다.

## 마이그레이션 (기존 사용자)

기존 `.env` 기반 단일 계정에서 새로운 시스템으로 마이그레이션:

```bash
python migrate_to_multi_account.py
```

## 설정 방법

### 1. 계정 설정 파일 구성

#### 단일 계정 설정
`config/accounts.json`:
```json
{
  "accounts": [
    {
      "account_index": 143145,
      "api_key_index": 3,
      "api_key": "YOUR_API_KEY",
      "api_secret": "YOUR_API_SECRET",
      "name": "Main Account",
      "active": true,
      "allowed_symbols": ["BTC", "ETH", "BNB", "SOL"]
    }
  ],
  "default_account_index": 143145
}
```

#### 다중 계정 설정
`config/accounts.json`:

```json
{
  "accounts": [
    {
      "account_index": 143145,
      "api_key_index": 3,
      "api_key": "YOUR_API_KEY_1",
      "api_secret": "YOUR_API_SECRET_1",
      "name": "Account 1",
      "active": true,
      "allowed_symbols": ["BTC", "ETH", "BNB", "SOL"]
    },
    {
      "account_index": 143146,
      "api_key_index": 4,
      "api_key": "YOUR_API_KEY_2",
      "api_secret": "YOUR_API_SECRET_2",
      "name": "Account 2",
      "active": true,
      "allowed_symbols": ["BTC", "ETH"]
    }
  ],
  "default_account_index": 143145
}
```

### 2. TradingView 웹훅 설정

#### 옵션 1: 특정 계정으로 신호 전송
URL에 account_index를 포함하여 특정 계정으로 신호를 보냅니다:
```
http://YOUR_SERVER:8000/webhook/tradingview/account/143145
```

웹훅 메시지 본문:
```json
{
  "secret": "lighter_to_the_moon_2918",
  "action": "{{strategy.order.action}}",
  "symbol": "BTC",
  "leverage": 1
}
```

#### 옵션 2: 메시지에서 계정 지정
기본 URL 사용하고 메시지에 account_index 포함:
```
http://YOUR_SERVER:8000/webhook/tradingview
```

웹훅 메시지 본문:
```json
{
  "secret": "lighter_to_the_moon_2918",
  "action": "{{strategy.order.action}}",
  "symbol": "BTC",
  "leverage": 1,
  "account_index": 143145
}
```

#### 옵션 3: 모든 활성 계정에 신호 전송
account_index를 지정하지 않으면 모든 활성 계정에서 거래가 실행됩니다:
```json
{
  "secret": "lighter_to_the_moon_2918",
  "action": "{{strategy.order.action}}",
  "symbol": "BTC",
  "leverage": 1
}
```

## API 엔드포인트

### 계정 관리

#### 모든 계정 조회
```bash
curl http://localhost:8000/api/accounts/
```

#### 특정 계정 정보 조회
```bash
curl http://localhost:8000/api/accounts/143145
```

#### 계정별 포지션 조회
```bash
curl http://localhost:8000/api/accounts/143145/positions
```

#### 모든 계정의 포지션 조회
```bash
curl http://localhost:8000/api/accounts/positions/all
```

#### 잔액 요약 조회
```bash
curl http://localhost:8000/api/accounts/balance/summary
```

#### 설정 파일 다시 로드
```bash
curl -X POST http://localhost:8000/api/accounts/reload-config
```

#### 특정 계정 재연결
```bash
curl -X POST http://localhost:8000/api/accounts/143145/reload
```

## 테스트 방법

### 1. 서버 시작
```bash
python main.py
```

### 2. 계정 확인
```bash
# 모든 계정 확인
curl http://localhost:8000/api/accounts/

# 특정 계정 정보
curl http://localhost:8000/api/accounts/143145
```

### 3. 테스트 신호 전송

#### 특정 계정에 Long 신호
```bash
curl -X POST http://localhost:8000/webhook/tradingview/account/143145 \
  -H "Content-Type: application/json" \
  -d '{
    "secret": "lighter_to_the_moon_2918",
    "action": "buy",
    "symbol": "BTC",
    "leverage": 1
  }'
```

#### 모든 계정에 Short 신호
```bash
curl -X POST http://localhost:8000/webhook/tradingview \
  -H "Content-Type: application/json" \
  -d '{
    "secret": "lighter_to_the_moon_2918",
    "action": "sell",
    "symbol": "ETH",
    "leverage": 1
  }'
```

### 4. 포지션 확인
```bash
# 모든 계정의 포지션 확인
curl http://localhost:8000/api/accounts/positions/all
```

## 주의사항

1. **계정별 심볼 필터링**: 각 계정의 `allowed_symbols` 설정에 따라 특정 심볼만 거래 가능
2. **활성 상태**: `active: false`로 설정된 계정은 신호를 무시
3. **독립적 포지션 관리**: 각 계정은 독립적으로 포지션을 관리
4. **병렬 처리**: 여러 계정의 거래는 동시에 병렬로 처리

## 로그 확인

각 계정의 거래 활동은 로그에서 account_index로 구분됩니다:
```
grep "account_index=143145" logs/trading.log
```

## 문제 해결

### 계정이 연결되지 않는 경우
1. API 키와 시크릿이 올바른지 확인
2. account_index와 api_key_index가 정확한지 확인
3. 계정 재연결 시도: `curl -X POST http://localhost:8000/api/accounts/143145/reload`

### 신호가 처리되지 않는 경우
1. 계정이 active 상태인지 확인
2. 심볼이 allowed_symbols에 포함되어 있는지 확인
3. 웹훅 시크릿 토큰이 일치하는지 확인