from pydantic_settings import BaseSettings
from pydantic import Field, field_validator
from typing import List, Optional, Union
from functools import lru_cache
import os


class Settings(BaseSettings):
    # Lighter DEX
    lighter_api_key: str = Field(..., env="LIGHTER_API_KEY")
    lighter_api_secret: str = Field(..., env="LIGHTER_API_SECRET")
    lighter_network: str = Field(default="mainnet", env="LIGHTER_NETWORK")
    lighter_endpoint: str = Field(
        default="https://mainnet.zklighter.elliot.ai",
        env="LIGHTER_ENDPOINT"
    )
    lighter_account_index: int = Field(default=0, env="LIGHTER_ACCOUNT_INDEX")
    lighter_api_key_index: int = Field(default=0, env="LIGHTER_API_KEY_INDEX")

    # TradingView
    tradingview_secret_token: str = Field(..., env="TRADINGVIEW_SECRET_TOKEN")
    tradingview_allowed_ips: Union[List[str], str] = Field(
        default="52.89.214.238,34.212.75.30,52.32.178.7,54.218.53.128,52.36.31.181",
        env="TRADINGVIEW_ALLOWED_IPS"
    )

    # Risk Management
    max_position_size_usd: float = Field(default=100.0, env="MAX_POSITION_SIZE_USD")
    max_daily_loss_pct: float = Field(default=5.0, env="MAX_DAILY_LOSS_PCT")
    max_trades_per_minute: int = Field(default=3, env="MAX_TRADES_PER_MINUTE")
    max_leverage: int = Field(default=5, env="MAX_LEVERAGE")
    kill_switch_enabled: bool = Field(default=False, env="KILL_SWITCH_ENABLED")

    # Notifications
    telegram_bot_token: Optional[str] = Field(default="", env="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: Optional[str] = Field(default="", env="TELEGRAM_CHAT_ID")

    # Server
    host: str = Field(default="127.0.0.1", env="HOST")
    port: int = Field(default=8000, env="PORT")
    debug: bool = Field(default=False, env="DEBUG")
    log_level: str = Field(default="INFO", env="LOG_LEVEL")

    @field_validator("tradingview_allowed_ips", mode="before")
    def parse_allowed_ips(cls, v):
        if isinstance(v, str):
            return [ip.strip() for ip in v.split(",")]
        return v

    class Config:
        env_file = ".env"
        case_sensitive = False
        env_parse_none_str = ["", "null", "None"]


@lru_cache()
def get_settings() -> Settings:
    return Settings()


# Convenience function for getting settings
settings = get_settings()