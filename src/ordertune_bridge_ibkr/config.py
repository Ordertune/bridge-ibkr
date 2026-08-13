"""bridge.env loader mit Pydantic-Validierung.

Der Bridge-Client liest ausschließlich aus einer `bridge.env`-Datei
im Working-Directory oder aus Env-Vars. Missing/invalid Values führen
zu Exit 1 mit klarer Error-Message beim Startup.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class BridgeConfig(BaseSettings):
    """Konfiguration aus bridge.env."""

    model_config = SettingsConfigDict(
        env_file="bridge.env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Ordertune-Server (from Setup-Wizard-Download) ──────────────────
    ordertune_api_base: HttpUrl = Field(
        default="https://t1.ordertune.com",  # type: ignore[arg-type]
        description="Base-URL of the Ordertune server (typically https://t1.ordertune.com).",
    )
    ordertune_bridge_token: str = Field(
        min_length=32,
        description="Bearer token for /api/bridge/v1/* (from the setup wizard).",
    )
    ordertune_bridge_connection_id: str = Field(
        min_length=1,
        description="UUID of the broker_connections row this bridge represents.",
    )

    # ── IBKR TWS/Gateway (lokaler Socket) ──────────────────────────────
    ibkr_gateway_host: str = Field(
        default="127.0.0.1",
        description="Host running TWS or IB Gateway (normally 127.0.0.1).",
    )
    ibkr_gateway_port: int = Field(
        default=7497,
        description="Socket port. Read it out of the API settings in TWS or IB Gateway — it is a setting there and does not follow from the account type. IBKR defaults: TWS 7497 paper / 7496 live, Gateway 4002 paper / 4001 live.",
    )
    ibkr_trading_mode: Literal["paper", "live"] = Field(
        default="paper",
        description="Label only. The actual trading mode comes from the account you log in to in TWS or IB Gateway; this value changes nothing.",
    )
    ibkr_client_id: int = Field(
        default=17,
        description="IBKR API client id. Must be unique per connection to one TWS or Gateway instance.",
    )

    # ── Optional overrides ──────────────────────────────────────────────
    order_submit_delay_ms: int = Field(
        default=100,
        ge=0,
        le=5000,
        description="Delay between independent order submits, in milliseconds. Protects against IBKR rate limits.",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")
    update_check_enabled: bool = Field(default=True)


def load_config(env_file: str | Path | None = None) -> BridgeConfig:
    """Load bridge.env from CWD (or explicit path)."""
    if env_file is not None:
        return BridgeConfig(_env_file=str(env_file))  # type: ignore[call-arg]
    return BridgeConfig()
