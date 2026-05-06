import AppKit
import CoreGraphics
import Foundation
import SwiftUI

struct DeskSummary: Decodable {
    struct Bot: Decodable {
        let status: String
        let lastCycleAt: String?
        let dataMode: String

        enum CodingKeys: String, CodingKey {
            case status
            case lastCycleAt = "last_cycle_at"
            case dataMode = "data_mode"
        }
    }

    struct Account: Decodable {
        let cash: Double
        let equity: Double
        let realizedPnL: Double
        let unrealizedPnL: Double
        let feesTotal: Double
        let currentExposureEUR: Double
        let currentExposurePct: Double

        enum CodingKeys: String, CodingKey {
            case cash
            case equity
            case realizedPnL = "realized_pnl"
            case unrealizedPnL = "unrealized_pnl"
            case feesTotal = "fees_total"
            case currentExposureEUR = "current_exposure_eur"
            case currentExposurePct = "current_exposure_pct"
        }
    }

    struct Risk: Decodable {
        let guardrailStatus: String
        let killSwitchReason: String
        let dailyTradeCount: Int
        let dailyTradeLimit: Int
        let dailyRealizedPnL: Double
        let currentDrawdownPct: Double
        let openPositions: Int
        let maxOpenPositions: Int
        let consecutiveLosses: Int
        let dailyLossLimitPct: Double
        let maxRiskPerTradePct: Double

        enum CodingKeys: String, CodingKey {
            case guardrailStatus = "guardrail_status"
            case killSwitchReason = "kill_switch_reason"
            case dailyTradeCount = "daily_trade_count"
            case dailyTradeLimit = "daily_trade_limit"
            case dailyRealizedPnL = "daily_realized_pnl"
            case currentDrawdownPct = "current_drawdown_pct"
            case openPositions = "open_positions"
            case maxOpenPositions = "max_open_positions"
            case consecutiveLosses = "consecutive_losses"
            case dailyLossLimitPct = "daily_loss_limit_pct"
            case maxRiskPerTradePct = "max_risk_per_trade_pct"
        }
    }

    struct Performance: Decodable {
        let todayFeesEUR: Double
        let expectancyEUR: Double

        enum CodingKeys: String, CodingKey {
            case todayFeesEUR = "today_fees_eur"
            case expectancyEUR = "expectancy_eur"
        }
    }

    struct Provider: Decodable {
        struct Current: Decodable {
            let label: String
        }

        let current: Current
    }

    struct Analysis: Decodable {
        let status: String
        let reason: String
        let details: [String: JSONValue]?
    }

    struct TradeActivity: Decodable {
        let count: Int
    }

    struct Symbol: Decodable, Identifiable {
        let symbol: String
        let midPrice: Double?
        let spreadBps: Double?
        let tradeActivity: TradeActivity
        let analysis: Analysis?

        var id: String { symbol }

        enum CodingKeys: String, CodingKey {
            case symbol
            case midPrice = "mid_price"
            case spreadBps = "spread_bps"
            case tradeActivity = "trade_activity"
            case analysis
        }
    }

    let bot: Bot
    let account: Account
    let risk: Risk
    let performance: Performance
    let provider: Provider
    let symbols: [Symbol]
}

enum JSONValue: Decodable {
    case string(String)
    case number(Double)
    case int(Int)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Int.self) {
            self = .int(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([String: JSONValue].self) {
            self = .object(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else {
            throw DecodingError.typeMismatch(
                JSONValue.self,
                DecodingError.Context(codingPath: decoder.codingPath, debugDescription: "Unsupported JSON value")
            )
        }
    }
}

enum DeskPalette {
    static let ink = Color(red: 244 / 255, green: 238 / 255, blue: 232 / 255)
    static let muted = Color(red: 194 / 255, green: 184 / 255, blue: 175 / 255)
    static let accent = Color(red: 245 / 255, green: 145 / 255, blue: 73 / 255)
    static let accentSoft = Color(red: 248 / 255, green: 191 / 255, blue: 156 / 255)
    static let good = Color(red: 78 / 255, green: 214 / 255, blue: 168 / 255)
    static let bad = Color(red: 255 / 255, green: 124 / 255, blue: 120 / 255)
    static let watch = Color(red: 255 / 255, green: 196 / 255, blue: 102 / 255)
    static let shellTop = Color(red: 39 / 255, green: 38 / 255, blue: 43 / 255)
    static let shellBottom = Color(red: 22 / 255, green: 22 / 255, blue: 27 / 255)
    static let card = Color.white.opacity(0.08)
    static let cardStrong = Color.white.opacity(0.12)
    static let line = Color.white.opacity(0.12)
}

func deskFormatterEUR(_ value: Double?) -> String {
    guard let value else { return "n/d" }
    let formatter = NumberFormatter()
    formatter.numberStyle = .currency
    formatter.currencyCode = "EUR"
    formatter.currencySymbol = "EUR"
    formatter.locale = Locale(identifier: "it_IT")
    formatter.maximumFractionDigits = 2
    return formatter.string(from: NSNumber(value: value)) ?? String(format: "%.2f EUR", value)
}

func deskFormatterCompact(_ value: Double?) -> String {
    guard let value else { return "n/d" }
    let formatter = NumberFormatter()
    formatter.locale = Locale(identifier: "it_IT")
    formatter.maximumFractionDigits = value > 1000 ? 1 : 2
    formatter.minimumFractionDigits = 0
    return formatter.string(from: NSNumber(value: value)) ?? String(format: "%.2f", value)
}

func deskPercent(_ value: Double?, digits: Int = 2) -> String {
    guard let value else { return "n/d" }
    return String(format: "%.\(digits)f%%", value).replacingOccurrences(of: ".", with: ",")
}

func niceStatus(_ status: String) -> String {
    switch status.uppercased() {
    case "ATTIVO": return "Attivo"
    case "COOLDOWN": return "Cooldown"
    case "HARD_STOP": return "Hard stop"
    case "OSSERVAZIONE": return "Osserva"
    case "BLOCCATO": return "Bloccato"
    case "IN_POSIZIONE": return "In posizione"
    case "ENTRATA_ESEGUITA": return "Entrata"
    default: return status.capitalized
    }
}

func statusColor(_ status: String) -> Color {
    switch status.uppercased() {
    case "ATTIVO", "IN_POSIZIONE", "ENTRATA_ESEGUITA":
        return DeskPalette.good
    case "HARD_STOP", "BLOCCATO":
        return DeskPalette.bad
    default:
        return DeskPalette.watch
    }
}

@MainActor
final class CompanionViewModel: ObservableObject {
    @Published var summary: DeskSummary?
    @Published var errorMessage: String?
    @Published var isPinnedToDesktop = true

    let endpoint = URL(string: "http://127.0.0.1:8765/api/summary")!
    weak var appDelegate: AppDelegate?
    private var timer: Timer?

    init() {
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.refresh()
            }
        }
    }

    deinit {
        timer?.invalidate()
    }

    func refresh() {
        let request = URLRequest(url: endpoint, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 3)
        URLSession.shared.dataTask(with: request) { [weak self] data, _, error in
            guard let self else { return }
            if let error {
                DispatchQueue.main.async {
                    self.errorMessage = error.localizedDescription
                    self.appDelegate?.updateStatusTitle("Desk ERR")
                }
                return
            }
            guard let data else {
                DispatchQueue.main.async {
                    self.errorMessage = "Nessun dato ricevuto."
                    self.appDelegate?.updateStatusTitle("Desk ERR")
                }
                return
            }
            do {
                let decoder = JSONDecoder()
                let summary = try decoder.decode(DeskSummary.self, from: data)
                DispatchQueue.main.async {
                    self.summary = summary
                    self.errorMessage = nil
                    self.appDelegate?.updateStatusTitle(self.statusLine(summary))
                }
            } catch {
                DispatchQueue.main.async {
                    self.errorMessage = error.localizedDescription
                    self.appDelegate?.updateStatusTitle("Desk ERR")
                }
            }
        }.resume()
    }

    func statusLine(_ summary: DeskSummary) -> String {
        let short: String
        switch summary.risk.guardrailStatus.uppercased() {
        case "ATTIVO":
            short = "OK"
        case "COOLDOWN":
            short = "PAUSA"
        default:
            short = "STOP"
        }
        let pnl = deskFormatterCompact(summary.risk.dailyRealizedPnL)
        return "Desk \(short) \(pnl)"
    }

    func openDashboard() {
        guard let url = URL(string: "http://127.0.0.1:8765") else { return }
        NSWorkspace.shared.open(url)
    }

    func toggleWindow() {
        appDelegate?.toggleMainWindow()
    }

    func toggleDesktopPinned() {
        appDelegate?.toggleDesktopPinned()
    }
}

struct StatCard: View {
    let title: String
    let value: String
    let subtitle: String
    let systemImage: String
    let tone: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Image(systemName: systemImage)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(tone)
                Text(title)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(DeskPalette.muted)
                Spacer()
            }
            Text(value)
                .font(.system(size: 23, weight: .bold, design: .rounded))
                .foregroundStyle(tone)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
            Text(subtitle)
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(DeskPalette.muted)
                .lineLimit(2)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .fill(DeskPalette.cardStrong)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .strokeBorder(DeskPalette.line, lineWidth: 1)
        )
    }
}

struct SymbolCard: View {
    let symbol: DeskSummary.Symbol

    var body: some View {
        let analysis = symbol.analysis
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(symbol.symbol)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(DeskPalette.muted)
                Spacer()
                Text(niceStatus(analysis?.status ?? "OSSERVAZIONE"))
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(statusColor(analysis?.status ?? "OSSERVAZIONE"))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(
                        Capsule(style: .continuous)
                            .fill(Color.white.opacity(0.08))
                    )
            }
            Text(deskFormatterCompact(symbol.midPrice))
                .font(.system(size: 21, weight: .bold, design: .rounded))
                .foregroundStyle(DeskPalette.ink)
                .lineLimit(1)
                .minimumScaleFactor(0.75)
            Text("Spread \(symbol.spreadBps.map { deskPercent($0, digits: 1).replacingOccurrences(of: "%", with: "b") } ?? "n/d")  |  T\(symbol.tradeActivity.count)")
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(DeskPalette.muted)
            Text(analysis?.reason ?? "Monitoraggio in corso.")
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(DeskPalette.ink.opacity(0.8))
                .lineLimit(2)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .fill(DeskPalette.cardStrong)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .strokeBorder(DeskPalette.line, lineWidth: 1)
        )
    }
}

struct ActionButton: View {
    let title: String
    let systemImage: String
    let tone: Color
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 8) {
                ZStack {
                    Circle()
                        .fill(Color.white.opacity(0.08))
                        .frame(width: 42, height: 42)
                    Image(systemName: systemImage)
                        .font(.system(size: 17, weight: .semibold))
                        .foregroundStyle(tone)
                }
                Text(title)
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(DeskPalette.muted)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 6)
        }
        .buttonStyle(.plain)
    }
}

struct MetricPill: View {
    let title: String
    let value: String
    let tone: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(DeskPalette.muted)
            Text(value)
                .font(.system(size: 13, weight: .bold, design: .rounded))
                .foregroundStyle(tone)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(Color.white.opacity(0.08))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .strokeBorder(DeskPalette.line, lineWidth: 1)
        )
    }
}

struct CompanionRootView: View {
    @ObservedObject var model: CompanionViewModel

    var body: some View {
        ZStack {
            Circle()
                .fill(DeskPalette.accent.opacity(0.18))
                .frame(width: 250, height: 250)
                .blur(radius: 28)
                .offset(x: 124, y: -192)
            Circle()
                .fill(DeskPalette.good.opacity(0.12))
                .frame(width: 220, height: 220)
                .blur(radius: 24)
                .offset(x: -132, y: 196)
            RoundedRectangle(cornerRadius: 30, style: .continuous)
                .fill(
                    LinearGradient(
                        colors: [DeskPalette.shellTop, DeskPalette.shellBottom],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
            RoundedRectangle(cornerRadius: 30, style: .continuous)
                .strokeBorder(Color.white.opacity(0.12), lineWidth: 1)

            if let summary = model.summary {
                ScrollView(.vertical, showsIndicators: false) {
                    content(summary: summary)
                }
            } else {
                ScrollView(.vertical, showsIndicators: false) {
                    placeholder
                }
            }
        }
        .padding(10)
        .frame(width: 390, height: 620)
    }

    @ViewBuilder
    private func content(summary: DeskSummary) -> some View {
        VStack(alignment: .leading, spacing: 15) {
            header(summary: summary)
            actions
            grid(summary: summary)
            strip(summary: summary)
            alert(summary: summary)
            HStack(spacing: 12) {
                ForEach(Array(summary.symbols.prefix(2))) { symbol in
                    SymbolCard(symbol: symbol)
                }
            }
        }
        .padding(.horizontal, 18)
        .padding(.top, 18)
        .padding(.bottom, 22)
    }

    private func header(summary: DeskSummary) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top, spacing: 10) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Trading Desk")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(DeskPalette.muted)
                        .textCase(.uppercase)
                    HStack(spacing: 8) {
                        Circle()
                            .fill(statusColor(summary.risk.guardrailStatus))
                            .frame(width: 8, height: 8)
                        Text(niceStatus(summary.risk.guardrailStatus))
                            .font(.system(size: 32, weight: .heavy, design: .rounded))
                            .foregroundStyle(statusColor(summary.risk.guardrailStatus))
                    }
                    Text("Bot \(summary.bot.status.capitalized) · ultimo ciclo \(summary.bot.lastCycleAt ?? "n/d")")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(DeskPalette.muted)
                        .lineLimit(2)
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 8) {
                    Text(summary.provider.current.label)
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(DeskPalette.ink)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 8)
                        .background(
                            Capsule(style: .continuous)
                                .fill(Color.white.opacity(0.10))
                        )
                    Text(model.isPinnedToDesktop ? "Scrivania" : "Finestra")
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(model.isPinnedToDesktop ? DeskPalette.accentSoft : DeskPalette.good)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 6)
                        .background(
                            Capsule(style: .continuous)
                                .fill(Color.white.opacity(0.08))
                        )
                }
            }
            HStack(spacing: 10) {
                headerBadge(
                    title: "PnL oggi",
                    value: deskFormatterEUR(summary.risk.dailyRealizedPnL),
                    tone: summary.risk.dailyRealizedPnL >= 0 ? DeskPalette.good : DeskPalette.bad
                )
                headerBadge(
                    title: "Esposizione",
                    value: deskPercent(summary.account.currentExposurePct),
                    tone: summary.account.currentExposurePct > 0 ? DeskPalette.watch : DeskPalette.ink
                )
            }
        }
        .padding(18)
        .background(
            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .fill(
                    LinearGradient(
                        colors: [Color.white.opacity(0.10), Color.white.opacity(0.05)],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
        )
        .overlay(
            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .strokeBorder(DeskPalette.line, lineWidth: 1)
        )
    }

    private var actions: some View {
        HStack(spacing: 10) {
            ActionButton(
                title: model.isPinnedToDesktop ? "Modalita" : "Scrivania",
                systemImage: model.isPinnedToDesktop ? "macwindow.on.rectangle" : "sparkles.rectangle.stack",
                tone: model.isPinnedToDesktop ? DeskPalette.accent : DeskPalette.good
            ) {
                model.toggleDesktopPinned()
            }
            ActionButton(title: "Dashboard", systemImage: "safari", tone: DeskPalette.ink) {
                model.openDashboard()
            }
            ActionButton(title: "Sincronizza", systemImage: "arrow.clockwise", tone: DeskPalette.ink) {
                model.refresh()
            }
            ActionButton(title: "Nascondi", systemImage: "minus.circle", tone: DeskPalette.muted) {
                model.toggleWindow()
            }
        }
        .padding(.horizontal, 4)
    }

    private func grid(summary: DeskSummary) -> some View {
        VStack(spacing: 12) {
            HStack(spacing: 12) {
                StatCard(
                    title: "Equity",
                    value: deskFormatterEUR(summary.account.equity),
                    subtitle: "Cassa \(deskFormatterEUR(summary.account.cash))",
                    systemImage: "eurosign.circle",
                    tone: summary.account.equity >= summary.account.cash ? DeskPalette.good : DeskPalette.bad
                )
                StatCard(
                    title: "PnL oggi",
                    value: deskFormatterEUR(summary.risk.dailyRealizedPnL),
                    subtitle: "Trade \(summary.risk.dailyTradeCount)/\(summary.risk.dailyTradeLimit)",
                    systemImage: "chart.line.uptrend.xyaxis",
                    tone: summary.risk.dailyRealizedPnL >= 0 ? DeskPalette.good : DeskPalette.bad
                )
            }
            HStack(spacing: 12) {
                StatCard(
                    title: "Rischio",
                    value: deskPercent(summary.account.currentExposurePct),
                    subtitle: "Drawdown \(deskPercent(summary.risk.currentDrawdownPct))",
                    systemImage: "shield.lefthalf.filled",
                    tone: statusColor(summary.risk.guardrailStatus)
                )
                StatCard(
                    title: "Costi",
                    value: deskFormatterEUR(summary.performance.todayFeesEUR),
                    subtitle: "Fee totali \(deskFormatterEUR(summary.account.feesTotal))",
                    systemImage: "creditcard",
                    tone: DeskPalette.watch
                )
            }
        }
    }

    private func strip(summary: DeskSummary) -> some View {
        HStack(spacing: 10) {
            MetricPill(
                title: "Posizioni",
                value: "\(summary.risk.openPositions)/\(summary.risk.maxOpenPositions)",
                tone: summary.risk.openPositions > 0 ? DeskPalette.watch : DeskPalette.ink
            )
            MetricPill(
                title: "Disciplina",
                value: "\(summary.risk.dailyTradeCount)/\(summary.risk.dailyTradeLimit)",
                tone: summary.risk.consecutiveLosses > 0 ? DeskPalette.bad : DeskPalette.ink
            )
            MetricPill(
                title: "Drawdown",
                value: deskPercent(summary.risk.currentDrawdownPct),
                tone: summary.risk.currentDrawdownPct > 0 ? DeskPalette.bad : DeskPalette.good
            )
        }
    }

    private func alert(summary: DeskSummary) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(summary.risk.guardrailStatus.uppercased() == "ATTIVO" ? "Desk operativo" : "Alert desk")
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(statusColor(summary.risk.guardrailStatus))
            Text(
                summary.risk.killSwitchReason.isEmpty
                    ? "Nessun blocco attivo. Il desk puo continuare a monitorare i setup."
                    : summary.risk.killSwitchReason
            )
            .font(.system(size: 12, weight: .medium))
            .foregroundStyle(DeskPalette.ink)
            .lineLimit(2)
            Text("Open \(summary.risk.openPositions)/\(summary.risk.maxOpenPositions) | stop day \(deskPercent(summary.risk.dailyLossLimitPct)) | risk/trade \(deskPercent(summary.risk.maxRiskPerTradePct))")
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(DeskPalette.muted)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .fill(Color.white.opacity(0.08))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .strokeBorder(DeskPalette.line, lineWidth: 1)
        )
    }

    private var placeholder: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Trading Desk")
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(DeskPalette.muted)
            Text("Connessione")
                .font(.system(size: 34, weight: .heavy, design: .rounded))
                .foregroundStyle(DeskPalette.watch)
            Text(model.errorMessage ?? "Sto aspettando i dati dalla dashboard locale.")
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(DeskPalette.ink)
            ActionButton(title: "Riprova", systemImage: "arrow.clockwise", tone: DeskPalette.ink) {
                model.refresh()
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .padding(.horizontal, 22)
        .padding(.top, 24)
        .padding(.bottom, 24)
    }

    private func headerBadge(title: String, value: String, tone: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(DeskPalette.muted)
            Text(value)
                .font(.system(size: 14, weight: .bold, design: .rounded))
                .foregroundStyle(tone)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(Color.white.opacity(0.06))
        )
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var window: NSWindow!
    private var model: CompanionViewModel!
    private var statusItem: NSStatusItem!
    private var statusMenu: NSMenu!
    private var toggleVisibilityItem: NSMenuItem!
    private var togglePinItem: NSMenuItem!
    private let frameName = "TradingDeskCompanionWindow"
    private let pinnedDefaultsKey = "TradingDeskCompanionPinned"
    private var isPinnedToDesktop = UserDefaults.standard.object(forKey: "TradingDeskCompanionPinned") as? Bool ?? true

    @MainActor
    func applicationDidFinishLaunching(_ notification: Notification) {
        model = CompanionViewModel()
        model.appDelegate = self
        setupStatusItem()
        setupWindow()
        applyWindowMode(activate: false)
        showWindow()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    @MainActor
    func toggleMainWindow() {
        if window.isVisible {
            window.orderOut(nil)
            toggleVisibilityItem.title = "Mostra widget"
        } else {
            showWindow()
        }
    }

    @MainActor
    func updateStatusTitle(_ title: String) {
        statusItem.button?.title = title
    }

    @MainActor
    func toggleDesktopPinned() {
        isPinnedToDesktop.toggle()
        UserDefaults.standard.set(isPinnedToDesktop, forKey: pinnedDefaultsKey)
        applyWindowMode()
        showWindow()
    }

    @MainActor
    @objc private func toggleFromStatusItem(_ sender: Any?) {
        toggleMainWindow()
    }

    @MainActor
    private func setupStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.title = "Desk"
        statusMenu = NSMenu()
        toggleVisibilityItem = NSMenuItem(title: "Nascondi widget", action: #selector(toggleFromStatusItem(_:)), keyEquivalent: "")
        toggleVisibilityItem.target = self
        togglePinItem = NSMenuItem(title: "", action: #selector(togglePinFromMenu(_:)), keyEquivalent: "")
        togglePinItem.target = self
        let openDashboardItem = NSMenuItem(title: "Apri dashboard", action: #selector(openDashboardFromMenu(_:)), keyEquivalent: "")
        openDashboardItem.target = self
        let refreshItem = NSMenuItem(title: "Aggiorna ora", action: #selector(refreshFromMenu(_:)), keyEquivalent: "")
        refreshItem.target = self
        let quitItem = NSMenuItem(title: "Chiudi companion", action: #selector(quitFromMenu(_:)), keyEquivalent: "")
        quitItem.target = self
        statusMenu.addItem(toggleVisibilityItem)
        statusMenu.addItem(togglePinItem)
        statusMenu.addItem(.separator())
        statusMenu.addItem(openDashboardItem)
        statusMenu.addItem(refreshItem)
        statusMenu.addItem(.separator())
        statusMenu.addItem(quitItem)
        statusItem.menu = statusMenu
        updateMenuTitles()
    }

    @MainActor
    private func setupWindow() {
        let contentView = NSHostingView(rootView: CompanionRootView(model: model))
        let style: NSWindow.StyleMask = [.borderless]
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 390, height: 620),
            styleMask: style,
            backing: .buffered,
            defer: false
        )
        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = true
        window.isMovableByWindowBackground = true
        window.isReleasedWhenClosed = false
        window.minSize = NSSize(width: 390, height: 560)
        window.contentView = contentView
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        window.setFrameAutosaveName(frameName)
        if !window.setFrameUsingName(frameName) {
            placeWindowAtDefaultAnchor()
        } else {
            enforceMinimumWindowSize()
            keepWindowVisibleOnScreen()
        }
    }

    @MainActor
    private func applyWindowMode(activate: Bool = true) {
        model.isPinnedToDesktop = isPinnedToDesktop
        if isPinnedToDesktop {
            let level = Int(CGWindowLevelForKey(.desktopIconWindow)) + 1
            window.level = NSWindow.Level(rawValue: level)
            window.collectionBehavior = [.canJoinAllSpaces, .stationary]
        } else {
            window.level = .normal
            window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        }
        updateMenuTitles()
        if activate {
            showWindow()
        }
    }

    @MainActor
    private func showWindow() {
        window.orderFrontRegardless()
        keepWindowVisibleOnScreen()
        toggleVisibilityItem.title = "Nascondi widget"
        if isPinnedToDesktop {
            window.orderBack(nil)
        } else {
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
        }
    }

    @MainActor
    private func placeWindowAtDefaultAnchor() {
        guard let screen = NSScreen.main ?? NSScreen.screens.first else {
            window.center()
            return
        }
        let visibleFrame = screen.visibleFrame
        let origin = NSPoint(
            x: visibleFrame.maxX - window.frame.width - 28,
            y: visibleFrame.minY + 24
        )
        window.setFrameOrigin(origin)
    }

    @MainActor
    private func keepWindowVisibleOnScreen() {
        guard let screen = NSScreen.main ?? NSScreen.screens.first else { return }
        let visibleFrame = screen.visibleFrame
        var frame = window.frame
        if !visibleFrame.intersects(frame) {
            placeWindowAtDefaultAnchor()
            return
        }
        frame.origin.x = min(max(frame.origin.x, visibleFrame.minX + 12), visibleFrame.maxX - frame.width - 12)
        frame.origin.y = min(max(frame.origin.y, visibleFrame.minY + 12), visibleFrame.maxY - frame.height - 12)
        window.setFrame(frame, display: true)
    }

    @MainActor
    private func enforceMinimumWindowSize() {
        var frame = window.frame
        let minWidth: CGFloat = 390
        let minHeight: CGFloat = 560
        let needsResize = frame.width < minWidth || frame.height < minHeight
        if !needsResize {
            return
        }
        frame.size.width = max(frame.width, minWidth)
        frame.size.height = max(frame.height, minHeight)
        window.setFrame(frame, display: true)
    }

    @MainActor
    private func updateMenuTitles() {
        togglePinItem.title = isPinnedToDesktop ? "Passa a finestra" : "Fissa su scrivania"
        toggleVisibilityItem?.title = window != nil && window.isVisible ? "Nascondi widget" : "Mostra widget"
    }

    @MainActor
    @objc private func togglePinFromMenu(_ sender: Any?) {
        toggleDesktopPinned()
    }

    @MainActor
    @objc private func openDashboardFromMenu(_ sender: Any?) {
        model.openDashboard()
    }

    @MainActor
    @objc private func refreshFromMenu(_ sender: Any?) {
        model.refresh()
    }

    @MainActor
    @objc private func quitFromMenu(_ sender: Any?) {
        NSApp.terminate(nil)
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
