import asyncio
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from decimal import Decimal
import structlog
import json
import os
from config.settings import get_settings

logger = structlog.get_logger()
settings = get_settings()


class RiskManager:
    def __init__(self):
        self.kill_switch = False
        self.daily_loss = Decimal(0)
        self.trade_counts = {}
        self.state_file = "data/risk_state.json"

    async def connect(self):
        try:
            os.makedirs("data", exist_ok=True)
            await self.load_state()
            logger.info("Risk manager initialized")
        except Exception as e:
            logger.error("Failed to initialize risk manager", error=str(e))
            raise

    async def disconnect(self):
        await self.save_state()

    async def load_state(self):
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                    self.kill_switch = state.get("kill_switch", False)
                    self.daily_loss = Decimal(str(state.get("daily_loss", 0)))

                    # Reset daily counters if needed
                    last_reset = state.get("last_daily_reset")
                    today = datetime.utcnow().date().isoformat()
                    if last_reset != today:
                        await self.reset_daily_counters()
            else:
                await self.reset_daily_counters()

        except Exception as e:
            logger.error("Failed to load risk state", error=str(e))
            await self.reset_daily_counters()

    async def save_state(self):
        try:
            state = {
                "kill_switch": self.kill_switch,
                "daily_loss": str(self.daily_loss),
                "daily_trades_count": len(self.trade_counts),
                "last_daily_reset": datetime.utcnow().date().isoformat()
            }
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error("Failed to save risk state", error=str(e))

    async def reset_daily_counters(self):
        self.daily_loss = Decimal(0)
        self.trade_counts = {}
        await self.save_state()
        logger.info("Daily risk counters reset")

    async def check_pre_trade(self, signal: Dict[str, Any]) -> tuple[bool, str]:
        try:
            # Check kill switch
            if await self.is_kill_switch_active():
                return False, "Kill switch is active"

            # Check daily loss limit
            if not await self.check_daily_loss_limit():
                return False, "Daily loss limit exceeded"

            # Check position size
            if not await self.check_position_size(signal.get("quantity", 0)):
                return False, "Position size exceeds maximum allowed"

            # Check trade frequency
            if not await self.check_trade_frequency(signal.get("symbol")):
                return False, "Trade frequency limit exceeded"

            # Check leverage
            if not await self.check_leverage(signal.get("leverage", 1)):
                return False, "Leverage exceeds maximum allowed"

            return True, "Risk checks passed"

        except Exception as e:
            logger.error("Risk check failed", error=str(e))
            return False, f"Risk check error: {str(e)}"

    async def is_kill_switch_active(self) -> bool:
        return self.kill_switch

    async def activate_kill_switch(self):
        self.kill_switch = True
        await self.save_state()
        logger.warning("KILL SWITCH ACTIVATED")

    async def deactivate_kill_switch(self):
        self.kill_switch = False
        await self.save_state()
        logger.info("Kill switch deactivated")

    async def check_daily_loss_limit(self) -> bool:
        try:
            max_daily_loss_usd = Decimal(settings.max_position_size_usd) * Decimal(settings.max_daily_loss_pct) / Decimal(100)

            if abs(self.daily_loss) >= max_daily_loss_usd:
                logger.warning(
                    "Daily loss limit reached",
                    daily_loss=float(self.daily_loss),
                    limit=float(max_daily_loss_usd)
                )
                return False

            return True

        except Exception as e:
            logger.error("Failed to check daily loss limit", error=str(e))
            return False

    async def check_position_size(self, quantity: float) -> bool:
        if quantity > settings.max_position_size_usd:
            logger.warning(
                "Position size exceeds limit",
                requested=quantity,
                limit=settings.max_position_size_usd
            )
            return False
        return True

    async def check_trade_frequency(self, symbol: str) -> bool:
        try:
            current_minute = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
            minute_key = f"minute_{current_minute}"

            # Count trades in current minute
            minute_trades = sum(1 for k in self.trade_counts.keys() if k.startswith(minute_key))

            if minute_trades >= settings.max_trades_per_minute:
                logger.warning(
                    "Trade frequency limit reached",
                    count=minute_trades,
                    limit=settings.max_trades_per_minute
                )
                return False

            # Check last trade time for the symbol
            symbol_key = f"symbol_{symbol}"
            last_trade = self.trade_counts.get(symbol_key)

            if last_trade:
                last_trade_time = datetime.fromisoformat(last_trade)
                time_since_last = datetime.utcnow() - last_trade_time

                # Minimum 5 seconds between trades on same symbol
                if time_since_last < timedelta(seconds=5):
                    logger.warning(
                        "Too frequent trading on symbol",
                        symbol=symbol,
                        seconds_since_last=time_since_last.total_seconds()
                    )
                    return False

            return True

        except Exception as e:
            logger.error("Failed to check trade frequency", error=str(e))
            return False

    async def check_leverage(self, leverage: int) -> bool:
        if leverage > settings.max_leverage:
            logger.warning(
                "Leverage exceeds limit",
                requested=leverage,
                limit=settings.max_leverage
            )
            return False
        return True

    async def record_trade(self, symbol: str, pnl: Optional[Decimal] = None):
        try:
            # Update trade count
            current_minute = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
            minute_key = f"minute_{current_minute}_{len(self.trade_counts)}"
            self.trade_counts[minute_key] = datetime.utcnow().isoformat()

            # Update last trade time for symbol
            symbol_key = f"symbol_{symbol}"
            self.trade_counts[symbol_key] = datetime.utcnow().isoformat()

            # Clean old entries (keep only last hour)
            cutoff_time = datetime.utcnow() - timedelta(hours=1)
            self.trade_counts = {
                k: v for k, v in self.trade_counts.items()
                if not k.startswith("minute_") or
                datetime.fromisoformat(v) > cutoff_time
            }

            # Update PnL if provided
            if pnl is not None:
                await self.update_daily_pnl(pnl)

            await self.save_state()

        except Exception as e:
            logger.error("Failed to record trade", error=str(e))

    async def update_daily_pnl(self, pnl: Decimal):
        try:
            self.daily_loss += pnl

            if pnl < 0:
                logger.info(
                    "Loss recorded",
                    loss=float(pnl),
                    daily_total=float(self.daily_loss)
                )

            await self.save_state()

        except Exception as e:
            logger.error("Failed to update daily PnL", error=str(e))

    async def get_risk_status(self) -> Dict[str, Any]:
        try:
            daily_trades = len([k for k in self.trade_counts.keys() if k.startswith("minute_")])

            return {
                "kill_switch": self.kill_switch,
                "daily_trades_count": daily_trades,
                "daily_loss": float(self.daily_loss),
                "max_daily_loss": settings.max_daily_loss_pct,
                "max_position_size": settings.max_position_size_usd,
                "max_leverage": settings.max_leverage,
                "max_trades_per_minute": settings.max_trades_per_minute,
                "timestamp": datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error("Failed to get risk status", error=str(e))
            return {}


# Global risk manager instance
risk_manager = RiskManager()