from __future__ import annotations

import hashlib
import json
import math
from calendar import monthrange
from datetime import datetime
from typing import Any

from trading_bot.config import AppConfig
from trading_bot.providers import get_provider_profile, provider_state_items
from trading_bot.risk_manager import RiskManager
from trading_bot.storage import TradingStorage, parse_iso8601, utc_now_iso


class PaperEngine:
    strategy_name = "momentum_context_v9"
    strategy_description = (
        "Taratura data-led su feed Hyperliquid: dopo il campione v8 concentro le nuove entrate sul simbolo "
        "con migliore evidenza netta, mantengo il resto in osservazione e separo gli short dal test operativo "
        "finche non dimostrano edge senza outlier da esecuzione non continua."
    )
    imbalance_metric_label = "log_depth_pressure_v1"
    entry_momentum_threshold = 0.0006
    candle_trend_threshold = 0.0008
    long_book_imbalance_threshold = 0.02
    short_book_imbalance_threshold = -0.02
    volatility_floor_pct = 0.0008
    volatility_ceiling_pct = 0.012
    minimum_recent_trade_count = 8
    spread_limit_bps = 12.0
    stop_loss_pct = 0.003
    take_profit_pct = 0.005
    reward_to_risk_ratio = 1.8
    exit_reverse_threshold = -0.00015
    imbalance_reverse_threshold = -0.18
    short_exit_reverse_threshold = 0.00015
    short_imbalance_reverse_threshold = 0.18
    max_hold_minutes = 30
    emergency_exit_discount_pct = 0.0025
    emergency_cover_premium_pct = 0.0025

    def __init__(self, config: AppConfig, storage: TradingStorage) -> None:
        self.config = config
        self.storage = storage
        self.risk_manager = RiskManager(config, storage)

    def initialize_account(self) -> None:
        current_start_balance = self.storage.get_state("paper_start_balance")
        if self.storage.get_state("paper_cash") is None:
            self.storage.set_state("paper_cash", f"{self.config.paper_start_balance:.8f}")
            self.storage.set_state(
                "paper_start_balance", f"{self.config.paper_start_balance:.8f}"
            )
            self.storage.set_state(
                "paper_contributed_capital_total", f"{self.config.paper_start_balance:.8f}"
            )
            self.storage.log_event(
                "INFO",
                "paper_engine",
                "Conto paper inizializzato",
                {
                    "saldo_iniziale": self.config.paper_start_balance,
                    "valuta_portafoglio": self.config.quote_currency,
                },
            )
            self.storage.log_ledger_event(
                event_type="deposit",
                title="Capitale paper iniziale registrato",
                mode="PAPER",
                payload={
                    "amount_eur": self.config.paper_start_balance,
                    "currency": self.config.quote_currency,
                },
            )
        elif current_start_balance is not None:
            previous_start_balance = float(current_start_balance)
            delta = self.config.paper_start_balance - previous_start_balance
            if abs(delta) > 1e-9:
                current_cash = float(
                    self.storage.get_state("paper_cash", str(self.config.paper_start_balance))
                )
                current_contributed = float(
                    self.storage.get_state(
                        "paper_contributed_capital_total", current_start_balance
                    )
                )
                updated_cash = current_cash + delta
                updated_contributed = current_contributed + delta
                self.storage.set_state("paper_cash", f"{updated_cash:.8f}")
                self.storage.set_state(
                    "paper_start_balance", f"{self.config.paper_start_balance:.8f}"
                )
                self.storage.set_state(
                    "paper_contributed_capital_total", f"{updated_contributed:.8f}"
                )
                self.storage.log_event(
                    "INFO",
                    "paper_engine",
                    "Capitale iniziale paper riallineato",
                    {
                        "saldo_precedente": previous_start_balance,
                        "saldo_nuovo": self.config.paper_start_balance,
                        "delta_eur": delta,
                    },
                )
                self.storage.log_ledger_event(
                    event_type="deposit" if delta > 0 else "withdrawal",
                    title="Capitale iniziale paper riallineato",
                    mode="PAPER",
                    payload={
                        "delta_eur": delta,
                        "previous_start_balance": previous_start_balance,
                        "new_start_balance": self.config.paper_start_balance,
                    },
                )
        else:
            legacy_start_balance = 100.0
            if abs(self.config.paper_start_balance - legacy_start_balance) > 1e-9:
                current_cash = float(
                    self.storage.get_state("paper_cash", str(legacy_start_balance))
                )
                current_contributed = float(
                    self.storage.get_state(
                        "paper_contributed_capital_total", str(legacy_start_balance)
                    )
                )
                updated_cash = current_cash + (
                    self.config.paper_start_balance - legacy_start_balance
                )
                updated_contributed = current_contributed + (
                    self.config.paper_start_balance - legacy_start_balance
                )
                self.storage.set_state("paper_cash", f"{updated_cash:.8f}")
                self.storage.set_state(
                    "paper_contributed_capital_total", f"{updated_contributed:.8f}"
                )
                self.storage.log_event(
                    "INFO",
                    "paper_engine",
                    "Capitale paper riallineato dal default storico",
                    {
                        "saldo_storico_assunto": legacy_start_balance,
                        "saldo_nuovo": self.config.paper_start_balance,
                        "delta_eur": self.config.paper_start_balance - legacy_start_balance,
                    },
                )
                self.storage.log_ledger_event(
                    event_type=(
                        "deposit"
                        if self.config.paper_start_balance >= legacy_start_balance
                        else "withdrawal"
                    ),
                    title="Capitale paper riallineato dal default storico",
                    mode="PAPER",
                    payload={
                        "legacy_start_balance": legacy_start_balance,
                        "new_start_balance": self.config.paper_start_balance,
                        "delta_eur": self.config.paper_start_balance - legacy_start_balance,
                    },
                )
            self.storage.set_state(
                "paper_start_balance", f"{self.config.paper_start_balance:.8f}"
            )

        if self.storage.get_state("paper_contributed_capital_total") is None:
            self.storage.set_state(
                "paper_contributed_capital_total", f"{self.config.paper_start_balance:.8f}"
            )

        self._sync_experiment_state()
        self._apply_recurring_contribution_if_due()
        self._sync_provider_state()
        self.storage.set_state("portfolio_currency", self.config.quote_currency)
        self.storage.set_state("strategy_name", self.strategy_name)
        self.storage.set_state("strategy_description", self.strategy_description)
        self.storage.set_state("imbalance_metric_label", self.imbalance_metric_label)
        self.storage.set_state("experiment_name", self.config.experiment_name)
        self.storage.set_state("experiment_notes", self.config.experiment_notes)
        self.storage.set_state(
            "experiment_freeze_enabled",
            "true" if self.config.experiment_freeze_enabled else "false",
        )
        self.storage.set_state(
            "entry_momentum_threshold_pct",
            f"{self.entry_momentum_threshold * 100:.4f}",
        )
        self.storage.set_state(
            "candle_trend_threshold_pct",
            f"{self.candle_trend_threshold * 100:.4f}",
        )
        self.storage.set_state(
            "book_imbalance_threshold_pct",
            f"{self.long_book_imbalance_threshold * 100:.4f}",
        )
        self.storage.set_state(
            "book_imbalance_long_threshold_pct",
            f"{self.long_book_imbalance_threshold * 100:.4f}",
        )
        self.storage.set_state(
            "book_imbalance_short_threshold_pct",
            f"{self.short_book_imbalance_threshold * 100:.4f}",
        )
        self.storage.set_state(
            "volatility_floor_pct", f"{self.volatility_floor_pct * 100:.4f}"
        )
        self.storage.set_state(
            "volatility_ceiling_pct", f"{self.volatility_ceiling_pct * 100:.4f}"
        )
        self.storage.set_state(
            "minimum_recent_trade_count", str(self.minimum_recent_trade_count)
        )
        self.storage.set_state(
            "monitored_symbols", ",".join(self.config.monitored_symbols)
        )
        self.storage.set_state(
            "entry_enabled_symbols", ",".join(self.config.entry_enabled_symbols)
        )
        self.storage.set_state("spread_limit_bps", f"{self.spread_limit_bps:.2f}")
        self.storage.set_state("stop_loss_pct", f"{self.stop_loss_pct * 100:.2f}")
        self.storage.set_state("take_profit_pct", f"{self.take_profit_pct * 100:.2f}")
        self.storage.set_state(
            "reward_to_risk_ratio", f"{self.reward_to_risk_ratio:.2f}"
        )
        self.storage.set_state(
            "exit_reverse_threshold_pct", f"{self.exit_reverse_threshold * 100:.4f}"
        )
        self.storage.set_state(
            "imbalance_reverse_threshold_pct",
            f"{self.imbalance_reverse_threshold * 100:.4f}",
        )
        self.storage.set_state("max_hold_minutes", f"{self.max_hold_minutes:.0f}")
        self.storage.set_state("paper_trade_size", f"{self.config.paper_trade_size:.2f}")
        self.storage.set_state(
            "perps_default_leverage", f"{self.config.perps_default_leverage:.2f}"
        )
        self.storage.set_state("perps_margin_mode", self.config.perps_margin_mode)
        self.storage.set_state(
            "perps_execution_policy", self.config.perps_execution_policy
        )
        self.storage.set_state(
            "short_entries_enabled",
            "true" if self.config.short_entries_enabled else "false",
        )
        self.storage.set_state(
            "reduce_only_exits_enabled",
            "true" if self.config.reduce_only_exits_enabled else "false",
        )
        self.risk_manager.initialize()
        self._ensure_daily_operational_snapshot()

    def _sync_experiment_state(self) -> None:
        payload = {
            "experiment_name": self.config.experiment_name,
            "monitored_symbols": self.config.monitored_symbols,
            "quote_currency": self.config.quote_currency,
            "poll_interval_seconds": self.config.poll_interval_seconds,
            "candles_interval_minutes": self.config.candles_interval_minutes,
            "candles_refresh_seconds": self.config.candles_refresh_seconds,
            "paper_trade_size": self.config.paper_trade_size,
            "simulation_provider": self.config.simulation_provider,
            "entry_enabled_symbols": self.config.entry_enabled_symbols,
            "strategy_name": self.strategy_name,
            "imbalance_metric_label": self.imbalance_metric_label,
            "entry_momentum_threshold": self.entry_momentum_threshold,
            "candle_trend_threshold": self.candle_trend_threshold,
            "long_book_imbalance_threshold": self.long_book_imbalance_threshold,
            "short_book_imbalance_threshold": self.short_book_imbalance_threshold,
            "volatility_floor_pct": self.volatility_floor_pct,
            "volatility_ceiling_pct": self.volatility_ceiling_pct,
            "minimum_recent_trade_count": self.minimum_recent_trade_count,
            "spread_limit_bps": self.spread_limit_bps,
            "perps_default_leverage": self.config.perps_default_leverage,
            "perps_margin_mode": self.config.perps_margin_mode,
            "perps_execution_policy": self.config.perps_execution_policy,
            "short_entries_enabled": self.config.short_entries_enabled,
            "reduce_only_exits_enabled": self.config.reduce_only_exits_enabled,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "reward_to_risk_ratio": self.reward_to_risk_ratio,
            "exit_reverse_threshold": self.exit_reverse_threshold,
            "imbalance_reverse_threshold": self.imbalance_reverse_threshold,
            "max_hold_minutes": self.max_hold_minutes,
            "max_open_positions": self.config.max_open_positions,
            "max_total_exposure_pct": self.config.max_total_exposure_pct,
            "max_trade_allocation_pct": self.config.max_trade_allocation_pct,
            "min_cash_reserve_pct": self.config.min_cash_reserve_pct,
            "max_risk_per_trade_pct": self.config.max_risk_per_trade_pct,
            "min_order_notional_eur": self.config.min_order_notional_eur,
            "daily_loss_limit_pct": self.config.daily_loss_limit_pct,
            "max_drawdown_pct": self.config.max_drawdown_pct,
            "daily_trade_limit": self.config.daily_trade_limit,
            "max_consecutive_losses": self.config.max_consecutive_losses,
            "cooldown_after_trade_minutes": self.config.cooldown_after_trade_minutes,
            "cooldown_after_loss_minutes": self.config.cooldown_after_loss_minutes,
        }
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()[:16]
        self.storage.set_state("experiment_current_fingerprint", fingerprint)
        self.storage.set_state("experiment_name", self.config.experiment_name)
        self.storage.set_state(
            "experiment_freeze_enabled",
            "true" if self.config.experiment_freeze_enabled else "false",
        )
        baseline = self.storage.get_state("experiment_baseline_fingerprint")
        if not baseline:
            self.storage.set_state("experiment_baseline_fingerprint", fingerprint)
            self.storage.set_state("experiment_drift_detected", "false")
            self.storage.log_event(
                "INFO",
                "paper_engine",
                "Baseline esperimento registrata",
                {"fingerprint": fingerprint, "config": payload},
            )
            self.storage.log_ledger_event(
                event_type="strategy_change",
                title="Baseline strategica registrata",
                mode="PAPER",
                payload={"fingerprint": fingerprint, "config": payload},
            )
            return
        if baseline == fingerprint:
            if self.storage.get_state("experiment_drift_detected", "false") == "true":
                self.storage.log_event(
                    "INFO",
                    "paper_engine",
                    "Rientro sulla baseline dell'esperimento",
                    {"baseline": baseline, "current": fingerprint},
                )
            self.storage.set_state("experiment_drift_detected", "false")
            self.storage.set_state("experiment_drift_detected_at", "")
            return
        self.storage.set_state("experiment_drift_detected", "true")
        if not self.storage.get_state("experiment_drift_detected_at"):
            self.storage.set_state("experiment_drift_detected_at", utc_now_iso())
        last_reported = self.storage.get_state("experiment_last_reported_drift_fingerprint")
        if last_reported == fingerprint:
            return
        self.storage.set_state("experiment_last_reported_drift_fingerprint", fingerprint)
        self.storage.log_event(
            "WARNING",
            "paper_engine",
            (
                "La configurazione del desk e cambiata rispetto alla baseline dell'esperimento. "
                "Le statistiche future non sono piu perfettamente comparabili."
            ),
            {
                "baseline_fingerprint": baseline,
                "current_fingerprint": fingerprint,
                "freeze_enabled": self.config.experiment_freeze_enabled,
                "config": payload,
            },
        )
        self.storage.log_ledger_event(
            event_type="strategy_change",
            title="Drift configurazione rispetto alla baseline",
            mode="PAPER",
            level="WARNING",
            payload={
                "baseline_fingerprint": baseline,
                "current_fingerprint": fingerprint,
            },
        )

    def _apply_recurring_contribution_if_due(self) -> None:
        self.storage.set_state(
            "paper_recurring_contribution_enabled",
            "true" if self.config.recurring_contribution_enabled else "false",
        )
        self.storage.set_state(
            "paper_recurring_contribution_amount",
            f"{self.config.recurring_contribution_amount:.2f}",
        )
        self.storage.set_state(
            "paper_recurring_contribution_frequency",
            self.config.recurring_contribution_frequency,
        )
        self.storage.set_state(
            "paper_recurring_contribution_month_day",
            str(self.config.recurring_contribution_month_day),
        )
        self.storage.set_state(
            "paper_recurring_contribution_weekday",
            str(self.config.recurring_contribution_weekday),
        )
        self.storage.set_state(
            "paper_recurring_contribution_start_mode",
            self.config.recurring_contribution_start_mode,
        )

        if (
            not self.config.recurring_contribution_enabled
            or self.config.recurring_contribution_amount <= 0
        ):
            return

        now = datetime.now().astimezone()
        frequency = self.config.recurring_contribution_frequency
        period_key = ""
        due = False
        if frequency == "monthly":
            scheduled_day = min(
                max(self.config.recurring_contribution_month_day, 1),
                monthrange(now.year, now.month)[1],
            )
            due = now.day >= scheduled_day
            period_key = f"{now.year:04d}-{now.month:02d}"
        elif frequency == "weekly":
            scheduled_weekday = min(max(self.config.recurring_contribution_weekday, 0), 6)
            due = now.weekday() >= scheduled_weekday
            iso_year, iso_week, _ = now.isocalendar()
            period_key = f"{iso_year:04d}-W{iso_week:02d}"
        else:
            self.storage.log_event(
                "WARNING",
                "paper_engine",
                "Frequenza versamento paper non riconosciuta",
                {"frequency": frequency},
            )
            return

        current_period = self.storage.get_state("paper_last_contribution_period")
        if (
            current_period is None
            and self.config.recurring_contribution_start_mode == "next_period"
        ):
            self.storage.set_state("paper_last_contribution_period", period_key)
            self.storage.log_event(
                "INFO",
                "paper_engine",
                "Piano versamenti paper attivato",
                {
                    "start_mode": self.config.recurring_contribution_start_mode,
                    "first_effective_period": "prossimo periodo utile",
                    "seeded_period_key": period_key,
                },
            )
            self.storage.log_ledger_event(
                event_type="workflow_note",
                title="Piano versamenti paper attivato",
                mode="PAPER",
                payload={
                    "start_mode": self.config.recurring_contribution_start_mode,
                    "first_effective_period": "next_period",
                    "period_key": period_key,
                },
            )
            return

        if not due:
            return
        if current_period == period_key:
            return

        cash = float(self.storage.get_state("paper_cash", str(self.config.paper_start_balance)))
        contributed = float(
            self.storage.get_state(
                "paper_contributed_capital_total", str(self.config.paper_start_balance)
            )
        )
        new_cash = cash + self.config.recurring_contribution_amount
        new_contributed = contributed + self.config.recurring_contribution_amount
        self.storage.set_state("paper_cash", f"{new_cash:.8f}")
        self.storage.set_state(
            "paper_contributed_capital_total", f"{new_contributed:.8f}"
        )
        self.storage.set_state("paper_last_contribution_period", period_key)
        self.storage.set_state(
            "paper_recurring_contribution_last_at",
            now.isoformat(timespec="seconds"),
        )
        self.storage.log_event(
            "INFO",
            "paper_engine",
            "Versamento paper ricorrente applicato",
            {
                "amount_eur": self.config.recurring_contribution_amount,
                "frequency": frequency,
                "period_key": period_key,
                "new_cash_eur": new_cash,
                "contributed_capital_total_eur": new_contributed,
            },
        )
        self.storage.log_ledger_event(
            event_type="deposit",
            title="Versamento paper ricorrente applicato",
            mode="PAPER",
            payload={
                "amount_eur": self.config.recurring_contribution_amount,
                "frequency": frequency,
                "period_key": period_key,
                "new_cash_eur": new_cash,
            },
        )

    def run_once(self) -> None:
        self.initialize_account()
        self.risk_manager.refresh_runtime_state(self.config.monitored_symbols)
        for symbol in self.config.monitored_symbols:
            self._evaluate_symbol(symbol)
        self.risk_manager.refresh_runtime_state(self.config.monitored_symbols)

    def _evaluate_symbol(self, symbol: str) -> None:
        rows = self.storage.get_recent_snapshots(symbol, limit=8)
        if len(rows) < 6:
            self._save_analysis(
                symbol,
                status="DATI_INSUFFICIENTI",
                action="ATTENDI",
                reason="Sto aspettando abbastanza snapshot dell'order book per misurare il momentum.",
                details={"snapshots_necessari": 6, "snapshots_disponibili": len(rows)},
                filter_code="insufficient_snapshots",
            )
            return

        ordered = list(reversed(rows))
        mids = [float(row["mid_price"]) for row in ordered if row["mid_price"] is not None]
        if len(mids) < 6:
            self._save_analysis(
                symbol,
                status="DATI_INSUFFICIENTI",
                action="ATTENDI",
                reason="Negli ultimi snapshot mancano alcuni prezzi medi, quindi il segnale non e ancora affidabile.",
                details={"snapshot_con_mid_validi": len(mids)},
                filter_code="missing_mid_prices",
            )
            return

        current = ordered[-1]
        if (
            current["best_ask"] is None
            or current["best_bid"] is None
            or current["mid_price"] is None
        ):
            self._save_analysis(
                symbol,
                status="DATI_INSUFFICIENTI",
                action="ATTENDI",
                reason="L'ultimo order book e incompleto, quindi non posso prendere una decisione.",
                details={},
                filter_code="incomplete_order_book",
            )
            return

        best_ask = float(current["best_ask"])
        best_bid = float(current["best_bid"])
        current_mid = float(current["mid_price"])
        short_ma = sum(mids[-3:]) / 3
        long_ma = sum(mids[-6:]) / 6
        momentum = (short_ma / long_ma) - 1
        spread_bps = ((best_ask - best_bid) / current_mid) * 10000 if current_mid else 0.0
        asks = self.storage.get_order_book_levels(int(current["id"]), "ask", limit=8)
        bids = self.storage.get_order_book_levels(int(current["id"]), "bid", limit=8)
        book_imbalance = self._book_imbalance(bids, asks)

        candles = list(
            reversed(
                self.storage.get_recent_candles(
                    symbol,
                    interval_minutes=self.config.candles_interval_minutes,
                    limit=12,
                )
            )
        )
        candle_closes = [float(row["close"]) for row in candles]
        candle_trend = None
        candle_volatility = None
        if len(candle_closes) >= 6:
            candle_average = sum(candle_closes[-6:]) / 6
            candle_trend = (candle_closes[-1] / candle_average) - 1
            recent_ranges = [
                (float(row["high"]) - float(row["low"])) / float(row["close"])
                for row in candles[-6:]
                if float(row["close"]) > 0
            ]
            candle_volatility = (
                sum(recent_ranges) / len(recent_ranges) if recent_ranges else None
            )

        trade_activity = self.storage.get_trade_activity(symbol)
        fee_profile = self._current_provider()
        taker_fee_rate = fee_profile.taker_fee_rate
        risk_runtime = self.risk_manager.refresh_runtime_state(self.config.monitored_symbols)

        base_details = {
            "short_ma": short_ma,
            "long_ma": long_ma,
            "momentum_pct": momentum * 100,
            "candle_trend_pct": candle_trend * 100 if candle_trend is not None else None,
            "candle_volatility_pct": (
                candle_volatility * 100 if candle_volatility is not None else None
            ),
            "book_imbalance_pct": (
                book_imbalance * 100 if book_imbalance is not None else None
            ),
            "book_imbalance_metric": self.imbalance_metric_label,
            "spread_bps": spread_bps,
            "spread_limit_bps": self.spread_limit_bps,
            "entry_momentum_threshold_pct": self.entry_momentum_threshold * 100,
            "candle_trend_threshold_pct": self.candle_trend_threshold * 100,
            "book_imbalance_threshold_pct": self.long_book_imbalance_threshold * 100,
            "long_book_imbalance_threshold_pct": self.long_book_imbalance_threshold * 100,
            "short_book_imbalance_threshold_pct": self.short_book_imbalance_threshold * 100,
            "volatility_floor_pct": self.volatility_floor_pct * 100,
            "volatility_ceiling_pct": self.volatility_ceiling_pct * 100,
            "minimum_recent_trade_count": self.minimum_recent_trade_count,
            "recent_trade_count": trade_activity["count"],
            "recent_trade_volume": trade_activity.get("recent_volume", 0.0),
            "best_bid": best_bid,
            "best_ask": best_ask,
            "latest_mid": current_mid,
            "candle_context_ready": candle_trend is not None,
            "provider_label": fee_profile.label,
            "provider_key": fee_profile.key,
            "maker_fee_rate_pct": fee_profile.maker_fee_rate * 100,
            "taker_fee_rate_pct": fee_profile.taker_fee_rate * 100,
            "ordine_paper_eur": self.config.paper_trade_size,
            "guardrail_status": risk_runtime["guardrail_status"],
            "risk_trading_enabled": risk_runtime["trading_enabled"],
            "risk_kill_reason": risk_runtime["kill_reason"],
            "current_exposure_eur": risk_runtime["current_exposure_eur"],
            "current_exposure_pct": risk_runtime["current_exposure_pct"],
            "perps_default_leverage": self.config.perps_default_leverage,
            "perps_margin_mode": self.config.perps_margin_mode,
            "perps_execution_policy": self.config.perps_execution_policy,
            "short_entries_enabled": self.config.short_entries_enabled,
            "reduce_only_exits_enabled": self.config.reduce_only_exits_enabled,
        }

        open_position = self.storage.get_open_position(symbol)
        if open_position:
            self._maybe_close_position(
                symbol=symbol,
                position=open_position,
                current_snapshot=current,
                bids=bids,
                asks=asks,
                momentum=momentum,
                book_imbalance=book_imbalance,
                details=base_details,
                taker_fee_rate=taker_fee_rate,
            )
            return

        if symbol not in self.config.entry_enabled_symbols:
            self._save_analysis(
                symbol,
                status="WATCH_ONLY",
                action="ATTENDI",
                reason="Il simbolo resta monitorato ma in questa taratura non apro nuove entrate su di lui.",
                details={
                    **base_details,
                    "entry_enabled_symbols": self.config.entry_enabled_symbols,
                    "prossima_condizione": (
                        "Resta in osservazione. Lo riabilito per le entrate solo dopo nuova evidenza statistica."
                    ),
                },
                filter_code="symbol_watch_only",
            )
            return

        if spread_bps > self.spread_limit_bps:
            self._save_analysis(
                symbol,
                status="BLOCCATO",
                action="ATTENDI",
                reason="Lo spread e troppo largo: entrerei pagando troppo in partenza.",
                details={
                    **base_details,
                    "prossima_condizione": (
                        f"Aspetto che lo spread scenda sotto {self.spread_limit_bps:.2f} bps."
                    ),
                },
                filter_code="spread_too_wide",
            )
            return

        if trade_activity["count"] < self.minimum_recent_trade_count:
            self._save_analysis(
                symbol,
                status="OSSERVAZIONE",
                action="ATTENDI",
                reason="Il flusso di trade recenti e troppo scarso per un ingresso disciplinato.",
                details={
                    **base_details,
                    "prossima_condizione": (
                        "Entro solo con almeno "
                        f"{self.minimum_recent_trade_count} trade recenti nel feed pubblico."
                    ),
                },
                filter_code="recent_trade_flow_too_low",
            )
            return

        if candle_trend is None or candle_volatility is None:
            self._save_analysis(
                symbol,
                status="ATTESA_CANDELE",
                action="ATTENDI",
                reason="Mi manca ancora contesto sufficiente dalle candele autenticate.",
                details={
                    **base_details,
                    "prossima_condizione": (
                        "Mi servono almeno 6 candele recenti per valutare trend e volatilita."
                    ),
                },
                filter_code="awaiting_candles",
            )
            return

        if candle_volatility < self.volatility_floor_pct:
            self._save_analysis(
                symbol,
                status="OSSERVAZIONE",
                action="ATTENDI",
                reason="La volatilita recente e troppo bassa: rischio un trade senza spinta vera.",
                details={
                    **base_details,
                    "prossima_condizione": (
                        "Aspetto una volatilita media sopra "
                        f"{self.volatility_floor_pct * 100:.4f}%."
                    ),
                },
                filter_code="volatility_too_low",
            )
            return

        if candle_volatility > self.volatility_ceiling_pct:
            self._save_analysis(
                symbol,
                status="BLOCCATO",
                action="ATTENDI",
                reason="La volatilita recente e troppo alta per il profilo di rischio attuale.",
                details={
                    **base_details,
                    "prossima_condizione": (
                        "Rientro solo quando la volatilita media torna sotto "
                        f"{self.volatility_ceiling_pct * 100:.4f}%."
                    ),
                },
                filter_code="volatility_too_high",
            )
            return

        direction_setups = [
            self._evaluate_direction_setup(
                side="LONG",
                momentum=momentum,
                candle_trend=candle_trend,
                book_imbalance=book_imbalance,
            )
        ]
        if self.config.short_entries_enabled:
            direction_setups.append(
                self._evaluate_direction_setup(
                    side="SHORT",
                    momentum=momentum,
                    candle_trend=candle_trend,
                    book_imbalance=book_imbalance,
                )
            )

        ready_setups = [item for item in direction_setups if item["ready"]]
        selected_setup = (
            max(ready_setups, key=lambda item: item["score"])
            if ready_setups
            else max(direction_setups, key=lambda item: item["score"])
        )

        if not selected_setup["ready"]:
            self._save_analysis(
                symbol,
                status="OSSERVAZIONE",
                action="ATTENDI",
                reason=selected_setup["reason"],
                details={
                    **base_details,
                    "decision_side": selected_setup["side"],
                    "decision_side_label": selected_setup["side_label"],
                    "direction_bias": selected_setup["side_label"],
                    "direction_score": selected_setup["score"],
                    "entry_action_label": selected_setup["entry_action"],
                    "prossima_condizione": selected_setup["next_condition"],
                },
                filter_code=selected_setup["filter_code"],
            )
            return

        dynamic_stop_pct = max(self.stop_loss_pct, candle_volatility * 0.9)
        dynamic_take_profit_pct = max(
            self.take_profit_pct,
            dynamic_stop_pct * self.reward_to_risk_ratio,
        )
        permission = self.risk_manager.evaluate_entry(
            symbol=symbol,
            requested_notional=self.config.paper_trade_size,
            stop_loss_pct=dynamic_stop_pct,
            leverage=self.config.perps_default_leverage,
            symbols=self.config.monitored_symbols,
        )
        if not permission.allowed:
            self._save_analysis(
                symbol,
                status="BLOCCATO",
                action="ATTENDI",
                reason=permission.reason,
                details={
                    **base_details,
                    "risk_manager": permission.details,
                    "prossima_condizione": "Il risk manager deve tornare in stato attivo.",
                },
                filter_code="risk_manager_block",
            )
            return

        cash = float(self.storage.get_state("paper_cash", str(self.config.paper_start_balance)))
        if selected_setup["side"] == "SHORT":
            execution = self._simulate_short_sell_fill(
                bids=bids,
                target_notional=permission.approved_notional,
                reference_price=best_bid,
                snapshot_id=int(current["id"]),
            )
        else:
            execution = self._simulate_buy_fill(
                asks=asks,
                target_notional=permission.approved_notional,
                reference_price=best_ask,
                snapshot_id=int(current["id"]),
            )
        if not execution["filled"]:
            self._save_analysis(
                symbol,
                status="BLOCCATO",
                action="ATTENDI",
                reason=(
                    "Profondita bid insufficiente per simulare un ingresso short credibile."
                    if selected_setup["side"] == "SHORT"
                    else "Profondita ask insufficiente per simulare un ingresso credibile."
                ),
                details={
                    **base_details,
                    "decision_side": selected_setup["side"],
                    "decision_side_label": selected_setup["side_label"],
                    "prossima_condizione": (
                        "Mi serve piu liquidita sul lato bid."
                        if selected_setup["side"] == "SHORT"
                        else "Mi serve piu liquidita sul lato ask."
                    ),
                },
                filter_code=(
                    "bid_depth_insufficient"
                    if selected_setup["side"] == "SHORT"
                    else "ask_depth_insufficient"
                ),
            )
            return

        entry_fee = execution["notional"] * taker_fee_rate
        margin_reserved = execution["notional"] / max(self.config.perps_default_leverage, 1.0)
        if (margin_reserved + entry_fee) > cash:
            self._save_analysis(
                symbol,
                status="BLOCCATO",
                action="ATTENDI",
                reason="La cassa paper non basta per coprire margine iniziale e fee del prossimo trade.",
                details={
                    **base_details,
                    "decision_side": selected_setup["side"],
                    "decision_side_label": selected_setup["side_label"],
                    "cassa_disponibile": cash,
                    "cassa_richiesta": margin_reserved + entry_fee,
                    "margin_required": margin_reserved,
                    "prossima_condizione": (
                        "Serve piu collateral libero oppure un ordine paper piu piccolo."
                    ),
                },
                filter_code="cash_insufficient",
            )
            return

        stop_loss_price = (
            execution["average_price"] * (1 - dynamic_stop_pct)
            if selected_setup["side"] == "LONG"
            else execution["average_price"] * (1 + dynamic_stop_pct)
        )
        take_profit_price = (
            execution["average_price"] * (1 + dynamic_take_profit_pct)
            if selected_setup["side"] == "LONG"
            else execution["average_price"] * (1 - dynamic_take_profit_pct)
        )
        planned_risk_eur = execution["notional"] * dynamic_stop_pct
        planned_reward_eur = execution["notional"] * dynamic_take_profit_pct
        entry_action = selected_setup["entry_action"]
        reason = (
            f"Apro una posizione {selected_setup['side_label'].lower()} paper: momentum "
            f"{momentum * 100:.4f}%, trend candele {candle_trend * 100:.4f}%, "
            f"imbalance {(book_imbalance * 100) if book_imbalance is not None else 0.0:.2f}% e spread {spread_bps:.2f} bps."
        )
        entry_context = {
            "snapshot_id": execution["snapshot_id"],
            "reference_price": execution["reference_price"],
            "average_price": execution["average_price"],
            "mid_price": current_mid,
            "position_side": selected_setup["side"],
            "direction_bias": selected_setup["side_label"],
            "spread_bps": spread_bps,
            "momentum_pct": momentum * 100,
            "candle_trend_pct": candle_trend * 100,
            "book_imbalance_pct": book_imbalance * 100 if book_imbalance is not None else None,
            "long_book_imbalance_threshold_pct": self.long_book_imbalance_threshold * 100,
            "short_book_imbalance_threshold_pct": self.short_book_imbalance_threshold * 100,
            "candle_volatility_pct": candle_volatility * 100,
            "recent_trade_count": trade_activity["count"],
            "provider_key": fee_profile.key,
            "provider_label": fee_profile.label,
            "slippage_pct": execution["slippage_pct"],
            "fill_levels": execution["fill_levels"],
            "notional_eur": execution["notional"],
            "quantity": execution["quantity"],
            "leverage": self.config.perps_default_leverage,
            "margin_mode": self.config.perps_margin_mode,
            "execution_policy": self.config.perps_execution_policy,
            "margin_reserved": margin_reserved,
            "reduce_only_exit": self.config.reduce_only_exits_enabled,
            "stop_loss_price": stop_loss_price,
            "take_profit_price": take_profit_price,
            "stop_loss_pct": dynamic_stop_pct * 100,
            "take_profit_pct": dynamic_take_profit_pct * 100,
            "planned_risk_eur": planned_risk_eur,
            "planned_reward_eur": planned_reward_eur,
            "risk_manager": permission.details,
        }
        position_id = self.storage.open_position(
            symbol=symbol,
            quote_currency=self.config.quote_currency,
            side=selected_setup["side"],
            strategy=self.strategy_name,
            quantity=execution["quantity"],
            entry_price=execution["average_price"],
            entry_notional=execution["notional"],
            entry_fee=entry_fee,
            open_reason=reason,
            entry_context=entry_context,
        )
        self.storage.set_state("paper_cash", f"{cash - margin_reserved - entry_fee:.8f}")
        self.storage.record_signal(
            symbol,
            self.strategy_name,
            entry_action,
            selected_setup["score"],
            reason,
            {
                **base_details,
                "decision_side": selected_setup["side"],
                "decision_side_label": selected_setup["side_label"],
                "position_id": position_id,
                "prezzo": execution["average_price"],
                "quantita": execution["quantity"],
                "notional_eur": execution["notional"],
                "margin_reserved": margin_reserved,
                "fee_ingresso_eur": entry_fee,
                "slippage_ingresso_pct": execution["slippage_pct"],
                "fill_levels": execution["fill_levels"],
                "risk_manager": permission.details,
            },
        )
        self.storage.log_event(
            "INFO",
            "paper_engine",
            f"Aperta posizione paper {selected_setup['side_label'].lower()} su {symbol}",
            {
                "position_id": position_id,
                "side": selected_setup["side"],
                "prezzo": execution["average_price"],
                "quantita": execution["quantity"],
                "notional_eur": execution["notional"],
                "margin_reserved": margin_reserved,
                "fee_ingresso_eur": entry_fee,
                "slippage_ingresso_pct": execution["slippage_pct"],
                "provider_fee": fee_profile.label,
            },
        )
        self.storage.log_ledger_event(
            event_type="signal_decision",
            title=f"Ingresso paper su {symbol}",
            mode="PAPER",
            symbol=symbol,
            reference_type="position",
            reference_id=position_id,
            payload={
                "action": entry_action,
                "side": selected_setup["side"],
                "reason": reason,
                "entry_price": execution["average_price"],
                "notional_eur": execution["notional"],
                "margin_reserved": margin_reserved,
                "entry_fee_eur": entry_fee,
                "slippage_pct": execution["slippage_pct"],
            },
        )
        self.storage.log_ledger_event(
            event_type="fee_event",
            title=f"Fee di ingresso registrata su {symbol}",
            mode="PAPER",
            symbol=symbol,
            reference_type="position",
            reference_id=position_id,
            payload={
                "fee_eur": entry_fee,
                "phase": "entry",
                "provider": fee_profile.label,
            },
        )
        self._save_analysis(
            symbol,
            status="ENTRATA_ESEGUITA",
            action=entry_action,
            reason=reason,
            details={
                **base_details,
                "decision_side": selected_setup["side"],
                "decision_side_label": selected_setup["side_label"],
                "position_id": position_id,
                "entry_price": execution["average_price"],
                "quantity": execution["quantity"],
                "margin_reserved": margin_reserved,
                "entry_fee_eur": entry_fee,
                "entry_slippage_pct": execution["slippage_pct"],
                "fill_levels": execution["fill_levels"],
                "stop_loss_price": stop_loss_price,
                "take_profit_price": take_profit_price,
                "planned_risk_eur": planned_risk_eur,
                "planned_reward_eur": planned_reward_eur,
                "risk_manager": permission.details,
                "prossima_condizione": (
                    "Ora la posizione e aperta: usciro in reduce-only su stop loss, take profit, inversione del momentum, imbalance contrario o tempo massimo."
                ),
            },
            filter_code="entry_executed",
        )

    def _maybe_close_position(
        self,
        *,
        symbol: str,
        position: Any,
        current_snapshot: Any,
        bids: list[Any],
        asks: list[Any],
        momentum: float,
        book_imbalance: float | None,
        details: dict[str, Any],
        taker_fee_rate: float,
    ) -> None:
        entry_context = self._load_context(position["entry_context_json"])
        side = str(position["side"] or entry_context.get("position_side") or "LONG").upper()
        entry_price = float(position["entry_price"])
        quantity = float(position["quantity"])
        entry_notional = float(position["entry_notional"])
        entry_fee = float(position["entry_fee"])
        margin_reserved = float(
            entry_context.get("margin_reserved")
            or entry_context.get("margin_reserved_eur")
            or entry_notional
        )
        opened_at = parse_iso8601(position["opened_at"])
        now = parse_iso8601(utc_now_iso())
        holding_minutes = (now - opened_at).total_seconds() / 60

        stop_loss = float(
            entry_context.get(
                "stop_loss_price",
                entry_price * (1 - self.stop_loss_pct)
                if side == "LONG"
                else entry_price * (1 + self.stop_loss_pct),
            )
        )
        take_profit = float(
            entry_context.get(
                "take_profit_price",
                entry_price * (1 + self.take_profit_pct)
                if side == "LONG"
                else entry_price * (1 - self.take_profit_pct),
            )
        )
        best_bid = (
            float(current_snapshot["best_bid"])
            if current_snapshot["best_bid"] is not None
            else entry_price
        )
        best_ask = (
            float(current_snapshot["best_ask"])
            if current_snapshot["best_ask"] is not None
            else entry_price
        )
        mark_price = best_bid if side == "LONG" else best_ask
        should_exit = False
        close_reason = ""

        if side == "LONG":
            if best_bid <= stop_loss:
                should_exit = True
                close_reason = "Stop loss dinamico raggiunto"
            elif best_bid >= take_profit:
                should_exit = True
                close_reason = "Take profit dinamico raggiunto"
            elif momentum < self.exit_reverse_threshold:
                should_exit = True
                close_reason = "Momentum invertito"
            elif (
                book_imbalance is not None
                and book_imbalance < self.imbalance_reverse_threshold
            ):
                should_exit = True
                close_reason = "Imbalance del book invertito"
            elif holding_minutes >= self.max_hold_minutes:
                should_exit = True
                close_reason = "Tempo massimo di permanenza raggiunto"
        else:
            if best_ask >= stop_loss:
                should_exit = True
                close_reason = "Stop loss short raggiunto"
            elif best_ask <= take_profit:
                should_exit = True
                close_reason = "Take profit short raggiunto"
            elif momentum > self.short_exit_reverse_threshold:
                should_exit = True
                close_reason = "Momentum invertito contro lo short"
            elif (
                book_imbalance is not None
                and book_imbalance > self.short_imbalance_reverse_threshold
            ):
                should_exit = True
                close_reason = "Imbalance del book invertito contro lo short"
            elif holding_minutes >= self.max_hold_minutes:
                should_exit = True
                close_reason = "Tempo massimo di permanenza raggiunto"

        if not should_exit:
            mark_notional = quantity * mark_price
            exit_fee_estimate = mark_notional * taker_fee_rate
            unrealized_pnl = (
                entry_notional - mark_notional - exit_fee_estimate
                if side == "SHORT"
                else mark_notional - entry_notional - exit_fee_estimate
            )
            self._save_analysis(
                symbol,
                status="IN_POSIZIONE",
                action="MANTIENI",
                reason=(
                    "La posizione short paper e aperta e al momento non c'e una condizione di uscita."
                    if side == "SHORT"
                    else "La posizione paper e aperta e al momento non c'e una condizione di uscita."
                ),
                details={
                    **details,
                    "decision_side": side,
                    "decision_side_label": side,
                    "holding_minutes": holding_minutes,
                    "entry_price": entry_price,
                    "stop_loss_price": stop_loss,
                    "take_profit_price": take_profit,
                    "margin_reserved": margin_reserved,
                    "unrealized_pnl": unrealized_pnl,
                    "entry_slippage_pct": entry_context.get("slippage_pct"),
                    "prossima_condizione": (
                        "Uscita reduce-only se si attiva stop loss, take profit, inversione del momentum, imbalance contrario o tempo massimo."
                    ),
                },
                filter_code="position_active",
            )
            return

        if side == "SHORT":
            execution = self._simulate_buy_cover_fill(
                asks=asks,
                quantity=quantity,
                reference_price=best_ask,
                snapshot_id=int(current_snapshot["id"]),
            )
        else:
            execution = self._simulate_sell_fill(
                bids=bids,
                quantity=quantity,
                reference_price=best_bid,
                snapshot_id=int(current_snapshot["id"]),
            )
        exit_notional = execution["notional"]
        exit_fee = exit_notional * taker_fee_rate
        gross_pnl = (
            entry_notional - exit_notional
            if side == "SHORT"
            else exit_notional - entry_notional
        )
        realized_pnl = gross_pnl - entry_fee - exit_fee
        exit_action = "COMPRA" if side == "SHORT" else "VENDI"
        exit_context = {
            "snapshot_id": execution["snapshot_id"],
            "reference_price": execution["reference_price"],
            "average_price": execution["average_price"],
            "mid_price": float(current_snapshot["mid_price"]) if current_snapshot["mid_price"] is not None else None,
            "slippage_pct": execution["slippage_pct"],
            "fill_levels": execution["fill_levels"],
            "fallback_used": execution["fallback_used"],
            "holding_minutes": holding_minutes,
            "execution_action": exit_action,
            "reduce_only": self.config.reduce_only_exits_enabled,
        }
        self.storage.close_position(
            position_id=int(position["id"]),
            exit_price=execution["average_price"],
            exit_notional=exit_notional,
            exit_fee=exit_fee,
            realized_pnl=realized_pnl,
            close_reason=close_reason,
            exit_context=exit_context,
        )

        cash = float(self.storage.get_state("paper_cash", str(self.config.paper_start_balance)))
        self.storage.set_state(
            "paper_cash",
            f"{cash + margin_reserved + gross_pnl - exit_fee:.8f}",
        )
        self.risk_manager.register_close(realized_pnl)
        self.storage.record_signal(
            symbol,
            self.strategy_name,
            exit_action,
            momentum,
            close_reason,
            {
                **details,
                "decision_side": side,
                "decision_side_label": side,
                "position_id": int(position["id"]),
                "exit_price": execution["average_price"],
                "exit_fee_eur": exit_fee,
                "exit_slippage_pct": execution["slippage_pct"],
                "reduce_only": self.config.reduce_only_exits_enabled,
                "realized_pnl": realized_pnl,
                "fill_levels": execution["fill_levels"],
            },
        )
        self.storage.log_event(
            "INFO",
            "paper_engine",
            f"Chiusa posizione paper {side.lower()} su {symbol}",
            {
                "position_id": int(position["id"]),
                "side": side,
                "prezzo_uscita": execution["average_price"],
                "pnl_realizzato_eur": realized_pnl,
                "fee_uscita_eur": exit_fee,
                "slippage_uscita_pct": execution["slippage_pct"],
                "motivo": close_reason,
            },
        )
        self.storage.log_ledger_event(
            event_type="signal_decision",
            title=f"Uscita paper su {symbol}",
            mode="PAPER",
            symbol=symbol,
            reference_type="position",
            reference_id=int(position["id"]),
            payload={
                "action": exit_action,
                "side": side,
                "reduce_only": self.config.reduce_only_exits_enabled,
                "reason": close_reason,
                "exit_price": execution["average_price"],
                "exit_fee_eur": exit_fee,
                "realized_pnl_eur": realized_pnl,
                "slippage_pct": execution["slippage_pct"],
            },
        )
        self.storage.log_ledger_event(
            event_type="fee_event",
            title=f"Fee di uscita registrata su {symbol}",
            mode="PAPER",
            symbol=symbol,
            reference_type="position",
            reference_id=int(position["id"]),
            payload={
                "fee_eur": exit_fee,
                "phase": "exit",
                "provider": self._current_provider().label,
            },
        )
        self._save_analysis(
            symbol,
            status="USCITA_ESEGUITA",
            action=exit_action,
            reason=close_reason,
            details={
                **details,
                "decision_side": side,
                "decision_side_label": side,
                "holding_minutes": holding_minutes,
                "exit_price": execution["average_price"],
                "exit_slippage_pct": execution["slippage_pct"],
                "reduce_only": self.config.reduce_only_exits_enabled,
                "realized_pnl": realized_pnl,
                "prossima_condizione": (
                    "Ora torno in osservazione e aspetto un nuovo setup long o short pulito."
                ),
            },
            filter_code="exit_executed",
        )

    def _evaluate_direction_setup(
        self,
        *,
        side: str,
        momentum: float,
        candle_trend: float | None,
        book_imbalance: float | None,
    ) -> dict[str, Any]:
        normalized_side = side.upper()
        is_short = normalized_side == "SHORT"
        side_label = "SHORT" if is_short else "LONG"
        direction_word = "short" if is_short else "long"
        momentum_target = -self.entry_momentum_threshold if is_short else self.entry_momentum_threshold
        trend_target = -self.candle_trend_threshold if is_short else self.candle_trend_threshold
        imbalance_target = (
            self.short_book_imbalance_threshold if is_short else self.long_book_imbalance_threshold
        )

        momentum_ok = momentum <= momentum_target if is_short else momentum >= momentum_target
        candle_ok = (
            candle_trend is not None
            and (candle_trend <= trend_target if is_short else candle_trend >= trend_target)
        )
        imbalance_ok = (
            book_imbalance is not None
            and (book_imbalance <= imbalance_target if is_short else book_imbalance >= imbalance_target)
        )

        momentum_score = (
            (-momentum / self.entry_momentum_threshold)
            if is_short
            else (momentum / self.entry_momentum_threshold)
        )
        trend_score = (
            (-candle_trend / self.candle_trend_threshold)
            if is_short and candle_trend is not None
            else (
                candle_trend / self.candle_trend_threshold
                if candle_trend is not None
                else 0.0
            )
        )
        imbalance_divisor = abs(imbalance_target) if abs(imbalance_target) > 1e-9 else 0.01
        imbalance_score = (
            (-book_imbalance / imbalance_divisor)
            if is_short and book_imbalance is not None
            else (
                book_imbalance / imbalance_divisor
                if book_imbalance is not None
                else 0.0
            )
        )
        score = (momentum_score + trend_score + imbalance_score) / 3.0

        if book_imbalance is None or not imbalance_ok:
            return {
                "side": normalized_side,
                "side_label": side_label,
                "ready": False,
                "score": score,
                "entry_action": "VENDI" if is_short else "COMPRA",
                "filter_code": f"{direction_word}_book_imbalance_not_ready",
                "reason": (
                    "L'imbalance del book non supporta ancora uno short ad alta convinzione."
                    if is_short
                    else "L'imbalance del book non supporta ancora un long ad alta convinzione."
                ),
                "next_condition": (
                    "Entro short solo se l'imbalance scende sotto "
                    f"{imbalance_target * 100:.2f}%."
                    if is_short
                    else "Entro long solo se l'imbalance sale sopra "
                    f"{imbalance_target * 100:.2f}%."
                ),
            }

        if not momentum_ok:
            return {
                "side": normalized_side,
                "side_label": side_label,
                "ready": False,
                "score": score,
                "entry_action": "VENDI" if is_short else "COMPRA",
                "filter_code": f"{direction_word}_momentum_not_ready",
                "reason": (
                    "C'e pressione ribassista, ma il momentum non e ancora abbastanza forte per uno short."
                    if is_short
                    else "Il momentum dell'order book non e ancora abbastanza forte per un ingresso long."
                ),
                "next_condition": (
                    "Entro short solo se il momentum scende sotto "
                    f"{momentum_target * 100:.4f}%."
                    if is_short
                    else "Entro long solo se il momentum supera "
                    f"{momentum_target * 100:.4f}%."
                ),
            }

        if not candle_ok:
            return {
                "side": normalized_side,
                "side_label": side_label,
                "ready": False,
                "score": score,
                "entry_action": "VENDI" if is_short else "COMPRA",
                "filter_code": f"{direction_word}_candle_trend_not_ready",
                "reason": (
                    "Il trend delle candele non conferma ancora uno short disciplinato."
                    if is_short
                    else "Il trend delle candele e troppo debole per confermare un long disciplinato."
                ),
                "next_condition": (
                    "Entro short solo se il trend delle candele scende sotto "
                    f"{trend_target * 100:.4f}%."
                    if is_short
                    else "Entro long solo se il trend delle candele supera "
                    f"{trend_target * 100:.4f}%."
                ),
            }

        return {
            "side": normalized_side,
            "side_label": side_label,
            "ready": True,
            "score": score,
            "entry_action": "VENDI" if is_short else "COMPRA",
            "filter_code": "entry_ready",
            "reason": (
                "Setup short completo e coerente."
                if is_short
                else "Setup long completo e coerente."
            ),
            "next_condition": (
                "Posso aprire lo short se il risk manager approva l'ordine."
                if is_short
                else "Posso aprire il long se il risk manager approva l'ordine."
            ),
        }

    def _simulate_buy_fill(
        self,
        *,
        asks: list[Any],
        target_notional: float,
        reference_price: float,
        snapshot_id: int,
    ) -> dict[str, Any]:
        remaining_quote = target_notional
        acquired_quantity = 0.0
        spent_quote = 0.0
        fill_levels = 0

        for level in asks:
            price = float(level["price"])
            available_quantity = float(level["quantity"])
            available_quote = price * available_quantity
            take_quote = min(remaining_quote, available_quote)
            if take_quote <= 0:
                continue
            acquired_quantity += take_quote / price
            spent_quote += take_quote
            remaining_quote -= take_quote
            fill_levels += 1
            if remaining_quote <= 1e-9:
                break

        if remaining_quote > 1e-6 or acquired_quantity <= 0:
            return {
                "filled": False,
                "snapshot_id": snapshot_id,
                "reference_price": reference_price,
            }

        average_price = spent_quote / acquired_quantity
        slippage_pct = ((average_price / reference_price) - 1.0) * 100.0 if reference_price else 0.0
        return {
            "filled": True,
            "snapshot_id": snapshot_id,
            "reference_price": reference_price,
            "average_price": average_price,
            "notional": spent_quote,
            "quantity": acquired_quantity,
            "fill_levels": fill_levels,
            "slippage_pct": slippage_pct,
        }

    def _simulate_short_sell_fill(
        self,
        *,
        bids: list[Any],
        target_notional: float,
        reference_price: float,
        snapshot_id: int,
    ) -> dict[str, Any]:
        remaining_quote = target_notional
        sold_quantity = 0.0
        proceeds_quote = 0.0
        fill_levels = 0

        for level in bids:
            price = float(level["price"])
            available_quantity = float(level["quantity"])
            available_quote = price * available_quantity
            take_quote = min(remaining_quote, available_quote)
            if take_quote <= 0:
                continue
            sold_quantity += take_quote / price
            proceeds_quote += take_quote
            remaining_quote -= take_quote
            fill_levels += 1
            if remaining_quote <= 1e-9:
                break

        if remaining_quote > 1e-6 or sold_quantity <= 0:
            return {
                "filled": False,
                "snapshot_id": snapshot_id,
                "reference_price": reference_price,
            }

        average_price = proceeds_quote / sold_quantity
        slippage_pct = (
            (1.0 - (average_price / reference_price)) * 100.0 if reference_price else 0.0
        )
        return {
            "filled": True,
            "snapshot_id": snapshot_id,
            "reference_price": reference_price,
            "average_price": average_price,
            "notional": proceeds_quote,
            "quantity": sold_quantity,
            "fill_levels": fill_levels,
            "slippage_pct": slippage_pct,
        }

    def _simulate_sell_fill(
        self,
        *,
        bids: list[Any],
        quantity: float,
        reference_price: float,
        snapshot_id: int,
    ) -> dict[str, Any]:
        remaining_quantity = quantity
        proceeds_quote = 0.0
        fill_levels = 0
        fallback_used = False

        for level in bids:
            price = float(level["price"])
            available_quantity = float(level["quantity"])
            trade_quantity = min(remaining_quantity, available_quantity)
            if trade_quantity <= 0:
                continue
            proceeds_quote += trade_quantity * price
            remaining_quantity -= trade_quantity
            fill_levels += 1
            if remaining_quantity <= 1e-9:
                break

        if remaining_quantity > 1e-9:
            fallback_used = True
            fallback_price = reference_price * (1.0 - self.emergency_exit_discount_pct)
            proceeds_quote += remaining_quantity * fallback_price
            fill_levels += 1
            remaining_quantity = 0.0

        average_price = proceeds_quote / quantity if quantity > 0 else reference_price
        slippage_pct = (
            (1.0 - (average_price / reference_price)) * 100.0 if reference_price else 0.0
        )
        return {
            "filled": True,
            "snapshot_id": snapshot_id,
            "reference_price": reference_price,
            "average_price": average_price,
            "notional": proceeds_quote,
            "quantity": quantity,
            "fill_levels": fill_levels,
            "slippage_pct": slippage_pct,
            "fallback_used": fallback_used,
        }

    def _simulate_buy_cover_fill(
        self,
        *,
        asks: list[Any],
        quantity: float,
        reference_price: float,
        snapshot_id: int,
    ) -> dict[str, Any]:
        remaining_quantity = quantity
        spent_quote = 0.0
        fill_levels = 0
        fallback_used = False

        for level in asks:
            price = float(level["price"])
            available_quantity = float(level["quantity"])
            trade_quantity = min(remaining_quantity, available_quantity)
            if trade_quantity <= 0:
                continue
            spent_quote += trade_quantity * price
            remaining_quantity -= trade_quantity
            fill_levels += 1
            if remaining_quantity <= 1e-9:
                break

        if remaining_quantity > 1e-9:
            fallback_used = True
            fallback_price = reference_price * (1.0 + self.emergency_cover_premium_pct)
            spent_quote += remaining_quantity * fallback_price
            fill_levels += 1
            remaining_quantity = 0.0

        average_price = spent_quote / quantity if quantity > 0 else reference_price
        slippage_pct = (
            ((average_price / reference_price) - 1.0) * 100.0 if reference_price else 0.0
        )
        return {
            "filled": True,
            "snapshot_id": snapshot_id,
            "reference_price": reference_price,
            "average_price": average_price,
            "notional": spent_quote,
            "quantity": quantity,
            "fill_levels": fill_levels,
            "slippage_pct": slippage_pct,
            "fallback_used": fallback_used,
        }

    def _book_imbalance(self, bids: list[Any], asks: list[Any]) -> float | None:
        def side_pressure(levels: list[Any]) -> float:
            pressure = 0.0
            for index, level in enumerate(levels[:5], start=1):
                notional = float(level["price"]) * float(level["quantity"])
                if notional <= 0:
                    continue
                # Compress oversized resting orders so one level cannot dominate the whole signal.
                pressure += (1 / math.sqrt(index)) * math.log1p(notional)
            return pressure

        bid_liquidity = side_pressure(bids)
        ask_liquidity = side_pressure(asks)
        total = bid_liquidity + ask_liquidity
        if total <= 0:
            return None
        return (bid_liquidity - ask_liquidity) / total

    def _load_context(self, raw_value: Any) -> dict[str, Any]:
        if raw_value in (None, ""):
            return {}
        try:
            return json.loads(raw_value)
        except (TypeError, json.JSONDecodeError):
            return {}

    def _save_analysis(
        self,
        symbol: str,
        *,
        status: str,
        action: str,
        reason: str,
        details: dict[str, Any],
        filter_code: str = "unclassified",
    ) -> None:
        previous = self.storage.get_strategy_analysis(symbol)
        self.storage.upsert_strategy_analysis(
            symbol,
            strategy=self.strategy_name,
            status=status,
            action=action,
            reason=reason,
            details=details,
        )
        self.storage.increment_analysis_counter(
            symbol=symbol,
            filter_code=filter_code,
            status=status,
            action=action,
            reason=reason,
        )
        changed = (
            previous is None
            or previous["status"] != status
            or previous["action"] != action
            or previous["reason"] != reason
        )
        replay_worthy = changed or filter_code in {
            "entry_executed",
            "exit_executed",
            "risk_manager_block",
        }
        if replay_worthy:
            replay_mode = "PAPER" if action in {"COMPRA", "VENDI", "MANTIENI"} and status in {
                "ENTRATA_ESEGUITA",
                "USCITA_ESEGUITA",
                "IN_POSIZIONE",
            } else "SHADOW"
            decisive_rule = self._decision_rule_label(filter_code)
            self.storage.record_decision_replay(
                symbol=symbol,
                mode=replay_mode,
                status=status,
                action=action,
                reason=reason,
                decisive_rule=decisive_rule,
                filter_code=filter_code,
                signal_present=action in {"COMPRA", "VENDI"},
                payload=details,
            )
            if filter_code == "risk_manager_block":
                self.storage.log_ledger_event(
                    event_type="guardrail_block",
                    title=f"Guard rail ha bloccato {symbol}",
                    mode=replay_mode,
                    symbol=symbol,
                    payload={
                        "reason": reason,
                        "status": status,
                        "action": action,
                        "filter_code": filter_code,
                    },
                )
            self.storage.log_ledger_event(
                event_type="replay_snapshot_reference",
                title=f"Replay decisionale aggiornato per {symbol}",
                mode=replay_mode,
                symbol=symbol,
                payload={
                    "status": status,
                    "action": action,
                    "reason": reason,
                    "filter_code": filter_code,
                    "decisive_rule": decisive_rule,
                },
            )

    def _current_provider(self):
        configured_key = self.storage.get_state(
            "paper_provider_key", self.config.simulation_provider
        )
        return get_provider_profile(configured_key)

    def _sync_provider_state(self) -> None:
        previous_key = self.storage.get_state("paper_provider_key")
        if previous_key != self.config.simulation_provider:
            self.storage.set_state("paper_provider_key", self.config.simulation_provider)
        profile = get_provider_profile(self.config.simulation_provider)
        for key, value in provider_state_items(profile).items():
            self.storage.set_state(key, value)
        if previous_key and previous_key != profile.key:
            self.storage.log_ledger_event(
                event_type="risk_config_change",
                title=f"Profilo provider aggiornato a {profile.label}",
                mode="PAPER",
                payload={
                    "previous_provider_key": previous_key,
                    "new_provider_key": profile.key,
                    "fee_model": profile.fee_model,
                },
            )

    def _ensure_daily_operational_snapshot(self) -> None:
        day_key = datetime.now().astimezone().date().isoformat()
        if self.storage.get_state("alpha_operational_snapshot_day") == day_key:
            return
        provider = self._current_provider()
        self.storage.set_state("alpha_operational_snapshot_day", day_key)
        self.storage.log_ledger_event(
            event_type="workflow_note",
            title="Snapshot operativo alpha registrato",
            mode="PAPER",
            payload={
                "day_key": day_key,
                "provider": provider.label,
                "modes": ["PAPER", "SHADOW", "LIVE_DISABLED"],
                "symbols": self.config.monitored_symbols,
            },
        )
        self.storage.log_ledger_event(
            event_type="risk_config_change",
            title="Snapshot rischio alpha registrato",
            mode="PAPER",
            payload={
                "max_open_positions": self.config.max_open_positions,
                "max_total_exposure_pct": self.config.max_total_exposure_pct,
                "daily_loss_limit_pct": self.config.daily_loss_limit_pct,
                "max_drawdown_pct": self.config.max_drawdown_pct,
            },
        )

    def _decision_rule_label(self, filter_code: str) -> str:
        mapping = {
            "insufficient_snapshots": "snapshot insufficienti",
            "missing_mid_prices": "mid price mancanti",
            "incomplete_order_book": "order book incompleto",
            "spread_too_wide": "spread troppo largo",
            "recent_trade_flow_too_low": "flusso trade troppo scarso",
            "awaiting_candles": "contesto candele mancante",
            "volatility_too_low": "volatilita troppo bassa",
            "volatility_too_high": "volatilita troppo alta",
            "book_imbalance_too_weak": "imbalance book troppo debole",
            "momentum_too_weak": "momentum troppo debole",
            "candle_trend_too_weak": "trend candele troppo debole",
            "long_book_imbalance_not_ready": "setup long: imbalance non pronto",
            "long_momentum_not_ready": "setup long: momentum non pronto",
            "long_candle_trend_not_ready": "setup long: trend non pronto",
            "short_book_imbalance_not_ready": "setup short: imbalance non pronto",
            "short_momentum_not_ready": "setup short: momentum non pronto",
            "short_candle_trend_not_ready": "setup short: trend non pronto",
            "risk_manager_block": "guard rail del risk manager",
            "ask_depth_insufficient": "liquidita ask insufficiente",
            "bid_depth_insufficient": "liquidita bid insufficiente",
            "cash_insufficient": "cassa insufficiente",
            "entry_executed": "ingresso eseguito",
            "position_active": "posizione attiva",
            "exit_executed": "uscita eseguita",
        }
        return mapping.get(filter_code, filter_code.replace("_", " "))
