import lighter
import asyncio
from typing import Dict, Any, Optional, List, Callable
import structlog
from decimal import Decimal
from config.settings import get_settings
from datetime import datetime, timedelta
import os
import threading
import json
import aiohttp

logger = structlog.get_logger()
settings = get_settings()


class LighterClient:
    def __init__(self):
        self.api_client = None
        self.signer_client = None
        self.account_api = None
        self.ws_client = None
        self.api_key = settings.lighter_api_key
        self.api_secret = settings.lighter_api_secret
        self.connected = False
        self._auth_token = None
        self._auth_expiry = None

        # Get account and API key indices from settings
        self.account_index = settings.lighter_account_index
        self.api_key_index = settings.lighter_api_key_index
        self.base_url = settings.lighter_endpoint

        # WebSocket related variables
        self.ws_running = False
        self.ws_thread = None
        self.account_update_callbacks = []
        self.position_update_callbacks = []

        # Order tracking for WebSocket monitoring
        self.pending_orders = {}  # Dict[order_id, order_info]
        self.order_update_callbacks = []

    async def connect(self):
        try:
            # Initialize API client for read operations
            self.api_client = lighter.ApiClient()
            self.account_api = lighter.AccountApi(self.api_client)

            # Initialize signer client for write operations (orders, etc)
            # Note: This requires the private key, not just API key/secret
            # For now, we'll use API client for reading and need to implement signing later
            if self.api_secret:
                try:
                    self.signer_client = lighter.SignerClient(
                        url=settings.lighter_endpoint,
                        private_key=self.api_secret,  # This should be the private key
                        account_index=self.account_index,
                        api_key_index=self.api_key_index,
                    )

                    # Check if signer client is properly configured
                    err = self.signer_client.check_client()
                    if err:
                        logger.warning(f"SignerClient check failed: {err}")
                        self.signer_client = None
                except Exception as e:
                    logger.warning(f"Failed to initialize SignerClient: {e}")
                    self.signer_client = None

            # Test connection by fetching account info
            try:
                # Try to get account info to verify connection
                test_account = await self.account_api.account(
                    by="index",
                    value=str(self.account_index)
                )
                logger.info("Successfully connected and verified account", account_index=self.account_index)
            except Exception as e:
                logger.warning(f"Could not verify account (may need correct account_index): {e}")

            self.connected = True
            logger.info("Connected to Lighter DEX", endpoint=settings.lighter_endpoint)

            # Start WebSocket for real-time updates
            try:
                self.start_websocket()
                logger.info("WebSocket real-time tracking enabled")
            except Exception as e:
                logger.warning("Failed to start WebSocket - continuing without real-time updates", error=str(e))

            return True
        except Exception as e:
            logger.error("Failed to connect to Lighter DEX", error=str(e))
            self.connected = False
            raise

    async def _refresh_auth_token(self):
        try:
            if self.signer_client:
                # Use signer client to create auth token
                auth, err = self.signer_client.create_auth_token_with_expiry(
                    lighter.SignerClient.DEFAULT_10_MIN_AUTH_EXPIRY
                )
                if err:
                    raise Exception(f"Failed to create auth token: {err}")

                self._auth_token = auth
                self._auth_expiry = datetime.utcnow() + timedelta(minutes=9)
                logger.info("Auth token refreshed using SignerClient")
            else:
                # Fallback: create a simple token structure
                self._auth_token = {
                    "api_key": self.api_key,
                    "timestamp": datetime.utcnow().isoformat()
                }
                self._auth_expiry = datetime.utcnow() + timedelta(minutes=9)
                logger.info("Auth token created (fallback mode - read-only)")

        except Exception as e:
            logger.error("Failed to create auth token", error=str(e))
            raise

    async def _ensure_auth(self):
        if not self._auth_token or datetime.utcnow() >= self._auth_expiry:
            await self._refresh_auth_token()

    async def create_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        leverage: int = 1,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None
    ) -> Dict[str, Any]:
        try:
            if not self.signer_client:
                raise Exception("SignerClient not initialized - cannot create orders")

            await self._ensure_auth()

            market_index = self._get_market_index(symbol)
            is_ask = (side.lower() == "sell")

            # Get dynamic decimal info from orderbook API
            from src.utils.price_fetcher import price_fetcher
            decimal_info = await price_fetcher.get_token_decimal_info(symbol)

            if decimal_info:
                # Use API-based multiplier
                multiplier = decimal_info["multiplier"]
                min_base_amount = decimal_info["min_base_amount"]

                # Ensure quantity meets minimum requirement
                if quantity < min_base_amount:
                    logger.warning(
                        f"Quantity {quantity} is below minimum {min_base_amount} for {symbol}, adjusting"
                    )
                    quantity = min_base_amount

                base_amount = int(quantity * multiplier)
            else:
                # Fallback to safe conservative values
                logger.warning(f"Could not get decimal info for {symbol}, using fallback")
                safe_multipliers = {
                    "HYPE": 100,       # HYPE fallback
                    "ASTER": 10,       # ASTER fallback
                    "APEX": 10,        # APEX fallback
                    "ETH": 10000,      # ETH fallback (4 decimals = 10^4)
                    "FF": 10,          # FF fallback
                }
                multiplier = safe_multipliers.get(symbol, 1000)
                base_amount = int(quantity * multiplier)

            # For market orders, we need to estimate execution price using real-time data
            from src.utils.price_fetcher import price_fetcher
            real_price = await price_fetcher.get_token_price(symbol)

            if real_price and real_price > 0:
                estimated_price = real_price
                logger.info(f"Using real-time price for {symbol}: ${real_price}")
            else:
                # Fallback prices if API fails
                fallback_prices = {
                    "ETH": 4500.0,
                    "HYPE": 49.0,
                    "ASTER": 2.2,
                    "APEX": 1.7,
                    "FF": 0.18
                }
                estimated_price = fallback_prices.get(symbol, 1.0)
                logger.warning(f"Using fallback price for {symbol}: ${estimated_price}")

            # Get price decimals for proper scaling
            if decimal_info and decimal_info.get("price_decimals"):
                price_decimals = decimal_info["price_decimals"]
                avg_execution_price = int(estimated_price * (10 ** price_decimals))
            else:
                # Fallback scaling
                avg_execution_price = int(estimated_price * 100)

            logger.info(
                "Creating market order",
                symbol=symbol,
                side=side,
                quantity=quantity,
                leverage=leverage,
                base_amount=base_amount,
                estimated_price=estimated_price,
                avg_execution_price=avg_execution_price
            )

            # Get current order book price for better execution
            orderbook_data = await price_fetcher.get_orderbook(symbol, 1)
            if orderbook_data:
                if is_ask:  # Selling - use bid price
                    ideal_price = orderbook_data.get("bids", [{}])[0].get("price", estimated_price)
                else:  # Buying - use ask price
                    ideal_price = orderbook_data.get("asks", [{}])[0].get("price", estimated_price)
            else:
                ideal_price = estimated_price

            # Calculate acceptable execution price with 5% slippage tolerance
            slippage = 0.05  # 5% slippage (increased from 2% to handle volatile market)
            if is_ask:  # Selling - accept lower price
                acceptable_price = ideal_price * (1 - slippage)
            else:  # Buying - accept higher price
                acceptable_price = ideal_price * (1 + slippage)

            # Scale the price properly
            if decimal_info and decimal_info.get("price_decimals"):
                price_decimals = decimal_info["price_decimals"]
                acceptable_price_scaled = int(acceptable_price * (10 ** price_decimals))
            else:
                acceptable_price_scaled = int(acceptable_price * 100)

            logger.info(
                "Creating market order with slippage",
                symbol=symbol,
                side=side,
                ideal_price=ideal_price,
                acceptable_price=acceptable_price,
                slippage=f"{slippage*100}%"
            )

            # Generate unique order index for tracking
            order_index = self._generate_order_index()

            # Create market order using create_order directly with IOC
            tx, tx_hash, err = await self.signer_client.create_order(
                market_index=market_index,
                client_order_index=order_index,
                base_amount=base_amount,
                price=acceptable_price_scaled,
                is_ask=is_ask,
                order_type=1,  # ORDER_TYPE_MARKET
                time_in_force=0,  # ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL
                order_expiry=0,  # DEFAULT_IOC_EXPIRY
                reduce_only=False
            )

            if err:
                logger.error("Market order failed", error=err)
                raise Exception(f"Market order failed: {err}")

            # Track this order for WebSocket monitoring
            order_id = str(order_index)
            self.track_order(order_id, {
                'symbol': symbol,
                'side': side,
                'quantity': quantity,
                'expected_price': ideal_price,
                'acceptable_price': acceptable_price,
                'order_type': 'market',
                'timestamp': datetime.utcnow().isoformat(),
                'market_index': market_index,
                'base_amount': base_amount
            })

            result = {
                "transaction": tx,
                "tx_hash": tx_hash,
                "order_id": order_id,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "leverage": leverage,
                "timestamp": datetime.utcnow().isoformat()
            }

            # Create stop loss if specified
            if stop_loss:
                await self._create_stop_loss(
                    market_index,
                    base_amount,
                    stop_loss,
                    not is_ask
                )

            # Create take profit if specified
            if take_profit:
                await self._create_take_profit(
                    market_index,
                    base_amount,
                    take_profit,
                    not is_ask
                )

            logger.info("Market order created successfully", tx_hash=tx_hash)
            return result

        except Exception as e:
            logger.error("Failed to create market order", error=str(e))
            raise

    async def create_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        leverage: int = 1
    ) -> Dict[str, Any]:
        try:
            if not self.signer_client:
                raise Exception("SignerClient not initialized - cannot create orders")

            await self._ensure_auth()

            market_index = self._get_market_index(symbol)
            is_ask = (side.lower() == "sell")

            # Get dynamic decimal info from orderbook API
            from src.utils.price_fetcher import price_fetcher
            decimal_info = await price_fetcher.get_token_decimal_info(symbol)

            if decimal_info:
                # Use API-based multiplier
                multiplier = decimal_info["multiplier"]
                min_base_amount = decimal_info["min_base_amount"]
                price_decimals = decimal_info["price_decimals"]

                # Ensure quantity meets minimum requirement
                if quantity < min_base_amount:
                    logger.warning(
                        f"Quantity {quantity} is below minimum {min_base_amount} for {symbol}, adjusting"
                    )
                    quantity = min_base_amount

                base_amount = int(quantity * multiplier)
                price_scaled = int(price * (10 ** price_decimals))
            else:
                # Fallback to safe conservative values
                logger.warning(f"Could not get decimal info for {symbol}, using fallback")
                safe_multipliers = {
                    "HYPE": 100,       # HYPE fallback
                    "ASTER": 10,       # ASTER fallback
                    "APEX": 10,        # APEX fallback
                    "ETH": 10000,      # ETH fallback (4 decimals = 10^4)
                    "FF": 10,          # FF fallback
                }
                multiplier = safe_multipliers.get(symbol, 1000)
                base_amount = int(quantity * multiplier)
                price_scaled = int(price * 100000)  # Fallback price scaling

            logger.info(
                "Creating limit order",
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                base_amount=base_amount,
                price_scaled=price_scaled
            )

            # Generate unique order index for tracking
            order_index = self._generate_order_index()

            tx, tx_hash, err = await self.signer_client.create_order(
                market_index=market_index,
                client_order_index=order_index,
                base_amount=base_amount,
                price=price_scaled,
                is_ask=is_ask,
                order_type=lighter.SignerClient.ORDER_TYPE_LIMIT,
                time_in_force=lighter.SignerClient.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
                reduce_only=0
            )

            if err:
                logger.error("Limit order failed", error=err)
                raise Exception(f"Limit order failed: {err}")

            # Track this order for WebSocket monitoring
            order_id = str(order_index)
            self.track_order(order_id, {
                'symbol': symbol,
                'side': side,
                'quantity': quantity,
                'expected_price': price,
                'order_type': 'limit',
                'timestamp': datetime.utcnow().isoformat(),
                'market_index': market_index,
                'base_amount': base_amount
            })

            logger.info("Limit order created successfully", tx_hash=tx_hash)
            return {
                "transaction": tx,
                "tx_hash": tx_hash,
                "order_id": order_id,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": price,
                "timestamp": datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error("Failed to create limit order", error=str(e))
            raise

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        try:
            if not self.signer_client:
                raise Exception("SignerClient not initialized - cannot cancel orders")

            await self._ensure_auth()

            market_index = self._get_market_index(symbol)

            tx, tx_hash, err = await self.signer_client.cancel_order(
                market_index=market_index,
                order_index=order_id
            )

            if err:
                logger.error("Order cancellation failed", error=err)
                return False

            logger.info("Order cancelled successfully", order_id=order_id, tx_hash=tx_hash)
            return True

        except Exception as e:
            logger.error("Failed to cancel order", error=str(e))
            return False

    async def get_account_info(self, force_refresh: bool = False) -> Dict[str, Any]:
        try:
            if not self.account_api:
                raise Exception("Account API not initialized")

            # Force refresh auth token if requested
            if force_refresh:
                logger.info("Force refreshing account info - clearing any cached data")
                # Refresh auth token to ensure latest data
                await self._refresh_auth_token()

            # Get account information using the Lighter SDK
            account_data = await self.account_api.account(
                by="index",
                value=str(self.account_index)
            )

            # Parse the response - account_data is a DetailedAccounts object with accounts array
            if account_data and hasattr(account_data, 'accounts') and account_data.accounts:
                # Get the first account from the accounts array
                detailed_account = account_data.accounts[0]

                # Extract data from the DetailedAccount object
                positions = []
                orders = []
                balances = {}


                # Try to access positions - check various possible attribute names
                for pos_attr in ['positions', 'position', 'account_positions', 'open_positions']:
                    if hasattr(detailed_account, pos_attr):
                        positions = getattr(detailed_account, pos_attr, [])
                        if positions:
                            logger.info(f"Found positions in attribute: {pos_attr}, count: {len(positions)}")
                            # Log first position details if exists
                            if len(positions) > 0:
                                first_pos = positions[0]
                                logger.info(f"First position type: {type(first_pos)}, data: {first_pos}")
                            break

                # If positions found but empty list, still log it
                if hasattr(detailed_account, 'positions'):
                    pos_data = getattr(detailed_account, 'positions', None)
                    logger.info(f"Positions attribute exists: type={type(pos_data)}, value={pos_data}")

                # Try to access orders - check various possible attribute names
                for ord_attr in ['orders', 'open_orders', 'active_orders']:
                    if hasattr(detailed_account, ord_attr):
                        orders = getattr(detailed_account, ord_attr, [])
                        if orders:
                            logger.info(f"Found orders in attribute: {ord_attr}")
                            break

                # Try to access balances - use available_balance and collateral
                available_balance = getattr(detailed_account, 'available_balance', 0)
                collateral = getattr(detailed_account, 'collateral', 0)
                total_asset_value = getattr(detailed_account, 'total_asset_value', 0)
                cross_asset_value = getattr(detailed_account, 'cross_asset_value', 0)

                # Convert string values to float if necessary
                try:
                    available_balance = float(available_balance) if isinstance(available_balance, str) else available_balance
                    collateral = float(collateral) if isinstance(collateral, str) else collateral
                    total_asset_value = float(total_asset_value) if isinstance(total_asset_value, str) else total_asset_value
                    cross_asset_value = float(cross_asset_value) if isinstance(cross_asset_value, str) else cross_asset_value
                except:
                    pass

                balances = {
                    "available_balance": available_balance,
                    "collateral": collateral,
                    "total_asset_value": total_asset_value,
                    "cross_asset_value": cross_asset_value
                }

                # Get L1 address
                l1_address = getattr(detailed_account, 'l1_address', '')

                logger.info(f"Account details - L1: {l1_address}, Available Balance: {available_balance}, Collateral: {collateral}, Positions: {len(positions)}, Orders: {len(orders)}")

                return {
                    "account_index": self.account_index,
                    "l1_address": l1_address,
                    "balance": balances,
                    "positions": positions,
                    "open_orders": orders,
                    "total_order_count": getattr(detailed_account, 'total_order_count', 0),
                    "pending_order_count": getattr(detailed_account, 'pending_order_count', 0),
                    "timestamp": datetime.utcnow().isoformat(),
                    "connected": self.connected,
                    "network": settings.lighter_network,
                    "status": getattr(detailed_account, 'status', None)
                }
            else:
                # Fallback to mock data if API call fails
                logger.warning("No account data received, using defaults")
                return {
                    "account_index": self.account_index,
                    "balance": 0,
                    "positions": [],
                    "open_orders": [],
                    "timestamp": datetime.utcnow().isoformat(),
                    "connected": self.connected,
                    "network": settings.lighter_network
                }

        except Exception as e:
            logger.error("Failed to get account info", error=str(e))
            # Return basic info even on error
            return {
                "error": str(e),
                "account_index": self.account_index,
                "connected": self.connected,
                "network": settings.lighter_network,
                "timestamp": datetime.utcnow().isoformat()
            }

    async def get_positions(self, symbol: Optional[str] = None) -> List[Dict]:
        try:
            account_info = await self.get_account_info()
            positions = account_info.get("positions", [])

            if symbol:
                positions = [p for p in positions if p.get("symbol") == symbol]

            return positions

        except Exception as e:
            logger.error("Failed to get positions", error=str(e))
            return []

    async def close_position(self, symbol: str) -> bool:
        try:
            positions = await self.get_positions(symbol)

            if not positions:
                logger.warning("No position to close", symbol=symbol)
                return False

            for position in positions:
                quantity = abs(position.get("quantity", 0))
                side = "sell" if position.get("quantity", 0) > 0 else "buy"

                await self.create_market_order(
                    symbol=symbol,
                    side=side,
                    quantity=quantity
                )

            logger.info("Position closed", symbol=symbol)
            return True

        except Exception as e:
            logger.error("Failed to close position", error=str(e))
            return False

    async def close_all_positions(self) -> bool:
        try:
            positions = await self.get_positions()

            for position in positions:
                symbol = position.get("symbol")
                await self.close_position(symbol)

            logger.info("All positions closed")
            return True

        except Exception as e:
            logger.error("Failed to close all positions", error=str(e))
            return False

    async def _create_stop_loss(
        self,
        market_index: int,
        base_amount: int,
        trigger_price: float,
        is_ask: bool
    ):
        try:
            tx, tx_hash, err = await self.client.create_sl_order(
                market_index=market_index,
                client_order_index=self._generate_order_index(),
                base_amount=base_amount,
                trigger_price=trigger_price,
                is_ask=is_ask,
                auth_token=self._auth_token
            )

            if err:
                logger.error("Stop loss creation failed", error=err)
            else:
                logger.info("Stop loss created", trigger_price=trigger_price)

        except Exception as e:
            logger.error("Failed to create stop loss", error=str(e))

    async def _create_take_profit(
        self,
        market_index: int,
        base_amount: int,
        trigger_price: float,
        is_ask: bool
    ):
        try:
            tx, tx_hash, err = await self.client.create_tp_order(
                market_index=market_index,
                client_order_index=self._generate_order_index(),
                base_amount=base_amount,
                trigger_price=trigger_price,
                is_ask=is_ask,
                auth_token=self._auth_token
            )

            if err:
                logger.error("Take profit creation failed", error=err)
            else:
                logger.info("Take profit created", trigger_price=trigger_price)

        except Exception as e:
            logger.error("Failed to create take profit", error=str(e))

    def _get_market_index(self, symbol: str) -> int:
        # Map symbols to market indices - Updated for new trading tokens
        # User requested: APEX, ZEC, STBL, 2Z, 0G, FF, EDEN (7 tokens only)
        market_map = {
            # Core trading tokens (user selected)
            "APEX": 86,    # market_id=86 - User requested
            "ZEC": 90,     # market_id=90 - User requested
            "STBL": 85,    # market_id=85 - User requested
            "2Z": 88,      # market_id=88 - User requested
            "0G": 84,      # market_id=84 - User requested
            "FF": 87,      # market_id=87 - User requested
            "EDEN": 89,    # market_id=89 - User requested

            # Keep other tokens for reference (not actively traded)
            "ETH": 0,      # market_id=0
            "BTC": 1,      # market_id=1
            "SOL": 2,      # market_id=2
            "DOGE": 3,     # market_id=3
            "AVAX": 9,     # market_id=9
            "HYPE": 24,    # market_id=24
            "BNB": 25,     # market_id=25
            "UNI": 30,     # market_id=30
            "USELESS": 66, # market_id=66
            "1000TOSHI": 81, # market_id=81
            "ASTER": 83,   # market_id=83
        }

        result = market_map.get(symbol, 0)
        logger.info(f"Market index mapping: {symbol} -> {result}")
        return result

    def _generate_order_index(self) -> int:
        # Generate unique order index using timestamp
        return int(datetime.utcnow().timestamp() * 1000) % 1000000

    # WebSocket related methods
    def start_websocket(self):
        """Start WebSocket connection for real-time updates"""
        if self.ws_running:
            logger.warning("WebSocket already running")
            return

        try:
            logger.info("Starting WebSocket connection for real-time account updates")

            # Initialize WebSocket client with account subscription
            self.ws_client = lighter.WsClient(
                account_ids=[self.account_index],  # Subscribe to our account
                order_book_ids=[0, 86, 87]  # ETH(0), APEX(86), FF(87)
            )

            # Set up callback handlers
            self.ws_client.on_account_update = self._on_account_update
            self.ws_client.on_order_book_update = self._on_order_book_update

            # Start WebSocket in separate thread to avoid blocking
            self.ws_running = True
            self.ws_thread = threading.Thread(target=self._run_websocket, daemon=True)
            self.ws_thread.start()

            logger.info("WebSocket connection started successfully")

        except Exception as e:
            logger.error("Failed to start WebSocket connection", error=str(e))
            self.ws_running = False

    def _run_websocket(self):
        """Run WebSocket client in separate thread"""
        try:
            logger.info("WebSocket thread started")
            self.ws_client.run()
        except Exception as e:
            logger.error("WebSocket connection error", error=str(e))
        finally:
            self.ws_running = False
            logger.info("WebSocket thread stopped")

    def _on_account_update(self, account_id: int, account_data: dict):
        """Handle real-time account updates including order status changes"""
        try:
            logger.info(
                "Real-time account update received",
                account_id=account_id,
                account_data=json.dumps(account_data, indent=2) if account_data else "None"
            )

            # Process order status updates first
            if account_data and 'orders' in account_data:
                self._process_order_updates(account_data['orders'])

            # Process account data to extract position changes
            if account_data and 'positions' in account_data:
                positions = {}
                for pos in account_data['positions']:
                    symbol = pos.get('symbol')
                    position_size = float(pos.get('position', 0))
                    sign = int(pos.get('sign', 1))
                    actual_position = position_size * sign

                    if symbol and abs(actual_position) > 0.001:
                        positions[symbol] = actual_position

                # Notify all registered callbacks
                for callback in self.account_update_callbacks:
                    try:
                        callback(account_id, account_data)
                    except Exception as e:
                        logger.error("Account update callback error", error=str(e))

                for callback in self.position_update_callbacks:
                    try:
                        callback(positions)
                    except Exception as e:
                        logger.error("Position update callback error", error=str(e))

        except Exception as e:
            logger.error("Error processing account update", error=str(e))

    def _process_order_updates(self, orders_data: list):
        """Process order status updates and categorize order outcomes"""
        try:
            for order in orders_data:
                order_id = order.get('id', str(order.get('client_order_index', '')))
                order_status = order.get('status', 'unknown')
                symbol = order.get('symbol', 'UNKNOWN')
                side = order.get('side', 'unknown')
                quantity = order.get('quantity', 0)
                price = order.get('price', 0)

                # Check if we're tracking this order
                if order_id in self.pending_orders:
                    tracked_order = self.pending_orders[order_id]

                    # Analyze order outcome
                    outcome = self._analyze_order_outcome(order, tracked_order)

                    logger.info(
                        "Order status update received",
                        order_id=order_id,
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                        price=price,
                        status=order_status,
                        outcome=outcome
                    )

                    # Notify callbacks about order status change
                    for callback in self.order_update_callbacks:
                        try:
                            callback({
                                'order_id': order_id,
                                'symbol': symbol,
                                'side': side,
                                'quantity': quantity,
                                'price': price,
                                'status': order_status,
                                'outcome': outcome,
                                'order_data': order,
                                'tracked_data': tracked_order
                            })
                        except Exception as e:
                            logger.error("Order update callback error", error=str(e))

                    # Remove from tracking if order is final
                    if order_status in ['filled', 'cancelled', 'rejected', 'expired']:
                        del self.pending_orders[order_id]
                        logger.info(f"Stopped tracking completed order {order_id}")

        except Exception as e:
            logger.error("Error processing order updates", error=str(e))

    def _analyze_order_outcome(self, order: dict, tracked_order: dict) -> str:
        """Analyze the reason for order outcome (filled/cancelled/margin/slippage)"""
        try:
            order_status = order.get('status', '').lower()

            if order_status == 'filled':
                fill_price = float(order.get('filled_price', order.get('price', 0)))
                expected_price = float(tracked_order.get('expected_price', 0))

                # Check for significant slippage
                if expected_price > 0:
                    slippage = abs(fill_price - expected_price) / expected_price
                    if slippage > 0.05:  # 5% slippage threshold
                        return 'filled_with_high_slippage'
                    else:
                        return 'filled_normally'
                else:
                    return 'filled_normally'

            elif order_status == 'cancelled':
                cancel_reason = order.get('cancel_reason', '').lower()
                error_message = order.get('error', '').lower()

                # Analyze cancellation reason
                if 'margin' in cancel_reason or 'insufficient' in cancel_reason:
                    return 'cancelled_insufficient_margin'
                elif 'slippage' in cancel_reason or 'price' in cancel_reason:
                    return 'cancelled_slippage'
                elif 'timeout' in cancel_reason or 'expired' in cancel_reason:
                    return 'cancelled_timeout'
                elif error_message:
                    if 'margin' in error_message or 'balance' in error_message:
                        return 'cancelled_insufficient_margin'
                    elif 'slippage' in error_message or 'price' in error_message:
                        return 'cancelled_slippage'
                    else:
                        return f'cancelled_error: {error_message}'
                else:
                    return 'cancelled_unknown_reason'

            elif order_status == 'rejected':
                reject_reason = order.get('reject_reason', '').lower()
                if 'margin' in reject_reason or 'balance' in reject_reason:
                    return 'rejected_insufficient_margin'
                elif 'price' in reject_reason or 'slippage' in reject_reason:
                    return 'rejected_slippage'
                else:
                    return f'rejected: {reject_reason}'

            elif order_status == 'expired':
                return 'expired'

            else:
                return f'unknown_status: {order_status}'

        except Exception as e:
            logger.error("Error analyzing order outcome", error=str(e))
            return 'analysis_error'

    def _on_order_book_update(self, market_id: int, order_book_data: dict):
        """Handle real-time order book updates"""
        try:
            logger.debug(
                "Real-time order book update",
                market_id=market_id,
                has_data=bool(order_book_data)
            )
            # Order book updates can be used for price monitoring if needed
        except Exception as e:
            logger.error("Error processing order book update", error=str(e))

    def add_account_update_callback(self, callback: Callable):
        """Register callback for account updates"""
        self.account_update_callbacks.append(callback)
        logger.info("Account update callback registered")

    def add_position_update_callback(self, callback: Callable):
        """Register callback for position updates"""
        self.position_update_callbacks.append(callback)
        logger.info("Position update callback registered")

    def add_order_update_callback(self, callback: Callable):
        """Register callback for order status updates"""
        self.order_update_callbacks.append(callback)
        logger.info("Order update callback registered")

    def track_order(self, order_id: str, order_info: dict):
        """Start tracking an order for status updates"""
        self.pending_orders[order_id] = order_info
        logger.info(f"Now tracking order {order_id}", order_info=order_info)

    def stop_websocket(self):
        """Stop WebSocket connection"""
        if not self.ws_running:
            return

        logger.info("Stopping WebSocket connection")
        self.ws_running = False

        if self.ws_client:
            try:
                # WebSocket client should handle graceful shutdown
                pass
            except Exception as e:
                logger.error("Error stopping WebSocket", error=str(e))

        if self.ws_thread and self.ws_thread.is_alive():
            self.ws_thread.join(timeout=5)

        logger.info("WebSocket connection stopped")

    async def get_account_inactive_orders(self, limit: int = 100, market_id: int = None) -> dict:
        """Get account's inactive orders (order history)"""
        try:
            # Ensure we have a proper auth token from SignerClient
            if not self.signer_client:
                logger.error("SignerClient not initialized - cannot get inactive orders")
                return {"orders": [], "error": "SignerClient not available"}

            # Create fresh auth token for this request
            auth_token, err = self.signer_client.create_auth_token_with_expiry(
                lighter.SignerClient.DEFAULT_10_MIN_AUTH_EXPIRY
            )

            if err:
                logger.error(f"Failed to create auth token: {err}")
                return {"orders": [], "error": f"Auth token creation failed: {err}"}

            params = {
                "account_index": self.account_index,
                "limit": min(limit, 100),  # Max 100 per API
                "auth": auth_token  # Use SignerClient generated auth token
            }

            # Add market filter if specified
            if market_id is not None:
                params["market_id"] = market_id

            logger.info(f"Calling accountInactiveOrders with SignerClient auth token")

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/api/v1/accountInactiveOrders",
                    params=params
                ) as response:
                    logger.info(f"accountInactiveOrders API response status: {response.status}")
                    if response.status == 200:
                        data = await response.json()
                        logger.info(f"Successfully retrieved {len(data.get('orders', []))} inactive orders")
                        logger.debug(f"Response data: {data}")
                        return data
                    else:
                        error_text = await response.text()
                        logger.error(f"Failed to get inactive orders: {response.status} - {error_text}")
                        return {"orders": [], "error": f"HTTP {response.status}: {error_text}"}

        except Exception as e:
            logger.error("Failed to get account inactive orders", error=str(e))
            return {"orders": [], "error": str(e)}

    async def get_recent_trades_by_symbol(self, hours: int = 24) -> dict:
        """Get recent trades grouped by symbol for the last N hours"""
        try:
            # Get all recent orders
            orders_data = await self.get_account_inactive_orders(limit=100)
            orders = orders_data.get("orders", [])

            if not orders:
                return {"trades_by_symbol": {}, "total_trades": 0}

            # Filter trades from last N hours and group by symbol
            from datetime import datetime, timedelta
            cutoff_time = datetime.now() - timedelta(hours=hours)
            trades_by_symbol = {}
            total_trades = 0

            for order in orders:
                try:
                    # Parse timestamp (adjust format as needed)
                    order_time_str = order.get("created_at", order.get("timestamp", ""))
                    if not order_time_str:
                        continue

                    # Parse different timestamp formats
                    order_time = None
                    for fmt in ["%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"]:
                        try:
                            order_time = datetime.strptime(order_time_str, fmt)
                            break
                        except ValueError:
                            continue

                    if not order_time or order_time < cutoff_time:
                        continue

                    # Extract trade info
                    symbol = order.get("symbol", "UNKNOWN")
                    side = order.get("side", "")
                    status = order.get("status", "")
                    filled_qty = float(order.get("filled_quantity", 0))
                    filled_price = float(order.get("filled_price", 0))

                    # Only count filled orders
                    if status.lower() == "filled" and filled_qty > 0:
                        if symbol not in trades_by_symbol:
                            trades_by_symbol[symbol] = []

                        trades_by_symbol[symbol].append({
                            "side": side,
                            "quantity": filled_qty,
                            "price": filled_price,
                            "timestamp": order_time_str,
                            "order_id": order.get("id", "")
                        })
                        total_trades += 1

                except Exception as e:
                    logger.warning(f"Error processing order: {e}")
                    continue

            logger.info(f"Found {total_trades} trades across {len(trades_by_symbol)} symbols in last {hours}h")
            return {
                "trades_by_symbol": trades_by_symbol,
                "total_trades": total_trades,
                "hours": hours
            }

        except Exception as e:
            logger.error("Failed to get recent trades by symbol", error=str(e))
            return {"trades_by_symbol": {}, "total_trades": 0, "error": str(e)}


# Singleton instance
lighter_client = LighterClient()