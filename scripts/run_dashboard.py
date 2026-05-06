from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

load_dotenv(ROOT / ".env")

from trading_bot import AppConfig, TradingStorage, create_dashboard_app  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local trading dashboard")
    parser.add_argument("--host", default=None, help="Override DASHBOARD_HOST")
    parser.add_argument("--port", type=int, default=None, help="Override DASHBOARD_PORT")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = AppConfig.from_env()
    host = args.host or config.dashboard_host
    port = args.port or config.dashboard_port
    storage = TradingStorage(config.db_path)
    storage.init_db()
    app = create_dashboard_app(config, storage)
    app.run(host=host, port=port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
