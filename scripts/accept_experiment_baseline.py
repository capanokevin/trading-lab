from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

load_dotenv(ROOT / ".env")

from trading_bot import AppConfig, TradingStorage  # noqa: E402
from trading_bot.storage import utc_now_iso  # noqa: E402


def main() -> int:
    config = AppConfig.from_env()
    storage = TradingStorage(config.db_path)
    storage.init_db()

    current = storage.get_state("experiment_current_fingerprint")
    if not current:
        print("Nessun fingerprint corrente trovato. Avvia prima un ciclo del bot.", flush=True)
        return 1

    accepted_at = utc_now_iso()
    storage.set_state("experiment_baseline_fingerprint", current)
    storage.set_state("experiment_drift_detected", "false")
    storage.set_state("experiment_drift_detected_at", "")
    storage.set_state("experiment_last_reported_drift_fingerprint", "")
    storage.log_event(
        "INFO",
        "experiment",
        "Baseline esperimento accettata senza reset storico",
        {"fingerprint": current, "accepted_at": accepted_at},
    )
    storage.log_ledger_event(
        event_type="strategy_change",
        title="Baseline esperimento accettata",
        mode="PAPER",
        payload={"fingerprint": current, "accepted_at": accepted_at},
    )
    print(f"Baseline accettata: {current}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
