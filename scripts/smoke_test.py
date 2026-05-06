from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

load_dotenv(ROOT / ".env")

from revolut_x import RevolutXClient, RevolutXConfig  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Revolut X smoke test")
    parser.add_argument(
        "--symbol",
        default=os.getenv("REVOLUT_X_DEFAULT_SYMBOL", "BTC-USD"),
        help="Trading pair symbol, for example BTC-USD",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override REVOLUT_X_BASE_URL",
    )
    parser.add_argument(
        "--authenticated",
        action="store_true",
        help="Also test authenticated endpoints",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=5,
        help="Candle interval in minutes for authenticated test",
    )
    return parser.parse_args()


def print_json(title: str, payload: dict) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(payload, indent=2)[:2000])


def main() -> int:
    args = parse_args()

    config = RevolutXConfig.from_env()
    if args.base_url:
        config.base_url = args.base_url

    client = RevolutXClient(config)

    print(f"Base URL: {config.base_url}")
    print(f"Symbol:   {args.symbol}")

    order_book = client.get_public_order_book(args.symbol)
    last_trades = client.get_public_last_trades()

    print_json("Public order book", order_book)
    print_json("Public last trades", last_trades)

    if args.authenticated:
        pairs = client.get_pairs()
        candles = client.get_candles(args.symbol, interval=args.interval)
        print_json("Authenticated pairs", pairs)
        print_json("Authenticated candles", candles)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

