from __future__ import annotations

from pathlib import Path
import sys

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

load_dotenv(ROOT / ".env")

from trading_bot.config import AppConfig
from trading_bot.storage import TradingStorage


LABELS = {
    "insufficient_snapshots": "Snapshot insufficienti",
    "missing_mid_prices": "Prezzi medi mancanti",
    "incomplete_order_book": "Order book incompleto",
    "spread_too_wide": "Spread troppo largo",
    "recent_trade_flow_too_low": "Flusso trade troppo basso",
    "awaiting_candles": "Candele insufficienti",
    "volatility_too_low": "Volatilita troppo bassa",
    "volatility_too_high": "Volatilita troppo alta",
    "book_imbalance_too_weak": "Imbalance troppo debole",
    "momentum_too_weak": "Momentum troppo debole",
    "candle_trend_too_weak": "Trend candele troppo debole",
    "symbol_watch_only": "Simbolo solo in osservazione",
    "risk_manager_block": "Blocco risk manager",
    "ask_depth_insufficient": "Liquidita ask insufficiente",
    "cash_insufficient": "Cassa insufficiente",
    "entry_executed": "Entrata eseguita",
    "position_active": "Posizione attiva",
    "exit_executed": "Uscita eseguita",
    "unclassified": "Non classificato",
}


def main() -> int:
    config = AppConfig.from_env()
    storage = TradingStorage(config.db_path)
    storage.init_db()
    summary = storage.get_analysis_filter_summary(days=7)

    print(f"Audit filtri ultimi {summary['window_days']} giorni")
    print()
    print("Aggregato:")
    for item in summary["aggregate"][:20]:
        label = LABELS.get(item["filter_code"], item["filter_code"])
        print(
            f"- {label}: {item['total_count']} cicli | "
            f"{item['symbol_count']} simboli | ultimo {item['last_seen_at']}"
        )

    print()
    print("Oggi per simbolo:")
    for item in summary["today_by_symbol"][:40]:
        label = LABELS.get(item["filter_code"], item["filter_code"])
        print(
            f"- {item['symbol']} | {label}: {item['count']} | "
            f"{item['last_status']} | {item['last_reason']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
