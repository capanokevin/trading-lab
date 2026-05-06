from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

load_dotenv(ROOT / ".env")

from trading_bot import AppConfig, PublicTradingBot, TradingStorage  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the default Hyperliquid-backed simulation bot"
    )
    parser.add_argument("--once", action="store_true", help="Run a single cycle and exit")
    parser.add_argument(
        "--cycles",
        type=int,
        default=None,
        help="Run a fixed number of cycles",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=None,
        help="Override BOT_POLL_INTERVAL_SECONDS",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = AppConfig.from_env()
    if args.poll_interval is not None:
        config.poll_interval_seconds = args.poll_interval

    storage = TradingStorage(config.db_path)
    bot = PublicTradingBot(config, storage)
    bot.initialize()

    cycles_remaining = 1 if args.once else args.cycles
    while True:
        cycle_started = time.monotonic()
        try:
            summary = bot.run_cycle()
            print(summary)
        except KeyboardInterrupt:
            storage.set_state("bot_status", "stopped")
            storage.log_event("INFO", "public_bot", "Bot fermato dall'utente")
            return 0
        except Exception as exc:
            bot.handle_cycle_error(exc)
            print(f"Cycle failed: {exc}", file=sys.stderr)

        if cycles_remaining is not None:
            cycles_remaining -= 1
            if cycles_remaining <= 0:
                storage.set_state("bot_status", "stopped")
                return 0

        elapsed = time.monotonic() - cycle_started
        sleep_for = max(config.poll_interval_seconds - elapsed, 0)
        time.sleep(sleep_for)


if __name__ == "__main__":
    raise SystemExit(main())
