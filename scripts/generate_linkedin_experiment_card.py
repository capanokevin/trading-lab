from __future__ import annotations

import sqlite3
from io import BytesIO
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "trading_paper.sqlite3"
OUTPUT_PATH = ROOT / "data" / "exports" / "linkedin-trader-digitale-2026-05-05.png"


WIDTH = 1080
HEIGHT = 1350
MARGIN = 64

INK = "#111111"
MUTED = "#5f646b"
LINE = "#d8dde3"
PAPER = "#f7f8fa"
CARD = "#ffffff"
TEAL = "#00a884"
RED = "#d64f4f"
AMBER = "#c58a00"
BLUE = "#276ef1"


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    family = "DejaVu Sans"
    weight = "bold" if bold else "normal"
    path = font_manager.findfont(
        font_manager.FontProperties(family=family, weight=weight)
    )
    return ImageFont.truetype(path, size)


def fmt_money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):.2f}"


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: str, outline: str = LINE) -> None:
    draw.rounded_rectangle(box, radius=18, fill=fill, outline=outline, width=2)


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    max_width: int,
    text_font: ImageFont.FreeTypeFont,
    fill: str,
    line_gap: int = 8,
) -> int:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=text_font)[2] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=text_font, fill=fill)
        y += text_font.size + line_gap
    return y


def load_stats() -> dict[str, object]:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT strategy, symbol, side, closed_at, realized_pnl, entry_fee, exit_fee
        FROM paper_positions
        WHERE status = 'CLOSED'
        ORDER BY closed_at
        """
    ).fetchall()
    by_strategy = connection.execute(
        """
        SELECT strategy,
               COUNT(*) AS trades,
               SUM(realized_pnl) AS pnl,
               100.0 * SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) / COUNT(*) AS win_rate
        FROM paper_positions
        WHERE status = 'CLOSED'
        GROUP BY strategy
        ORDER BY strategy
        """
    ).fetchall()
    counters = {
        "decision_replay": connection.execute("SELECT COUNT(*) FROM decision_replay").fetchone()[0],
        "event_ledger": connection.execute("SELECT COUNT(*) FROM event_ledger").fetchone()[0],
        "signals": connection.execute("SELECT COUNT(*) FROM signals").fetchone()[0],
    }
    versions_text = (ROOT / "docs" / "strategy_versions.md").read_text()
    versions = versions_text.count("### `momentum_context_v")
    connection.close()

    cumulative: list[float] = []
    running = 0.0
    fees = 0.0
    for row in rows:
        pnl = float(row["realized_pnl"] or 0.0)
        running += pnl
        fees += float(row["entry_fee"] or 0.0) + float(row["exit_fee"] or 0.0)
        cumulative.append(running)

    return {
        "rows": rows,
        "by_strategy": by_strategy,
        "cumulative": cumulative,
        "versions": versions,
        "fees": fees,
        "counters": counters,
    }


def chart_image(cumulative: list[float], by_strategy: list[sqlite3.Row]) -> Image.Image:
    fig, ax = plt.subplots(figsize=(8.7, 4.35), dpi=120)
    fig.patch.set_facecolor(CARD)
    ax.set_facecolor(CARD)

    x = list(range(1, len(cumulative) + 1))
    ax.plot(x, cumulative, color=RED, linewidth=3.8)
    ax.fill_between(x, cumulative, 0, color=RED, alpha=0.08)
    ax.axhline(0, color="#8e949c", linewidth=1.2)

    v8_count = next((int(row["trades"]) for row in by_strategy if row["strategy"] == "momentum_context_v8"), 0)
    if v8_count:
        ax.axvline(v8_count, color=BLUE, linestyle="--", linewidth=1.5, alpha=0.8)
        ax.text(v8_count + 1, min(cumulative) * 0.9, "v9", color=BLUE, fontsize=11, weight="bold")

    ax.set_title("PnL cumulativo paper trading", loc="left", fontsize=16, fontweight="bold", color=INK, pad=18)
    ax.set_xlabel("Trade chiusi", color=MUTED, fontsize=10)
    ax.set_ylabel("USD", color=MUTED, fontsize=10)
    ax.grid(axis="y", color=LINE, linewidth=1, alpha=0.8)
    ax.tick_params(axis="both", colors=MUTED, labelsize=9)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout(pad=1.4)

    buffer = BytesIO()
    fig.savefig(buffer, format="png", transparent=False)
    plt.close(fig)
    buffer.seek(0)
    return Image.open(buffer).convert("RGBA")


def render() -> Path:
    stats = load_stats()
    rows = stats["rows"]
    by_strategy = stats["by_strategy"]
    cumulative = stats["cumulative"]
    counters = stats["counters"]

    total_trades = len(rows)
    total_pnl = cumulative[-1] if cumulative else 0.0
    fees = float(stats["fees"])
    versions = int(stats["versions"])
    win_rate = (
        sum(1 for row in rows if float(row["realized_pnl"] or 0.0) > 0) / total_trades * 100
        if total_trades
        else 0.0
    )

    image = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(image)

    draw.rectangle((0, 0, WIDTH, 16), fill=TEAL)
    draw.text((MARGIN, 54), "VIBE-CODED TRADER DIGITALE", font=font(25, bold=True), fill=TEAL)
    draw_wrapped(
        draw,
        "Ho costruito un trader digitale con l'AI.",
        (MARGIN, 102),
        WIDTH - MARGIN * 2,
        font(48, bold=True),
        INK,
        line_gap=6,
    )
    draw_wrapped(
        draw,
        "Non una money machine: un prodotto locale che osserva mercati crypto, simula entrate, misura costi, registra decisioni e mi mostra perche il bot ha agito o aspettato.",
        (MARGIN, 218),
        WIDTH - MARGIN * 2,
        font(25),
        MUTED,
        line_gap=9,
    )

    y = 350
    metric_w = 220
    gap = 22
    metrics = [
        ("Versioni", str(versions), "da v5 a v9"),
        ("Trade paper", str(total_trades), "zero soldi reali"),
        ("PnL netto", fmt_money(total_pnl), "dopo fee simulate"),
        ("Win rate", f"{win_rate:.1f}%", "strategia non validata"),
    ]
    for idx, (label, value, detail) in enumerate(metrics):
        x0 = MARGIN + idx * (metric_w + gap)
        rounded(draw, (x0, y, x0 + metric_w, y + 146), CARD)
        color = RED if label == "PnL netto" else (TEAL if idx < 2 else INK)
        draw.text((x0 + 22, y + 22), label, font=font(19, bold=True), fill=MUTED)
        draw.text((x0 + 22, y + 56), value, font=font(36, bold=True), fill=color)
        draw.text((x0 + 22, y + 108), detail, font=font(17), fill=MUTED)

    chart = chart_image(cumulative, by_strategy)
    rounded(draw, (MARGIN, 535, WIDTH - MARGIN, 915), CARD)
    chart_rendered = chart.resize((WIDTH - MARGIN * 2 - 34, 335))
    image.paste(chart_rendered, (MARGIN + 17, 557), chart_rendered.split()[-1])

    y2 = 955
    left = (MARGIN, y2, 512, y2 + 250)
    right = (536, y2, WIDTH - MARGIN, y2 + 250)
    rounded(draw, left, CARD)
    rounded(draw, right, CARD)

    draw.text((left[0] + 24, y2 + 24), "Cosa ha fatto l'AI", font=font(25, bold=True), fill=INK)
    ai_lines = [
        "architettura e codice",
        "debug continuo",
        "UI + widget desktop",
        "analisi trade e logica v9",
    ]
    yy = y2 + 76
    for line in ai_lines:
        draw.ellipse((left[0] + 24, yy + 6, left[0] + 38, yy + 20), fill=TEAL)
        draw.text((left[0] + 52, yy), line, font=font(22), fill=INK)
        yy += 40

    draw.text((right[0] + 24, y2 + 24), "Cosa ho imparato", font=font(25, bold=True), fill=INK)
    learn = "La competenza verticale conta piu del prompt: senza dominio, l'AI accelera anche gli errori."
    draw_wrapped(draw, learn, (right[0] + 24, y2 + 76), right[2] - right[0] - 48, font(24), INK, line_gap=8)
    draw.text((right[0] + 24, y2 + 182), f"{counters['decision_replay']:,}".replace(",", "."), font=font(34, bold=True), fill=BLUE)
    draw.text((right[0] + 170, y2 + 194), "decision replay registrati", font=font(19), fill=MUTED)

    footer = (
        f"Periodo: 09 Apr - 05 Mag 2026 | Fee simulate: {fmt_money(fees)} | "
        "Paper trading, nessuna promessa di rendimento"
    )
    draw.text((MARGIN, HEIGHT - 90), footer, font=font(19), fill=MUTED)
    draw_wrapped(
        draw,
        "Domanda: vale di piu saper programmare, o saper scegliere il problema giusto?",
        (MARGIN, HEIGHT - 58),
        WIDTH - MARGIN * 2,
        font(20, bold=True),
        INK,
        line_gap=4,
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT_PATH, quality=95)
    return OUTPUT_PATH


if __name__ == "__main__":
    print(render())
