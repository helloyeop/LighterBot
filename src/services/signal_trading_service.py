"""
신호 기반 거래 서비스
TradingView에서 오는 long/short 신호를 처리하여 포지션을 관리합니다.
"""

import structlog
from typing import Dict, Optional
from datetime import datetime
import asyncio
from config.settings import get_settings
from src.core.lighter_client import lighter_client
from src.api.webhook import TradingViewSignal

logger = structlog.get_logger()
settings = get_settings()


class SignalTradingService:
    def __init__(self):
        self.current_positions: Dict[str, float] = {}  # symbol -> position size (양수: long, 음수: short)
        self.base_quantity = 0.001  # 기본 포지션 크기

    async def process_signal(self, signal: TradingViewSignal):
        """신호를 처리하고 포지션을 관리합니다."""
        try:
            symbol = signal.symbol
            sale_type = signal.sale

            # 신호 처리 전 실제 DEX 포지션과 동기화
            await self._sync_position_with_dex(symbol)

            logger.info(
                "Processing signal",
                symbol=symbol,
                sale_type=sale_type,
                current_position=self.current_positions.get(symbol, 0)
            )

            # 현재 포지션 상태 확인
            current_position = self.current_positions.get(symbol, 0)

            if sale_type == "long":
                await self._handle_long_signal(symbol, current_position, signal)
            elif sale_type == "short":
                await self._handle_short_signal(symbol, current_position, signal)

        except Exception as e:
            logger.error("Failed to process signal", error=str(e), signal=signal.dict())

    async def _handle_long_signal(self, symbol: str, current_position: float, signal: TradingViewSignal):
        """Long 신호 처리"""
        target_position = self.base_quantity  # Long 포지션으로 설정

        if current_position == target_position:
            logger.info("Already in target long position", symbol=symbol, position=current_position)
            return

        # 필요한 거래량 계산
        trade_quantity = target_position - current_position

        success = False
        if trade_quantity > 0:
            # Long 포지션 증가 (Buy)
            success = await self._execute_trade(symbol, "buy", abs(trade_quantity), signal.leverage)
        else:
            # Short 포지션 감소 (Sell/Close short)
            success = await self._execute_trade(symbol, "sell", abs(trade_quantity), signal.leverage)

        # 거래 성공 시에만 포지션 업데이트
        if success:
            self.current_positions[symbol] = target_position
            logger.info("Position updated after successful trade", symbol=symbol, new_position=target_position)
        else:
            logger.warning("Position not updated due to trade failure", symbol=symbol, target_position=target_position)

    async def _handle_short_signal(self, symbol: str, current_position: float, signal: TradingViewSignal):
        """Short 신호 처리"""
        target_position = -self.base_quantity  # Short 포지션으로 설정

        if current_position == target_position:
            logger.info("Already in target short position", symbol=symbol, position=current_position)
            return

        # 필요한 거래량 계산
        trade_quantity = target_position - current_position

        success = False
        if trade_quantity < 0:
            # Short 포지션 증가 (Sell)
            success = await self._execute_trade(symbol, "sell", abs(trade_quantity), signal.leverage)
        else:
            # Long 포지션 감소 (Buy/Close long)
            success = await self._execute_trade(symbol, "buy", abs(trade_quantity), signal.leverage)

        # 거래 성공 시에만 포지션 업데이트
        if success:
            self.current_positions[symbol] = target_position
            logger.info("Position updated after successful trade", symbol=symbol, new_position=target_position)
        else:
            logger.warning("Position not updated due to trade failure", symbol=symbol, target_position=target_position)

    async def _execute_trade(self, symbol: str, side: str, quantity: float, leverage: int) -> bool:
        """실제 거래 실행 및 체결 확인"""
        try:
            logger.info(
                "Executing trade",
                symbol=symbol,
                side=side,
                quantity=quantity,
                leverage=leverage
            )

            # Lighter DEX에서 마켓 주문 실행
            result = await lighter_client.create_market_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                leverage=leverage
            )

            # order_id가 있으면 거래 성공으로 판단
            order_id = result.get("order_id") if result else None
            if order_id:
                logger.info(
                    "Trade executed successfully",
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    order_id=order_id,
                    tx_hash=result.get("tx_hash", {}).get("tx_hash") if result.get("tx_hash") else None
                )

                # 체결 처리 대기 후 실제 포지션 동기화
                await asyncio.sleep(1)  # 체결 처리 대기
                await self._sync_position_with_dex(symbol)

                return True
            else:
                logger.error(
                    "Trade execution failed - no order_id",
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    result=result
                )
                return False

        except Exception as e:
            logger.error(
                "Failed to execute trade",
                symbol=symbol,
                side=side,
                quantity=quantity,
                error=str(e)
            )
            return False

    async def _sync_position_with_dex(self, symbol: str):
        """실제 DEX 포지션과 내부 추적 동기화"""
        try:
            # API를 통해 실제 포지션 조회
            from src.core.lighter_client import lighter_client

            # 계정 정보에서 포지션 추출
            positions = await lighter_client.get_positions()
            if positions:
                for pos in positions:
                    if pos.get('symbol') == symbol:
                        actual_position = float(pos.get('position', 0))
                        if pos.get('sign') == -1:  # Short 포지션
                            actual_position = -actual_position

                        # 내부 추적 업데이트
                        old_position = self.current_positions.get(symbol, 0)
                        self.current_positions[symbol] = actual_position

                        logger.info(
                            "Position synced with DEX",
                            symbol=symbol,
                            old_internal=old_position,
                            new_actual=actual_position
                        )
                        return

            # 포지션을 찾지 못한 경우 0으로 설정
            old_position = self.current_positions.get(symbol, 0)
            self.current_positions[symbol] = 0
            logger.info(
                "No position found in DEX, reset to 0",
                symbol=symbol,
                old_internal=old_position
            )

        except Exception as e:
            logger.error(
                "Failed to sync position with DEX",
                symbol=symbol,
                error=str(e)
            )

    async def get_current_position(self, symbol: str) -> float:
        """현재 포지션 크기 반환"""
        return self.current_positions.get(symbol, 0)

    async def reset_position(self, symbol: str):
        """포지션 리셋"""
        if symbol in self.current_positions:
            del self.current_positions[symbol]
            logger.info("Position reset", symbol=symbol)


# 싱글톤 인스턴스
signal_trading_service = SignalTradingService()


async def process_trading_signal(signal: TradingViewSignal):
    """웹훅에서 호출되는 신호 처리 함수"""
    logger.info("Background task started processing signal", signal=signal.dict())
    try:
        await signal_trading_service.process_signal(signal)
        logger.info("Background task completed successfully", signal=signal.dict())
    except Exception as e:
        logger.error("Background task failed", error=str(e), signal=signal.dict())