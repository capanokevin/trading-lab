from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import warnings

import objc
from AppKit import (
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSButton,
    NSColor,
    NSFont,
    NSMakeRect,
    NSScreen,
    NSStatusBar,
    NSTextField,
    NSView,
    NSVisualEffectMaterialSidebar,
    NSVisualEffectStateActive,
    NSVisualEffectView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskFullSizeContentView,
    NSWindowStyleMaskTitled,
    NSPanel,
    NSWorkspace,
)
from Foundation import NSTimer, NSURL
from PyObjCTools import AppHelper
from Quartz import CGWindowLevelForKey, kCGDesktopIconWindowLevelKey

from trading_bot.config import AppConfig
from trading_bot.storage import TradingStorage

warnings.filterwarnings("ignore", category=objc.ObjCPointerWarning)


def _color(r: int, g: int, b: int, a: float = 1.0) -> NSColor:
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(
        r / 255.0, g / 255.0, b / 255.0, a
    )


INK = _color(36, 23, 18)
MUTED = _color(106, 88, 79)
ACCENT = _color(201, 97, 36)
GOOD = _color(18, 112, 77)
BAD = _color(179, 71, 59)
WATCH = _color(143, 106, 30)
CARD_BG = _color(255, 255, 255, 0.70)
CARD_LINE = _color(74, 54, 43, 0.12)
SOFT_BG = _color(255, 248, 240, 0.82)


def _eur(value: float | int | None) -> str:
    if value is None:
        return "n/d"
    return f"{float(value):,.2f} EUR".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(value: float | int | None, digits: int = 2) -> str:
    if value is None:
        return "n/d"
    return f"{float(value):.{digits}f}%".replace(".", ",")


def _short_status(status: str | None) -> str:
    mapping = {
        "ATTIVO": "OK",
        "COOLDOWN": "PAUSA",
        "HARD_STOP": "STOP",
    }
    return mapping.get((status or "").upper(), "DESK")


def _nice_status(status: str | None) -> str:
    mapping = {
        "ATTIVO": "Attivo",
        "COOLDOWN": "Cooldown",
        "HARD_STOP": "Hard stop",
        "ENTRATA_ESEGUITA": "Entrata",
        "IN_POSIZIONE": "In posizione",
        "OSSERVAZIONE": "Osservazione",
        "BLOCCATO": "Bloccato",
        "ATTESA_CANDELE": "Attesa candele",
        "DATI_INSUFFICIENTI": "Dati insufficienti",
    }
    return mapping.get((status or "").upper(), status or "n/d")


def _tone_color(status: str | None) -> NSColor:
    code = (status or "").upper()
    if code in {"ATTIVO", "ENTRATA_ESEGUITA", "IN_POSIZIONE"}:
        return GOOD
    if code in {"HARD_STOP", "BLOCCATO"}:
        return BAD
    return WATCH


def _clip_text(value: str | None, limit: int = 82) -> str:
    if not value:
        return "Nessun messaggio."
    clean = " ".join(value.split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


@dataclass(slots=True)
class SymbolWidgets:
    container: Any
    title: Any
    status: Any
    price: Any
    meta: Any
    reason: Any


class DeskCompanionAppDelegate(objc.lookUpClass("NSObject")):
    config = objc.ivar()
    storage = objc.ivar()
    status_item = objc.ivar()
    panel = objc.ivar()
    timer = objc.ivar()
    widgets = objc.ivar()
    desktop_level = objc.ivar()

    def initWithConfig_storage_(self, config: AppConfig, storage: TradingStorage):  # noqa: N802
        self = objc.super(DeskCompanionAppDelegate, self).init()
        if self is None:
            return None
        self.config = config
        self.storage = storage
        self.widgets = {}
        self.desktop_level = CGWindowLevelForKey(kCGDesktopIconWindowLevelKey) - 1
        return self

    def applicationDidFinishLaunching_(self, notification) -> None:  # noqa: N802
        self.storage.init_db()
        self._build_status_item()
        self._build_panel()
        self.refresh_(None)
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            5.0, self, "refresh:", None, True
        )

    def applicationShouldTerminateAfterLastWindowClosed_(self, app) -> bool:  # noqa: N802
        return False

    def togglePanel_(self, sender) -> None:  # noqa: N802
        if self.panel.isVisible():
            self.panel.orderOut_(None)
            return
        self._position_panel()
        self.panel.orderFront_(None)
        self.panel.orderBack_(None)

    def refresh_(self, sender) -> None:  # noqa: N802
        try:
            summary = self.storage.build_dashboard_summary(
                symbols=self.config.monitored_symbols,
                paper_start_balance=self.config.paper_start_balance,
                candles_interval_minutes=self.config.candles_interval_minutes,
            )
        except Exception as exc:  # pragma: no cover - UI fallback
            self._set_status_title("Desk ERR")
            self.widgets["hero_value"].setStringValue_("Connessione dati")
            self.widgets["hero_sub"].setStringValue_(str(exc))
            return

        risk = summary["risk"]
        account = summary["account"]
        performance = summary["performance"]
        symbols = summary["symbols"]
        bot = summary["bot"]

        status_text = _nice_status(risk["guardrail_status"])
        self._set_status_title(
            f"Desk {_short_status(risk['guardrail_status'])} {_eur(risk['daily_realized_pnl']).split()[0]}"
        )
        self.widgets["hero_value"].setStringValue_(status_text)
        self.widgets["hero_value"].setTextColor_(_tone_color(risk["guardrail_status"]))
        self.widgets["hero_sub"].setStringValue_(
            f"Bot {_nice_status(bot['status'])} | ultimo ciclo {bot['last_cycle_at'] or 'n/d'}"
        )
        self.widgets["hero_badge"].setStringValue_(
            f"{summary['provider']['current']['label']} | {bot['data_mode']}"
        )

        self._update_stat(
            "equity",
            _eur(account["equity"]),
            f"Cassa {_eur(account['cash'])}",
            GOOD if float(account["equity"]) >= float(account["starting_balance"]) else BAD,
        )
        self._update_stat(
            "pnl",
            _eur(risk["daily_realized_pnl"]),
            f"PnL chiuso oggi | trade {risk['daily_trade_count']}",
            GOOD if float(risk["daily_realized_pnl"]) >= 0 else BAD,
        )
        self._update_stat(
            "risk",
            _pct(account["current_exposure_pct"], 2),
            f"Drawdown {_pct(risk['current_drawdown_pct'], 2)}",
            _tone_color(risk["guardrail_status"]),
        )
        self._update_stat(
            "fees",
            _eur(performance["today_fees_eur"]),
            f"Fee totali {_eur(account['fees_total'])}",
            WATCH,
        )
        self.widgets["positions_value"].setStringValue_(str(risk["open_positions"]))
        self.widgets["positions_value"].setTextColor_(INK)
        self.widgets["discipline_value"].setStringValue_(
            f"{risk['daily_trade_count']}/{risk['daily_trade_limit']}"
        )
        self.widgets["discipline_value"].setTextColor_(
            BAD if risk["consecutive_losses"] else INK
        )
        self.widgets["focus_value"].setStringValue_(_pct(risk["current_drawdown_pct"], 2))
        self.widgets["focus_value"].setTextColor_(
            BAD if float(risk["current_drawdown_pct"]) > 0 else INK
        )

        kill_reason = risk["kill_switch_reason"] or "Nessun blocco attivo. Il desk puo continuare a monitorare setup."
        self.widgets["alert_title"].setStringValue_(
            "Alert desk" if risk["guardrail_status"] != "ATTIVO" else "Desk operativo"
        )
        self.widgets["alert_title"].setTextColor_(_tone_color(risk["guardrail_status"]))
        self.widgets["alert_body"].setStringValue_(_clip_text(kill_reason, 130))

        for index, symbol in enumerate(symbols[:2]):
            slot = self.widgets[f"symbol_{index}"]
            analysis = symbol.get("analysis") or {}
            details = analysis.get("details") or {}
            slot.title.setStringValue_(symbol["symbol"])
            slot.status.setStringValue_(_nice_status(analysis.get("status")))
            slot.status.setTextColor_(_tone_color(analysis.get("status")))
            slot.price.setStringValue_(_eur(symbol.get("mid_price")).replace(" EUR", ""))
            slot.meta.setStringValue_(
                f"S {('n/d' if symbol.get('spread_bps') is None else _pct(symbol.get('spread_bps'), 1).replace('%', 'b'))}  T{symbol['trade_activity']['count']}"
            )
            slot.reason.setStringValue_(
                _clip_text(
                    details.get("prossima_condizione") or analysis.get("reason") or "Monitoraggio in corso.",
                    84,
                )
            )
            slot.container.setHidden_(False)

        for index in range(len(symbols), 2):
            self.widgets[f"symbol_{index}"].container.setHidden_(True)

    @objc.python_method
    def _build_status_item(self) -> None:
        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(-1)
        button = self.status_item.button()
        button.setTitle_("Desk")
        button.setTarget_(self)
        button.setAction_("togglePanel:")

    @objc.python_method
    def _build_panel(self) -> None:
        width = 332
        height = 432
        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskFullSizeContentView
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, width, height),
            style,
            NSBackingStoreBuffered,
            False,
        )
        self.panel.setReleasedWhenClosed_(False)
        self.panel.setFloatingPanel_(False)
        self.panel.setLevel_(self.desktop_level)
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setMovableByWindowBackground_(True)
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setHasShadow_(False)
        self.panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
            | NSWindowCollectionBehaviorStationary
        )
        self._position_panel()

        root = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        root.setMaterial_(NSVisualEffectMaterialSidebar)
        root.setState_(NSVisualEffectStateActive)
        root.setBlendingMode_(0)
        root.setWantsLayer_(True)
        root.layer().setCornerRadius_(26.0)
        root.layer().setMasksToBounds_(True)
        self.panel.setContentView_(root)

        header = self._make_box(root, NSMakeRect(14, 338, 304, 78), _color(255, 248, 240, 0.76))
        title = self._make_label(header, NSMakeRect(16, 48, 180, 16), "Trading Desk", 13, True)
        title.setTextColor_(MUTED)
        hero_value = self._make_label(header, NSMakeRect(16, 18, 170, 28), "Attivo", 28, True)
        hero_sub = self._make_label(header, NSMakeRect(16, 4, 210, 14), "", 10, False)
        hero_sub.setTextColor_(MUTED)
        hero_badge = self._make_badge(header, NSMakeRect(198, 24, 90, 26), "")

        button_refresh = self._make_button(root, NSMakeRect(14, 304, 94, 26), "Aggiorna", "refresh:")
        button_open = self._make_button(root, NSMakeRect(118, 304, 104, 26), "Dashboard", "openDashboard:")
        button_hide = self._make_button(root, NSMakeRect(232, 304, 86, 26), "Chiudi", "togglePanel:")

        stat_specs = [
            ("equity", "Equity", NSMakeRect(14, 214, 146, 76)),
            ("pnl", "PnL oggi", NSMakeRect(172, 214, 146, 76)),
            ("risk", "Rischio", NSMakeRect(14, 128, 146, 76)),
            ("fees", "Costi", NSMakeRect(172, 128, 146, 76)),
        ]
        for key, title_text, frame in stat_specs:
            box = self._make_box(root, frame, CARD_BG)
            label = self._make_label(box, NSMakeRect(12, 50, 120, 14), title_text, 11, True)
            label.setTextColor_(MUTED)
            value = self._make_label(box, NSMakeRect(12, 22, 120, 24), "--", 18, True, mono=True)
            sub = self._make_label(box, NSMakeRect(12, 7, 126, 14), "", 10, False)
            sub.setTextColor_(MUTED)
            self.widgets[key] = {"value": value, "sub": sub}

        micro = self._make_box(root, NSMakeRect(14, 84, 304, 34), _color(255, 251, 246, 0.66))
        positions_title = self._make_label(micro, NSMakeRect(12, 16, 90, 12), "Posizioni", 10, True)
        positions_title.setTextColor_(MUTED)
        positions_value = self._make_label(micro, NSMakeRect(12, 0, 84, 16), "0", 15, True, mono=True)
        discipline_title = self._make_label(micro, NSMakeRect(112, 16, 90, 12), "Disciplina", 10, True)
        discipline_title.setTextColor_(MUTED)
        discipline_value = self._make_label(micro, NSMakeRect(112, 0, 84, 16), "0/10", 15, True, mono=True)
        focus_title = self._make_label(micro, NSMakeRect(210, 16, 80, 12), "Drawdown", 10, True)
        focus_title.setTextColor_(MUTED)
        focus_value = self._make_label(micro, NSMakeRect(210, 0, 84, 16), "0,00%", 15, True, mono=True)

        alert = self._make_box(root, NSMakeRect(14, 42, 304, 34), _color(255, 251, 246, 0.72))
        alert_title = self._make_label(alert, NSMakeRect(12, 18, 150, 14), "Desk operativo", 11, True)
        alert_body = self._make_label(alert, NSMakeRect(12, 4, 280, 14), "", 10, False)
        alert_body.setTextColor_(INK)
        alert_foot = self._make_label(alert, NSMakeRect(0, 0, 0, 0), "", 10, False)
        alert_foot.setHidden_(True)
        alert_foot.setTextColor_(MUTED)

        symbol_zero = self._build_symbol_card(root, "BTC-EUR", NSMakeRect(14, 8, 146, 28))
        symbol_one = self._build_symbol_card(root, "ETH-EUR", NSMakeRect(172, 8, 146, 28))

        self.widgets.update(
            {
                "hero_value": hero_value,
                "hero_sub": hero_sub,
                "hero_badge": hero_badge,
                "button_refresh": button_refresh,
                "button_open": button_open,
                "button_hide": button_hide,
                "symbol_0": symbol_zero,
                "symbol_1": symbol_one,
                "alert_title": alert_title,
                "alert_body": alert_body,
                "alert_foot": alert_foot,
                "positions_value": positions_value,
                "discipline_value": discipline_value,
                "focus_value": focus_value,
            }
        )

        self.panel.orderFront_(None)
        self.panel.orderBack_(None)

    def openDashboard_(self, sender) -> None:  # noqa: N802
        NSWorkspace.sharedWorkspace().openURL_(
            NSURL.URLWithString_(f"http://{self.config.dashboard_host}:{self.config.dashboard_port}")
        )

    @objc.python_method
    def _position_panel(self) -> None:
        screen = NSScreen.mainScreen()
        if screen is None:
            return
        visible = screen.visibleFrame()
        width = self.panel.frame().size.width
        height = self.panel.frame().size.height
        x = visible.origin.x + visible.size.width - width - 28
        y = visible.origin.y + 28
        self.panel.setFrame_display_(NSMakeRect(x, y, width, height), True)

    @objc.python_method
    def _update_stat(
        self, key: str, value: str, sub: str, color: NSColor | None = None
    ) -> None:
        self.widgets[key]["value"].setStringValue_(value)
        self.widgets[key]["value"].setTextColor_(color or INK)
        self.widgets[key]["sub"].setStringValue_(sub)

    @objc.python_method
    def _build_symbol_card(self, parent: Any, title_text: str, frame: Any) -> SymbolWidgets:
        box = self._make_box(parent, frame, CARD_BG)
        title = self._make_label(box, NSMakeRect(10, 13, 66, 12), title_text, 10, True)
        title.setTextColor_(MUTED)
        status = self._make_label(box, NSMakeRect(74, 13, 62, 12), "Attesa", 10, True)
        price = self._make_label(box, NSMakeRect(10, 0, 72, 14), "--", 13, True, mono=True)
        meta = self._make_label(box, NSMakeRect(88, 0, 50, 12), "", 8, False)
        meta.setTextColor_(MUTED)
        reason = self._make_label(box, NSMakeRect(146, 2, 0, 0), "", 10, False)
        reason.setHidden_(True)
        reason.setTextColor_(MUTED)
        return SymbolWidgets(container=box, title=title, status=status, price=price, meta=meta, reason=reason)

    @objc.python_method
    def _make_box(self, parent: Any, frame: Any, background: NSColor) -> Any:
        view = NSView.alloc().initWithFrame_(frame)
        view.setWantsLayer_(True)
        layer = view.layer()
        layer.setCornerRadius_(18.0)
        layer.setBackgroundColor_(background.CGColor())
        layer.setBorderWidth_(1.0)
        layer.setBorderColor_(CARD_LINE.CGColor())
        parent.addSubview_(view)
        return view

    @objc.python_method
    def _make_label(
        self,
        parent: Any,
        frame: Any,
        text: str,
        size: float,
        bold: bool,
        mono: bool = False,
    ) -> Any:
        label = NSTextField.alloc().initWithFrame_(frame)
        label.setEditable_(False)
        label.setBordered_(False)
        label.setDrawsBackground_(False)
        label.setSelectable_(False)
        label.setStringValue_(text)
        label.setTextColor_(INK)
        if mono:
            label.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(size, 0.62 if bold else 0.42))
        else:
            label.setFont_(NSFont.systemFontOfSize_weight_(size, 0.62 if bold else 0.42))
        parent.addSubview_(label)
        return label

    @objc.python_method
    def _make_badge(self, parent: Any, frame: Any, text: str) -> Any:
        badge = NSTextField.alloc().initWithFrame_(frame)
        badge.setEditable_(False)
        badge.setBordered_(False)
        badge.setDrawsBackground_(True)
        badge.setBackgroundColor_(_color(255, 255, 255, 0.86))
        badge.setSelectable_(False)
        badge.setBezeled_(False)
        badge.setAlignment_(1)
        badge.setStringValue_(text)
        badge.setTextColor_(MUTED)
        badge.setFont_(NSFont.systemFontOfSize_weight_(11, 0.55))
        badge.setWantsLayer_(True)
        badge.layer().setCornerRadius_(13.0)
        parent.addSubview_(badge)
        return badge

    @objc.python_method
    def _make_button(self, parent: Any, frame: Any, title: str, action: str) -> Any:
        button = NSButton.alloc().initWithFrame_(frame)
        button.setTitle_(title)
        button.setBezelStyle_(1)
        button.setTarget_(self)
        button.setAction_(action)
        parent.addSubview_(button)
        return button

    @objc.python_method
    def _set_status_title(self, title: str) -> None:
        self.status_item.button().setTitle_(title)


def run_desk_companion(config: AppConfig, storage: TradingStorage) -> None:
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    delegate = DeskCompanionAppDelegate.alloc().initWithConfig_storage_(config, storage)
    app.setDelegate_(delegate)
    AppHelper.runEventLoop()
