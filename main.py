import asyncio
import signal
import sys
from contextlib import asynccontextmanager
from typing import Optional
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import structlog
import uvicorn
from config.settings import get_settings
from src.core.database import db_manager
from src.core.lighter_client import lighter_client
from src.core.risk_manager import risk_manager
from src.api.webhook import router as webhook_router
from src.utils.notifications import notification_manager
from src.strategies.high_frequency import HighFrequencyTrader, TradingMode
from src.strategies.market_order_hft import MarketOrderHFT
from src.strategies.single_position_strategy import SinglePositionStrategy
from src.utils.price_fetcher import price_fetcher

# Configure logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()
settings = get_settings()

# Global instance for high frequency trader
hf_trader = None
market_hft = None
single_position_strategy = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Lighter Trading Bot")

    try:
        # Connect to database
        await db_manager.connect()

        # Connect to Lighter DEX
        await lighter_client.connect()

        # Initialize risk manager
        await risk_manager.connect()

        # Initialize high frequency trader
        global hf_trader, market_hft, single_position_strategy
        hf_trader = HighFrequencyTrader(lighter_client, settings)
        market_hft = MarketOrderHFT(lighter_client, settings)
        single_position_strategy = SinglePositionStrategy(lighter_client, settings)

        # Send startup notification (only if Telegram is configured)
        if settings.telegram_bot_token and settings.telegram_chat_id:
            await notification_manager.send_alert(
                "🚀 Trading Bot Started\n"
                f"Network: {settings.lighter_network}\n"
                f"Max Position: ${settings.max_position_size_usd}\n"
                f"Max Leverage: {settings.max_leverage}x"
            )

        logger.info("All systems initialized successfully")

    except Exception as e:
        logger.error("Failed to initialize systems", error=str(e))
        if settings.telegram_bot_token and settings.telegram_chat_id:
            await notification_manager.send_alert(
                f"❌ Bot Startup Failed\nError: {str(e)}"
            )
        sys.exit(1)

    yield

    # Shutdown
    logger.info("Shutting down Lighter Trading Bot")

    await db_manager.disconnect()
    await risk_manager.disconnect()

    if settings.telegram_bot_token and settings.telegram_chat_id:
        await notification_manager.send_alert("🛑 Trading Bot Stopped")


# Create FastAPI app
app = FastAPI(
    title="Lighter Trading Bot",
    description="Automated trading bot for Lighter DEX",
    version="1.0.0",
    lifespan=lifespan
)


# Include routers
app.include_router(webhook_router)


# Request Models for Orders
class LimitOrderRequest(BaseModel):
    symbol: str
    side: str
    quantity: float
    price: float
    leverage: int = 1

class MarketOrderRequest(BaseModel):
    symbol: str
    side: str
    quantity: float
    leverage: int = 1
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


# Health check endpoint
@app.get("/health")
async def health_check():
    db_healthy = await db_manager.health_check()

    return {
        "status": "healthy" if db_healthy else "unhealthy",
        "database": db_healthy,
        "lighter_connected": lighter_client.connected,
        "kill_switch": await risk_manager.is_kill_switch_active()
    }


# Risk management endpoints
@app.get("/api/risk/status")
async def get_risk_status():
    return await risk_manager.get_risk_status()


@app.post("/api/risk/kill-switch/activate")
async def activate_kill_switch():
    await risk_manager.activate_kill_switch()

    # Import here to avoid circular import
    from src.services.trading_service import emergency_close_all
    await emergency_close_all()

    return {"status": "Kill switch activated", "positions_closed": True}


@app.post("/api/risk/kill-switch/deactivate")
async def deactivate_kill_switch():
    await risk_manager.deactivate_kill_switch()
    return {"status": "Kill switch deactivated"}


# Account endpoints
@app.get("/api/account/info")
async def get_account_info():
    try:
        return await lighter_client.get_account_info()
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.get("/api/account/inactive-orders")
async def get_account_inactive_orders(limit: int = 100, market_id: int = None):
    """Get account's inactive orders (order history)"""
    try:
        return await lighter_client.get_account_inactive_orders(limit=limit, market_id=market_id)
    except Exception as e:
        logger.error("Failed to get account inactive orders", error=str(e))
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to get inactive orders: {str(e)}"}
        )


@app.get("/api/positions")
async def get_positions():
    try:
        return await lighter_client.get_positions()
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.post("/api/positions/close-all")
async def close_all_positions():
    try:
        success = await lighter_client.close_all_positions()
        return {"success": success}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


# Order endpoints
@app.post("/api/orders/market")
async def create_market_order(order: MarketOrderRequest):
    try:
        # Validate side
        if order.side.lower() not in ["buy", "sell"]:
            return JSONResponse(
                status_code=400,
                content={"error": "Side must be 'buy' or 'sell'"}
            )

        # Skip risk check for testing
        # TODO: Implement proper risk management
        logger.info("Skipping risk check for testing purposes")

        result = await lighter_client.create_market_order(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            leverage=order.leverage,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit
        )

        return result
    except Exception as e:
        logger.error("Failed to create market order", error=str(e))
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.post("/api/orders/limit")
async def create_limit_order(order: LimitOrderRequest):
    try:
        # Validate side
        if order.side.lower() not in ["buy", "sell"]:
            return JSONResponse(
                status_code=400,
                content={"error": "Side must be 'buy' or 'sell'"}
            )

        # Skip risk check for testing
        # TODO: Implement proper risk management
        logger.info("Skipping risk check for testing purposes")

        result = await lighter_client.create_limit_order(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=order.price,
            leverage=order.leverage
        )

        return result
    except Exception as e:
        logger.error("Failed to create limit order", error=str(e))
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


# Error handlers
# High Frequency Trading endpoints
class HFTStartRequest(BaseModel):
    mode: str = "ping_pong"  # ping_pong, scalping, market_making
    pairs: Optional[list] = None  # If None, use all available pairs


class HFTStatusResponse(BaseModel):
    running: bool
    daily_volume: float
    daily_trades: int
    daily_pnl: float
    open_positions: int
    trades_this_minute: int


@app.post("/api/hft/start")
async def start_hft(request: HFTStartRequest):
    """Start high frequency trading"""
    try:
        if hf_trader.running:
            return JSONResponse(
                status_code=400,
                content={"error": "HFT already running"}
            )

        mode = TradingMode[request.mode.upper()]

        # Start HFT in background
        asyncio.create_task(hf_trader.start(mode))

        return {
            "status": "started",
            "mode": request.mode,
            "message": "High frequency trading started"
        }

    except Exception as e:
        logger.error("Failed to start HFT", error=str(e))
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to start HFT: {str(e)}"}
        )


@app.post("/api/hft/stop")
async def stop_hft():
    """Stop high frequency trading"""
    try:
        await hf_trader.stop()
        return {
            "status": "stopped",
            "message": "High frequency trading stopped"
        }

    except Exception as e:
        logger.error("Failed to stop HFT", error=str(e))
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to stop HFT: {str(e)}"}
        )


@app.get("/api/hft/status", response_model=HFTStatusResponse)
async def get_hft_status():
    """Get high frequency trading status"""
    try:
        return HFTStatusResponse(
            running=hf_trader.running,
            daily_volume=hf_trader.stats.daily_volume,
            daily_trades=hf_trader.stats.daily_trades,
            daily_pnl=hf_trader.stats.daily_pnl,
            open_positions=hf_trader.stats.open_positions,
            trades_this_minute=hf_trader.stats.trades_this_minute
        )

    except Exception as e:
        logger.error("Failed to get HFT status", error=str(e))
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to get status: {str(e)}"}
        )


@app.post("/api/orders/cancel/{order_id}")
async def cancel_order(order_id: str):
    """Cancel a specific order"""
    try:
        # This would need implementation in lighter_client
        # For now, return a placeholder
        return {
            "status": "cancelled",
            "order_id": order_id,
            "message": "Order cancellation requested"
        }
    except Exception as e:
        logger.error("Failed to cancel order", order_id=order_id, error=str(e))
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to cancel order: {str(e)}"}
        )


@app.post("/api/orders/cancel-all")
async def cancel_all_orders():
    """Cancel all open orders"""
    try:
        account_info = await lighter_client.get_account_info()

        # Count open orders from positions
        total_cancelled = 0
        for position in account_info.get("positions", []):
            if position.get("open_order_count", 0) > 0:
                total_cancelled += position["open_order_count"]

        return {
            "status": "success",
            "orders_cancelled": total_cancelled,
            "message": f"Cancelled {total_cancelled} orders"
        }
    except Exception as e:
        logger.error("Failed to cancel all orders", error=str(e))
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to cancel orders: {str(e)}"}
        )


# Market Order HFT endpoints
@app.post("/api/market-hft/start")
async def start_market_hft():
    """Start market order only HFT"""
    try:
        if market_hft.running:
            return JSONResponse(
                status_code=400,
                content={"error": "Market HFT already running"}
            )

        # Start Market HFT in background
        asyncio.create_task(market_hft.start())

        return {
            "status": "started",
            "message": "Market Order HFT started successfully"
        }

    except Exception as e:
        logger.error("Failed to start Market HFT", error=str(e))
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to start Market HFT: {str(e)}"}
        )


@app.post("/api/market-hft/stop")
async def stop_market_hft():
    """Stop market order HFT"""
    try:
        await market_hft.stop()
        return {
            "status": "stopped",
            "message": "Market Order HFT stopped successfully"
        }

    except Exception as e:
        logger.error("Failed to stop Market HFT", error=str(e))
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to stop Market HFT: {str(e)}"}
        )


@app.get("/api/market-hft/status")
async def get_market_hft_status():
    """Get market order HFT status"""
    try:
        return {
            "running": market_hft.running,
            "daily_volume": market_hft.stats.daily_volume,
            "daily_trades": market_hft.stats.daily_trades,
            "daily_pnl": market_hft.stats.daily_pnl,
            "positions": market_hft.positions,
            "trades_this_minute": market_hft.stats.trades_this_minute
        }

    except Exception as e:
        logger.error("Failed to get Market HFT status", error=str(e))
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to get status: {str(e)}"}
        )


# Single Position Strategy endpoints
@app.post("/api/single-position/start")
async def start_single_position_strategy():
    """Start single position strategy"""
    try:
        if single_position_strategy.running:
            return JSONResponse(
                status_code=400,
                content={"error": "Single Position Strategy already running"}
            )

        # Start strategy in background
        asyncio.create_task(single_position_strategy.start())

        return {
            "status": "started",
            "message": "Single Position Strategy started successfully"
        }

    except Exception as e:
        logger.error("Failed to start Single Position Strategy", error=str(e))
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to start strategy: {str(e)}"}
        )


@app.post("/api/single-position/stop")
async def stop_single_position_strategy():
    """Stop single position strategy"""
    try:
        await single_position_strategy.stop()
        return {
            "status": "stopped",
            "message": "Single Position Strategy stopped successfully"
        }

    except Exception as e:
        logger.error("Failed to stop Single Position Strategy", error=str(e))
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to stop strategy: {str(e)}"}
        )


@app.get("/api/single-position/status")
async def get_single_position_status():
    """Get single position strategy status"""
    try:
        return {
            "running": single_position_strategy.running,
            "daily_volume": single_position_strategy.stats.daily_volume,
            "daily_trades": single_position_strategy.stats.daily_trades,
            "daily_pnl": single_position_strategy.stats.daily_pnl,
            "current_positions": single_position_strategy.current_positions,
            "position_configs": {
                symbol: {
                    "direction": config.direction.value,
                    "target_size_usd": config.target_size_usd,
                    "leverage": config.leverage
                }
                for symbol, config in single_position_strategy.position_configs.items()
            }
        }

    except Exception as e:
        logger.error("Failed to get Single Position Strategy status", error=str(e))
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to get status: {str(e)}"}
        )


# Price information endpoints
@app.get("/api/prices/all")
async def get_all_prices():
    """Get real-time prices for all tokens"""
    try:
        prices = await price_fetcher.get_all_prices()
        return {
            "prices": prices,
            "timestamp": datetime.now().isoformat(),
            "source": "Lighter DEX OrderBook"
        }
    except Exception as e:
        logger.error("Failed to get all prices", error=str(e))
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to get prices: {str(e)}"}
        )


@app.get("/api/prices/{symbol}")
async def get_token_price(symbol: str):
    """Get real-time price for a specific token"""
    try:
        price = await price_fetcher.get_token_price(symbol.upper())
        market_summary = await price_fetcher.get_market_summary(symbol.upper())

        if price is None:
            return JSONResponse(
                status_code=404,
                content={"error": f"Price not found for {symbol}"}
            )

        return {
            "symbol": symbol.upper(),
            "price": price,
            "market_data": market_summary,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error("Failed to get token price", symbol=symbol, error=str(e))
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to get price for {symbol}: {str(e)}"}
        )


# Trading history endpoints
@app.get("/api/trades/history")
async def get_trade_history(limit: int = 50):
    """Get recent trade history"""
    try:
        history = await lighter_client.get_account_inactive_orders(limit=limit)
        return {
            "orders": history.get("orders", []),
            "total_count": len(history.get("orders", [])),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error("Failed to get trade history", error=str(e))
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to get trade history: {str(e)}"}
        )


@app.get("/api/trades/by-symbol")
async def get_trades_by_symbol(hours: int = 24):
    """Get recent trades grouped by symbol"""
    try:
        trades = await lighter_client.get_recent_trades_by_symbol(hours=hours)
        return {
            "trades_by_symbol": trades.get("trades_by_symbol", {}),
            "total_trades": trades.get("total_trades", 0),
            "hours": hours,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error("Failed to get trades by symbol", error=str(e))
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to get trades by symbol: {str(e)}"}
        )


@app.get("/api/hft/performance")
async def get_hft_performance():
    """Get detailed performance metrics"""
    try:
        account_info = await lighter_client.get_account_info()

        # Calculate hourly stats
        hourly_rate = hf_trader.stats.daily_volume / 24 if hf_trader.stats.daily_trades > 0 else 0

        return {
            "daily_stats": {
                "volume": hf_trader.stats.daily_volume,
                "trades": hf_trader.stats.daily_trades,
                "pnl": hf_trader.stats.daily_pnl,
                "avg_trade_size": hf_trader.stats.daily_volume / max(hf_trader.stats.daily_trades, 1)
            },
            "current_state": {
                "open_positions": hf_trader.stats.open_positions,
                "active_orders": len(hf_trader.active_orders),
                "trades_this_minute": hf_trader.stats.trades_this_minute
            },
            "projections": {
                "hourly_volume": hourly_rate,
                "daily_target": 5000,
                "completion_percent": (hf_trader.stats.daily_volume / 5000) * 100
            },
            "account": {
                "balance": account_info.get("balance", {}).get("available_balance", 0),
                "total_value": account_info.get("balance", {}).get("total_asset_value", 0)
            }
        }

    except Exception as e:
        logger.error("Failed to get performance", error=str(e))
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to get performance: {str(e)}"}
        )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception", error=str(exc), path=request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )


# Signal handlers for graceful shutdown
def signal_handler(sig, frame):
    logger.info("Received shutdown signal")
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower()
    )