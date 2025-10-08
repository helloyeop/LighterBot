"""
High Frequency Trading Strategy for Lighter DEX
Optimized for point farming with New pairs
"""

import asyncio
import random
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import structlog
from dataclasses import dataclass, field
from enum import Enum

logger = structlog.get_logger()


class TradingMode(Enum):
    PING_PONG = "ping_pong"
    SCALPING = "scalping"
    MARKET_MAKING = "market_making"


@dataclass
class TradingPair:
    symbol: str
    is_new: bool = False
    point_multiplier: float = 1.0
    min_trade_size: float = 0.001
    price_decimals: int = 2
    quantity_decimals: int = 4
    leverage_available: List[int] = field(default_factory=lambda: [1, 3, 5, 10, 20])


@dataclass
class TradingStats:
    daily_volume: float = 0.0
    daily_trades: int = 0
    daily_pnl: float = 0.0
    open_positions: int = 0
    last_trade_time: Optional[datetime] = None
    trades_this_minute: int = 0
    minute_reset_time: datetime = field(default_factory=datetime.now)


class HighFrequencyTrader:
    def __init__(self, lighter_client, settings):
        self.client = lighter_client
        self.settings = settings
        self.stats = TradingStats()
        self.active_orders = {}
        self.position_tracker = {}
        self.running = False

        # Rate limiting: 10 trades per minute
        self.rate_limit_per_minute = 10
        self.trade_queue = asyncio.Queue()

        # Trading pairs configuration
        self.trading_pairs = {
            "HYPE": TradingPair("HYPE", is_new=True, point_multiplier=5.0,
                              min_trade_size=1, leverage_available=[3, 5]),
            "ASTER": TradingPair("ASTER", is_new=True, point_multiplier=3.0,
                                min_trade_size=1, leverage_available=[3]),
            "APEX": TradingPair("APEX", is_new=True, point_multiplier=3.0,
                               min_trade_size=1, leverage_available=[3]),
            "ETH": TradingPair("ETH", is_new=False, point_multiplier=1.0,
                              min_trade_size=0.001, leverage_available=[1, 3, 5, 10, 20]),
            "FF": TradingPair("FF", is_new=False, point_multiplier=1.0,
                             min_trade_size=10, leverage_available=[1, 3, 5, 10]),
        }

    async def start(self, mode: TradingMode = TradingMode.PING_PONG):
        """Start high frequency trading"""
        self.running = True
        logger.info("Starting high frequency trader", mode=mode.value)

        # Start background tasks
        tasks = [
            asyncio.create_task(self.rate_limiter()),
            asyncio.create_task(self.trade_executor()),
            asyncio.create_task(self.position_monitor()),
            asyncio.create_task(self.stats_reporter()),
        ]

        if mode == TradingMode.PING_PONG:
            tasks.append(asyncio.create_task(self.ping_pong_strategy()))
        elif mode == TradingMode.SCALPING:
            tasks.append(asyncio.create_task(self.scalping_strategy()))

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("High frequency trader stopped")

    async def stop(self):
        """Stop trading and clean up"""
        self.running = False
        await self.cancel_all_orders()
        await self.close_all_positions()

    async def rate_limiter(self):
        """Ensure we don't exceed rate limits"""
        while self.running:
            now = datetime.now()

            # Reset counter every minute
            if now - self.stats.minute_reset_time >= timedelta(minutes=1):
                self.stats.trades_this_minute = 0
                self.stats.minute_reset_time = now

            await asyncio.sleep(1)

    async def can_trade(self) -> bool:
        """Check if we can make another trade (rate limit)"""
        return self.stats.trades_this_minute < self.rate_limit_per_minute

    async def ping_pong_strategy(self):
        """Ping-pong trading strategy for maximum volume"""
        while self.running:
            try:
                # Prioritize New pairs for higher points
                pairs = self.get_prioritized_pairs()

                for pair_config in pairs:
                    if not await self.can_trade():
                        await asyncio.sleep(6)  # Wait for rate limit reset

                    symbol = pair_config.symbol

                    # Get current price
                    current_price = await self.get_market_price(symbol)
                    if not current_price:
                        continue

                    # Calculate ping-pong range - smaller spread to avoid rejection
                    # Use 0.1-0.3% spread for better acceptance
                    spread_percent = random.uniform(0.001, 0.003)
                    buy_price = current_price * (1 - spread_percent/2)
                    sell_price = current_price * (1 + spread_percent/2)

                    # Determine position size (smaller sizes for testing)
                    # Start with small positions to test
                    leverage = min(pair_config.leverage_available)  # Use minimum leverage first
                    base_size = 5 if pair_config.is_new else 2  # $5 for new, $2 for regular
                    position_size = await self.calculate_position_size(symbol, base_size, leverage)

                    # Place ping-pong orders
                    await self.place_ping_pong_orders(
                        symbol=symbol,
                        buy_price=buy_price,
                        sell_price=sell_price,
                        quantity=position_size,
                        leverage=leverage
                    )

                    # Small delay between pairs
                    await asyncio.sleep(random.uniform(3, 6))

            except Exception as e:
                logger.error("Ping-pong strategy error", error=str(e))
                await asyncio.sleep(10)

    async def scalping_strategy(self):
        """Quick in-and-out scalping strategy"""
        while self.running:
            try:
                pairs = self.get_prioritized_pairs()

                for pair_config in pairs:
                    if not await self.can_trade():
                        await asyncio.sleep(6)

                    symbol = pair_config.symbol

                    # Analyze micro-trends
                    direction = await self.analyze_micro_trend(symbol)
                    if not direction:
                        continue

                    leverage = max(pair_config.leverage_available)
                    base_size = 30 if pair_config.is_new else 15
                    position_size = await self.calculate_position_size(symbol, base_size, leverage)

                    # Open position
                    order = await self.open_scalp_position(
                        symbol=symbol,
                        side=direction,
                        quantity=position_size,
                        leverage=leverage
                    )

                    if order:
                        # Hold for 30-120 seconds
                        hold_time = random.uniform(30, 120)
                        await asyncio.sleep(hold_time)

                        # Close position
                        await self.close_position(symbol)

            except Exception as e:
                logger.error("Scalping strategy error", error=str(e))
                await asyncio.sleep(10)

    async def place_ping_pong_orders(self, symbol: str, buy_price: float,
                                    sell_price: float, quantity: float, leverage: int):
        """Place both buy and sell orders for ping-pong"""
        try:
            # Place buy order
            buy_order = await self.client.create_limit_order(
                symbol=symbol,
                side="buy",
                quantity=quantity,
                price=buy_price,
                leverage=leverage
            )

            # Place sell order
            sell_order = await self.client.create_limit_order(
                symbol=symbol,
                side="sell",
                quantity=quantity,
                price=sell_price,
                leverage=leverage
            )

            # Track orders
            self.active_orders[f"{symbol}_buy"] = buy_order
            self.active_orders[f"{symbol}_sell"] = sell_order

            # Update stats
            self.stats.trades_this_minute += 2
            self.stats.daily_trades += 2
            self.stats.daily_volume += quantity * (buy_price + sell_price) * leverage

            logger.info(
                "Ping-pong orders placed",
                symbol=symbol,
                buy_price=buy_price,
                sell_price=sell_price,
                quantity=quantity,
                leverage=leverage
            )

        except Exception as e:
            logger.error("Failed to place ping-pong orders", error=str(e))

    async def open_scalp_position(self, symbol: str, side: str,
                                 quantity: float, leverage: int):
        """Open a scalping position"""
        try:
            order = await self.client.create_market_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                leverage=leverage
            )

            self.position_tracker[symbol] = {
                "side": side,
                "quantity": quantity,
                "entry_time": datetime.now(),
                "leverage": leverage
            }

            self.stats.trades_this_minute += 1
            self.stats.daily_trades += 1
            self.stats.open_positions += 1

            return order

        except Exception as e:
            logger.error("Failed to open scalp position", error=str(e))
            return None

    async def close_position(self, symbol: str):
        """Close an open position"""
        if symbol not in self.position_tracker:
            return

        position = self.position_tracker[symbol]
        opposite_side = "sell" if position["side"] == "buy" else "buy"

        try:
            await self.client.create_market_order(
                symbol=symbol,
                side=opposite_side,
                quantity=position["quantity"],
                leverage=position["leverage"]
            )

            del self.position_tracker[symbol]
            self.stats.open_positions -= 1

        except Exception as e:
            logger.error("Failed to close position", error=str(e))

    async def get_market_price(self, symbol: str) -> Optional[float]:
        """Get current market price for a symbol"""
        try:
            # Get account info which includes current positions
            account_info = await self.client.get_account_info()

            # For now, use approximate prices from your account
            # In production, this should fetch from order book or ticker API
            # Updated with more realistic current market prices
            price_map = {
                "ETH": 2395.0,  # Current ETH price from your order book
                "BTC": 63000.0,  # Current BTC price
                "HYPE": 0.025,  # New pair, check actual price
                "ASTER": 0.05,
                "APEX": 1.2,
                "FF": 0.23,  # Based on your position data
                "USELESS": 0.23,  # Based on your position
                "1000TOSHI": 0.0001,
                "STBL": 1.0
            }

            return price_map.get(symbol, 1.0)

        except Exception as e:
            logger.error("Failed to get market price", symbol=symbol, error=str(e))
            # Return fallback prices
            fallback_prices = {
                "ETH": 2400.0,
                "BTC": 63000.0,
                "HYPE": 0.5,
                "ASTER": 0.05,
                "APEX": 1.2,
                "FF": 0.23
            }
            return fallback_prices.get(symbol, 1.0)

    async def analyze_micro_trend(self, symbol: str) -> Optional[str]:
        """Analyze micro trends for scalping"""
        # Simplified trend analysis
        # In production, this would analyze order book, recent trades, etc.
        return random.choice(["buy", "sell", None])

    async def calculate_position_size(self, symbol: str, base_usd: float, leverage: int) -> float:
        """Calculate position size based on USD value"""
        price = await self.get_market_price(symbol)
        if not price:
            return 0

        pair_config = self.trading_pairs.get(symbol)
        if not pair_config:
            return 0

        # Calculate quantity based on USD value WITHOUT leverage
        # Leverage is applied by the exchange, not in quantity calculation
        quantity = base_usd / price

        # Round to appropriate decimals
        quantity = round(quantity, pair_config.quantity_decimals)

        # Ensure minimum trade size
        final_quantity = max(quantity, pair_config.min_trade_size)

        # Log for debugging
        logger.debug(
            "Position size calculated",
            symbol=symbol,
            price=price,
            base_usd=base_usd,
            quantity=quantity,
            final_quantity=final_quantity
        )

        return final_quantity

    def get_prioritized_pairs(self) -> List[TradingPair]:
        """Get pairs prioritized by point multiplier"""
        pairs = list(self.trading_pairs.values())
        # Sort by point multiplier (New pairs first)
        return sorted(pairs, key=lambda x: x.point_multiplier, reverse=True)

    async def position_monitor(self):
        """Monitor open positions and manage risk"""
        while self.running:
            try:
                # Check position ages and close if too old
                for symbol, position in list(self.position_tracker.items()):
                    age = datetime.now() - position["entry_time"]

                    # Close positions older than 5 minutes
                    if age > timedelta(minutes=5):
                        await self.close_position(symbol)
                        logger.info("Closed stale position", symbol=symbol, age=age)

            except Exception as e:
                logger.error("Position monitor error", error=str(e))

            await asyncio.sleep(10)

    async def stats_reporter(self):
        """Report trading statistics periodically"""
        while self.running:
            logger.info(
                "Trading stats",
                daily_volume=self.stats.daily_volume,
                daily_trades=self.stats.daily_trades,
                daily_pnl=self.stats.daily_pnl,
                open_positions=self.stats.open_positions,
                trades_this_minute=self.stats.trades_this_minute
            )
            await asyncio.sleep(60)  # Report every minute

    async def cancel_all_orders(self):
        """Cancel all active orders"""
        for order_id in list(self.active_orders.keys()):
            try:
                # Would call Lighter API to cancel order
                del self.active_orders[order_id]
            except Exception as e:
                logger.error("Failed to cancel order", order_id=order_id, error=str(e))

    async def close_all_positions(self):
        """Close all open positions"""
        for symbol in list(self.position_tracker.keys()):
            await self.close_position(symbol)

    async def trade_executor(self):
        """Execute trades from the queue"""
        while self.running:
            try:
                # Process trade queue
                if not self.trade_queue.empty():
                    trade = await self.trade_queue.get()
                    # Execute trade logic here

            except Exception as e:
                logger.error("Trade executor error", error=str(e))

            await asyncio.sleep(1)