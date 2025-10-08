"""
Real-time price fetcher from Lighter DEX order book
"""

import aiohttp
import asyncio
from typing import Dict, Optional
import structlog

logger = structlog.get_logger()


class LighterPriceFetcher:
    def __init__(self):
        self.base_url = "https://mainnet.zklighter.elliot.ai/api/v1"
        self.price_cache = {}
        self.cache_ttl = 30  # Cache for 30 seconds
        self.last_fetch_time = {}

    async def get_orderbook_data(self) -> Optional[Dict]:
        """Fetch orderbook data from Lighter DEX API"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/orderBookDetails") as response:
                    if response.status == 200:
                        data = await response.json()
                        return data
                    else:
                        logger.error("Failed to fetch orderbook", status=response.status)
                        return None

        except Exception as e:
            logger.error("Failed to fetch orderbook data", error=str(e))
            return None

    async def get_token_price(self, symbol: str) -> Optional[float]:
        """Get current price for a specific token"""
        try:
            # Check cache first
            import time
            current_time = time.time()

            if (symbol in self.price_cache and
                symbol in self.last_fetch_time and
                current_time - self.last_fetch_time[symbol] < self.cache_ttl):
                return self.price_cache[symbol]

            # Fetch fresh data
            orderbook_data = await self.get_orderbook_data()
            if not orderbook_data:
                return None

            # Find token in order book details
            for token_data in orderbook_data.get("order_book_details", []):
                if token_data.get("symbol") == symbol:
                    price = float(token_data.get("last_trade_price", 0))

                    # Update cache
                    self.price_cache[symbol] = price
                    self.last_fetch_time[symbol] = current_time

                    logger.debug(f"Fetched price for {symbol}: ${price}")
                    return price

            logger.warning(f"Token {symbol} not found in orderbook")
            return None

        except Exception as e:
            logger.error("Failed to get token price", symbol=symbol, error=str(e))
            return None

    async def get_all_prices(self) -> Dict[str, float]:
        """Get prices for all available tokens"""
        try:
            orderbook_data = await self.get_orderbook_data()
            if not orderbook_data:
                return {}

            prices = {}
            for token_data in orderbook_data.get("order_book_details", []):
                symbol = token_data.get("symbol")
                price = float(token_data.get("last_trade_price", 0))
                if symbol and price > 0:
                    prices[symbol] = price

            # Update cache
            import time
            current_time = time.time()
            self.price_cache.update(prices)
            for symbol in prices:
                self.last_fetch_time[symbol] = current_time

            logger.info("Fetched all prices", count=len(prices), prices=prices)
            return prices

        except Exception as e:
            logger.error("Failed to get all prices", error=str(e))
            return {}

    async def get_market_summary(self, symbol: str) -> Optional[Dict]:
        """Get comprehensive market data for a token"""
        try:
            orderbook_data = await self.get_orderbook_data()
            if not orderbook_data:
                return None

            for token_data in orderbook_data.get("order_book_details", []):
                if token_data.get("symbol") == symbol:
                    return {
                        "symbol": symbol,
                        "price": float(token_data.get("last_trade_price", 0)),
                        "daily_trades": int(token_data.get("daily_trades_count", 0)),
                        "daily_volume": float(token_data.get("daily_base_token_volume", 0)),
                        "quote_volume": float(token_data.get("daily_quote_token_volume", 0)),
                        "market_id": token_data.get("market_id"),
                        "size_decimals": token_data.get("size_decimals"),
                        "supported_size_decimals": token_data.get("supported_size_decimals"),
                        "min_base_amount": float(token_data.get("min_base_amount", 0)),
                        "price_decimals": token_data.get("price_decimals"),
                        "supported_price_decimals": token_data.get("supported_price_decimals"),
                    }

            return None

        except Exception as e:
            logger.error("Failed to get market summary", symbol=symbol, error=str(e))
            return None

    async def get_token_decimal_info(self, symbol: str) -> Optional[Dict]:
        """Get decimal and scaling information for a token"""
        try:
            orderbook_data = await self.get_orderbook_data()
            if not orderbook_data:
                return None

            for token_data in orderbook_data.get("order_book_details", []):
                if token_data.get("symbol") == symbol:
                    size_decimals = token_data.get("size_decimals", 6)
                    min_base_amount = float(token_data.get("min_base_amount", 0.001))

                    # Calculate proper multiplier based on size_decimals
                    multiplier = 10 ** size_decimals

                    logger.info(
                        f"Token {symbol} decimal info",
                        size_decimals=size_decimals,
                        min_base_amount=min_base_amount,
                        calculated_multiplier=multiplier
                    )

                    return {
                        "symbol": symbol,
                        "size_decimals": size_decimals,
                        "min_base_amount": min_base_amount,
                        "multiplier": multiplier,
                        "market_id": token_data.get("market_id"),
                        "price_decimals": token_data.get("price_decimals", 2)
                    }

            return None

        except Exception as e:
            logger.error("Failed to get token decimal info", symbol=symbol, error=str(e))
            return None

    async def get_leverage_info(self, symbol: str) -> Optional[Dict]:
        """Get leverage and margin information for a token"""
        try:
            orderbook_data = await self.get_orderbook_data()
            if not orderbook_data:
                return None

            for token_data in orderbook_data.get("order_book_details", []):
                if token_data.get("symbol") == symbol:
                    min_initial_margin_fraction = token_data.get("min_initial_margin_fraction", 3333)

                    # Calculate maximum leverage: max_leverage = 10000 / min_initial_margin_fraction
                    max_leverage = 10000 / min_initial_margin_fraction

                    # Set minimum leverage to 3x
                    min_leverage = 3

                    # Adjust if max leverage is less than min leverage
                    if max_leverage < min_leverage:
                        logger.warning(
                            f"Token {symbol} max leverage ({max_leverage:.1f}x) is less than minimum (3x), using max available",
                            symbol=symbol,
                            max_leverage=max_leverage,
                            min_initial_margin_fraction=min_initial_margin_fraction
                        )
                        min_leverage = max_leverage

                    logger.info(
                        f"Token {symbol} leverage info",
                        min_initial_margin_fraction=min_initial_margin_fraction,
                        max_leverage=max_leverage,
                        min_leverage=min_leverage
                    )

                    return {
                        "symbol": symbol,
                        "min_initial_margin_fraction": min_initial_margin_fraction,
                        "max_leverage": max_leverage,
                        "min_leverage": min_leverage,
                        "initial_margin_percentage": min_initial_margin_fraction / 100
                    }

            return None

        except Exception as e:
            logger.error("Failed to get leverage info", symbol=symbol, error=str(e))
            return None

    async def get_all_leverage_info(self) -> Dict[str, Dict]:
        """Get leverage information for all available tokens"""
        try:
            orderbook_data = await self.get_orderbook_data()
            if not orderbook_data:
                return {}

            leverage_info = {}
            for token_data in orderbook_data.get("order_book_details", []):
                symbol = token_data.get("symbol")
                if symbol:
                    min_initial_margin_fraction = token_data.get("min_initial_margin_fraction", 3333)
                    max_leverage = 10000 / min_initial_margin_fraction
                    min_leverage = 3

                    if max_leverage < min_leverage:
                        min_leverage = max_leverage

                    leverage_info[symbol] = {
                        "min_initial_margin_fraction": min_initial_margin_fraction,
                        "max_leverage": max_leverage,
                        "min_leverage": min_leverage,
                        "initial_margin_percentage": min_initial_margin_fraction / 100
                    }

            logger.info("Fetched all leverage info", count=len(leverage_info), symbols=list(leverage_info.keys()))
            return leverage_info

        except Exception as e:
            logger.error("Failed to get all leverage info", error=str(e))
            return {}

    async def get_orderbook(self, symbol: str, depth: int = 1) -> Optional[Dict]:
        """Get orderbook data for a specific symbol with bid/ask prices"""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Get market ID for the symbol
                market_summary = await self.get_market_summary(symbol)
                if not market_summary:
                    logger.warning(f"Could not find market summary for {symbol}")
                    return None

                market_id = market_summary.get("market_id")
                if market_id is None:
                    logger.warning(f"No market ID found for {symbol}")
                    return None

                # Fetch orderbook data
                url = f"https://mainnet.zklighter.elliot.ai/api/v1/order_book_orders?market_index={market_id}&depth={depth}"
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()

                        # Parse bids and asks
                        bids = []
                        asks = []

                        for bid in data.get("bids", []):
                            bids.append({
                                "price": float(bid.get("price", 0)),
                                "size": float(bid.get("size", 0))
                            })

                        for ask in data.get("asks", []):
                            asks.append({
                                "price": float(ask.get("price", 0)),
                                "size": float(ask.get("size", 0))
                            })

                        return {
                            "symbol": symbol,
                            "bids": bids,
                            "asks": asks,
                            "market_id": market_id
                        }
                    else:
                        logger.error(f"Failed to fetch orderbook for {symbol}, status: {response.status}")
                        return None

        except Exception as e:
            logger.error("Failed to get orderbook", symbol=symbol, error=str(e))
            return None


# Singleton instance
price_fetcher = LighterPriceFetcher()