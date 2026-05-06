from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from hyperliquid import DEFAULT_INFO_URL
from revolut_x import DEFAULT_PROD_BASE_URL
from trading_bot.providers import DEFAULT_PROVIDER_KEY, get_provider_profile


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_symbols(raw: str) -> list[str]:
    symbols = [item.strip().upper().replace("/", "-") for item in raw.split(",") if item.strip()]
    if not symbols:
        raise ValueError("At least one monitored symbol is required.")
    quote_currencies = {symbol.split("-")[1] for symbol in symbols if "-" in symbol}
    if len(quote_currencies) != 1:
        raise ValueError(
            "For the first paper-trading version, use symbols with the same quote currency."
        )
    return symbols


@dataclass(slots=True)
class AppConfig:
    base_url: str
    monitored_symbols: list[str]
    entry_enabled_symbols: list[str]
    db_path: Path
    poll_interval_seconds: float
    public_trades_refresh_seconds: float
    public_request_spacing_seconds: float
    rate_limit_backoff_seconds: float
    candles_interval_minutes: int
    candles_refresh_seconds: float
    paper_start_balance: float
    paper_trade_size: float
    simulation_provider: str
    perps_default_leverage: float
    perps_margin_mode: str
    perps_execution_policy: str
    short_entries_enabled: bool
    reduce_only_exits_enabled: bool
    max_open_positions: int
    max_total_exposure_pct: float
    max_trade_allocation_pct: float
    min_cash_reserve_pct: float
    max_risk_per_trade_pct: float
    min_order_notional_eur: float
    daily_loss_limit_pct: float
    max_drawdown_pct: float
    daily_trade_limit: int
    max_consecutive_losses: int
    cooldown_after_trade_minutes: float
    cooldown_after_loss_minutes: float
    max_consecutive_cycle_errors: int
    dashboard_host: str
    dashboard_port: int
    quote_currency: str
    recurring_contribution_enabled: bool
    recurring_contribution_amount: float
    recurring_contribution_frequency: str
    recurring_contribution_month_day: int
    recurring_contribution_weekday: int
    recurring_contribution_start_mode: str
    experiment_name: str
    experiment_notes: str
    experiment_freeze_enabled: bool
    daily_report_enabled: bool

    @classmethod
    def from_env(cls) -> "AppConfig":
        provider = get_provider_profile(
            os.getenv("SIMULATION_PROVIDER", DEFAULT_PROVIDER_KEY).strip().upper()
        )
        if provider.key == "HYPERLIQUID":
            symbols = _parse_symbols(
                os.getenv(
                    "HYPERLIQUID_MONITORED_SYMBOLS",
                    "BTC-USD,ETH-USD,SOL-USD,XRP-USD,ADA-USD,DOGE-USD",
                )
            )
            base_url = os.getenv("HYPERLIQUID_INFO_URL", DEFAULT_INFO_URL)
        else:
            symbols = _parse_symbols(
                os.getenv("REVOLUT_X_MONITORED_SYMBOLS", "BTC-EUR,ETH-EUR")
            )
            base_url = os.getenv("REVOLUT_X_BASE_URL", DEFAULT_PROD_BASE_URL)
        entry_enabled_symbols = _parse_symbols(
            os.getenv("ENTRY_ENABLED_SYMBOLS", ",".join(symbols))
        )
        unknown_entry_symbols = sorted(set(entry_enabled_symbols) - set(symbols))
        if unknown_entry_symbols:
            raise ValueError(
                "ENTRY_ENABLED_SYMBOLS deve essere un sottoinsieme dei simboli monitorati: "
                + ", ".join(unknown_entry_symbols)
            )
        quote_currency = symbols[0].split("-")[1]
        return cls(
            base_url=base_url,
            monitored_symbols=symbols,
            entry_enabled_symbols=entry_enabled_symbols,
            db_path=Path(os.getenv("TRADING_DB_PATH", "data/trading.sqlite3")),
            poll_interval_seconds=float(os.getenv("BOT_POLL_INTERVAL_SECONDS", "15")),
            public_trades_refresh_seconds=float(
                os.getenv("PUBLIC_TRADES_REFRESH_SECONDS", "45")
            ),
            public_request_spacing_seconds=float(
                os.getenv("PUBLIC_REQUEST_SPACING_SECONDS", "0.35")
            ),
            rate_limit_backoff_seconds=float(
                os.getenv("RATE_LIMIT_BACKOFF_SECONDS", "60")
            ),
            candles_interval_minutes=int(os.getenv("CANDLES_INTERVAL_MINUTES", "5")),
            candles_refresh_seconds=float(os.getenv("CANDLES_REFRESH_SECONDS", "60")),
            paper_start_balance=float(os.getenv("PAPER_START_BALANCE", "500")),
            paper_trade_size=float(os.getenv("PAPER_TRADE_SIZE", "100")),
            simulation_provider=provider.key,
            perps_default_leverage=float(os.getenv("PERPS_DEFAULT_LEVERAGE", "3")),
            perps_margin_mode=os.getenv("PERPS_MARGIN_MODE", "ISOLATED").strip().upper(),
            perps_execution_policy=os.getenv("PERPS_EXECUTION_POLICY", "IOC").strip().upper(),
            short_entries_enabled=_env_bool("SHORT_ENTRIES_ENABLED", True),
            reduce_only_exits_enabled=_env_bool("REDUCE_ONLY_EXITS_ENABLED", True),
            max_open_positions=int(os.getenv("MAX_OPEN_POSITIONS", "2")),
            max_total_exposure_pct=float(os.getenv("MAX_TOTAL_EXPOSURE_PCT", "40")),
            max_trade_allocation_pct=float(os.getenv("MAX_TRADE_ALLOCATION_PCT", "20")),
            min_cash_reserve_pct=float(os.getenv("MIN_CASH_RESERVE_PCT", "20")),
            max_risk_per_trade_pct=float(os.getenv("MAX_RISK_PER_TRADE_PCT", "0.35")),
            min_order_notional_eur=float(os.getenv("MIN_ORDER_NOTIONAL_EUR", "50")),
            daily_loss_limit_pct=float(os.getenv("DAILY_LOSS_LIMIT_PCT", "2.0")),
            max_drawdown_pct=float(os.getenv("MAX_DRAWDOWN_PCT", "6.0")),
            daily_trade_limit=int(os.getenv("DAILY_TRADE_LIMIT", "10")),
            max_consecutive_losses=int(os.getenv("MAX_CONSECUTIVE_LOSSES", "3")),
            cooldown_after_trade_minutes=float(
                os.getenv("COOLDOWN_AFTER_TRADE_MINUTES", "4")
            ),
            cooldown_after_loss_minutes=float(
                os.getenv("COOLDOWN_AFTER_LOSS_MINUTES", "20")
            ),
            max_consecutive_cycle_errors=int(
                os.getenv("MAX_CONSECUTIVE_CYCLE_ERRORS", "3")
            ),
            dashboard_host=os.getenv("DASHBOARD_HOST", "127.0.0.1"),
            dashboard_port=int(os.getenv("DASHBOARD_PORT", "8765")),
            quote_currency=quote_currency,
            recurring_contribution_enabled=_env_bool(
                "PAPER_RECURRING_CONTRIBUTION_ENABLED", True
            ),
            recurring_contribution_amount=float(
                os.getenv("PAPER_RECURRING_CONTRIBUTION_AMOUNT", "200")
            ),
            recurring_contribution_frequency=os.getenv(
                "PAPER_RECURRING_CONTRIBUTION_FREQUENCY", "monthly"
            ).strip().lower(),
            recurring_contribution_month_day=int(
                os.getenv("PAPER_RECURRING_CONTRIBUTION_MONTH_DAY", "5")
            ),
            recurring_contribution_weekday=int(
                os.getenv("PAPER_RECURRING_CONTRIBUTION_WEEKDAY", "0")
            ),
            recurring_contribution_start_mode=os.getenv(
                "PAPER_RECURRING_CONTRIBUTION_START_MODE", "next_period"
            ).strip().lower(),
            experiment_name=os.getenv("EXPERIMENT_NAME", "paper_research_v1").strip(),
            experiment_notes=os.getenv(
                "EXPERIMENT_NOTES",
                "Esperimento paper con guard rail fissi e raccolta dati continua.",
            ).strip(),
            experiment_freeze_enabled=_env_bool("EXPERIMENT_FREEZE_ENABLED", True),
            daily_report_enabled=_env_bool("DAILY_REPORT_ENABLED", True),
        )
