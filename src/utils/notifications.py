import asyncio
from typing import Dict, Any, Optional
import structlog
from datetime import datetime
import httpx
from config.settings import get_settings

logger = structlog.get_logger()
settings = get_settings()


class NotificationManager:
    def __init__(self):
        self.telegram_enabled = bool(settings.telegram_bot_token and settings.telegram_chat_id)

    async def send_telegram(self, message: str) -> bool:
        if not self.telegram_enabled:
            return False

        try:
            url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json={
                        "chat_id": settings.telegram_chat_id,
                        "text": message,
                        "parse_mode": "Markdown"
                    }
                )

                if response.status_code == 200:
                    logger.info("Telegram notification sent")
                    return True
                else:
                    logger.error(
                        "Telegram notification failed",
                        status=response.status_code,
                        response=response.text
                    )
                    return False

        except Exception as e:
            logger.error("Failed to send Telegram notification", error=str(e))
            return False

    async def send_trade_notification(self, trade_result: Dict[str, Any]):
        try:
            action = trade_result.get("action", "unknown")
            symbol = trade_result.get("symbol", "")
            side = trade_result.get("side", "")
            quantity = trade_result.get("quantity", 0)
            leverage = trade_result.get("leverage", 1)

            if action == "open_position":
                emoji = "📈" if side.lower() == "buy" else "📉"
                message = f"""
{emoji} *Position Opened*
Symbol: {symbol}
Side: {side.upper()}
Quantity: {quantity}
Leverage: {leverage}x
Time: {datetime.utcnow().strftime('%H:%M:%S UTC')}
                """
            elif action == "close_position":
                message = f"""
🔒 *Position Closed*
Symbol: {symbol}
Time: {datetime.utcnow().strftime('%H:%M:%S UTC')}
                """
            else:
                message = f"""
📊 *Trade Executed*
Action: {action}
Symbol: {symbol}
Time: {datetime.utcnow().strftime('%H:%M:%S UTC')}
                """

            await self.send_telegram(message)

        except Exception as e:
            logger.error("Failed to send trade notification", error=str(e))

    async def send_alert(self, message: str):
        try:
            await self.send_telegram(message)
        except Exception as e:
            logger.error("Failed to send alert", error=str(e))

    async def send_daily_summary(self, summary: Dict[str, Any]):
        try:
            total_trades = summary.get("total_trades", 0)
            total_pnl = summary.get("total_pnl", 0)
            win_rate = summary.get("win_rate", 0)
            total_volume = summary.get("total_volume", 0)

            emoji = "💰" if total_pnl > 0 else "📉"

            message = f"""
📊 *Daily Summary*
{emoji} PnL: ${total_pnl:.2f}
📈 Total Trades: {total_trades}
🎯 Win Rate: {win_rate:.1f}%
💱 Volume: ${total_volume:.2f}
⏰ Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
            """

            await self.send_telegram(message)

        except Exception as e:
            logger.error("Failed to send daily summary", error=str(e))

    async def send_error_notification(self, error: str, context: Optional[Dict] = None):
        try:
            message = f"""
⚠️ *Error Alert*
Error: {error}
Time: {datetime.utcnow().strftime('%H:%M:%S UTC')}
            """

            if context:
                message += f"\nContext: {str(context)[:200]}"

            await self.send_telegram(message)

        except Exception as e:
            logger.error("Failed to send error notification", error=str(e))


# Global notification manager instance
notification_manager = NotificationManager()