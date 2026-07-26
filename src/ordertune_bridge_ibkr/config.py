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
        description="Bearer-Token für /api/bridge/v1/* (from Wizard).",
    )
    ordertune_bridge_connection_id: str = Field(
        min_length=1,
        description="UUID of the broker_connections row this bridge represents.",
    )

    # ── IBKR TWS/Gateway (lokaler Socket) ──────────────────────────────
    ibkr_gateway_host: str = Field(
        default="127.0.0.1",
        description="Host von TWS oder IB Gateway (typischerweise 127.0.0.1).",
    )
    ibkr_gateway_port: int = Field(
        default=7497,
        description="Socket-Port. Paper=7497, Live=7496 (Gateway) / 7497,7496 (TWS).",
    )
    ibkr_trading_mode: Literal["paper", "live"] = Field(
        default="paper",
        description="Nur informational — der tatsächliche Mode wird vom TWS/Gateway-Login vorgegeben.",
    )
    ibkr_client_id: int = Field(
        default=17,
        description="IBKR API Client-ID. Muss unique pro TWS-Connection sein.",
    )

    # ── Optional overrides ──────────────────────────────────────────────
    order_submit_delay_ms: int = Field(
        default=100,
        ge=0,
        le=5000,
        description="Delay zwischen unabhängigen Order-Submits (Rate-Limit-Schutz).",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")
    update_check_enabled: bool = Field(default=True)


def load_config(env_file: str | Path | None = None) -> BridgeConfig:
    """Load bridge.env from CWD (or explicit path)."""
    if env_file is not None:
        return BridgeConfig(_env_file=str(env_file))  # type: ignore[call-arg]
    return BridgeConfig()
