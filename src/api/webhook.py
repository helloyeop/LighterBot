from fastapi import APIRouter, Request, HTTPException, Depends, BackgroundTasks
from typing import Dict, Any, Optional
from datetime import datetime
import json
import structlog
from pydantic import BaseModel, Field, validator
from config.settings import get_settings

logger = structlog.get_logger()
router = APIRouter(prefix="/webhook", tags=["webhook"])
settings = get_settings()


class TradingViewSignal(BaseModel):
    secret: str = Field(default=None)
    # TradingView의 action 필드를 sale 필드로 매핑
    action: str = Field(default=None, pattern="^(buy|sell|long|short|close)$")
    sale: str = Field(default=None, pattern="^(long|short|close)$")
    symbol: str = Field(default="BTC")
    quantity: float = Field(default=0.001, gt=0)
    leverage: int = Field(default=1, ge=1, le=20)
    alert_time: str = Field(default=None)
    strategy: str = Field(default="signal_following")
    comment: str = Field(default=None)
    # TradingView 표준 필드들 추가
    orderType: str = Field(default="market")
    stopLoss: float = Field(default=None)
    takeProfit: float = Field(default=None)
    # Multi-account support
    account_index: Optional[int] = Field(default=None)

    @validator('sale', pre=True, always=True)
    def set_sale_from_action(cls, v, values):
        # action 필드가 있으면 sale 필드로 변환
        if not v and 'action' in values:
            action = values['action']
            if action in ['buy', 'long']:
                return 'long'
            elif action in ['sell', 'short']:
                return 'short'
            elif action == 'close':
                return 'close'
        return v or 'long'  # 기본값


async def verify_tradingview_ip(request: Request) -> bool:
    # Nginx 리버스 프록시 사용 시 실제 IP 가져오기
    client_ip = request.headers.get("X-Real-IP") or \
                request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or \
                request.client.host

    allowed_ips = settings.tradingview_allowed_ips

    # 디버깅을 위한 로그 추가
    logger.info("Webhook IP check",
                detected_ip=client_ip,
                x_real_ip=request.headers.get("X-Real-IP"),
                x_forwarded_for=request.headers.get("X-Forwarded-For"),
                client_host=request.client.host if request.client else None,
                allowed_ips=allowed_ips)

    # 로컬 테스트용 IP 추가
    if client_ip in ["127.0.0.1", "::1", "localhost"]:
        logger.info("Local webhook request allowed", ip=client_ip)
        return True

    if client_ip not in allowed_ips:
        logger.warning("Unauthorized webhook attempt", ip=client_ip)
        return False

    logger.info("Authorized webhook request", ip=client_ip)
    return True


async def verify_secret_token(signal: TradingViewSignal) -> bool:
    return signal.secret == settings.tradingview_secret_token


@router.post("/tradingview")
async def receive_tradingview_webhook(
    signal: TradingViewSignal,
    request: Request,
    background_tasks: BackgroundTasks
):
    try:
        # IP verification
        if not await verify_tradingview_ip(request):
            raise HTTPException(status_code=403, detail="Unauthorized IP")

        #Secret token verification (temporarily disabled for testing)
        if not await verify_secret_token(signal):
            raise HTTPException(status_code=401, detail="Invalid secret token")

        logger.info(
            "Webhook received",
            sale=signal.sale,
            symbol=signal.symbol,
            quantity=signal.quantity,
            leverage=signal.leverage
        )

        # Add to background task queue for processing
        from src.services.multi_account_signal_service import process_trading_signal_multi

        if signal.account_index is not None:
            # Process for specific account
            background_tasks.add_task(process_trading_signal_multi, signal, signal.account_index)
            logger.info(f"Routing signal to specific account: {signal.account_index}")
        else:
            # Process for all active accounts (even if only 1 account)
            background_tasks.add_task(process_trading_signal_multi, signal, None)
            logger.info("Processing signal for all active accounts")

        return {
            "status": "success",
            "message": "Signal received and queued for processing",
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error("Webhook processing error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tradingview/account/{account_index}")
async def receive_tradingview_webhook_for_account(
    account_index: int,
    signal: TradingViewSignal,
    request: Request,
    background_tasks: BackgroundTasks
):
    """
    Webhook endpoint for specific account
    URL: /webhook/tradingview/account/143145
    """
    try:
        # IP verification
        if not await verify_tradingview_ip(request):
            raise HTTPException(status_code=403, detail="Unauthorized IP")

        # Secret token verification
        if not await verify_secret_token(signal):
            raise HTTPException(status_code=401, detail="Invalid secret token")

        # Override account_index from URL path
        signal.account_index = account_index

        logger.info(
            "Webhook received for specific account",
            account_index=account_index,
            sale=signal.sale,
            symbol=signal.symbol,
            quantity=signal.quantity,
            leverage=signal.leverage
        )

        # Process for specific account
        from src.services.multi_account_signal_service import process_trading_signal_multi
        background_tasks.add_task(process_trading_signal_multi, signal, account_index)

        return {
            "status": "success",
            "message": f"Signal received and queued for account {account_index}",
            "account_index": account_index,
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"Webhook processing error for account {account_index}", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def webhook_health():
    return {
        "status": "healthy",
        "service": "webhook",
        "timestamp": datetime.utcnow().isoformat()
    }