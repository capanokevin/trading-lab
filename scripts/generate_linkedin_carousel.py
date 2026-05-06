from __future__ import annotations

import sqlite3
from datetime import datetime
from io import BytesIO
from pathlib import Path

import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "trading_paper.sqlite3"
EXPORT_DIR = ROOT / "data" / "exports" / "linkedin-carousel-trader-digitale-2026-05-05"
PDF_PATH = ROOT / "data" / "exports" / "linkedin-carousel-trader-digitale-2026-05-05.pdf"
GITHUB_URL = "https://github.com/capanokevin/trading-lab"
GITHUB_DISPLAY_URL = "github.com/capanokevin/trading-lab"
SNAPSHOT_END_ISO = "2026-05-05T23:59:59Z"

W = 1080
H = 1350
M = 78

INK = "#111318"
MUTED = "#68707a"
WHITE = "#fbfcff"
CREAM = "#f4efe5"
PAPER = "#fffaf0"
LINE = "#d8d0c1"
GREEN = "#00a884"
BLUE = "#276ef1"
YELLOW = "#e8ff5f"
RED = "#d84c4c"
BLACK = "#0e1116"
CARD = "#1a1d23"
FONT_COLLECTION = Path("/System/Library/Fonts/Avenir Next.ttc")
FONT_REGULAR_INDEX = 5
FONT_BOLD_INDEX = 0

plt.rcParams["font.family"] = "Avenir Next"


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    index = FONT_BOLD_INDEX if bold else FONT_REGULAR_INDEX
    if FONT_COLLECTION.exists():
        return ImageFont.truetype(str(FONT_COLLECTION), size, index=index)
    return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size, index=1 if bold else 0)


def money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):.2f}"


def short_money(value: float) -> str:
    return f"${abs(value):.0f}"


def it_date(value: str) -> str:
    months = {
        1: "gen",
        2: "feb",
        3: "mar",
        4: "apr",
        5: "mag",
        6: "giu",
        7: "lug",
        8: "ago",
        9: "set",
        10: "ott",
        11: "nov",
        12: "dic",
    }
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return f"{dt.day} {months[dt.month]}"


def wrapped(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    max_width: int,
    text_font: ImageFont.FreeTypeFont,
    fill: str,
    gap: int = 10,
) -> int:
    words = text.split()
    lines: list[str] = []
    line = ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=text_font)[2] <= max_width:
            line = candidate
            continue
        if line:
            lines.append(line)
        line = word
    if line:
        lines.append(line)
    x, y = xy
    for item in lines:
        draw.text((x, y), item, font=text_font, fill=fill)
        y += text_font.size + gap
    return y


def badge(draw: ImageDraw.ImageDraw, text: str, x: int, y: int, bg: str, fg: str) -> None:
    text_font = font(24, bold=True)
    box = draw.textbbox((0, 0), text, font=text_font)
    width = box[2] + 44
    draw.rounded_rectangle((x, y, x + width, y + 54), radius=27, fill=bg)
    draw.text((x + 22, y + 13), text, font=text_font, fill=fg)


def footer(draw: ImageDraw.ImageDraw, idx: int, total: int, fg: str = MUTED) -> None:
    draw.text((M, H - 82), "vibe-coded trading lab", font=font(22, bold=True), fill=fg)
    draw.text((W - M - 56, H - 82), f"{idx}/{total}", font=font(22, bold=True), fill=fg)


def vertical_item(
    draw: ImageDraw.ImageDraw,
    idx: int,
    title: str,
    body: str,
    y: int,
    *,
    bg: str = PAPER,
    fg: str = INK,
    accent: str = YELLOW,
) -> None:
    draw.rounded_rectangle((M, y, W - M, y + 92), radius=26, fill=bg, outline=LINE, width=2)
    draw.rounded_rectangle((M + 22, y + 22, M + 68, y + 68), radius=14, fill=accent)
    draw.text((M + 38, y + 33), str(idx), font=font(19, bold=True), fill=BLACK)
    draw.text((M + 92, y + 18), title, font=font(28, bold=True), fill=fg)
    draw.text((M + 92, y + 55), body, font=font(20), fill=MUTED)


def metric_card(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    value: str,
    *,
    accent: str,
    w: int = 430,
    h: int = 142,
    dark: bool = False,
) -> None:
    fill = CARD if dark else PAPER
    outline = "#343a45" if dark else LINE
    label_fill = "#bfc6d2" if dark else MUTED
    value_fill = accent
    draw.rounded_rectangle((x, y, x + w, y + h), radius=30, fill=fill, outline=outline, width=2)
    draw.text((x + 28, y + 28), value, font=font(42, bold=True), fill=value_fill)
    draw.text((x + 28, y + 86), label, font=font(24, bold=True), fill=label_fill)


def stats() -> dict[str, object]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT strategy, closed_at, realized_pnl, entry_fee, exit_fee
        FROM paper_positions
        WHERE status = 'CLOSED'
          AND closed_at <= ?
        ORDER BY closed_at
        """,
        (SNAPSHOT_END_ISO,),
    ).fetchall()
    versions = (ROOT / "docs" / "strategy_versions.md").read_text().count(
        "### `momentum_context_v"
    )
    conn.close()

    pnl = 0.0
    fees = 0.0
    cumulative: list[float] = []
    winners = 0
    first_closed_at = rows[0]["closed_at"] if rows else ""
    last_closed_at = rows[-1]["closed_at"] if rows else ""
    days = 0
    if first_closed_at and last_closed_at:
        start = datetime.fromisoformat(first_closed_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(last_closed_at.replace("Z", "+00:00"))
        days = max(1, round((end - start).total_seconds() / 86400))
    for row in rows:
        value = float(row["realized_pnl"] or 0.0)
        pnl += value
        fees += float(row["entry_fee"] or 0.0) + float(row["exit_fee"] or 0.0)
        cumulative.append(pnl)
        if value > 0:
            winners += 1
    win_rate = winners / len(rows) * 100 if rows else 0.0
    return {
        "trades": len(rows),
        "versions": versions,
        "pnl": pnl,
        "fees": fees,
        "win_rate": win_rate,
        "replay": "20k+",
        "cumulative": cumulative,
        "first_closed_at": first_closed_at,
        "last_closed_at": last_closed_at,
        "days": days,
    }


def chart(cumulative: list[float]) -> Image.Image:
    fig, ax = plt.subplots(figsize=(8.8, 4.1), dpi=130)
    fig.patch.set_facecolor(WHITE)
    ax.set_facecolor(WHITE)
    x = list(range(1, len(cumulative) + 1))
    ax.plot(x, cumulative, color=RED, linewidth=4.2)
    ax.fill_between(x, cumulative, 0, color=RED, alpha=0.1)
    ax.axhline(0, color="#808895", linewidth=1.2)
    ax.axvline(36, color=BLUE, linestyle="--", linewidth=1.6)
    ax.text(38, -4, "v9", color=BLUE, fontsize=12, weight="bold")
    ax.set_title("PnL cumulativo paper trading", loc="left", fontsize=17, fontweight="bold")
    ax.grid(axis="y", color=LINE)
    ax.tick_params(axis="both", colors=MUTED, labelsize=9)
    ax.set_xlabel("trade chiusi", color=MUTED, fontsize=10)
    ax.set_ylabel("USD", color=MUTED, fontsize=10)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def base(bg: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (W, H), bg)
    return image, ImageDraw.Draw(image)


def slide_1(total: int, s: dict[str, object]) -> Image.Image:
    image, draw = base(BLACK)
    draw.rectangle((0, 0, W, 18), fill=YELLOW)
    badge(draw, "paper trading lab", M, 84, YELLOW, BLACK)
    wrapped(draw, f"Ho perso {short_money(float(s['pnl']))} con un trader AI.", (M, 210), W - 2 * M, font(82, bold=True), WHITE, 16)
    wrapped(draw, "La parte interessante non era il PnL.", (M, 555), W - 2 * M, font(54, bold=True), YELLOW, 12)
    wrapped(draw, "Era capire cosa si può costruire quando l'AI diventa un partner tecnico, anche senza essere sviluppatore o trader professionista.", (M, 725), W - 2 * M, font(34), "#d8dde7", 12)
    draw.rounded_rectangle((M, 1030, W - M, 1148), radius=30, fill=CARD, outline="#333b49", width=2)
    draw.text((M + 34, 1062), f"{s['trades']} trade paper. Zero soldi reali.", font=font(34, bold=True), fill=WHITE)
    footer(draw, 1, total, "#9aa3b1")
    return image


def slide_2(total: int) -> Image.Image:
    image, draw = base(CREAM)
    badge(draw, "il progetto", M, 82, BLACK, YELLOW)
    wrapped(draw, "Non un bot magico.", (M, 205), W - 2 * M, font(74, bold=True), INK, 12)
    wrapped(draw, "Un laboratorio locale che osserva crypto, simula trade e spiega le decisioni.", (M, 435), W - 2 * M, font(42), INK, 12)
    items = [
        ("market data", "feed crypto e contesto operativo"),
        ("paper trading", "ordini simulati con rischio zero"),
        ("fee e slippage", "costi stimati, non solo PnL lordo"),
        ("dashboard", "stato del desk leggibile al volo"),
        ("decision replay", "perché ha fatto o non fatto un trade"),
        ("versioni", "ogni cambio strategia resta tracciato"),
    ]
    y = 600
    for idx, (title, body) in enumerate(items, start=1):
        vertical_item(draw, idx, title, body, y)
        y += 102
    footer(draw, 2, total)
    return image


def slide_3(total: int) -> Image.Image:
    image, draw = base(YELLOW)
    badge(draw, "ruolo umano", M, 82, BLACK, YELLOW)
    wrapped(draw, "Io non sono un trader.", (M, 220), W - 2 * M, font(74, bold=True), BLACK, 10)
    wrapped(draw, "Il mio contributo è stato fare domande, rompere la UI, guardare i dati e cambiare idea.", (M, 500), W - 2 * M, font(43), BLACK, 12)
    draw.line((M, 860, W - M, 860), fill=BLACK, width=4)
    draw.text((M, 910), "prompt != competenza", font=font(46, bold=True), fill=BLACK)
    draw.text((M, 980), "ma può diventare leva se hai giudizio", font=font(32), fill=BLACK)
    footer(draw, 3, total, BLACK)
    return image


def slide_4(total: int) -> Image.Image:
    image, draw = base(BLACK)
    draw.rectangle((0, 0, W, 18), fill=YELLOW)
    badge(draw, "cosa ha fatto l'AI", M, 82, YELLOW, BLACK)
    wrapped(draw, "Ha trasformato feedback in prodotto.", (M, 210), W - 2 * M, font(70, bold=True), WHITE, 12)
    items = ["API crypto", "Python bot", "debug", "UI + widget", "logging", "analisi trade"]
    y = 560
    for idx, item in enumerate(items):
        x = M + (idx % 2) * 465
        if idx and idx % 2 == 0:
            y += 130
        draw.rounded_rectangle((x, y, x + 405, y + 92), radius=28, fill=CARD, outline="#343a45", width=2)
        draw.text((x + 28, y + 26), item, font=font(31, bold=True), fill=WHITE)
    footer(draw, 4, total, "#9aa3b1")
    return image


def slide_5(total: int, s: dict[str, object]) -> Image.Image:
    image, draw = base(CREAM)
    badge(draw, "numeri veri", M, 82, BLACK, YELLOW)
    wrapped(draw, "Niente guru mode.", (M, 205), W - 2 * M, font(76, bold=True), INK, 10)
    data = [
        ("versioni", str(s["versions"]), GREEN),
        ("trade paper", str(s["trades"]), GREEN),
        ("decision replay", str(s["replay"]), BLUE),
        ("PnL netto", money(float(s["pnl"])), RED),
        ("fee simulate", money(float(s["fees"])), GREEN),
        ("win rate", f"{float(s['win_rate']):.1f}%", GREEN),
    ]
    y = 430
    for idx, (label, value, color) in enumerate(data):
        x = M + (idx % 2) * 465
        if idx and idx % 2 == 0:
            y += 172
        metric_card(draw, x, y, label, value, accent=color)
    horizon = f"{it_date(str(s['first_closed_at']))} - {it_date(str(s['last_closed_at']))} 2026 · circa {s['days']} giorni"
    wrapped(draw, horizon, (M, 1018), W - 2 * M, font(27, bold=True), MUTED, 8)
    wrapped(draw, "Campione ancora acerbo: utile per imparare, non per validare performance.", (M, 1070), W - 2 * M, font(33, bold=True), INK, 8)
    footer(draw, 5, total)
    return image


def slide_6(total: int, s: dict[str, object]) -> Image.Image:
    image, draw = base(CREAM)
    badge(draw, "la curva", M, 82, BLACK, YELLOW)
    wrapped(draw, "La curva non mente.", (M, 185), W - 2 * M, font(70, bold=True), INK, 10)
    plot = chart(list(s["cumulative"]))
    draw.rounded_rectangle((M, 360, W - M, 820), radius=28, fill=PAPER, outline=LINE, width=2)
    plot = plot.resize((W - 2 * M - 42, 398))
    image.paste(plot, (M + 21, 392))
    wrapped(draw, "L'AI accelera l'esperimento. Non garantisce che l'ipotesi sia giusta.", (M, 900), W - 2 * M, font(42, bold=True), INK, 12)
    footer(draw, 6, total)
    return image


def slide_7(total: int) -> Image.Image:
    image, draw = base(BLACK)
    draw.rectangle((0, 0, W, 18), fill=YELLOW)
    badge(draw, "lezione", M, 82, YELLOW, BLACK)
    wrapped(draw, "Il dominio batte il prompt.", (M, 210), W - 2 * M, font(78, bold=True), WHITE, 12)
    wrapped(draw, "Se non capisci il problema, l'AI può farti andare molto più veloce nella direzione sbagliata.", (M, 500), W - 2 * M, font(43), "#d8dde7", 12)
    metric_card(draw, M, 850, "con l'AI", "costruire è più facile", accent=WHITE, w=W - 2 * M, h=130, dark=True)
    metric_card(draw, M, 1010, "resta il punto difficile", "capire cosa costruire", accent=YELLOW, w=W - 2 * M, h=130, dark=True)
    footer(draw, 7, total, "#9aa3b1")
    return image


def slide_8(total: int) -> Image.Image:
    image, draw = base(YELLOW)
    badge(draw, "next", M, 82, BLACK, YELLOW)
    wrapped(draw, "Il codice va su GitHub.", (M, 220), W - 2 * M, font(78, bold=True), BLACK, 12)
    wrapped(draw, "Non come bot per fare soldi. Come esperimento open, leggibile e migliorabile.", (M, 515), W - 2 * M, font(43), BLACK, 12)
    draw.rounded_rectangle((M, 835, W - M, 955), radius=32, fill=BLACK)
    draw.text((M + 34, 875), GITHUB_DISPLAY_URL, font=font(31, bold=True), fill=YELLOW)
    draw.rounded_rectangle((M, 1030, W - M, 1158), radius=38, fill=PAPER, outline=BLACK, width=3)
    wrapped(draw, "Se avessi un dev AI sempre accanto, che prodotto verticale costruiresti?", (M + 36, 1060), W - 2 * M - 72, font(34, bold=True), BLACK, 8)
    footer(draw, 8, total, BLACK)
    return image


def render() -> tuple[Path, Path]:
    s = stats()
    slides = [
        slide_1(8, s),
        slide_2(8),
        slide_3(8),
        slide_4(8),
        slide_5(8, s),
        slide_6(8, s),
        slide_7(8),
        slide_8(8),
    ]
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for idx, slide in enumerate(slides, start=1):
        path = EXPORT_DIR / f"slide-{idx:02d}.png"
        slide.save(path, quality=96)
        paths.append(path)
    slides[0].save(PDF_PATH, save_all=True, append_images=slides[1:], resolution=96)
    return EXPORT_DIR, PDF_PATH


if __name__ == "__main__":
    out_dir, pdf = render()
    print(out_dir)
    print(pdf)
