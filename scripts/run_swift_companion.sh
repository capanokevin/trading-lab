#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$ROOT/macos/TradingDeskCompanion.swift"
BUILD_DIR="$ROOT/.build/desk-companion"
OUTPUT="$BUILD_DIR/TradingDeskCompanion"

mkdir -p "$BUILD_DIR"

if [[ ! -x "$OUTPUT" || "$SOURCE" -nt "$OUTPUT" ]]; then
  swiftc "$SOURCE" -framework AppKit -framework SwiftUI -o "$OUTPUT"
fi

exec "$OUTPUT"
