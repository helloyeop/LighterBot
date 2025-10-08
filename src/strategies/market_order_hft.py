"""
Market Order Only High Frequency Trading Strategy
Optimized for volume generation with zero fees
"""

import asyncio
import random
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import structlog
from dataclasses import dataclass, field
from enum import Enum
from src.utils.price_fetcher import price_fetcher

logger = structlog.get_logger()


@dataclass
class TradingPair:
    symbol: str
    is_new: bool = False
    point_multiplier: float = 1.0
    min_trade_size: float = 0.001
    quantity_decimals: int = 4


@dataclass
class TradingStats:
    daily_volume: float = 0.0
    daily_trades: int = 0
    daily_pnl: float = 0.0
    current_position: Dict[str, float] = field(default_factory=dict)
    last_trade_time: Optional[datetime] = None
    trades_this_minute: int = 0
    minute_reset_time: datetime = field(default_factory=datetime.now)


class MarketOrderHFT:
    def __init__(self, lighter_client, settings):
        self.client = lighter_client
        self.settings = settings
        self.stats = TradingStats()
        self.running = False

        # Rate limiting: 10 trades per minute
        self.rate_limit_per_minute = 10

        # Account-specific randomization characteristics
        self.account_randomness = {
            'trading_speed_factor': random.uniform(0.7, 1.3),      # ±30% speed variation
            'position_size_factor': random.uniform(0.8, 1.2),      # ±20% size variation
            'patience_factor': random.uniform(0.8, 1.3),           # ±30% wait time variation
            'token_order_seed': hash(str(settings.lighter_account_index)) % 1000,  # Consistent per account
        }

        logger.info("Account trading characteristics initialized",
                   speed_factor=self.account_randomness['trading_speed_factor'],
                   size_factor=self.account_randomness['position_size_factor'],
                   patience_factor=self.account_randomness['patience_factor'])

        # Trading pairs configuration - USER REQUESTED TOKENS
        # User requested: APEX, ZEC, STBL, 2Z, 0G, FF, EDEN (7 tokens only)
        self.trading_pairs = {
            # New token selection per user request
            "APEX": TradingPair("APEX", is_new=False, point_multiplier=1.5, min_trade_size=2.0),    # ~$4 min - market_id 86
            "ZEC": TradingPair("ZEC", is_new=True, point_multiplier=2.0, min_trade_size=0.03),      # ~$4.5 min - market_id 90, high value
            "STBL": TradingPair("STBL", is_new=True, point_multiplier=2.0, min_trade_size=15.0),    # ~$4.8 min - market_id 85
            "2Z": TradingPair("2Z", is_new=True, point_multiplier=2.0, min_trade_size=10.0),        # ~$5 min - market_id 88
            "0G": TradingPair("0G", is_new=True, point_multiplier=2.0, min_trade_size=1.7),         # ~$5 min - market_id 84
            "FF": TradingPair("FF", is_new=False, point_multiplier=1.5, min_trade_size=25.0),       # ~$4.5 min - market_id 87
            "EDEN": TradingPair("EDEN", is_new=True, point_multiplier=2.0, min_trade_size=12.0),    # ~$5 min - market_id 89
        }

        # Position tracking
        self.positions = {}

        # WebSocket-based order verification tracking
        self.pending_verifications = {}  # Dict[verification_id, verification_data]
        self.verification_events = {}    # Dict[verification_id, asyncio.Event]

    async def start(self):
        """Start market order only HFT"""
        self.running = True
        logger.info("Starting Market Order HFT")

        # Initialize position tracking with current blockchain positions
        await self.initialize_position_tracking()

        # Register WebSocket callbacks for real-time position updates
        self.client.add_position_update_callback(self.on_realtime_position_update)
        logger.info("Registered for real-time WebSocket position updates")

        # Register WebSocket callbacks for real-time order status updates
        self.client.add_order_update_callback(self.on_realtime_order_update)
        logger.info("Registered for real-time WebSocket order status updates")

        # Start background tasks
        tasks = [
            asyncio.create_task(self.rate_limiter()),
            asyncio.create_task(self.trading_cycle()),
            asyncio.create_task(self.stats_reporter()),
            asyncio.create_task(self.position_balancer()),
            asyncio.create_task(self.periodic_position_sync()),
        ]

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Market Order HFT stopped")

    async def stop(self):
        """Stop trading and clean up"""
        self.running = False
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

    async def trading_cycle(self):
        """Main trading cycle using market orders only"""
        while self.running:
            try:
                # Equal rotation through all pairs (no priority)
                pairs = self.get_equal_rotation_pairs()

                for pair_config in pairs:
                    if not await self.can_trade():
                        await asyncio.sleep(6)  # Wait for rate limit reset

                    symbol = pair_config.symbol

                    # Dynamic position sizing with account-specific variation
                    base_usd = await self.calculate_dynamic_position_size(symbol, pair_config.is_new)

                    # Apply account-specific size variation
                    size_factor = self.account_randomness['position_size_factor']
                    base_usd *= size_factor

                    logger.debug(
                        f"Position size adjusted for account characteristics",
                        symbol=symbol,
                        original_size=base_usd / size_factor,
                        size_factor=size_factor,
                        final_size=base_usd
                    )

                    # Check current position
                    current_pos = self.positions.get(symbol, 0)

                    # Safety check: Maximum position size per token
                    MAX_POSITION_USD = 100.0  # Maximum $100 per position - 더 큰 포지션 허용

                    # Get estimated price for position value calculation
                    estimated_price = await price_fetcher.get_token_price(symbol)
                    if not estimated_price or estimated_price <= 0:
                        price_estimates = {
                            "ETH": 2400, "BTC": 63000, "HYPE": 0.02,
                            "ASTER": 1.94, "APEX": 1.70, "FF": 0.18
                        }
                        estimated_price = price_estimates.get(symbol, 1)

                    current_position_value = abs(current_pos) * estimated_price

                    # Skip if position is already too large
                    if current_position_value > MAX_POSITION_USD:
                        logger.warning(
                            f"Position size limit exceeded for {symbol}",
                            current_position=current_pos,
                            position_value=current_position_value,
                            max_allowed=MAX_POSITION_USD
                        )
                        await asyncio.sleep(5)
                        continue

                    # Log current state for debugging
                    logger.info(
                        f"Trading decision for {symbol}",
                        current_position=current_pos,
                        base_usd_threshold=base_usd,
                        symbol=symbol
                    )

                    # Decide direction based on current position (maintain neutrality)
                    if current_pos > base_usd:
                        # We're long, so sell
                        side = "sell"
                        quantity = await self.calculate_trade_size(symbol, base_usd / 2)
                        logger.info(f"Long position detected for {symbol}, selling to neutralize")
                    elif current_pos < -base_usd:
                        # We're short, so buy
                        side = "buy"
                        quantity = await self.calculate_trade_size(symbol, base_usd / 2)
                        logger.info(f"Short position detected for {symbol}, buying to neutralize")
                    else:
                        # Neutral, random direction
                        side = random.choice(["buy", "sell"])
                        quantity = await self.calculate_trade_size(symbol, base_usd)
                        logger.info(f"Neutral position for {symbol}, random direction: {side}")

                    # Execute market order
                    first_order = await self.execute_market_order(symbol, side, quantity)

                    if not first_order:
                        logger.error("First order failed or was not executed, skipping pair", symbol=symbol)
                        continue

                    # Randomized hold time based on account characteristics
                    base_hold_time = random.uniform(120, 300)  # 2-5 minutes base
                    speed_factor = self.account_randomness['trading_speed_factor']
                    hold_time = base_hold_time * speed_factor
                    logger.info(f"First order executed successfully. Holding {symbol} position for {hold_time:.1f} seconds")
                    await asyncio.sleep(hold_time)

                    # Check current account status before reverse trade
                    try:
                        account_info = await self.client.get_account_info(force_refresh=True)
                        available_balance = account_info.get("balance", {}).get("available_balance", 0)
                        logger.info("Account status before reverse trade",
                                  balance=available_balance)

                        # If balance is critically low, free up some margin before continuing
                        if available_balance < 1.0:
                            logger.warning(f"Balance critically low (${available_balance}) before reverse trade")
                            freed = await self.free_margin_by_closing_positions(target_margin=3.0)
                            if freed <= 0:
                                logger.error("Cannot free enough margin for reverse trade, skipping")
                                continue
                    except Exception as e:
                        logger.error("Failed to get account info", error=str(e))

                    # Reverse the position (create volume)
                    opposite_side = "sell" if side == "buy" else "buy"
                    second_order = await self.execute_market_order(symbol, opposite_side, quantity)

                    if not second_order:
                        logger.error("Second order failed", symbol=symbol)

                    # Update stats
                    self.stats.daily_volume += quantity * 2 * base_usd  # Both sides
                    self.stats.daily_trades += 2

                    # Randomized delay between pairs based on account characteristics
                    base_delay = 150  # 2.5 minutes base
                    patience_factor = self.account_randomness['patience_factor']
                    randomized_delay = base_delay * patience_factor * random.uniform(0.8, 1.2)

                    logger.info(
                        f"Waiting {randomized_delay:.1f}s before next pair",
                        base_delay=base_delay,
                        patience_factor=patience_factor,
                        final_delay=randomized_delay
                    )

                    await asyncio.sleep(randomized_delay)

            except Exception as e:
                logger.error("Trading cycle error", error=str(e))
                await asyncio.sleep(10)

    async def execute_market_order(self, symbol: str, side: str, quantity: float):
        """Execute a market order"""
        try:
            if quantity <= 0:
                return

            # CRITICAL SAFETY CHECK: Verify we have sufficient funds BEFORE placing order
            account_info = await self.client.get_account_info()
            available_balance = account_info.get("balance", {}).get("available_balance", 0)

            # Calculate estimated order value
            estimated_price = await price_fetcher.get_token_price(symbol)
            if not estimated_price:
                price_estimates = {"ETH": 4500, "APEX": 1.95, "FF": 0.18}
                estimated_price = price_estimates.get(symbol, 1)

            order_value = quantity * estimated_price
            margin_requirements = await self.get_margin_requirements(symbol)
            required_margin = order_value * (margin_requirements["initial_margin_fraction"] / 100)

            # If we don't have enough margin, don't place the order (reasonable 1.2x buffer)
            if available_balance < required_margin * 1.2:
                logger.warning(
                    f"Insufficient funds for {symbol} order - SKIPPING",
                    available_balance=available_balance,
                    required_margin=required_margin,
                    safety_threshold=required_margin * 1.2,
                    order_value=order_value
                )
                return None

            # Calculate dynamic leverage based on API data
            margin_info = await self.get_margin_requirements(symbol)
            min_leverage = margin_info.get("min_leverage", 3)
            max_leverage = margin_info.get("max_leverage", 3)

            # Use higher leverage for new pairs, but respect API limits
            pair_config = self.trading_pairs.get(symbol)
            if pair_config and pair_config.is_new:
                leverage = min(max_leverage, 5)  # Up to 5x for new pairs
            else:
                leverage = min_leverage  # Use minimum leverage for regular pairs

            logger.info(
                "Executing market order",
                symbol=symbol,
                side=side,
                quantity=quantity,
                leverage=leverage
            )

            result = await self.client.create_market_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                leverage=leverage
            )

            # Do NOT update position tracking here - wait for verification
            # Position will be updated in sync_position_tracking() after verification

            # Update stats (only for submission, not execution)
            self.stats.trades_this_minute += 1
            self.stats.last_trade_time = datetime.now()

            # Extract tx_hash from result properly
            tx_hash = "unknown"
            if hasattr(result, 'tx_hash'):
                tx_hash = result.tx_hash
            elif isinstance(result, dict) and "tx_hash" in result:
                tx_hash = result["tx_hash"]

            logger.info(
                "Market order submitted successfully",
                symbol=symbol,
                side=side,
                quantity=quantity,
                leverage=leverage,
                current_tracked_position=self.positions.get(symbol, 0),
                tx_hash=tx_hash
            )

            # Wait for blockchain confirmation and verify execution
            predicted_time_ms = getattr(result, 'predicted_execution_time_ms', 3000)
            wait_time = max(predicted_time_ms / 1000, 3)  # At least 3 seconds

            logger.info(f"Waiting {wait_time:.1f}s for blockchain confirmation")
            await asyncio.sleep(wait_time)

            # Verify actual execution by checking account positions
            execution_verified = await self.verify_order_execution(symbol, side, quantity)

            if not execution_verified:
                logger.error(
                    "Order was submitted but not executed on blockchain",
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    tx_hash=tx_hash
                )
                # No need to revert since we didn't update position tracking yet
                return None
            else:
                logger.info(f"Order execution confirmed for {symbol} {side} {quantity}")
                # Update our position tracking to match actual position
                await self.sync_position_tracking(symbol)

            return result

        except Exception as e:
            logger.error("Failed to execute market order", error=str(e), symbol=symbol)
            return None

    async def calculate_trade_size(self, symbol: str, base_usd: float) -> float:
        """Calculate trade size based on USD value using real prices"""
        pair_config = self.trading_pairs.get(symbol)
        if not pair_config:
            return 0

        try:
            # Get real-time price from Lighter DEX orderbook
            real_price = await price_fetcher.get_token_price(symbol)

            if real_price and real_price > 0:
                estimated_price = real_price
                logger.info(f"Using real price for {symbol}: ${real_price}")
            else:
                # Fallback to estimates if API fails
                price_estimates = {
                    "ETH": 2400,
                    "BTC": 63000,
                    "HYPE": 0.02,  # Updated based on WebFetch: 49.725
                    "ASTER": 1.94,  # Updated: 1.94338
                    "APEX": 1.70,   # Updated: 1.69942
                    "FF": 0.18      # Updated: 0.17812
                }
                estimated_price = price_estimates.get(symbol, 1)
                logger.warning(f"Using fallback price for {symbol}: ${estimated_price}")

            quantity = base_usd / estimated_price

            # Round to appropriate decimals
            quantity = round(quantity, pair_config.quantity_decimals)

            # CRITICAL FIX: Always respect the minimum trade size from exchange/API
            # Don't allow quantities below the actual minimum required by the exchange
            exchange_min_quantity = pair_config.min_trade_size

            # If calculated quantity is below minimum, use minimum
            if quantity < exchange_min_quantity:
                logger.info(
                    f"Calculated quantity {quantity} below minimum {exchange_min_quantity} for {symbol}, using minimum",
                    calculated=quantity,
                    minimum_required=exchange_min_quantity,
                    symbol=symbol
                )
                final_quantity = exchange_min_quantity
            else:
                final_quantity = quantity

            # Log the calculation for debugging
            logger.debug(
                "Quantity calculation",
                symbol=symbol,
                calculated_quantity=quantity,
                exchange_min_quantity=exchange_min_quantity,
                final_quantity=final_quantity,
                was_adjusted=quantity < exchange_min_quantity
            )

            logger.info(
                "Trade size calculated",
                symbol=symbol,
                price=estimated_price,
                base_usd=base_usd,
                quantity=final_quantity
            )

            return final_quantity

        except Exception as e:
            logger.error("Failed to calculate trade size", symbol=symbol, error=str(e))
            return pair_config.min_trade_size

    async def calculate_dynamic_position_size(self, symbol: str, is_new_pair: bool = False) -> float:
        """Calculate position size based on available balance and risk parameters"""
        try:
            # Get current account info with force refresh to avoid cached data
            account_info = await self.client.get_account_info(force_refresh=True)
            available_balance = account_info.get("balance", {}).get("available_balance", 0)

            # Log the real balance for debugging
            logger.info(f"Real-time balance check - Available: ${available_balance}, Collateral: ${account_info.get('balance', {}).get('collateral', 0)}")

            # MAXIMUM AGGRESSION: Use 95% of available balance for high-volume trading
            max_allocation = available_balance * 0.95  # Maximum possible allocation

            # If balance is low, automatically free up margin by closing positions
            if available_balance < 2.0:  # Low balance threshold
                logger.warning(f"Available balance critically low: ${available_balance}, attempting to free margin")
                freed_margin = await self.free_margin_by_closing_positions(target_margin=5.0)
                if freed_margin > 0:
                    # Refresh account info after closing positions
                    account_info = await self.client.get_account_info(force_refresh=True)
                    available_balance = account_info.get("balance", {}).get("available_balance", 0)
                    logger.info(f"After position closure - New balance: ${available_balance}, Freed: ${freed_margin}")
                else:
                    logger.error("Failed to free any margin - insufficient positions to close")
                    return 0.0  # Cannot trade

            # Get margin requirements for the symbol (now async)
            margin_info = await self.get_margin_requirements(symbol)
            margin_fraction = margin_info["initial_margin_fraction"]
            max_leverage = margin_info.get("max_leverage", 3)
            min_leverage = margin_info.get("min_leverage", 3)

            # Calculate position size considering:
            # 1. Available balance
            # 2. Margin requirements
            # 3. Risk diversification (spread across multiple pairs)
            # 4. Priority boost for new pairs

            # AGGRESSIVE ALLOCATION: Focus on fewer pairs with larger sizes
            # Instead of diversifying across all pairs, concentrate on 1-2 main pairs
            active_pairs = len(self.get_equal_rotation_pairs())

            # Equal allocation for all pairs - no priority system
            # Use 50% of available balance per trade for all tokens
            base_allocation = max_allocation * 0.50

            # No priority multiplier - all tokens treated equally
            priority_multiplier = 1.0

            # Calculate position size with leverage
            position_size_usd = base_allocation * priority_multiplier

            # MAXIMUM LEVERAGE: Use the highest available leverage for maximum volume
            leverage = max_leverage  # Use maximum available leverage always
            effective_position_size = position_size_usd * leverage

            logger.info(
                f"AGGRESSIVE Leverage calculation for {symbol}",
                min_leverage=min_leverage,
                max_leverage=max_leverage,
                selected_leverage=leverage,
                note="Using MAXIMUM leverage for high volume"
            )

            # AGGRESSIVE margin usage - use most of available margin
            max_position_by_margin = (available_balance * 0.90) / (margin_fraction / 100)  # Much more aggressive
            position_size_usd = min(position_size_usd, max_position_by_margin)

            # Higher minimum position size for meaningful trades
            min_position = 5.0  # Much higher minimum for substantial volume
            position_size_usd = max(min_position, position_size_usd)

            # AGGRESSIVE MARGIN: Use most available margin with minimal buffer
            required_margin = position_size_usd * (margin_fraction / 100) * leverage
            margin_buffer = available_balance * 0.10  # Only 10% buffer for maximum usage

            # CRITICAL: Check if we have massive open positions already
            current_positions = account_info.get("positions", [])
            total_position_value = 0
            for pos in current_positions:
                if pos.symbol in self.trading_pairs:
                    pos_value = float(pos.position_value or 0)
                    total_position_value += abs(pos_value)

            # Allow larger position accumulation for high volume trading
            if total_position_value > available_balance * 20:  # Much higher threshold: 20x balance
                position_size_usd = min(position_size_usd, available_balance * 0.20)  # Still use 20% instead of 5%
                logger.warning(
                    "Very large existing positions detected, moderately reducing new position size",
                    symbol=symbol,
                    total_position_value=total_position_value,
                    available_balance=available_balance,
                    reduced_size=position_size_usd,
                    note="Allowing larger position accumulation for high volume"
                )

            if required_margin > (available_balance - margin_buffer):
                # AGGRESSIVE scaling - minimal safety factor
                safe_position_size = (available_balance - margin_buffer) / ((margin_fraction / 100) * leverage * 1.1)  # Minimal safety factor
                position_size_usd = max(min_position, safe_position_size)
                logger.warning(
                    "Position size reduced due to margin constraints",
                    symbol=symbol,
                    original_size=base_allocation * priority_multiplier,
                    reduced_size=position_size_usd,
                    required_margin=required_margin,
                    available_balance=available_balance,
                    total_existing_positions=total_position_value
                )

            logger.info(
                "Dynamic position sizing",
                symbol=symbol,
                available_balance=available_balance,
                max_allocation=max_allocation,
                base_allocation=base_allocation,
                priority_multiplier=priority_multiplier,
                position_size_usd=position_size_usd,
                leverage=leverage,
                margin_fraction=margin_fraction,
                required_margin=required_margin,
                margin_safety_buffer=margin_buffer,
                is_new_pair=is_new_pair
            )

            return position_size_usd

        except Exception as e:
            logger.error("Failed to calculate dynamic position size", symbol=symbol, error=str(e))
            # Fallback to conservative size
            return 1.0 if is_new_pair else 0.5

    async def get_margin_requirements(self, symbol: str) -> dict:
        """Get margin requirements for a symbol using dynamic API data"""
        try:
            # Try to get leverage info from API first
            leverage_info = await price_fetcher.get_leverage_info(symbol)
            if leverage_info:
                return {
                    "initial_margin_fraction": leverage_info["initial_margin_percentage"],
                    "max_leverage": leverage_info["max_leverage"],
                    "min_leverage": leverage_info["min_leverage"]
                }
        except Exception as e:
            logger.warning(f"Failed to get dynamic leverage info for {symbol}, using fallback", error=str(e))

        # Fallback to static data if API fails
        margin_map = {
            "ETH": {"initial_margin_fraction": 6.66, "max_leverage": 15, "min_leverage": 3},
            "BTC": {"initial_margin_fraction": 2.00, "max_leverage": 50, "min_leverage": 3},
            "HYPE": {"initial_margin_fraction": 6.66, "max_leverage": 15, "min_leverage": 3},
            "ASTER": {"initial_margin_fraction": 20.00, "max_leverage": 5, "min_leverage": 3},
            "APEX": {"initial_margin_fraction": 50.00, "max_leverage": 2, "min_leverage": 2},  # APEX max is 2x
            "FF": {"initial_margin_fraction": 33.33, "max_leverage": 3, "min_leverage": 3},
            "USELESS": {"initial_margin_fraction": 33.33, "max_leverage": 3, "min_leverage": 3},
            "1000TOSHI": {"initial_margin_fraction": 33.33, "max_leverage": 3, "min_leverage": 3},
            "STBL": {"initial_margin_fraction": 33.33, "max_leverage": 3, "min_leverage": 3},
            "2Z": {"initial_margin_fraction": 33.33, "max_leverage": 3, "min_leverage": 3},
        }

        return margin_map.get(symbol, {"initial_margin_fraction": 33.33, "max_leverage": 3, "min_leverage": 3})

    def get_equal_rotation_pairs(self) -> List[TradingPair]:
        """Get pairs in randomized rotation based on account characteristics"""
        pairs = list(self.trading_pairs.values())

        # Use account-specific seed for consistent randomization per account
        import random as random_module
        random_module.seed(self.account_randomness['token_order_seed'])

        # Shuffle the pairs based on account-specific seed
        shuffled_pairs = pairs.copy()
        random_module.shuffle(shuffled_pairs)

        # Reset random seed to system time to maintain other randomness
        random_module.seed()

        logger.info(
            "Token rotation order determined",
            account_seed=self.account_randomness['token_order_seed'],
            rotation_order=[pair.symbol for pair in shuffled_pairs]
        )

        return shuffled_pairs

    async def position_balancer(self):
        """Monitor and balance positions to maintain neutrality and free up margin when needed"""
        while self.running:
            try:
                # Get current account state
                account_info = await self.client.get_account_info()
                available_balance = account_info.get("balance", {}).get("available_balance", 0)

                # Calculate total position value
                positions_data = account_info.get("positions", [])
                total_position_value = 0
                largest_position = None
                largest_value = 0

                for pos in positions_data:
                    if pos.symbol in self.trading_pairs:
                        pos_value = abs(float(pos.position_value or 0))
                        total_position_value += pos_value

                        # Track largest position for potential closure
                        if pos_value > largest_value:
                            largest_value = pos_value
                            largest_position = pos

                # CRITICAL: If available balance is too low, close positions to free margin
                if available_balance < 2.0 and total_position_value > 10.0:
                    logger.warning(
                        "Low available balance detected - closing largest position to free margin",
                        available_balance=available_balance,
                        total_position_value=total_position_value,
                        largest_position_symbol=largest_position.symbol if largest_position else "None",
                        largest_position_value=largest_value
                    )

                    # Close the largest position to free up the most margin
                    if largest_position:
                        symbol = largest_position.symbol
                        position_size = float(largest_position.position)
                        sign = int(largest_position.sign)
                        actual_position = position_size * sign

                        # Determine closing side (opposite of current position)
                        if actual_position > 0:  # Long position, close with sell
                            side = "sell"
                            quantity = position_size
                        else:  # Short position, close with buy
                            side = "buy"
                            quantity = position_size

                        logger.info(
                            f"Closing largest position {symbol} to free margin",
                            position=actual_position,
                            side=side,
                            quantity=quantity
                        )

                        # Execute closing order
                        await self.execute_market_order(symbol, side, quantity)

                        # Wait a bit before checking again
                        await asyncio.sleep(60)
                        continue

                # Original exposure check (keep for risk management)
                total_exposure = sum(abs(self.positions.get(pos.symbol, 0)) for pos in positions_data if pos.symbol in self.trading_pairs)

                if total_exposure > 100:  # $100 total exposure limit
                    logger.warning("High exposure detected", total_exposure=total_exposure)

                    # Close largest tracked position
                    if self.positions:
                        largest_symbol = max(self.positions.items(),
                                           key=lambda x: abs(x[1]))
                        symbol, position = largest_symbol

                        if abs(position) > 0.001:
                            side = "sell" if position > 0 else "buy"
                            await self.execute_market_order(symbol, side, abs(position))

            except Exception as e:
                logger.error("Position balancer error", error=str(e))

            await asyncio.sleep(30)  # Check every 30 seconds

    async def stats_reporter(self):
        """Report trading statistics periodically"""
        while self.running:
            logger.info(
                "Trading stats",
                daily_volume=self.stats.daily_volume,
                daily_trades=self.stats.daily_trades,
                daily_pnl=self.stats.daily_pnl,
                positions=self.positions,
                trades_this_minute=self.stats.trades_this_minute
            )

            # Check if we're meeting volume targets
            hours_elapsed = (datetime.now().hour + datetime.now().minute / 60)
            if hours_elapsed > 0:
                hourly_rate = self.stats.daily_volume / hours_elapsed
                projected_daily = hourly_rate * 24

                logger.info(
                    "Volume projection",
                    hourly_rate=hourly_rate,
                    projected_daily=projected_daily,
                    target=5000,
                    completion_percent=(projected_daily / 5000) * 100
                )

            await asyncio.sleep(60)  # Report every minute

    async def verify_order_execution(self, symbol: str, side: str, expected_quantity: float) -> bool:
        """Verify that an order was actually executed using WebSocket real-time updates"""
        try:
            # Calculate expected position after this order
            previous_tracked_position = self.positions.get(symbol, 0)
            if side == "buy":
                expected_new_position = previous_tracked_position + expected_quantity
            else:  # sell
                expected_new_position = previous_tracked_position - expected_quantity

            logger.info(
                "Starting WebSocket-based order verification",
                symbol=symbol,
                side=side,
                expected_quantity=expected_quantity,
                previous_position=previous_tracked_position,
                expected_new_position=expected_new_position
            )

            # Generate unique verification ID
            import time
            verification_id = f"{symbol}_{side}_{int(time.time() * 1000)}"

            # Create verification event
            verification_event = asyncio.Event()

            # Store verification data
            self.pending_verifications[verification_id] = {
                'symbol': symbol,
                'side': side,
                'expected_quantity': expected_quantity,
                'expected_position': expected_new_position,
                'previous_position': previous_tracked_position,
                'tolerance': 0.001
            }
            self.verification_events[verification_id] = verification_event

            # Wait for WebSocket update or timeout (5 seconds max)
            try:
                await asyncio.wait_for(verification_event.wait(), timeout=5.0)
                logger.info(f"WebSocket order verification completed successfully for {symbol}")
                return True

            except asyncio.TimeoutError:
                # Timeout - verification failed
                logger.warning(
                    f"WebSocket order verification timed out for {symbol} - falling back to polling check",
                    verification_id=verification_id
                )

                # Clean up
                self.pending_verifications.pop(verification_id, None)
                self.verification_events.pop(verification_id, None)

                # Fallback to one-time position sync
                await self.sync_position_tracking(symbol)

                # Check if the fallback sync found the expected position
                current_position = self.positions.get(symbol, 0)
                position_diff = abs(current_position - expected_new_position)

                if position_diff <= 0.001:
                    logger.info(f"Fallback verification successful for {symbol}")
                    return True
                else:
                    logger.warning(
                        f"Order execution failed for {symbol} - position not matching expected",
                        expected_position=expected_new_position,
                        actual_position=current_position,
                        difference=position_diff
                    )
                    return False

        except Exception as e:
            logger.error("Failed to verify order execution", symbol=symbol, error=str(e))

            # Clean up on error
            verification_id = f"{symbol}_{side}_{int(time.time() * 1000)}"
            self.pending_verifications.pop(verification_id, None)
            self.verification_events.pop(verification_id, None)

            return False

    async def sync_position_tracking(self, symbol: str):
        """Sync our position tracking with actual blockchain position"""
        try:
            account_info = await self.client.get_account_info()
            positions = account_info.get("positions", [])

            for position in positions:
                if position.symbol == symbol:
                    # IMPORTANT: Consider the sign for position direction
                    position_raw = float(position.position)
                    sign = int(position.sign)

                    # Convert to signed position (negative for shorts, positive for longs)
                    actual_position = position_raw * sign
                    old_tracked = self.positions.get(symbol, 0)
                    self.positions[symbol] = actual_position

                    logger.info(
                        f"Position tracking synced for {symbol}",
                        old_tracked=old_tracked,
                        new_tracked=actual_position
                    )
                    return

        except Exception as e:
            logger.error("Failed to sync position tracking", symbol=symbol, error=str(e))

    async def initialize_position_tracking(self):
        """Initialize position tracking with current blockchain positions"""
        try:
            # First, initialize ALL trading pairs to 0
            for symbol in self.trading_pairs:
                self.positions[symbol] = 0

            logger.info("Initialized all trading pairs to 0", trading_pairs=list(self.trading_pairs.keys()))

            # Then update with actual blockchain positions
            account_info = await self.client.get_account_info()
            positions = account_info.get("positions", [])

            logger.info("Updating with actual blockchain positions...")

            for position in positions:
                symbol = position.symbol
                position_raw = float(position.position)
                sign = int(position.sign)

                # Convert to signed position (negative for shorts, positive for longs)
                current_position = position_raw * sign

                # Update positions that we trade
                if symbol in self.trading_pairs:
                    self.positions[symbol] = current_position
                    if position_raw != 0:
                        logger.info(
                            f"Updated position tracking from blockchain",
                            symbol=symbol,
                            position=current_position
                        )

            logger.info("Position tracking initialized", positions=self.positions)

        except Exception as e:
            logger.error("Failed to initialize position tracking", error=str(e))
            # Initialize with empty positions if failed
            for symbol in self.trading_pairs:
                self.positions[symbol] = 0

    async def periodic_position_sync(self):
        """Periodically sync our position tracking with blockchain state to prevent drift"""
        while self.running:
            try:
                await asyncio.sleep(300)  # Sync every 5 minutes

                logger.info("Running periodic position synchronization...")

                # Method 1: Get positions from our internal API
                account_info = await self.client.get_account_info()
                positions = account_info.get("positions", [])

                blockchain_positions = {}
                for position in positions:
                    if position.symbol in self.trading_pairs:
                        position_raw = float(position.position)
                        sign = int(position.sign)
                        actual_position = position_raw * sign
                        blockchain_positions[position.symbol] = actual_position

                # Method 2: Try to get positions from external API for additional verification
                try:
                    import aiohttp
                    external_positions = {}
                    async with aiohttp.ClientSession() as session:
                        external_url = "https://explorer.elliot.ai/api/accounts/0xC74Ef16B20c50B7337585a0a8e1eed3EDd50CF43/positions"
                        async with session.get(external_url) as response:
                            if response.status == 200:
                                external_data = await response.json()
                                for pos in external_data:
                                    if pos.get("symbol") in self.trading_pairs:
                                        ext_position_raw = float(pos.get("position", 0))
                                        ext_sign = int(pos.get("sign", 1))
                                        ext_actual_position = ext_position_raw * ext_sign
                                        external_positions[pos.get("symbol")] = ext_actual_position

                                logger.info("External API verification successful", external_positions=external_positions)
                            else:
                                logger.debug(f"External API returned status {response.status}, using internal data only")

                except Exception as ext_error:
                    logger.debug("External API verification failed, using internal data only", error=str(ext_error))
                    external_positions = {}

                # Compare with our tracked positions and sync if needed
                sync_count = 0
                for symbol in self.trading_pairs:
                    tracked_position = self.positions.get(symbol, 0)
                    blockchain_position = blockchain_positions.get(symbol, 0)
                    external_position = external_positions.get(symbol, blockchain_position)

                    # Cross-verify between internal and external APIs if both available
                    if external_positions and symbol in external_positions:
                        if abs(blockchain_position - external_position) > 0.001:
                            logger.warning(
                                f"Discrepancy between internal and external APIs for {symbol}",
                                internal=blockchain_position,
                                external=external_position
                            )

                    # Use the most reliable source (prioritize external if available and consistent)
                    authoritative_position = external_position if external_positions else blockchain_position

                    # Allow small tolerance for rounding differences
                    tolerance = 0.001
                    if abs(tracked_position - authoritative_position) > tolerance:
                        logger.warning(
                            f"Position drift detected for {symbol} - syncing",
                            tracked=tracked_position,
                            blockchain=blockchain_position,
                            external=external_position if external_positions else "N/A",
                            authoritative=authoritative_position,
                            drift=abs(tracked_position - authoritative_position)
                        )
                        self.positions[symbol] = authoritative_position
                        sync_count += 1

                if sync_count > 0:
                    logger.info(f"Periodic sync completed - {sync_count} positions corrected")
                else:
                    logger.info("Periodic sync completed - all positions in sync")

            except Exception as e:
                logger.error("Failed to perform periodic position sync", error=str(e))
                await asyncio.sleep(60)  # Wait 1 minute before retrying

    async def close_all_positions(self):
        """Close all open positions"""
        for symbol, position in list(self.positions.items()):
            if abs(position) > 0.001:
                side = "sell" if position > 0 else "buy"
                await self.execute_market_order(symbol, side, abs(position))
                self.positions[symbol] = 0

        logger.info("All positions closed")

    def on_realtime_position_update(self, positions: Dict[str, float]):
        """Handle real-time position updates from WebSocket"""
        try:
            updated_positions = {}

            for symbol, new_position in positions.items():
                if symbol in self.trading_pairs:
                    old_position = self.positions.get(symbol, 0)

                    # Update internal tracking immediately
                    self.positions[symbol] = new_position
                    updated_positions[symbol] = {
                        'old': old_position,
                        'new': new_position,
                        'change': new_position - old_position
                    }

                    logger.info(
                        "Real-time position update",
                        symbol=symbol,
                        old_position=old_position,
                        new_position=new_position,
                        change=new_position - old_position
                    )

            # If any significant changes occurred, log summary
            if updated_positions:
                total_changes = sum(abs(p['change']) for p in updated_positions.values())
                if total_changes > 0.001:
                    logger.info(
                        "WebSocket position sync completed",
                        updated_count=len(updated_positions),
                        total_change=total_changes,
                        positions=self.positions
                    )

            # Check for pending order verifications
            self._check_pending_verifications(updated_positions)

        except Exception as e:
            logger.error("Error processing real-time position update", error=str(e))

    def on_realtime_order_update(self, order_status: Dict):
        """Handle real-time order status updates from WebSocket"""
        try:
            order_id = order_status.get('order_id', 'unknown')
            symbol = order_status.get('symbol', 'UNKNOWN')
            side = order_status.get('side', 'unknown')
            status = order_status.get('status', 'unknown')
            outcome = order_status.get('outcome', 'unknown')
            quantity = order_status.get('quantity', 0)
            price = order_status.get('price', 0)

            # Log the order status update with detailed information
            logger.info(
                "🔄 Real-time order status update received",
                order_id=order_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                status=status,
                outcome=outcome
            )

            # Analyze and categorize the order outcome
            if outcome.startswith('filled'):
                if outcome == 'filled_normally':
                    logger.info(
                        "✅ Order filled successfully",
                        order_id=order_id,
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                        price=price
                    )
                    # Update our stats
                    self.stats.daily_trades += 1
                    self.stats.daily_volume += quantity * price
                elif outcome == 'filled_with_high_slippage':
                    logger.warning(
                        "⚠️ Order filled with high slippage",
                        order_id=order_id,
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                        price=price
                    )
                    # Still count as a successful trade but note the slippage
                    self.stats.daily_trades += 1
                    self.stats.daily_volume += quantity * price

            elif outcome.startswith('cancelled'):
                if outcome == 'cancelled_insufficient_margin':
                    logger.error(
                        "❌ Order cancelled - Insufficient margin",
                        order_id=order_id,
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                        price=price
                    )
                    # This indicates we need to check our margin management
                elif outcome == 'cancelled_slippage':
                    logger.warning(
                        "❌ Order cancelled - Slippage protection",
                        order_id=order_id,
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                        price=price
                    )
                elif outcome == 'cancelled_timeout':
                    logger.warning(
                        "❌ Order cancelled - Timeout/Expired",
                        order_id=order_id,
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                        price=price
                    )
                else:
                    logger.warning(
                        "❌ Order cancelled - Unknown reason",
                        order_id=order_id,
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                        price=price,
                        outcome=outcome
                    )

            elif outcome.startswith('rejected'):
                if outcome == 'rejected_insufficient_margin':
                    logger.error(
                        "🚫 Order rejected - Insufficient margin",
                        order_id=order_id,
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                        price=price
                    )
                elif outcome == 'rejected_slippage':
                    logger.warning(
                        "🚫 Order rejected - Slippage protection",
                        order_id=order_id,
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                        price=price
                    )
                else:
                    logger.error(
                        "🚫 Order rejected - Unknown reason",
                        order_id=order_id,
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                        price=price,
                        outcome=outcome
                    )

            else:
                logger.info(
                    "📊 Order status update",
                    order_id=order_id,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    price=price,
                    status=status,
                    outcome=outcome
                )

        except Exception as e:
            logger.error("Error processing real-time order update", error=str(e))

    def _check_pending_verifications(self, updated_positions: Dict[str, Dict]):
        """Check if any pending order verifications can be completed based on position updates"""
        completed_verifications = []

        for verification_id, verification_data in self.pending_verifications.items():
            symbol = verification_data['symbol']
            expected_position = verification_data['expected_position']
            tolerance = verification_data.get('tolerance', 0.001)

            if symbol in updated_positions:
                actual_position = updated_positions[symbol]['new']
                position_diff = abs(actual_position - expected_position)

                if position_diff <= tolerance:
                    # Verification successful
                    logger.info(
                        "WebSocket order verification successful",
                        verification_id=verification_id,
                        symbol=symbol,
                        expected_position=expected_position,
                        actual_position=actual_position,
                        difference=position_diff
                    )
                    completed_verifications.append(verification_id)

                    # Signal the verification event
                    if verification_id in self.verification_events:
                        self.verification_events[verification_id].set()

        # Clean up completed verifications
        for verification_id in completed_verifications:
            self.pending_verifications.pop(verification_id, None)
            self.verification_events.pop(verification_id, None)

    async def free_margin_by_closing_positions(self, target_margin: float = 5.0) -> float:
        """
        Free up margin by strategically closing existing positions
        Returns the amount of margin freed
        """
        try:
            logger.info(f"Attempting to free ${target_margin} in margin by closing positions")

            # Get current account info to see positions
            account_info = await self.client.get_account_info(force_refresh=True)
            positions_data = account_info.get("positions", [])

            # Find positions that can be partially closed
            positions_to_close = []

            for position in positions_data:
                symbol = position.symbol if hasattr(position, 'symbol') else position.get('symbol')
                current_position = float(position.position if hasattr(position, 'position') else position.get('position', 0))
                sign = int(position.sign if hasattr(position, 'sign') else position.get('sign', 1))
                position_value = float(position.position_value if hasattr(position, 'position_value') else position.get('position_value', 0))

                # Skip empty positions
                if current_position == 0:
                    continue

                # Calculate actual signed position
                signed_position = current_position * sign

                positions_to_close.append({
                    'symbol': symbol,
                    'position': signed_position,
                    'value': abs(position_value),
                    'priority': self._get_close_priority(symbol, signed_position)
                })

            # Sort by priority (higher priority = close first)
            positions_to_close.sort(key=lambda x: x['priority'], reverse=True)

            total_freed = 0.0
            positions_closed = 0

            for pos_info in positions_to_close:
                if total_freed >= target_margin:
                    break

                symbol = pos_info['symbol']
                current_position = pos_info['position']

                # Calculate how much to close (25-50% of position)
                close_percentage = 0.25 if abs(current_position) > 10 else 0.5
                quantity_to_close = abs(current_position) * close_percentage

                # Determine side for closing order
                side = "sell" if current_position > 0 else "buy"

                logger.info(f"Closing {close_percentage*100}% of {symbol} position to free margin")
                logger.info(f"Position: {current_position}, Closing: {quantity_to_close} ({side})")

                # Execute the closing order
                try:
                    result = await self.client.create_market_order(
                        symbol=symbol,
                        side=side,
                        quantity=quantity_to_close,
                        leverage=1  # Use minimal leverage for closing
                    )

                    if result:
                        # Estimate freed margin (rough calculation)
                        estimated_freed = quantity_to_close * 0.1  # Assume 10% margin requirement
                        total_freed += estimated_freed
                        positions_closed += 1

                        logger.info(f"Successfully closed {quantity_to_close} {symbol}, estimated freed: ${estimated_freed}")

                        # Update our position tracking
                        new_position = current_position - (quantity_to_close if side == "sell" else -quantity_to_close)
                        self.positions[symbol] = new_position

                        # Wait a bit for settlement
                        await asyncio.sleep(1.0)
                    else:
                        logger.warning(f"Failed to close {symbol} position")

                except Exception as e:
                    logger.error(f"Error closing {symbol} position", error=str(e))
                    continue

            logger.info(f"Position closure complete - Freed: ${total_freed}, Positions closed: {positions_closed}")
            return total_freed

        except Exception as e:
            logger.error("Failed to free margin by closing positions", error=str(e))
            return 0.0

    def _get_close_priority(self, symbol: str, position: float) -> float:
        """
        Calculate priority for closing a position
        Higher values = close first
        """
        # Prioritize:
        # 1. Larger positions (more margin to free)
        # 2. Losing positions (cut losses)
        # 3. Non-core trading pairs

        priority = abs(position)  # Base priority on position size

        # Reduce priority for core trading pairs
        if symbol in ["ETH", "BTC"]:
            priority *= 0.5

        # Increase priority for new/experimental pairs
        if symbol in ["APEX", "FF", "HYPE"]:
            priority *= 1.5

        return priority