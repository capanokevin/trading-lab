# Crypto Trading Control Plane

Un laboratorio desktop-first e local-first per osservare mercati crypto, simulare trade, misurare costi e capire perche' una strategia ha fatto o non ha fatto qualcosa.

Questo progetto nasce come esperimento di `vibe coding` con AI: non e' un bot magico, non promette rendimento e non esegue ordini reali nella configurazione pubblica.

## Cosa fa

- raccoglie market data pubblici da Hyperliquid
- esegue paper trading locale con guard rail di rischio
- separa modalita' paper, shadow e live readiness
- registra decision replay, blocchi e motivazioni operative
- mostra una dashboard locale in italiano
- include un companion desktop macOS opzionale
- misura fee, slippage stimato, PnL lordo/netto e failure analysis

## Stato esperimento

Snapshot pubblico al 5 maggio 2026:

- 5 versioni strategiche documentate
- 81 trade paper chiusi
- circa 20k decision replay registrati
- PnL netto paper: -43,07 USD
- fee simulate: 72,66 USD
- win rate: 18,5%
- orizzonte: 9 aprile - 5 maggio 2026, circa 26 giorni

Il campione e' volutamente dichiarato acerbo: e' utile per raccontare l'esperimento e validare l'infrastruttura, non per valutare seriamente la performance della strategia.

## Disclaimer

Questo repository e' solo a scopo educativo e sperimentale.

Non e' consulenza finanziaria, non e' una raccomandazione di investimento e non contiene una strategia validata per trading live. Qualsiasi uso con capitale reale richiede audit, test, gestione del rischio, compliance e piena responsabilita' dell'utente.

## Quick Start

Requisiti:

- Python 3.11+
- macOS consigliato per il companion desktop
- nessuna chiave API richiesta per la simulazione pubblica di base

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
python3 scripts/run_public_bot.py
```

In un secondo terminale:

```bash
python3 scripts/run_dashboard.py
```

Apri la dashboard locale:

```text
http://127.0.0.1:8765
```

Companion macOS opzionale:

```bash
zsh scripts/run_swift_companion.sh
```

Avvio automatico al login macOS:

```bash
python3 scripts/install_launch_agents.py
```

Disinstallazione LaunchAgents:

```bash
python3 scripts/uninstall_launch_agents.py
```

## Configurazione

La configurazione vive in `.env`, partendo da `.env.example`.

Default principali:

- venue dati: Hyperliquid
- capitale paper: 5.000 USD
- ordine paper: 1.000 USD
- universo osservato: BTC, ETH, SOL, XRP, ADA, DOGE
- entry abilitate nella baseline pubblica: ETH-USD
- strategia corrente: `momentum_context_v9`
- short live: disabilitato
- execution live: non armata nella release pubblica

## Cosa non viene pubblicato

Per sicurezza sono esclusi da git:

- `.env` e varianti locali
- cartella `secrets/`
- chiavi `.pem`
- database SQLite locali
- log locali
- export e report generati
- build macOS
- cache Python e Playwright

Se cloni il progetto parti da uno stato pulito: i dati del mio esperimento non sono inclusi nel repository.

## Struttura

```text
src/
  hyperliquid/          client market data Hyperliquid
  revolut_x/            client Revolut X legacy/auth opzionale
  trading_bot/          motore paper, dashboard, risk manager, storage

scripts/
  run_public_bot.py     collector + paper trading locale
  run_dashboard.py      dashboard web locale
  run_swift_companion.sh companion macOS nativo
  analyze_trade_performance.py
  analyze_filter_audit.py
  export_daily_reports.py

docs/
  alpha_control_plane.md
  blockchain_alpha.md
  manual_import_schema.md
  provider_short_support.md
  strategy_versions.md
  system_architecture.md

macos/
  TradingDeskCompanion.swift
```

## Analisi e report locali

Analisi trade chiusi:

```bash
python3 scripts/analyze_trade_performance.py
```

Analisi filtri/blocchi:

```bash
python3 scripts/analyze_filter_audit.py
```

Export report giornalieri:

```bash
python3 scripts/export_daily_reports.py
```

## Roadmap

- migliorare decision replay e failure analysis
- rafforzare la separazione paper/shadow/live
- aggiungere import manuale piu' robusto da provider esterni
- migliorare report giornaliero e journaling
- preparare eventuale integrazione live solo dopo audit serio

## Perche' esiste

L'obiettivo non e' dimostrare che l'AI batte il mercato.

L'obiettivo e' capire quanto velocemente si puo' costruire un prodotto verticale, osservabile e misurabile usando AI come partner tecnico, anche partendo da competenze limitate nel dominio trading.
