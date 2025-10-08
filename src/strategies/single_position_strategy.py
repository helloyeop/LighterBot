"""
Single Direction Position Strategy
각 계정은 각 토큰에 대해 단일 방향(long 또는 short)의 포지션만 유지
"""

import asyncio
import random
from typing import Dict, List, Optional, Literal
from datetime import datetime, timedelta
import structlog
from dataclasses import dataclass, field
from enum import Enum
from src.utils.price_fetcher import price_fetcher

logger = structlog.get_logger()


class PositionDirection(Enum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"  # 포지션 없음


@dataclass
class TokenPositionConfig:
    """각 토큰의 포지션 설정"""
    symbol: str
    direction: PositionDirection  # 이 토큰에 대한 포지션 방향
    target_size_usd: float  # 목표 포지션 크기 (USD)
    min_trade_size: float  # 최소 거래 단위
    max_position_usd: float = 100.0  # 최대 포지션 크기
    leverage: int = 3  # 사용할 레버리지
    quantity_decimals: int = 4


@dataclass
class TradingStats:
    """거래 통계"""
    daily_volume: float = 0.0
    daily_trades: int = 0
    daily_pnl: float = 0.0
    current_positions: Dict[str, float] = field(default_factory=dict)
    last_trade_time: Optional[datetime] = None
    trades_this_minute: int = 0
    minute_reset_time: datetime = field(default_factory=datetime.now)


class SinglePositionStrategy:
    def __init__(self, lighter_client, settings):
        self.client = lighter_client
        self.settings = settings
        self.stats = TradingStats()
        self.running = False

        # Rate limiting
        self.rate_limit_per_minute = 5  # 분당 최대 거래 수

        # 포지션 설정 (예시 - 실제로는 계정별로 다르게 설정)
        # 이 부분을 환경변수나 설정 파일로 관리할 수 있습니다
        self.position_configs = self._initialize_position_configs()

        # 현재 포지션 추적
        self.current_positions = {}

        # WebSocket 이벤트 추적
        self.pending_verifications = {}
        self.verification_events = {}

    def _initialize_position_configs(self) -> Dict[str, TokenPositionConfig]:
        """
        포지션 설정 초기화
        실제 운영시에는 환경변수나 설정 파일에서 읽어올 수 있음
        """
        # 예시: 다양한 방향의 포지션 설정
        configs = {
            # Long positions
            "APEX": TokenPositionConfig(
                symbol="APEX",
                direction=PositionDirection.LONG,
                target_size_usd=30.0,
                min_trade_size=2.0,
                leverage=2  # APEX는 최대 2x
            ),
            "FF": TokenPositionConfig(
                symbol="FF",
                direction=PositionDirection.LONG,
                target_size_usd=25.0,
                min_trade_size=25.0,
                leverage=3
            ),
            "EDEN": TokenPositionConfig(
                symbol="EDEN",
                direction=PositionDirection.LONG,
                target_size_usd=20.0,
                min_trade_size=12.0,
                leverage=3
            ),

            # Short positions
            "ZEC": TokenPositionConfig(
                symbol="ZEC",
                direction=PositionDirection.SHORT,
                target_size_usd=40.0,
                min_trade_size=0.03,
                leverage=5  # ZEC는 최대 5x
            ),
            "STBL": TokenPositionConfig(
                symbol="STBL",
                direction=PositionDirection.SHORT,
                target_size_usd=25.0,
                min_trade_size=15.0,
                leverage=3
            ),
            "2Z": TokenPositionConfig(
                symbol="2Z",
                direction=PositionDirection.SHORT,
                target_size_usd=30.0,
                min_trade_size=10.0,
                leverage=3
            ),

            # Neutral (no position)
            "0G": TokenPositionConfig(
                symbol="0G",
                direction=PositionDirection.NEUTRAL,
                target_size_usd=0.0,
                min_trade_size=1.7,
                leverage=3
            ),
        }

        return configs

    async def start(self):
        """전략 시작"""
        self.running = True
        logger.info("Starting Single Position Strategy")
        logger.info("Position configurations:", configs=self._get_config_summary())

        # 현재 포지션 초기화
        await self.initialize_positions()

        # WebSocket 콜백 등록
        self.client.add_position_update_callback(self.on_position_update)
        self.client.add_order_update_callback(self.on_order_update)

        # 백그라운드 태스크 시작
        tasks = [
            asyncio.create_task(self.position_manager()),
            asyncio.create_task(self.rate_limiter()),
            asyncio.create_task(self.stats_reporter()),
            asyncio.create_task(self.position_monitor()),
        ]

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Single Position Strategy stopped")

    async def stop(self):
        """전략 중지"""
        self.running = False
        logger.info("Stopping Single Position Strategy")

    def _get_config_summary(self) -> Dict:
        """설정 요약 반환"""
        summary = {
            "long_positions": [],
            "short_positions": [],
            "neutral": []
        }

        for symbol, config in self.position_configs.items():
            config_info = {
                "symbol": symbol,
                "target_usd": config.target_size_usd,
                "leverage": config.leverage
            }

            if config.direction == PositionDirection.LONG:
                summary["long_positions"].append(config_info)
            elif config.direction == PositionDirection.SHORT:
                summary["short_positions"].append(config_info)
            else:
                summary["neutral"].append(symbol)

        return summary

    async def initialize_positions(self):
        """현재 포지션 상태 초기화"""
        try:
            account_info = await self.client.get_account_info()
            positions = account_info.get("positions", [])

            for position in positions:
                symbol = position.symbol
                if symbol in self.position_configs:
                    position_raw = float(position.position)
                    sign = int(position.sign)
                    actual_position = position_raw * sign
                    self.current_positions[symbol] = actual_position

                    logger.info(
                        f"Initialized position for {symbol}",
                        current_position=actual_position,
                        target_direction=self.position_configs[symbol].direction.value
                    )

            # 설정된 토큰 중 포지션이 없는 것들은 0으로 초기화
            for symbol in self.position_configs:
                if symbol not in self.current_positions:
                    self.current_positions[symbol] = 0

            logger.info("Position initialization complete", positions=self.current_positions)

        except Exception as e:
            logger.error("Failed to initialize positions", error=str(e))

    async def position_manager(self):
        """포지션 관리 메인 루프"""
        while self.running:
            try:
                # 각 설정된 토큰에 대해 포지션 체크 및 조정
                for symbol, config in self.position_configs.items():
                    if config.direction == PositionDirection.NEUTRAL:
                        # 중립 포지션은 건드리지 않음
                        continue

                    # Rate limit 체크
                    if self.stats.trades_this_minute >= self.rate_limit_per_minute:
                        await asyncio.sleep(10)
                        continue

                    # 포지션 조정 필요 여부 확인
                    await self.adjust_position(symbol, config)

                    # 토큰 간 간격
                    await asyncio.sleep(random.uniform(5, 10))

                # 전체 사이클 간격
                await asyncio.sleep(60)

            except Exception as e:
                logger.error("Position manager error", error=str(e))
                await asyncio.sleep(30)

    async def adjust_position(self, symbol: str, config: TokenPositionConfig):
        """포지션 조정"""
        try:
            current_pos = self.current_positions.get(symbol, 0)

            # 현재 가격 조회
            price = await price_fetcher.get_token_price(symbol)
            if not price or price <= 0:
                logger.warning(f"Cannot get price for {symbol}, skipping")
                return

            # 현재 포지션 가치 계산
            current_value_usd = abs(current_pos) * price

            # 목표 포지션과의 차이 계산
            if config.direction == PositionDirection.LONG:
                # Long 포지션
                target_position = config.target_size_usd / price
                position_diff = target_position - current_pos

                if current_pos < 0:
                    # 반대 방향 포지션이 있으면 먼저 청산
                    logger.info(f"{symbol}: Closing short position before going long")
                    await self.execute_order(symbol, "buy", abs(current_pos), config.leverage)
                    await asyncio.sleep(5)
                    # 그 다음 목표 포지션 진입
                    await self.execute_order(symbol, "buy", target_position, config.leverage)
                elif abs(position_diff) > config.min_trade_size:
                    # 포지션 조정 필요
                    if position_diff > 0:
                        # 추가 매수
                        logger.info(f"{symbol}: Adding to long position")
                        await self.execute_order(symbol, "buy", position_diff, config.leverage)
                    else:
                        # 일부 매도 (포지션 축소)
                        logger.info(f"{symbol}: Reducing long position")
                        await self.execute_order(symbol, "sell", abs(position_diff), config.leverage)

            elif config.direction == PositionDirection.SHORT:
                # Short 포지션
                target_position = -(config.target_size_usd / price)
                position_diff = target_position - current_pos

                if current_pos > 0:
                    # 반대 방향 포지션이 있으면 먼저 청산
                    logger.info(f"{symbol}: Closing long position before going short")
                    await self.execute_order(symbol, "sell", current_pos, config.leverage)
                    await asyncio.sleep(5)
                    # 그 다음 목표 포지션 진입
                    await self.execute_order(symbol, "sell", abs(target_position), config.leverage)
                elif abs(position_diff) > config.min_trade_size:
                    # 포지션 조정 필요
                    if position_diff < 0:
                        # 추가 매도 (숏 포지션 증가)
                        logger.info(f"{symbol}: Adding to short position")
                        await self.execute_order(symbol, "sell", abs(position_diff), config.leverage)
                    else:
                        # 일부 매수 (숏 포지션 축소)
                        logger.info(f"{symbol}: Reducing short position")
                        await self.execute_order(symbol, "buy", position_diff, config.leverage)

            # 통계 업데이트
            self.stats.current_positions[symbol] = current_pos

        except Exception as e:
            logger.error(f"Failed to adjust position for {symbol}", error=str(e))

    async def execute_order(self, symbol: str, side: str, quantity: float, leverage: int):
        """주문 실행"""
        try:
            if quantity <= 0:
                return None

            # 마진 체크
            account_info = await self.client.get_account_info()
            available_balance = account_info.get("balance", {}).get("available_balance", 0)

            # 예상 주문 가치 계산
            price = await price_fetcher.get_token_price(symbol)
            if not price:
                return None

            order_value = quantity * price

            # 마진 요구사항 체크
            margin_info = await self.get_margin_requirements(symbol)
            required_margin = order_value * (margin_info["initial_margin_fraction"] / 100)

            if available_balance < required_margin * 1.2:
                logger.warning(
                    f"Insufficient margin for {symbol} order",
                    available=available_balance,
                    required=required_margin
                )
                return None

            # 주문 실행
            logger.info(
                f"Executing order",
                symbol=symbol,
                side=side,
                quantity=quantity,
                leverage=leverage,
                value_usd=order_value
            )

            result = await self.client.create_market_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                leverage=leverage
            )

            if result:
                # 통계 업데이트
                self.stats.trades_this_minute += 1
                self.stats.daily_trades += 1
                self.stats.daily_volume += order_value
                self.stats.last_trade_time = datetime.now()

                # 포지션 업데이트 대기
                await asyncio.sleep(3)
                await self.sync_position(symbol)

                logger.info(f"Order executed successfully for {symbol}")
                return result

            return None

        except Exception as e:
            logger.error(f"Failed to execute order for {symbol}", error=str(e))
            return None

    async def sync_position(self, symbol: str):
        """포지션 동기화"""
        try:
            account_info = await self.client.get_account_info()
            positions = account_info.get("positions", [])

            for position in positions:
                if position.symbol == symbol:
                    position_raw = float(position.position)
                    sign = int(position.sign)
                    actual_position = position_raw * sign
                    old_position = self.current_positions.get(symbol, 0)
                    self.current_positions[symbol] = actual_position

                    logger.info(
                        f"Position synced for {symbol}",
                        old_position=old_position,
                        new_position=actual_position
                    )
                    return

            # 포지션이 없으면 0으로 설정
            self.current_positions[symbol] = 0

        except Exception as e:
            logger.error(f"Failed to sync position for {symbol}", error=str(e))

    async def get_margin_requirements(self, symbol: str) -> dict:
        """마진 요구사항 조회"""
        try:
            leverage_info = await price_fetcher.get_leverage_info(symbol)
            if leverage_info:
                return {
                    "initial_margin_fraction": leverage_info["initial_margin_percentage"],
                    "max_leverage": leverage_info["max_leverage"],
                    "min_leverage": leverage_info["min_leverage"]
                }
        except Exception as e:
            logger.warning(f"Failed to get leverage info for {symbol}", error=str(e))

        # 기본값 반환
        return {
            "initial_margin_fraction": 33.33,
            "max_leverage": 3,
            "min_leverage": 3
        }

    async def rate_limiter(self):
        """Rate limit 관리"""
        while self.running:
            now = datetime.now()

            # 매분 카운터 리셋
            if now - self.stats.minute_reset_time >= timedelta(minutes=1):
                self.stats.trades_this_minute = 0
                self.stats.minute_reset_time = now

            await asyncio.sleep(1)

    async def position_monitor(self):
        """포지션 모니터링 및 리스크 관리"""
        while self.running:
            try:
                # 전체 포지션 상태 체크
                account_info = await self.client.get_account_info()
                available_balance = account_info.get("balance", {}).get("available_balance", 0)
                total_position_value = 0

                position_summary = []
                for symbol, position in self.current_positions.items():
                    if abs(position) > 0.001:
                        price = await price_fetcher.get_token_price(symbol)
                        if price:
                            value = abs(position) * price
                            total_position_value += value

                            config = self.position_configs.get(symbol)
                            target_direction = config.direction.value if config else "unknown"
                            actual_direction = "long" if position > 0 else "short"

                            position_summary.append({
                                "symbol": symbol,
                                "position": position,
                                "value_usd": value,
                                "target_direction": target_direction,
                                "actual_direction": actual_direction,
                                "aligned": target_direction == actual_direction
                            })

                # 로그 출력
                logger.info(
                    "Position Monitor Report",
                    available_balance=available_balance,
                    total_position_value=total_position_value,
                    position_count=len([p for p in position_summary if p["value_usd"] > 1]),
                    positions=position_summary
                )

                # 포지션 방향 정합성 체크
                misaligned = [p for p in position_summary if not p["aligned"] and p["value_usd"] > 1]
                if misaligned:
                    logger.warning(
                        "Misaligned positions detected",
                        misaligned_positions=misaligned
                    )

                await asyncio.sleep(60)  # 1분마다 체크

            except Exception as e:
                logger.error("Position monitor error", error=str(e))
                await asyncio.sleep(30)

    async def stats_reporter(self):
        """통계 리포터"""
        while self.running:
            try:
                # 포지션별 요약
                long_positions = []
                short_positions = []
                neutral_positions = []

                for symbol, position in self.current_positions.items():
                    if abs(position) > 0.001:
                        if position > 0:
                            long_positions.append(f"{symbol}:{position:.4f}")
                        else:
                            short_positions.append(f"{symbol}:{position:.4f}")
                    else:
                        neutral_positions.append(symbol)

                logger.info(
                    "Trading Statistics",
                    daily_volume=self.stats.daily_volume,
                    daily_trades=self.stats.daily_trades,
                    daily_pnl=self.stats.daily_pnl,
                    long_positions=long_positions,
                    short_positions=short_positions,
                    neutral=neutral_positions,
                    trades_this_minute=self.stats.trades_this_minute
                )

                await asyncio.sleep(300)  # 5분마다 리포트

            except Exception as e:
                logger.error("Stats reporter error", error=str(e))
                await asyncio.sleep(60)

    def on_position_update(self, positions: Dict[str, float]):
        """WebSocket 포지션 업데이트 핸들러"""
        try:
            for symbol, new_position in positions.items():
                if symbol in self.position_configs:
                    old_position = self.current_positions.get(symbol, 0)
                    self.current_positions[symbol] = new_position

                    if abs(new_position - old_position) > 0.001:
                        logger.info(
                            f"Real-time position update",
                            symbol=symbol,
                            old=old_position,
                            new=new_position,
                            change=new_position - old_position
                        )
        except Exception as e:
            logger.error("Error handling position update", error=str(e))

    def on_order_update(self, order_status: Dict):
        """WebSocket 주문 업데이트 핸들러"""
        try:
            symbol = order_status.get("symbol")
            status = order_status.get("status")
            outcome = order_status.get("outcome")

            logger.info(
                "Order status update",
                symbol=symbol,
                status=status,
                outcome=outcome
            )

        except Exception as e:
            logger.error("Error handling order update", error=str(e))