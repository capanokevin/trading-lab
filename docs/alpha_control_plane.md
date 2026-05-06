# Alpha Control Plane

Aggiornato al `8 aprile 2026`.

## Posizionamento alpha

Questa alpha non vende rendimento e non promette auto-execution.

La promessa e:

- capire cosa e successo
- capire perche e successo o non e successo
- vedere quanto e costato davvero
- chiudere la review giornaliera in pochi minuti

## Supported workflows

- `Hyperliquid` come venue operativo di default per market data, paper trading e decisioni shadow
- `MetaMask watch + browser sync` per wallet EVM con snapshot locali di saldo, chain e attivita
- `Hyperliquid watch + API-wallet prep` per registrare signer o wallet venue-native e leggerne lo stato pubblico
- `daily review` locale con cost attribution, guard rail e target da rivedere
- `decision replay` locale per le decisioni piu importanti
- `manual import / concierge support` per provider secondari, solo per review e confronto limitato
- collector locale con pacing, spacing e backoff controllato sul feed Hyperliquid

## Known limitations

- live execution ancora `disabilitata`
- motore paper attuale `long + short` in modalita `paper`
- niente `multi-provider live` reali nella alpha
- niente `mobile app`
- `MetaMask` e wallet layer, non executor del bot
- la sync `MetaMask` richiede browser con estensione e permessi approvati
- short e perps sono disponibili a livello venue e gia armati nel motore della alpha in modalita `paper/shadow`
- niente `promessa di auto-exec o profitto`

## Trust UX principles

- nessuna azione opaca
- ogni blocco deve avere un motivo leggibile
- `Paper`, `Live Shadow` e `Live` devono essere sempre separati visivamente
- ogni schermata deve rispondere a una domanda forte

## Onboarding checklist design partner

1. verificare accesso a `http://127.0.0.1:8765`
2. spiegare differenza tra `Paper`, `Live Shadow` e `Live`
3. confermare venue operativo iniziale: `Hyperliquid`
4. mostrare `Daily Review`
5. mostrare `Decision Replay`
6. mostrare `Wallet e venue on-chain`
7. collegare almeno un wallet `MetaMask` oppure registrare un signer `Hyperliquid`
8. mostrare `Known limitations`
9. concordare primo feedback call entro 7 giorni

## Surface alpha attuale

Le superfici gia presenti nella UI locale sono:

- `Panoramica` con alert, daily review, trust layer e onboarding alpha
- `Mercati` con decision board e regole del motore
- `Account` con account center, import manuale CSV/JSON, insight account importati e activity feed
- `Account` con wallet blockchain, venue on-chain, sync wallet e import manuale CSV/JSON
- `Journal` con replay decisionale, ledger e failure analysis

## Configurazione operativa corrente

- budget paper: `5.000 USD`
- notional paper per trade: `1.000 USD`
- strategia: `momentum_context_v9`
- imbalance metric: `log_depth_pressure_v1`
- simboli con nuove entrate abilitate: `ETH-USD`
- simboli in watch-only: `BTC-USD, SOL-USD, XRP-USD, ADA-USD, DOGE-USD`
- modelli distinti: `Paper`, `Live Shadow`, `Live` disabilitato
- venue on-chain primaria consigliata: `Hyperliquid`
- wallet UX iniziale consigliato: `MetaMask`

## Storico versioni strategiche

Lo storico delle tarature non va letto a memoria o ricostruito dai log.

Riferimenti ufficiali:

- `docs/strategy_versions.md`
- `paper_positions.strategy` nel database locale
- `python3 scripts/analyze_trade_performance.py`

## Success criteria alpha

- il partner capisce la home in meno di 3 minuti
- la review giornaliera richiede meno di 10 minuti
- almeno 3 partner dicono che il prodotto fa risparmiare tempo o aumenta chiarezza operativa
