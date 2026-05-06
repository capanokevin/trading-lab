from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from trading_bot.config import AppConfig
from trading_bot.storage import TradingStorage, parse_iso8601


def _local_day_key() -> str:
    return datetime.now().astimezone().date().isoformat()


@dataclass(slots=True)
class EntryPermission:
    allowed: bool
    approved_notional: float
    reason: str
    details: dict[str, Any]


class RiskManager:
    def __init__(self, config: AppConfig, storage: TradingStorage) -> None:
        self.config = config
        self.storage = storage

    def initialize(self) -> None:
        self._sync_limits()
        self._reset_daily_controls_if_needed()
        self.refresh_runtime_state(self.config.monitored_symbols)

    def refresh_runtime_state(self, symbols: list[str]) -> dict[str, Any]:
        self._sync_limits()
        self._reset_daily_controls_if_needed()

        metrics = self.storage.build_runtime_metrics(
            symbols=symbols,
            paper_start_balance=self.config.paper_start_balance,
        )
        previous_guardrail_status = self.storage.get_state("paper_guardrail_status", "ATTIVO")
        previous_kill_reason = self.storage.get_state("paper_kill_switch_reason", "") or ""
        day_key = _local_day_key()
        # Start each refresh from the healthy default and let active guard rails
        # explicitly disable new entries. This avoids stale false flags lingering
        # after a previous stop condition has already cleared.
        trading_enabled = True
        stored_kill_reason = self.storage.get_state("paper_kill_switch_reason", "") or ""
        kill_reason = ""
        cooldown_until_raw = self.storage.get_state("paper_cooldown_until", "")
        cooldown_until = parse_iso8601(cooldown_until_raw) if cooldown_until_raw else None
        now = datetime.now().astimezone()
        cooldown_active = bool(cooldown_until and cooldown_until.astimezone() > now)
        if cooldown_until and not cooldown_active:
            self.storage.set_state("paper_cooldown_until", "")
            cooldown_until = None

        daily_loss_limit_base_eur = max(
            metrics["equity"],
            metrics.get("contributed_capital", metrics["starting_balance"]),
        )
        daily_loss_limit_eur = daily_loss_limit_base_eur * (
            self.config.daily_loss_limit_pct / 100.0
        )
        current_drawdown_pct = abs(min(metrics["current_drawdown_pct"], 0.0))

        if stored_kill_reason.startswith("Troppi errori"):
            trading_enabled = False
            kill_reason = stored_kill_reason
        elif metrics["today_realized_pnl"] <= -daily_loss_limit_eur:
            trading_enabled = False
            kill_reason = (
                "Limite di perdita giornaliera raggiunto: "
                f"{metrics['today_realized_pnl']:.2f} {self.config.quote_currency} "
                f"su soglia {daily_loss_limit_eur:.2f} {self.config.quote_currency}."
            )
        elif current_drawdown_pct >= self.config.max_drawdown_pct:
            trading_enabled = False
            kill_reason = (
                "Kill switch drawdown: "
                f"drawdown corrente {current_drawdown_pct:.2f}% oltre soglia {self.config.max_drawdown_pct:.2f}%."
            )
        elif metrics["consecutive_losses"] >= self.config.max_consecutive_losses:
            trading_enabled = False
            kill_reason = (
                "Kill switch disciplina: "
                f"{metrics['consecutive_losses']} perdite consecutive oltre limite {self.config.max_consecutive_losses}."
            )

        guardrail_status = "ATTIVO"
        if kill_reason:
            guardrail_status = "HARD_STOP"
        elif cooldown_active:
            guardrail_status = "COOLDOWN"

        self.storage.set_state("paper_trading_enabled", "true" if trading_enabled else "false")
        self.storage.set_state("paper_kill_switch_reason", kill_reason)
        self.storage.set_state("paper_guardrail_status", guardrail_status)
        self.storage.set_state("paper_guardrail_day_key", day_key)
        self.storage.set_state(
            "paper_daily_loss_limit_eur", f"{daily_loss_limit_eur:.8f}"
        )
        self.storage.set_state(
            "paper_daily_loss_limit_base_eur", f"{daily_loss_limit_base_eur:.8f}"
        )
        self.storage.set_state(
            "paper_daily_trade_count", str(metrics["today_trade_count"])
        )
        self.storage.set_state(
            "paper_consecutive_losses", str(metrics["consecutive_losses"])
        )
        self.storage.set_state(
            "paper_current_drawdown_pct", f"{metrics['current_drawdown_pct']:.6f}"
        )
        self.storage.set_state(
            "paper_max_drawdown_pct_observed", f"{metrics['max_drawdown_pct']:.6f}"
        )
        self.storage.set_state(
            "paper_current_exposure_eur", f"{metrics['current_exposure_eur']:.8f}"
        )
        self.storage.set_state(
            "paper_current_exposure_pct", f"{metrics['current_exposure_pct']:.6f}"
        )
        self.storage.set_state(
            "paper_daily_realized_pnl", f"{metrics['today_realized_pnl']:.8f}"
        )
        if guardrail_status != previous_guardrail_status or kill_reason != previous_kill_reason:
            self.storage.log_ledger_event(
                event_type="guardrail_block" if guardrail_status != "ATTIVO" else "risk_config_change",
                title=(
                    f"Guard rail passato a {guardrail_status}"
                    if guardrail_status != "ATTIVO"
                    else "Guard rail tornato attivo"
                ),
                mode="PAPER",
                level="WARNING" if guardrail_status != "ATTIVO" else "INFO",
                payload={
                    "previous_status": previous_guardrail_status,
                    "new_status": guardrail_status,
                    "kill_reason": kill_reason,
                    "cooldown_until": cooldown_until.astimezone().isoformat() if cooldown_until else None,
                },
            )

        return {
            **metrics,
            "guardrail_status": guardrail_status,
            "trading_enabled": trading_enabled and not kill_reason,
            "kill_reason": kill_reason,
            "cooldown_until": cooldown_until.astimezone().isoformat() if cooldown_until else None,
            "cooldown_active": cooldown_active,
            "daily_loss_limit_eur": daily_loss_limit_eur,
            "daily_loss_limit_base_eur": daily_loss_limit_base_eur,
        }

    def evaluate_entry(
        self,
        *,
        symbol: str,
        requested_notional: float,
        stop_loss_pct: float,
        leverage: float,
        symbols: list[str],
    ) -> EntryPermission:
        runtime = self.refresh_runtime_state(symbols)
        if not runtime["trading_enabled"]:
            return EntryPermission(
                allowed=False,
                approved_notional=0.0,
                reason=runtime["kill_reason"] or "Trading paper momentaneamente disabilitato.",
                details=runtime,
            )

        if runtime["cooldown_active"]:
            return EntryPermission(
                allowed=False,
                approved_notional=0.0,
                reason=(
                    "Cooldown attivo: il sistema aspetta prima di aprire nuove posizioni "
                    "per evitare overtrading."
                ),
                details=runtime,
            )

        if runtime["open_positions"] >= self.config.max_open_positions:
            return EntryPermission(
                allowed=False,
                approved_notional=0.0,
                reason=(
                    f"Massimo posizioni aperte raggiunto ({self.config.max_open_positions})."
                ),
                details=runtime,
            )

        if runtime["today_trade_count"] >= self.config.daily_trade_limit:
            return EntryPermission(
                allowed=False,
                approved_notional=0.0,
                reason=(
                    f"Limite trade giornaliero raggiunto ({self.config.daily_trade_limit})."
                ),
                details=runtime,
            )

        max_exposure_eur = runtime["equity"] * (self.config.max_total_exposure_pct / 100.0)
        remaining_exposure_eur = max(max_exposure_eur - runtime["current_exposure_eur"], 0.0)
        reserve_cash_eur = runtime["equity"] * (self.config.min_cash_reserve_pct / 100.0)
        available_cash_eur = max(runtime["cash"] - reserve_cash_eur, 0.0)
        max_trade_allocation_eur = runtime["equity"] * (
            self.config.max_trade_allocation_pct / 100.0
        )
        stop_loss_pct = max(stop_loss_pct, 0.0001)
        max_risk_budget_eur = runtime["equity"] * (self.config.max_risk_per_trade_pct / 100.0)
        max_notional_by_risk = max_risk_budget_eur / stop_loss_pct
        effective_leverage = max(leverage, 1.0)
        max_notional_by_cash = available_cash_eur * effective_leverage

        approved_notional = min(
            requested_notional,
            remaining_exposure_eur,
            max_notional_by_cash,
            max_trade_allocation_eur,
            max_notional_by_risk,
        )

        details = {
            **runtime,
            "remaining_exposure_eur": remaining_exposure_eur,
            "reserve_cash_eur": reserve_cash_eur,
            "available_cash_eur": available_cash_eur,
            "max_trade_allocation_eur": max_trade_allocation_eur,
            "max_risk_budget_eur": max_risk_budget_eur,
            "max_notional_by_risk": max_notional_by_risk,
            "effective_leverage": effective_leverage,
            "max_notional_by_cash": max_notional_by_cash,
            "requested_notional_eur": requested_notional,
            "approved_notional_eur": approved_notional,
            "symbol": symbol,
        }

        if approved_notional < self.config.min_order_notional_eur:
            return EntryPermission(
                allowed=False,
                approved_notional=0.0,
                reason=(
                    "Il notional approvato dal risk manager e troppo piccolo per un trade "
                    f"disciplinato (minimo {self.config.min_order_notional_eur:.2f} {self.config.quote_currency})."
                ),
                details=details,
            )

        return EntryPermission(
            allowed=True,
            approved_notional=approved_notional,
            reason="Ingresso approvato dal risk manager.",
            details=details,
        )

    def register_close(self, realized_pnl: float) -> None:
        now = datetime.now().astimezone()
        cooldown_minutes = (
            self.config.cooldown_after_loss_minutes
            if realized_pnl < 0
            else self.config.cooldown_after_trade_minutes
        )
        cooldown_until = now + timedelta(minutes=cooldown_minutes)
        self.storage.set_state(
            "paper_cooldown_until", cooldown_until.isoformat(timespec="seconds")
        )

    def activate_health_kill_switch(self, reason: str) -> None:
        self.storage.set_state("paper_trading_enabled", "false")
        self.storage.set_state("paper_kill_switch_reason", reason)
        self.storage.set_state("paper_guardrail_status", "HARD_STOP")
        self.storage.log_event(
            "ERROR",
            "risk_manager",
            "Kill switch salute sistema attivato",
            {"reason": reason},
        )
        self.storage.log_ledger_event(
            event_type="guardrail_block",
            title="Kill switch salute sistema attivato",
            mode="PAPER",
            level="ERROR",
            payload={"reason": reason},
        )

    def clear_health_kill_switch(self) -> None:
        if self.storage.get_state("paper_kill_switch_reason", "").startswith("Troppi errori"):
            self.storage.set_state("paper_trading_enabled", "true")
            self.storage.set_state("paper_kill_switch_reason", "")
            self.storage.set_state("paper_guardrail_status", "ATTIVO")

    def _sync_limits(self) -> None:
        state_items = {
            "risk_max_open_positions": str(self.config.max_open_positions),
            "risk_max_total_exposure_pct": f"{self.config.max_total_exposure_pct:.4f}",
            "risk_max_trade_allocation_pct": f"{self.config.max_trade_allocation_pct:.4f}",
            "risk_min_cash_reserve_pct": f"{self.config.min_cash_reserve_pct:.4f}",
            "risk_max_risk_per_trade_pct": f"{self.config.max_risk_per_trade_pct:.4f}",
            "risk_min_order_notional_eur": f"{self.config.min_order_notional_eur:.4f}",
            "risk_daily_loss_limit_pct": f"{self.config.daily_loss_limit_pct:.4f}",
            "risk_max_drawdown_pct": f"{self.config.max_drawdown_pct:.4f}",
            "risk_daily_trade_limit": str(self.config.daily_trade_limit),
            "risk_max_consecutive_losses": str(self.config.max_consecutive_losses),
            "risk_cooldown_after_trade_minutes": f"{self.config.cooldown_after_trade_minutes:.4f}",
            "risk_cooldown_after_loss_minutes": f"{self.config.cooldown_after_loss_minutes:.4f}",
            "risk_max_consecutive_cycle_errors": str(
                self.config.max_consecutive_cycle_errors
            ),
        }
        for key, value in state_items.items():
            self.storage.set_state(key, value)

    def _reset_daily_controls_if_needed(self) -> None:
        today_key = _local_day_key()
        last_key = self.storage.get_state("paper_guardrail_day_key")
        if last_key == today_key:
            return
        self.storage.set_state("paper_guardrail_day_key", today_key)
        self.storage.set_state("paper_trading_enabled", "true")
        self.storage.set_state("paper_kill_switch_reason", "")
        self.storage.set_state("paper_guardrail_status", "ATTIVO")
        self.storage.set_state("paper_cooldown_until", "")
        self.storage.set_state("bot_cycle_error_count", "0")
        self.storage.log_event(
            "INFO",
            "risk_manager",
            "Reset giornaliero guard rail completato",
            {"day_key": today_key},
        )
        self.storage.log_ledger_event(
            event_type="risk_config_change",
            title="Reset giornaliero guard rail",
            mode="PAPER",
            payload={"day_key": today_key},
        )
