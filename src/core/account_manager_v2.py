"""
Improved Multi-account manager with better error handling and thread safety
"""

import json
import os
import asyncio
from typing import Dict, Optional, List, Any
from threading import Lock
import structlog
from config.settings import get_settings
import lighter
from datetime import datetime, timedelta
import time
import random

logger = structlog.get_logger()
settings = get_settings()


class AccountManagerV2:
    def __init__(self):
        self.accounts = {}  # Dict[account_index, LighterAccountClient]
        self.account_configs = {}  # Dict[account_index, account_config]
        self.lock = Lock()  # Thread safety for account operations
        self.connection_retries = {}  # Track connection retry attempts
        self.max_retries = 3
        self.load_accounts()

    def load_accounts(self):
        """Load account configurations from accounts.json with validation"""
        with self.lock:
            try:
                config_path = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                    'config',
                    'accounts.json'
                )

                if not os.path.exists(config_path):
                    logger.warning(f"Accounts config not found at {config_path}, using default from .env")
                    self._load_default_account()
                    return

                with open(config_path, 'r') as f:
                    config = json.load(f)

                # Validate and load accounts
                for account in config.get('accounts', []):
                    if self._validate_account_config(account):
                        if account.get('active', True):
                            account_index = account['account_index']
                            self.account_configs[account_index] = account
                            self.connection_retries[account_index] = 0
                            logger.info(
                                "Loaded account configuration",
                                account_index=account_index,
                                name=account.get('name', 'Unknown')
                            )
                    else:
                        logger.error(f"Invalid account configuration: {account}")

                if not self.account_configs:
                    logger.warning("No valid accounts found, loading default")
                    self._load_default_account()

            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in accounts config: {e}")
                self._load_default_account()
            except Exception as e:
                logger.error(f"Failed to load accounts: {e}")
                self._load_default_account()

    def _load_default_account(self):
        """Load default account from environment variables"""
        default_config = {
            "account_index": settings.lighter_account_index,
            "api_key_index": settings.lighter_api_key_index,
            "api_key": settings.lighter_api_key,
            "api_secret": settings.lighter_api_secret,
            "name": "Default Account",
            "active": True,
            "allowed_symbols": []
        }

        if self._validate_account_config(default_config):
            self.account_configs[settings.lighter_account_index] = default_config
            self.connection_retries[settings.lighter_account_index] = 0

    def _validate_account_config(self, config: Dict) -> bool:
        """Validate account configuration"""
        required_fields = ['account_index', 'api_key_index', 'api_key', 'api_secret']

        for field in required_fields:
            if field not in config:
                logger.error(f"Missing required field '{field}' in account config")
                return False

        # Validate data types
        if not isinstance(config['account_index'], int):
            logger.error("account_index must be an integer")
            return False

        if not isinstance(config['api_key_index'], int):
            logger.error("api_key_index must be an integer")
            return False

        return True

    async def get_client(self, account_index: int) -> Optional[Any]:
        """Get or create a LighterClient for specific account with retry logic"""
        if account_index not in self.account_configs:
            logger.error(f"Account {account_index} not found in configuration")
            return None

        # Check if client exists and is connected
        if account_index in self.accounts:
            client = self.accounts[account_index]
            if client and client.connected:
                return client
            else:
                logger.info(f"Client for account {account_index} disconnected, reconnecting...")

        # Check retry limit
        if self.connection_retries.get(account_index, 0) >= self.max_retries:
            logger.error(f"Max retries exceeded for account {account_index}")
            return None

        # Try to create/reconnect client
        try:
            await self._create_client(account_index)
            self.connection_retries[account_index] = 0
            return self.accounts.get(account_index)
        except Exception as e:
            self.connection_retries[account_index] = self.connection_retries.get(account_index, 0) + 1
            logger.error(f"Failed to create client for account {account_index}: {e}")
            return None

    async def _create_client(self, account_index: int):
        """Create a new LighterClient for specific account with proper cleanup"""
        with self.lock:
            try:
                # Clean up existing client if any
                if account_index in self.accounts:
                    old_client = self.accounts[account_index]
                    if hasattr(old_client, 'stop_websocket'):
                        try:
                            old_client.stop_websocket()
                        except:
                            pass
                    del self.accounts[account_index]

                config = self.account_configs[account_index]
                client = LighterAccountClientV2(
                    api_key=config['api_key'],
                    api_secret=config['api_secret'],
                    account_index=account_index,
                    api_key_index=config['api_key_index']
                )

                await client.connect()
                self.accounts[account_index] = client

                logger.info(
                    "Created client for account",
                    account_index=account_index,
                    name=config.get('name', 'Unknown')
                )

            except Exception as e:
                logger.error(
                    "Failed to create client for account",
                    account_index=account_index,
                    error=str(e)
                )
                # Clean up on failure
                if account_index in self.accounts:
                    del self.accounts[account_index]
                raise

    def get_account_config(self, account_index: int) -> Optional[Dict]:
        """Get configuration for specific account (thread-safe)"""
        with self.lock:
            return self.account_configs.get(account_index, {}).copy()

    def get_all_accounts(self) -> List[Dict]:
        """Get all account configurations (thread-safe)"""
        with self.lock:
            return [config.copy() for config in self.account_configs.values()]

    def is_symbol_allowed(self, account_index: int, symbol: str) -> bool:
        """Check if symbol is allowed for specific account"""
        config = self.get_account_config(account_index)
        if not config:
            return False

        allowed_symbols = config.get('allowed_symbols', [])
        # If allowed_symbols is empty, all symbols are allowed
        if not allowed_symbols:
            return True

        return symbol in allowed_symbols

    async def close_all_clients(self):
        """Close all client connections properly"""
        tasks = []

        with self.lock:
            for account_index, client in list(self.accounts.items()):
                tasks.append(self._close_client_async(account_index, client))

        # Wait for all closures to complete
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        with self.lock:
            self.accounts.clear()
            self.connection_retries.clear()

    async def _close_client_async(self, account_index: int, client):
        """Async helper to close a client"""
        try:
            if hasattr(client, 'stop_websocket'):
                client.stop_websocket()
            logger.info(f"Closed client for account {account_index}")
        except Exception as e:
            logger.error(f"Error closing client for account {account_index}: {e}")

    def reset_retry_count(self, account_index: int):
        """Reset retry count for an account"""
        with self.lock:
            self.connection_retries[account_index] = 0

    async def health_check(self) -> Dict[int, bool]:
        """Check health status of all accounts"""
        health_status = {}

        for account_index in self.account_configs.keys():
            try:
                client = await self.get_client(account_index)
                if client and client.connected:
                    # Try a simple operation to verify connection
                    info = await client.get_account_info()
                    health_status[account_index] = bool(info and not info.get('error'))
                else:
                    health_status[account_index] = False
            except:
                health_status[account_index] = False

        return health_status


class LighterAccountClientV2:
    """Improved Lighter client for a specific account with better error handling"""

    def __init__(self, api_key: str, api_secret: str, account_index: int, api_key_index: int):
        self.api_client = None
        self.signer_client = None
        self.account_api = None
        self.ws_client = None
        self.api_key = api_key
        self.api_secret = api_secret
        self.account_index = account_index
        self.api_key_index = api_key_index
        self.connected = False
        self._auth_token = None
        self._auth_expiry = None
        self.base_url = settings.lighter_endpoint
        self.ws_running = False
        self.ws_thread = None
        self.pending_orders = {}
        self._position_lock = asyncio.Lock()  # Async lock for position updates
        # Nonce management
        self._nonce = None
        self._nonce_lock = asyncio.Lock()  # Lock for nonce updates
        self._last_order_index = None

    async def get_next_nonce(self):
        """Get next nonce from API"""
        async with self._nonce_lock:
            try:
                # Use the transaction API to get next nonce
                import aiohttp
                import json

                url = f"{self.base_url}/api/v1/accounts/{self.account_index}/next_nonce"
                headers = {
                    "Authorization": f"Bearer {self._auth_token}" if self._auth_token else "",
                    "Content-Type": "application/json"
                }

                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            self._nonce = data.get("next_nonce", 1)
                            logger.info(f"Got next nonce for account {self.account_index}: {self._nonce}")
                        else:
                            # Fallback to timestamp-based nonce
                            self._nonce = int(time.time() * 1000) % 1000000
                            logger.warning(f"Failed to get nonce from API, using fallback: {self._nonce}")
            except Exception as e:
                logger.error(f"Error getting next nonce: {e}")
                # Fallback to timestamp-based nonce
                self._nonce = int(time.time() * 1000) % 1000000

            return self._nonce

    async def increment_nonce(self):
        """Increment nonce for next order"""
        async with self._nonce_lock:
            if self._nonce is None:
                await self.get_next_nonce()
            else:
                self._nonce += 1
            return self._nonce

    async def connect(self):
        """Connect to Lighter DEX with timeout"""
        try:
            # Set connection timeout
            connect_timeout = 5  # seconds - reduced for faster response on limited VPS

            async def _connect():
                # Initialize API client for read operations
                self.api_client = lighter.ApiClient()
                self.account_api = lighter.AccountApi(self.api_client)

                # Initialize signer client for write operations
                if self.api_secret:
                    try:
                        self.signer_client = lighter.SignerClient(
                            url=settings.lighter_endpoint,
                            private_key=self.api_secret,
                            account_index=self.account_index,
                            api_key_index=self.api_key_index,
                        )

                        err = self.signer_client.check_client()
                        if err:
                            logger.warning(f"SignerClient check failed for account {self.account_index}: {err}")
                            # Don't fail completely, allow read-only mode
                    except Exception as e:
                        logger.warning(f"Failed to initialize SignerClient for account {self.account_index}: {e}")
                        # Continue in read-only mode

                self.connected = True
                logger.info(
                    "Connected to Lighter DEX",
                    account_index=self.account_index,
                    endpoint=settings.lighter_endpoint,
                    has_signer=bool(self.signer_client)
                )

            await asyncio.wait_for(_connect(), timeout=connect_timeout)
            return True

        except asyncio.TimeoutError:
            logger.error(f"Connection timeout for account {self.account_index}")
            self.connected = False
            raise Exception("Connection timeout")
        except Exception as e:
            logger.error(
                "Failed to connect to Lighter DEX",
                account_index=self.account_index,
                error=str(e)
            )
            self.connected = False
            raise

    async def create_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        leverage: int = 1
    ) -> Dict[str, Any]:
        """Create market order with improved error handling"""
        if not self.connected:
            raise Exception(f"Client not connected for account {self.account_index}")

        if not self.signer_client:
            raise Exception(f"SignerClient not initialized for account {self.account_index} - cannot create orders")

        try:
            market_index = self._get_market_index(symbol)
            is_ask = (side.lower() == "sell")

            # Get decimal info with fallback
            decimal_info = await self._get_decimal_info_safe(symbol)

            multiplier = decimal_info["multiplier"]
            min_base_amount = decimal_info["min_base_amount"]
            price_decimals = decimal_info["price_decimals"]

            # Ensure quantity meets minimum
            if quantity < min_base_amount:
                logger.warning(
                    f"Adjusting quantity from {quantity} to minimum {min_base_amount} for {symbol}"
                )
                quantity = min_base_amount

            base_amount = int(quantity * multiplier)

            # Get price with fallback
            estimated_price = await self._get_price_safe(symbol)

            # Calculate acceptable execution price with slippage
            slippage = 0.05  # 5% slippage
            if is_ask:
                acceptable_price = estimated_price * (1 - slippage)
            else:
                acceptable_price = estimated_price * (1 + slippage)

            acceptable_price_scaled = int(acceptable_price * (10 ** price_decimals))

            logger.info(
                "Creating market order",
                account_index=self.account_index,
                api_key_index=self.api_key_index,
                symbol=symbol,
                side=side,
                quantity=quantity,
                base_amount=base_amount,
                estimated_price=estimated_price,
                has_signer=bool(self.signer_client)
            )

            # Generate unique order index
            order_index = self._generate_order_index()

            # Get or increment nonce
            if self._nonce is None:
                await self.get_next_nonce()
            else:
                await self.increment_nonce()

            logger.info(f"Using nonce {self._nonce} for order index {order_index} on account {self.account_index}")

            # Create market order with timeout
            order_timeout = 30  # seconds

            async def _create_order():
                # Check and reinitialize signer if needed
                if not self.signer_client:
                    logger.warning(f"SignerClient not initialized for account {self.account_index}, attempting to reinitialize")
                    try:
                        self.signer_client = lighter.SignerClient(
                            url=settings.lighter_endpoint,
                            private_key=self.api_secret,
                            account_index=self.account_index,
                            api_key_index=self.api_key_index,
                        )
                        err = self.signer_client.check_client()
                        if err:
                            raise Exception(f"SignerClient check failed: {err}")
                    except Exception as e:
                        logger.error(f"Failed to reinitialize SignerClient: {e}")
                        raise

                return await self.signer_client.create_order(
                    market_index=market_index,
                    client_order_index=order_index,
                    base_amount=base_amount,
                    price=acceptable_price_scaled,
                    is_ask=is_ask,
                    order_type=1,  # ORDER_TYPE_MARKET
                    time_in_force=0,  # IOC
                    order_expiry=0,
                    reduce_only=False
                )

            tx, tx_hash, err = await asyncio.wait_for(_create_order(), timeout=order_timeout)

            if err:
                logger.error(f"Market order failed for account {self.account_index}: {err}")
                raise Exception(f"Market order failed: {err}")

            result = {
                "tx_hash": tx_hash,
                "order_id": str(order_index),
                "account_index": self.account_index,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "leverage": leverage,
                "timestamp": datetime.utcnow().isoformat(),
                "code": 200
            }

            logger.info(
                "Market order created successfully",
                account_index=self.account_index,
                tx_hash=tx_hash
            )
            return result

        except asyncio.TimeoutError:
            logger.error(f"Order timeout for account {self.account_index}")
            raise Exception("Order creation timeout")
        except Exception as e:
            logger.error(
                "Failed to create market order",
                account_index=self.account_index,
                symbol=symbol,
                error=str(e)
            )
            raise

    async def _get_decimal_info_safe(self, symbol: str) -> Dict:
        """Get decimal info with fallback values"""
        try:
            # Try to import price_fetcher if available
            from src.utils.price_fetcher import price_fetcher
            info = await price_fetcher.get_token_decimal_info(symbol)
            if info:
                return info
        except:
            pass

        # Fallback values
        fallback_info = {
            "BTC": {"multiplier": 100000000, "min_base_amount": 0.0001, "price_decimals": 2},
            "ETH": {"multiplier": 10000, "min_base_amount": 0.001, "price_decimals": 2},
            "BNB": {"multiplier": 1000, "min_base_amount": 0.01, "price_decimals": 2},
            "SOL": {"multiplier": 1000, "min_base_amount": 0.01, "price_decimals": 2},
        }

        return fallback_info.get(symbol, {
            "multiplier": 1000,
            "min_base_amount": 0.001,
            "price_decimals": 2
        })

    async def _get_price_safe(self, symbol: str) -> float:
        """Get price with fallback values"""
        try:
            # Try to import price_fetcher if available
            from src.utils.price_fetcher import price_fetcher
            price = await price_fetcher.get_token_price(symbol)
            if price and price > 0:
                return price
        except:
            pass

        # Fallback prices
        fallback_prices = {
            "BTC": 70000.0,
            "ETH": 4500.0,
            "BNB": 600.0,
            "SOL": 150.0
        }

        return fallback_prices.get(symbol, 100.0)

    async def get_account_info(self) -> Dict[str, Any]:
        """Get account information with error handling"""
        if not self.connected:
            return {
                "error": "Not connected",
                "account_index": self.account_index,
                "timestamp": datetime.utcnow().isoformat()
            }

        try:
            if not self.account_api:
                raise Exception(f"Account API not initialized for account {self.account_index}")

            # Set timeout for API call
            api_timeout = 10  # seconds

            async def _get_account():
                return await self.account_api.account(
                    by="index",
                    value=str(self.account_index)
                )

            account_data = await asyncio.wait_for(_get_account(), timeout=api_timeout)

            if account_data and hasattr(account_data, 'accounts') and account_data.accounts:
                detailed_account = account_data.accounts[0]

                # Extract positions
                positions = []
                for pos_attr in ['positions', 'position', 'account_positions']:
                    if hasattr(detailed_account, pos_attr):
                        positions = getattr(detailed_account, pos_attr, [])
                        break

                # Extract balance
                available_balance = getattr(detailed_account, 'available_balance', 0)
                collateral = getattr(detailed_account, 'collateral', 0)

                try:
                    available_balance = float(available_balance) if isinstance(available_balance, str) else available_balance
                    collateral = float(collateral) if isinstance(collateral, str) else collateral
                except:
                    available_balance = 0
                    collateral = 0

                return {
                    "account_index": self.account_index,
                    "balance": {
                        "available_balance": available_balance,
                        "collateral": collateral
                    },
                    "positions": positions,
                    "timestamp": datetime.utcnow().isoformat()
                }

            # Return empty data if no account found
            return {
                "account_index": self.account_index,
                "balance": {"available_balance": 0, "collateral": 0},
                "positions": [],
                "timestamp": datetime.utcnow().isoformat()
            }

        except asyncio.TimeoutError:
            logger.error(f"API timeout for account {self.account_index}")
            return {
                "error": "API timeout",
                "account_index": self.account_index,
                "timestamp": datetime.utcnow().isoformat()
            }
        except Exception as e:
            logger.error(
                "Failed to get account info",
                account_index=self.account_index,
                error=str(e)
            )
            return {
                "error": str(e),
                "account_index": self.account_index,
                "timestamp": datetime.utcnow().isoformat()
            }

    async def get_positions(self) -> List[Dict]:
        """Get current positions with position lock"""
        async with self._position_lock:
            try:
                account_info = await self.get_account_info()
                return account_info.get("positions", [])
            except Exception as e:
                logger.error(
                    "Failed to get positions",
                    account_index=self.account_index,
                    error=str(e)
                )
                return []

    def _get_market_index(self, symbol: str) -> int:
        """Map symbols to market indices"""
        market_map = {
            "BTC": 1,
            "ETH": 0,
            "BNB": 25,
            "SOL": 2,
        }
        return market_map.get(symbol, 0)

    def _generate_order_index(self) -> int:
        """Generate unique order index (12 digits max as per Lighter requirements)"""
        import time
        import random

        if self._last_order_index is None:
            # First order: use random number less than 12 digits
            self._last_order_index = random.randint(100000, 999999999999)  # Max 12 digits
        else:
            # Subsequent orders: increment by 1
            self._last_order_index += 1

        # Ensure it stays within 12 digits
        if self._last_order_index >= 1000000000000:  # 12 digits limit
            self._last_order_index = random.randint(100000, 999999999999)

        return self._last_order_index

    def stop_websocket(self):
        """Stop WebSocket connection if exists"""
        try:
            self.ws_running = False
            if self.ws_thread and self.ws_thread.is_alive():
                self.ws_thread.join(timeout=2)
        except:
            pass


# Singleton instance
account_manager_v2 = AccountManagerV2()