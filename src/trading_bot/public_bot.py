from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from hyperliquid import HyperliquidClient, HyperliquidConfig, HyperliquidRateLimitError
from revolut_x import RevolutXClient, RevolutXConfig, RevolutXRateLimitError
from trading_bot.config import AppConfig
from trading_bot.paper_engine import PaperEngine
from trading_bot.storage import TradingStorage, utc_now_iso


class PublicTradingBot:
    def __init__(self, config: AppConfig, storage: TradingStorage) -> None:
        self.config = config
        self.storage = storage
        self.market_data_provider_key = config.simulation_provider
        self.market_data_provider_label = config.simulation_provider.replace("_", " ").title()
        self.trade_feed_scope = "global"
        self.candles_supported = False
        self.auth_enabled = False
        if config.simulation_provider == "HYPERLIQUID":
            client_config = HyperliquidConfig.from_env()
            client_config.info_url = config.base_url
            self.client = HyperliquidClient(client_config)
            self.market_data_provider_label = "Hyperliquid"
            self.trade_feed_scope = "symbol"
            self.candles_supported = True
        else:
            client_config = RevolutXConfig.from_env()
            client_config.base_url = config.base_url
            self.client = RevolutXClient(client_config)
            self.market_data_provider_label = "Revolut X"
            self.trade_feed_scope = "global"
            self.candles_supported = True
            self.auth_enabled = self.client.has_auth_configured()
        self.paper_engine = PaperEngine(config, storage)
        self._last_candles_refresh = 0.0
        self._last_public_trades_refresh = 0.0
        self._api_backoff_until = 0.0
        self._auth_backoff_until = 0.0

    def initialize(self) -> None:
        self.storage.init_db()
        self.storage.set_state("bot_mode", "PUBLIC_SIM")
        self.storage.set_state("bot_status", "starting")
        self.storage.set_state(
            "bot_data_mode",
            "public+auth"
            if self.auth_enabled
            else ("public+candles" if self.candles_supported else "public-only"),
        )
        self.storage.set_state(
            "auth_context_enabled",
            "true" if self.candles_supported else "false",
        )
        self.storage.set_state("bot_market_data_provider_key", self.market_data_provider_key)
        self.storage.set_state(
            "bot_market_data_provider_label", self.market_data_provider_label
        )
        self.storage.set_state("bot_rate_limit_until", "")
        self.storage.set_state("bot_cycle_error_count", "0")
        self.storage.log_event(
            "INFO",
            "public_bot",
            "Bot di simulazione pubblica inizializzato",
            {
                "base_url": self.config.base_url,
                "market_data_provider": self.market_data_provider_label,
                "symbols": self.config.monitored_symbols,
                "poll_interval_seconds": self.config.poll_interval_seconds,
            },
        )
        self.paper_engine.initialize_account()

    def run_cycle(self) -> dict[str, Any]:
        monotonic_now = time.monotonic()
        cycle_at = utc_now_iso()
        if monotonic_now < self._api_backoff_until:
            remaining = max(self._api_backoff_until - monotonic_now, 0.0)
            self.storage.set_state("bot_status", "rate_limited")
            self.storage.set_state("bot_last_cycle_at", cycle_at)
            self.storage.set_state(
                "bot_last_error",
                f"Backoff rate limit attivo per altri {remaining:.1f}s.",
            )
            return {
                "cycle_at": cycle_at,
                "skipped": True,
                "reason": "rate_limit_backoff",
                "retry_in_seconds": round(remaining, 2),
            }

        inserted_trades = 0
        snapshot_ids: dict[str, int] = {}
        try:
            inserted_trades = self._refresh_public_trades(monotonic_now)
            snapshot_ids = self._refresh_order_books()
        except (RevolutXRateLimitError, HyperliquidRateLimitError) as exc:
            return self._handle_rate_limit(cycle_at, exc)

        candles_updated = self._refresh_candles_context()
        self.paper_engine.run_once()
        self.storage.record_equity_snapshot(
            symbols=self.config.monitored_symbols,
            paper_start_balance=self.config.paper_start_balance,
        )
        if self.config.daily_report_enabled:
            daily_report = self.storage.build_daily_report_snapshot(
                symbols=self.config.monitored_symbols,
                paper_start_balance=self.config.paper_start_balance,
                candles_interval_minutes=self.config.candles_interval_minutes,
            )
            self.storage.upsert_daily_report(daily_report["date"], daily_report)
        self.storage.set_state("bot_status", "running")
        self.storage.set_state("bot_last_cycle_at", cycle_at)
        self.storage.set_state("bot_rate_limit_until", "")
        self.storage.set_state("bot_last_error", "")
        self.storage.set_state("bot_cycle_error_count", "0")
        self.paper_engine.risk_manager.clear_health_kill_switch()

        cycle_summary = {
            "cycle_at": cycle_at,
            "inserted_trades": inserted_trades,
            "symbols": self.config.monitored_symbols,
            "snapshot_ids": snapshot_ids,
            "candles_updated": candles_updated,
        }
        self.storage.log_event(
            "INFO",
            "public_bot",
            "Ciclo bot completato",
            cycle_summary,
        )
        return cycle_summary

    def _refresh_public_trades(self, monotonic_now: float) -> int:
        if (
            monotonic_now - self._last_public_trades_refresh
        ) < self.config.public_trades_refresh_seconds:
            return 0
        inserted = 0
        if self.trade_feed_scope == "symbol":
            for index, symbol in enumerate(self.config.monitored_symbols):
                trades_payload = self.client.get_public_last_trades(symbol)
                inserted += self.storage.insert_public_trades(trades_payload)
                if (
                    index < len(self.config.monitored_symbols) - 1
                    and self.config.public_request_spacing_seconds > 0
                ):
                    time.sleep(self.config.public_request_spacing_seconds)
        else:
            trades_payload = self.client.get_public_last_trades()
            inserted = self.storage.insert_public_trades(trades_payload)
        self._last_public_trades_refresh = monotonic_now
        return inserted

    def _refresh_order_books(self) -> dict[str, int]:
        snapshot_ids: dict[str, int] = {}
        for index, symbol in enumerate(self.config.monitored_symbols):
            order_book_payload = self.client.get_public_order_book(symbol)
            snapshot_ids[symbol] = self.storage.insert_order_book_snapshot(symbol, order_book_payload)
            if (
                index < len(self.config.monitored_symbols) - 1
                and self.config.public_request_spacing_seconds > 0
            ):
                time.sleep(self.config.public_request_spacing_seconds)
        return snapshot_ids

    def _handle_rate_limit(
        self,
        cycle_at: str,
        exc: Exception,
    ) -> dict[str, Any]:
        retry_after_seconds = getattr(exc, "retry_after_seconds", None)
        backoff_seconds = max(
            retry_after_seconds or 0.0,
            self.config.rate_limit_backoff_seconds,
            self.config.poll_interval_seconds * 2,
        )
        self._api_backoff_until = time.monotonic() + backoff_seconds
        self.paper_engine.risk_manager.clear_health_kill_switch()
        backoff_until = (
            datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)
        ).isoformat(timespec="seconds").replace("+00:00", "Z")
        self.storage.set_state("bot_status", "rate_limited")
        self.storage.set_state("bot_last_cycle_at", cycle_at)
        self.storage.set_state("bot_last_error", str(exc))
        self.storage.set_state("bot_cycle_error_count", "0")
        self.storage.set_state("bot_rate_limit_until", backoff_until)
        self.storage.log_event(
            "WARNING",
            "public_bot",
            f"Rate limit {self.market_data_provider_label}: collector in backoff controllato",
            {
                "error": str(exc),
                "backoff_seconds": backoff_seconds,
            },
        )
        return {
            "cycle_at": cycle_at,
            "skipped": True,
            "reason": "rate_limited",
            "backoff_seconds": round(backoff_seconds, 2),
        }

    def handle_cycle_error(self, exc: Exception) -> None:
        current_errors = int(self.storage.get_state("bot_cycle_error_count", "0")) + 1
        self.storage.set_state("bot_cycle_error_count", str(current_errors))
        self.storage.set_state("bot_status", "error")
        self.storage.set_state("bot_last_error", str(exc))
        if current_errors >= self.config.max_consecutive_cycle_errors:
            self.paper_engine.risk_manager.activate_health_kill_switch(
                "Troppi errori consecutivi nel collector: nuove entrate bloccate finche il flusso dati non torna stabile."
            )
        self.storage.log_event(
            "ERROR",
            "public_bot",
            "Ciclo fallito",
            {"error": str(exc), "cycle_error_count": current_errors},
        )

    def _refresh_candles_context(self) -> int:
        if not self.candles_supported:
            return 0
        now = time.monotonic()
        if now < self._auth_backoff_until:
            return 0
        if (now - self._last_candles_refresh) < self.config.candles_refresh_seconds:
            return 0

        updated = 0
        for index, symbol in enumerate(self.config.monitored_symbols):
            try:
                payload = self.client.get_candles(
                    symbol,
                    interval=self.config.candles_interval_minutes,
                )
                updated += self.storage.insert_candles(
                    symbol=symbol,
                    interval_minutes=self.config.candles_interval_minutes,
                    payload=payload,
                )
                if (
                    index < len(self.config.monitored_symbols) - 1
                    and self.config.public_request_spacing_seconds > 0
                ):
                    time.sleep(self.config.public_request_spacing_seconds)
            except (RevolutXRateLimitError, HyperliquidRateLimitError) as exc:
                backoff_seconds = max(
                    getattr(exc, "retry_after_seconds", None) or 0.0,
                    self.config.rate_limit_backoff_seconds,
                )
                self._auth_backoff_until = time.monotonic() + backoff_seconds
                self.storage.log_event(
                    "WARNING",
                    "public_bot",
                    f"Aggiornamento candele {self.market_data_provider_label} in backoff per rate limit",
                    {
                        "symbol": symbol,
                        "error": str(exc),
                        "backoff_seconds": backoff_seconds,
                    },
                )
                break
            except Exception as exc:
                self.storage.log_event(
                    "WARNING",
                    "public_bot",
                    f"Aggiornamento candele fallito per {symbol}",
                    {"error": str(exc)},
                )
        self._last_candles_refresh = now
        return updated
