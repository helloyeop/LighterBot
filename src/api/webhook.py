from fastapi import APIRouter, Request, HTTPException, Depends, BackgroundTasks
from typing import Dict, Any
from datetime import datetime
import json
import structlog
from pydantic import BaseModel, Field
from config.settings import get_settings

logger = structlog.get_logger()
router = APIRouter(prefix="/webhook", tags=["webhook"])
settings = get_settings()


class TradingViewSignal(BaseModel):
    secret: str = Field(default=None)  # Make secret field optional for testing
    sale: str = Field(..., pattern="^(long|short)$")
    symbol: str = Field(default="BTC")  # 기본값으로 BTC 설정
    quantity: float = Field(default=0.001, gt=0)  # 기본 포지션 크기
    leverage: int = Field(default=1, ge=1, le=20)
    alert_time: str = Field(default=None)
    strategy: str = Field(default="signal_following")
    comment: str = Field(default=None)


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

        # Secret token verification (temporarily disabled for testing)
        # if not await verify_secret_token(signal):
        #     raise HTTPException(status_code=401, detail="Invalid secret token")

        logger.info(
            "Webhook received",
            sale=signal.sale,
            symbol=signal.symbol,
            quantity=signal.quantity,
            leverage=signal.leverage
        )

        # Add to background task queue for processing
        from src.services.signal_trading_service import process_trading_signal
        background_tasks.add_task(process_trading_signal, signal)

        return {
            "status": "success",
            "message": "Signal received and queued for processing",
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error("Webhook processing error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def webhook_health():
    return {
        "status": "healthy",
        "service": "webhook",
        "timestamp": datetime.utcnow().isoformat()
    }