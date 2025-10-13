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
        self.base_quantity = 0.01  # 기본 포지션 크기 (고정값 사용시)
        self.use_balance_percentage = True  # 잔액 비율 사용 여부
        self.balance_percentage = 0.8  # 사용할 잔액 비율 (80%)
        # 허용된 심볼 필터링 (빈 리스트이면 모든 심볼 허용)
        self.allowed_symbols = getattr(settings, 'allowed_symbols', []) or []

    async def _calculate_position_size(self, symbol: str, leverage: int = 1) -> float:
        """잔액 기반 포지션 크기 계산"""
        try:
            if not self.use_balance_percentage:
                return self.base_quantity

            # 계정 정보 조회
            account_info = await lighter_client.get_account_info()
            if not account_info:
                logger.warning("Failed to get account info, using base quantity")
                return self.base_quantity

            # 사용 가능한 잔액 추출 (여러 형태로 시도)
            available_balance = 0
            if isinstance(account_info, dict):
                # 먼저 balance 딕셔너리에서 확인
                balance_data = account_info.get('balance', {})
                if isinstance(balance_data, dict):
                    available_balance = balance_data.get('available_balance', 0)
                    if available_balance == 0:
                        # collateral이나 total_asset_value 사용
                        available_balance = balance_data.get('collateral', 0)
                        if available_balance == 0:
                            available_balance = balance_data.get('total_asset_value', 0)

                # 딕셔너리에서 직접 available_balance 확인
                if available_balance == 0:
                    available_balance = account_info.get('available_balance', 0)
            elif hasattr(account_info, 'available_balance'):
                # 객체 형태인 경우
                available_balance = getattr(account_info, 'available_balance', 0)

            # 잔액을 float로 변환
            try:
                available_balance = float(available_balance) if available_balance else 0
            except (ValueError, TypeError):
                available_balance = 0

            # 잔액이 유효하지 않으면 기본값 사용
            if available_balance <= 0:
                logger.warning(f"Invalid or zero balance ({available_balance}), using base quantity")
                return self.base_quantity

            # 현재 가격 조회 (price_fetcher 사용)
            from src.utils.price_fetcher import price_fetcher

            # 실시간 가격 가져오기
            current_price = await price_fetcher.get_token_price(symbol)
            if current_price and current_price > 0:
                mid_price = current_price
                logger.info(f"Using real-time price for {symbol}: ${current_price}")
            else:
                # 오더북에서 중간가 계산
                orderbook_data = await price_fetcher.get_orderbook(symbol, 1)
                if orderbook_data:
                    bids = orderbook_data.get("bids", [])
                    asks = orderbook_data.get("asks", [])
                    best_bid = float(bids[0].get("price", 4000)) if bids else 4000
                    best_ask = float(asks[0].get("price", 4000)) if asks else 4000
                    mid_price = (best_bid + best_ask) / 2
                    logger.info(f"Using orderbook mid-price for {symbol}: ${mid_price}")
                else:
                    # 폴백 가격
                    fallback_prices = {"ETH": 4000, "BTC": 70000, "APEX": 1.5}
                    mid_price = fallback_prices.get(symbol, 1.0)
                    logger.warning(f"Using fallback price for {symbol}: ${mid_price}")

            # 포지션 크기 계산: (잔액 * 비율 * 레버리지) / 가격
            position_value = available_balance * self.balance_percentage * leverage
            position_size = position_value / mid_price

            # 최소/최대 제한
            min_size = 0.001  # 최소 0.001 ETH
            max_size = 1000.0    # 최대 1 ETH
            position_size = max(min_size, min(position_size, max_size))

            # 소수점 4자리로 반올림
            position_size = round(position_size, 4)

            logger.info(
                "Position size calculated",
                symbol=symbol,
                available_balance=available_balance,
                percentage_used=self.balance_percentage,
                leverage=leverage,
                mid_price=mid_price,
                calculated_size=position_size
            )

            return position_size

        except Exception as e:
            logger.error("Failed to calculate position size", error=str(e))
            return self.base_quantity

    async def process_signal(self, signal: TradingViewSignal):
        """신호를 처리하고 포지션을 관리합니다."""
        try:
            symbol = signal.symbol
            sale_type = signal.sale

            # 심볼 필터링 체크
            if self.allowed_symbols and symbol not in self.allowed_symbols:
                logger.info(
                    "Signal ignored due to symbol filtering",
                    symbol=symbol,
                    allowed_symbols=self.allowed_symbols
                )
                return

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
            elif sale_type == "close":
                await self._handle_close_signal(symbol, current_position, signal)

        except Exception as e:
            logger.error("Failed to process signal", error=str(e), signal=signal.dict())

    async def _handle_long_signal(self, symbol: str, current_position: float, signal: TradingViewSignal):
        """Long 신호 처리 - 스마트 포지션 전환"""
        # 잔액 기반 포지션 크기 계산
        target_position = await self._calculate_position_size(symbol, signal.leverage)

        # 이미 Long 포지션인 경우 변화 없음
        if current_position > 0:
            logger.info("Already in long position, no action needed", symbol=symbol, position=current_position)
            return

        # 거래량 계산
        if current_position < 0:
            # Short 포지션이 있으면 2배 매수 (청산 + 반전)
            trade_quantity = abs(current_position) + target_position
            logger.info("Reversing short to long position", symbol=symbol,
                       current=current_position, trade_quantity=trade_quantity)
        else:
            # 포지션 없으면 기본 매수
            trade_quantity = target_position
            logger.info("Opening new long position", symbol=symbol, trade_quantity=trade_quantity)

        # Buy 거래 실행
        success = await self._execute_trade(symbol, "buy", trade_quantity, signal.leverage)

        # 거래 성공 시에만 포지션 업데이트 (DEX 동기화로 실제 포지션 확인)
        if success:
            # DEX와 동기화하여 실제 포지션으로 업데이트
            await self._sync_position_with_dex(symbol)
            logger.info("Position updated after successful trade", symbol=symbol,
                       expected_position=target_position,
                       actual_position=self.current_positions.get(symbol, 0))
        else:
            logger.warning("Position not updated due to trade failure", symbol=symbol, target_position=target_position)

    async def _handle_short_signal(self, symbol: str, current_position: float, signal: TradingViewSignal):
        """Short 신호 처리 - 스마트 포지션 전환"""
        # 잔액 기반 포지션 크기 계산
        calculated_size = await self._calculate_position_size(symbol, signal.leverage)
        target_position = -calculated_size  # Short 포지션 목표

        # 이미 Short 포지션인 경우 변화 없음
        if current_position < 0:
            logger.info("Already in short position, no action needed", symbol=symbol, position=current_position)
            return

        # 거래량 계산
        if current_position > 0:
            # Long 포지션이 있으면 2배 매도 (청산 + 반전)
            trade_quantity = current_position + abs(target_position)
            logger.info("Reversing long to short position", symbol=symbol,
                       current=current_position, trade_quantity=trade_quantity)
        else:
            # 포지션 없으면 기본 매도
            trade_quantity = abs(target_position)
            logger.info("Opening new short position", symbol=symbol, trade_quantity=trade_quantity)

        # Sell 거래 실행
        success = await self._execute_trade(symbol, "sell", trade_quantity, signal.leverage)

        # 거래 성공 시에만 포지션 업데이트 (DEX 동기화로 실제 포지션 확인)
        if success:
            # DEX와 동기화하여 실제 포지션으로 업데이트
            await self._sync_position_with_dex(symbol)
            logger.info("Position updated after successful trade", symbol=symbol,
                       expected_position=target_position,
                       actual_position=self.current_positions.get(symbol, 0))
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

            # RespSendTx 객체에서 성공 여부 판단 (code=200이면 성공)
            is_success = result and hasattr(result, 'code') and result.code == 200
            if is_success:
                logger.info(
                    "Trade executed successfully",
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    tx_hash=result.tx_hash if hasattr(result, 'tx_hash') else None
                )

                # 체결 처리 대기
                await asyncio.sleep(1)  # 체결 처리 대기

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
                    # AccountPosition 객체인 경우와 dict인 경우 모두 처리
                    if hasattr(pos, 'symbol'):  # AccountPosition 객체
                        pos_symbol = pos.symbol
                        pos_position = float(pos.position)
                        pos_sign = pos.sign
                    else:  # dict 형태
                        pos_symbol = pos.get('symbol')
                        pos_position = float(pos.get('position', 0))
                        pos_sign = pos.get('sign', 1)

                    if pos_symbol == symbol:
                        actual_position = pos_position
                        if pos_sign == -1:  # Short 포지션
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

    async def _handle_close_signal(self, symbol: str, current_position: float, signal: TradingViewSignal):
        """Close 신호 처리 - 현재 포지션 완전 종료"""
        # 포지션이 없는 경우 에러 처리
        if current_position == 0:
            logger.warning("No position to close", symbol=symbol, current_position=current_position)
            return

        logger.info(
            "Processing close signal",
            symbol=symbol,
            current_position=current_position
        )

        # 포지션 방향에 따라 반대 거래 실행
        if current_position > 0:
            # Long 포지션 종료 -> Sell
            side = "sell"
            trade_quantity = current_position
            logger.info("Closing long position", symbol=symbol, trade_quantity=trade_quantity)
        else:
            # Short 포지션 종료 -> Buy
            side = "buy"
            trade_quantity = abs(current_position)
            logger.info("Closing short position", symbol=symbol, trade_quantity=trade_quantity)

        # 거래 실행
        success = await self._execute_trade(symbol, side, trade_quantity, signal.leverage)

        # 거래 성공 시에만 포지션 업데이트 (DEX 동기화로 실제 포지션 확인)
        if success:
            # DEX와 동기화하여 실제 포지션으로 업데이트
            await self._sync_position_with_dex(symbol)
            logger.info("Position closed successfully", symbol=symbol,
                       previous_position=current_position,
                       current_position=self.current_positions.get(symbol, 0))
        else:
            logger.warning("Position close failed", symbol=symbol, current_position=current_position)

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