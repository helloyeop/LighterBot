"""
Multi-account signal-based trading service
Handles TradingView signals for multiple API accounts
"""

import structlog
from typing import Dict, Optional, List
from datetime import datetime
import asyncio
from config.settings import get_settings
from src.core.account_manager import account_manager
from src.api.webhook import TradingViewSignal

logger = structlog.get_logger()
settings = get_settings()


class MultiAccountSignalService:
    def __init__(self):
        # Track positions per account: {account_index: {symbol: position_size}}
        self.account_positions: Dict[int, Dict[str, float]] = {}
        self.base_quantity = 0.01
        self.use_balance_percentage = True
        self.balance_percentage = 0.8

    async def process_signal(self, signal: TradingViewSignal, account_index: int):
        """Process signal for specific account"""
        try:
            # Check if account exists and is active
            account_config = account_manager.get_account_config(account_index)
            if not account_config:
                logger.error(f"Account {account_index} not found in configuration")
                return

            if not account_config.get('active', True):
                logger.info(f"Account {account_index} is not active, skipping signal")
                return

            # Check symbol filtering for this account
            symbol = signal.symbol
            if not account_manager.is_symbol_allowed(account_index, symbol):
                logger.info(
                    "Signal ignored due to symbol filtering",
                    account_index=account_index,
                    symbol=symbol,
                    allowed_symbols=account_config.get('allowed_symbols', [])
                )
                return

            # Get client for this account
            client = await account_manager.get_client(account_index)

            # Initialize position tracking for account if needed
            if account_index not in self.account_positions:
                self.account_positions[account_index] = {}

            # Sync position with DEX
            await self._sync_position_with_dex(client, account_index, symbol)

            current_position = self.account_positions[account_index].get(symbol, 0)

            logger.info(
                "Processing signal for account",
                account_index=account_index,
                account_name=account_config.get('name', 'Unknown'),
                symbol=symbol,
                sale_type=signal.sale,
                current_position=current_position
            )

            # Handle signal based on type
            if signal.sale == "long":
                await self._handle_long_signal(client, account_index, symbol, current_position, signal)
            elif signal.sale == "short":
                await self._handle_short_signal(client, account_index, symbol, current_position, signal)
            elif signal.sale == "close":
                await self._handle_close_signal(client, account_index, symbol, current_position, signal)

        except Exception as e:
            logger.error(
                "Failed to process signal for account",
                account_index=account_index,
                error=str(e),
                signal=signal.dict()
            )

    async def process_signal_for_all_accounts(self, signal: TradingViewSignal):
        """Process signal for all active accounts"""
        try:
            all_accounts = account_manager.get_all_accounts()
            tasks = []

            for account_config in all_accounts:
                if account_config.get('active', True):
                    account_index = account_config['account_index']
                    # Create task for each account
                    task = self.process_signal(signal, account_index)
                    tasks.append(task)

            if tasks:
                # Process all accounts in parallel
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Log any errors
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        logger.error(
                            f"Error processing signal for account {all_accounts[i]['account_index']}: {result}"
                        )
            else:
                logger.warning("No active accounts found to process signal")

        except Exception as e:
            logger.error("Failed to process signal for all accounts", error=str(e))

    async def _calculate_position_size(
        self,
        client,
        account_index: int,
        symbol: str,
        leverage: int = 1
    ) -> float:
        """Calculate position size based on account balance"""
        try:
            if not self.use_balance_percentage:
                return self.base_quantity

            # Get account info
            account_info = await client.get_account_info()
            if not account_info:
                logger.warning(f"Failed to get account info for {account_index}, using base quantity")
                return self.base_quantity

            # Extract available balance
            balance_data = account_info.get('balance', {})
            available_balance = balance_data.get('available_balance', 0)

            if available_balance == 0:
                available_balance = balance_data.get('collateral', 0)

            try:
                available_balance = float(available_balance) if available_balance else 0
            except (ValueError, TypeError):
                available_balance = 0

            if available_balance <= 0:
                logger.warning(f"Invalid balance for account {account_index}, using base quantity")
                return self.base_quantity

            # Get current price
            from src.utils.price_fetcher import price_fetcher
            current_price = await price_fetcher.get_token_price(symbol)

            if not current_price or current_price <= 0:
                # Fallback prices
                fallback_prices = {"BTC": 70000, "ETH": 4500, "BNB": 600, "SOL": 150}
                current_price = fallback_prices.get(symbol, 1.0)

            # Calculate position size
            position_value = available_balance * self.balance_percentage * leverage
            position_size = position_value / current_price

            # Apply limits
            min_size = 0.001
            max_size = 10.0
            position_size = max(min_size, min(position_size, max_size))
            position_size = round(position_size, 4)

            logger.info(
                "Position size calculated",
                account_index=account_index,
                symbol=symbol,
                available_balance=available_balance,
                price=current_price,
                calculated_size=position_size
            )

            return position_size

        except Exception as e:
            logger.error(f"Failed to calculate position size for account {account_index}", error=str(e))
            return self.base_quantity

    async def _handle_long_signal(
        self,
        client,
        account_index: int,
        symbol: str,
        current_position: float,
        signal: TradingViewSignal
    ):
        """Handle long signal for specific account"""
        # Calculate target position size
        target_position = await self._calculate_position_size(client, account_index, symbol, signal.leverage)

        # Already in long position
        if current_position > 0:
            logger.info(
                "Already in long position",
                account_index=account_index,
                symbol=symbol,
                position=current_position
            )
            return

        # Calculate trade quantity
        if current_position < 0:
            # Close short and open long
            trade_quantity = abs(current_position) + target_position
            logger.info(
                "Reversing short to long",
                account_index=account_index,
                symbol=symbol,
                current=current_position,
                trade_quantity=trade_quantity
            )
        else:
            # Open new long
            trade_quantity = target_position
            logger.info(
                "Opening new long position",
                account_index=account_index,
                symbol=symbol,
                trade_quantity=trade_quantity
            )

        # Execute trade
        success = await self._execute_trade(client, account_index, symbol, "buy", trade_quantity, signal.leverage)

        if success:
            await self._sync_position_with_dex(client, account_index, symbol)
            logger.info(
                "Long position updated",
                account_index=account_index,
                symbol=symbol,
                new_position=self.account_positions[account_index].get(symbol, 0)
            )

    async def _handle_short_signal(
        self,
        client,
        account_index: int,
        symbol: str,
        current_position: float,
        signal: TradingViewSignal
    ):
        """Handle short signal for specific account"""
        # Calculate target position size
        calculated_size = await self._calculate_position_size(client, account_index, symbol, signal.leverage)
        target_position = -calculated_size

        # Already in short position
        if current_position < 0:
            logger.info(
                "Already in short position",
                account_index=account_index,
                symbol=symbol,
                position=current_position
            )
            return

        # Calculate trade quantity
        if current_position > 0:
            # Close long and open short
            trade_quantity = current_position + abs(target_position)
            logger.info(
                "Reversing long to short",
                account_index=account_index,
                symbol=symbol,
                current=current_position,
                trade_quantity=trade_quantity
            )
        else:
            # Open new short
            trade_quantity = abs(target_position)
            logger.info(
                "Opening new short position",
                account_index=account_index,
                symbol=symbol,
                trade_quantity=trade_quantity
            )

        # Execute trade
        success = await self._execute_trade(client, account_index, symbol, "sell", trade_quantity, signal.leverage)

        if success:
            await self._sync_position_with_dex(client, account_index, symbol)
            logger.info(
                "Short position updated",
                account_index=account_index,
                symbol=symbol,
                new_position=self.account_positions[account_index].get(symbol, 0)
            )

    async def _handle_close_signal(
        self,
        client,
        account_index: int,
        symbol: str,
        current_position: float,
        signal: TradingViewSignal
    ):
        """Handle close signal for specific account"""
        if current_position == 0:
            logger.warning(
                "No position to close",
                account_index=account_index,
                symbol=symbol
            )
            return

        logger.info(
            "Processing close signal",
            account_index=account_index,
            symbol=symbol,
            current_position=current_position
        )

        # Determine trade direction to close position
        if current_position > 0:
            # Close long -> Sell
            side = "sell"
            trade_quantity = current_position
        else:
            # Close short -> Buy
            side = "buy"
            trade_quantity = abs(current_position)

        # Execute trade
        success = await self._execute_trade(client, account_index, symbol, side, trade_quantity, signal.leverage)

        if success:
            await self._sync_position_with_dex(client, account_index, symbol)
            logger.info(
                "Position closed",
                account_index=account_index,
                symbol=symbol,
                previous_position=current_position,
                current_position=self.account_positions[account_index].get(symbol, 0)
            )

    async def _execute_trade(
        self,
        client,
        account_index: int,
        symbol: str,
        side: str,
        quantity: float,
        leverage: int
    ) -> bool:
        """Execute trade for specific account"""
        try:
            logger.info(
                "Executing trade",
                account_index=account_index,
                symbol=symbol,
                side=side,
                quantity=quantity,
                leverage=leverage
            )

            # Execute market order
            result = await client.create_market_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                leverage=leverage
            )

            # Check success
            is_success = result and result.get('code') == 200

            if is_success:
                logger.info(
                    "Trade executed successfully",
                    account_index=account_index,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    tx_hash=result.get('tx_hash')
                )

                # Wait for settlement
                await asyncio.sleep(1)
                return True
            else:
                logger.error(
                    "Trade execution failed",
                    account_index=account_index,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    result=result
                )
                return False

        except Exception as e:
            logger.error(
                "Failed to execute trade",
                account_index=account_index,
                symbol=symbol,
                side=side,
                quantity=quantity,
                error=str(e)
            )
            return False

    async def _sync_position_with_dex(
        self,
        client,
        account_index: int,
        symbol: str
    ):
        """Sync position with DEX for specific account"""
        try:
            # Get positions from DEX
            positions = await client.get_positions()

            if positions:
                for pos in positions:
                    if hasattr(pos, 'symbol'):
                        pos_symbol = pos.symbol
                        pos_position = float(pos.position)
                        pos_sign = pos.sign
                    else:
                        pos_symbol = pos.get('symbol')
                        pos_position = float(pos.get('position', 0))
                        pos_sign = pos.get('sign', 1)

                    if pos_symbol == symbol:
                        actual_position = pos_position
                        if pos_sign == -1:
                            actual_position = -actual_position

                        # Update tracking
                        if account_index not in self.account_positions:
                            self.account_positions[account_index] = {}

                        old_position = self.account_positions[account_index].get(symbol, 0)
                        self.account_positions[account_index][symbol] = actual_position

                        logger.info(
                            "Position synced with DEX",
                            account_index=account_index,
                            symbol=symbol,
                            old_position=old_position,
                            new_position=actual_position
                        )
                        return

            # No position found
            if account_index not in self.account_positions:
                self.account_positions[account_index] = {}

            old_position = self.account_positions[account_index].get(symbol, 0)
            self.account_positions[account_index][symbol] = 0

            logger.info(
                "No position found in DEX",
                account_index=account_index,
                symbol=symbol,
                old_position=old_position
            )

        except Exception as e:
            logger.error(
                "Failed to sync position with DEX",
                account_index=account_index,
                symbol=symbol,
                error=str(e)
            )

    async def get_all_positions(self) -> Dict[int, Dict[str, float]]:
        """Get all positions for all accounts"""
        return self.account_positions.copy()

    async def get_account_positions(self, account_index: int) -> Dict[str, float]:
        """Get positions for specific account"""
        return self.account_positions.get(account_index, {}).copy()


# Singleton instance
multi_account_signal_service = MultiAccountSignalService()


async def process_trading_signal_multi(signal: TradingViewSignal, account_index: Optional[int] = None):
    """Process trading signal for multiple accounts"""
    logger.info(
        "Processing trading signal",
        signal=signal.dict(),
        account_index=account_index
    )

    try:
        if account_index is not None:
            # Process for specific account
            await multi_account_signal_service.process_signal(signal, account_index)
        else:
            # Process for all active accounts
            await multi_account_signal_service.process_signal_for_all_accounts(signal)

        logger.info("Signal processing completed")

    except Exception as e:
        logger.error("Failed to process trading signal", error=str(e))