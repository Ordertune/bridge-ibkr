"""bridge.env loader mit Pydantic-Validierung.

Der Bridge-Client liest ausschließlich aus einer `bridge.env`-Datei
im Working-Directory oder aus Env-Vars. Missing/invalid Values führen
zu Exit 1 mit klarer Error-Message beim Startup.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

from .trade_reports import STANDARD_VERZEICHNIS as DEFAULT_TWS_EXPORT_DIR


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

    # ── IBKR TWS (lokaler Socket) ───────────────────────────────────────
    #
    # T1-214 — zwei Schreibweisen, eine Bedeutung.
    #
    # Die Felder hiessen bis zum 2026-09-23 `IBKR_GATEWAY_HOST` und
    # `IBKR_GATEWAY_PORT`. Sie heissen jetzt nach der TWS, weil die Bridge nur
    # noch mit ihr betrieben wird (T1-207: das IB Gateway hat keine
    # Berichtsfunktion).
    #
    # Die alten Namen bleiben **unbefristet** gueltig. Jede ausgelieferte
    # `bridge.env` traegt sie, und eine Installation durch eine Umbenennung
    # stehenzulassen waere ein schlechterer Ausgang als ein Feldname, der an
    # eine alte Entscheidung erinnert. `validation_alias` macht daraus genau
    # eine Zeile Aufwand.
    #
    # Stehen beide in derselben Datei, gewinnt die neue Schreibweise — das ist
    # die Reihenfolge in `AliasChoices` —, und `env_file.warne_bei_doppelung`
    # sagt es in einer Protokollzeile.
    ibkr_tws_host: str = Field(
        default="127.0.0.1",
        validation_alias=AliasChoices("IBKR_TWS_HOST", "IBKR_GATEWAY_HOST"),
        description="Host running TWS (normally 127.0.0.1).",
    )
    ibkr_tws_port: int = Field(
        default=7497,
        validation_alias=AliasChoices("IBKR_TWS_PORT", "IBKR_GATEWAY_PORT"),
        description="Socket port. Read it out of the API settings in TWS — it is a setting there and does not follow from the account type. IBKR defaults: 7497 paper / 7496 live.",
    )
    ibkr_trading_mode: Literal["paper", "live"] = Field(
        default="paper",
        description="Label only. The actual trading mode comes from the account you log in to in TWS; this value changes nothing.",
    )
    ibkr_client_id: int = Field(
        default=17,
        description="IBKR API client id. Must be unique per connection to one TWS instance.",
    )

    # Die alten Namen als Eigenschaft, damit nichts im Baum zweimal umgestellt
    # werden muss. Sie sind Lesezugriffe auf dasselbe Feld, keine zweite Quelle.
    @property
    def ibkr_gateway_host(self) -> str:
        return self.ibkr_tws_host

    @property
    def ibkr_gateway_port(self) -> int:
        return self.ibkr_tws_port

    # ── TWS trade reports (T1-207) ──────────────────────────────────────
    tws_export_dir: str = Field(
        default=DEFAULT_TWS_EXPORT_DIR,
        description=(
            "Folder that TWS writes its trade reports to. Set it in TWS under "
            "Global Configuration - Export Reports, and leave 'Export "
            "filename' EMPTY there so TWS writes one dated file per trading "
            "day. Without this archive a fill that happens while the Bridge is "
            "off cannot be recovered. This is why the Bridge is run with TWS "
            "and not with IB Gateway: the Gateway has no such function "
            "(T1-207, verified in its configuration tree)."
        ),
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
