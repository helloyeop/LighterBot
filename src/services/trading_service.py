from typing import Dict, Any
import structlog
from datetime import datetime
from src.core.lighter_client import lighter_client
from src.core.risk_manager import risk_manager
from src.core.database import db_manager
from src.models.database import Trade, Position, WebhookLog, OrderStatus, OrderSide
from src.utils.notifications import notification_manager
from sqlalchemy import select
from decimal import Decimal

logger = structlog.get_logger()


async def process_trading_signal(signal: Dict[str, Any]):
    trade = None
    try:
        logger.info("Processing trading signal", signal=signal)

        # Save webhook log
        async with db_manager.get_session() as session:
            webhook_log = WebhookLog(
                payload=signal.dict() if hasattr(signal, "dict") else signal,
                is_valid=True,
                processed=False
            )
            session.add(webhook_log)
            await session.commit()

        # Perform risk checks
        can_trade, risk_message = await risk_manager.check_pre_trade(signal)

        if not can_trade:
            logger.warning("Trade blocked by risk manager", reason=risk_message)
            await notification_manager.send_alert(
                f"⚠️ Trade Blocked\nReason: {risk_message}\nSymbol: {signal.get('symbol')}"
            )
            return

        # Process based on action type
        action = signal.get("action", "").lower()

        if action == "close":
            result = await process_close_position(signal)
        elif action in ["buy", "sell"]:
            result = await process_open_position(signal)
        else:
            logger.error("Invalid action", action=action)
            return

        # Record successful trade
        if result:
            await record_trade(signal, result)
            await notification_manager.send_trade_notification(result)

            # Update webhook log as processed
            async with db_manager.get_session() as session:
                webhook_log.processed = True
                await session.commit()

    except Exception as e:
        logger.error("Failed to process trading signal", error=str(e), signal=signal)
        await notification_manager.send_alert(
            f"❌ Trade Failed\nError: {str(e)}\nSymbol: {signal.get('symbol')}"
        )

        # Record failed trade
        if trade:
            async with db_manager.get_session() as session:
                trade.status = OrderStatus.FAILED
                trade.error_message = str(e)
                await session.commit()


async def process_open_position(signal: Dict[str, Any]) -> Dict[str, Any]:
    try:
        symbol = signal.get("symbol")
        side = signal.get("action")
        quantity = signal.get("quantity")
        leverage = signal.get("leverage", 1)
        stop_loss = signal.get("stopLoss")
        take_profit = signal.get("takeProfit")
        order_type = signal.get("orderType", "market").lower()

        logger.info(
            "Opening position",
            symbol=symbol,
            side=side,
            quantity=quantity,
            leverage=leverage
        )

        # Execute order based on type
        if order_type == "market":
            result = await lighter_client.create_market_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                leverage=leverage,
                stop_loss=stop_loss,
                take_profit=take_profit
            )
        else:
            # For limit orders, you'd need a price parameter
            price = signal.get("price")
            if not price:
                raise ValueError("Price required for limit orders")

            result = await lighter_client.create_limit_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                leverage=leverage
            )

        # Record trade execution
        await risk_manager.record_trade(symbol)

        return {
            **result,
            "action": "open_position",
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "leverage": leverage
        }

    except Exception as e:
        logger.error("Failed to open position", error=str(e))
        raise


async def process_close_position(signal: Dict[str, Any]) -> Dict[str, Any]:
    try:
        symbol = signal.get("symbol")

        logger.info("Closing position", symbol=symbol)

        # Close the position
        success = await lighter_client.close_position(symbol)

        if not success:
            raise Exception("Failed to close position")

        # Record trade execution
        await risk_manager.record_trade(symbol)

        return {
            "action": "close_position",
            "symbol": symbol,
            "success": success,
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error("Failed to close position", error=str(e))
        raise


async def record_trade(signal: Dict[str, Any], result: Dict[str, Any]):
    try:
        async with db_manager.get_session() as session:
            trade = Trade(
                symbol=signal.get("symbol"),
                side=OrderSide.BUY if signal.get("action") == "buy" else OrderSide.SELL,
                quantity=Decimal(str(signal.get("quantity", 0))),
                price=Decimal(str(result.get("price", 0))) if result.get("price") else Decimal(0),
                status=OrderStatus.FILLED,
                order_id=result.get("tx_hash"),
                strategy=signal.get("strategy", "manual"),
                leverage=signal.get("leverage", 1),
                stop_loss=Decimal(str(signal.get("stopLoss", 0))) if signal.get("stopLoss") else None,
                take_profit=Decimal(str(signal.get("takeProfit", 0))) if signal.get("takeProfit") else None,
                webhook_data=signal
            )
            session.add(trade)
            await session.commit()

            logger.info("Trade recorded", trade_id=str(trade.id))

    except Exception as e:
        logger.error("Failed to record trade", error=str(e))


async def emergency_close_all():
    try:
        logger.warning("EMERGENCY: Closing all positions")

        # Activate kill switch
        await risk_manager.activate_kill_switch()

        # Close all positions
        success = await lighter_client.close_all_positions()

        await notification_manager.send_alert(
            "🚨 EMERGENCY SHUTDOWN\nAll positions closed\nKill switch activated"
        )

        return success

    except Exception as e:
        logger.error("Emergency close failed", error=str(e))
        await notification_manager.send_alert(
            f"❌ EMERGENCY CLOSE FAILED\nError: {str(e)}"
        )
        return False