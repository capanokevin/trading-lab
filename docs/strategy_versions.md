# Strategy Versions

Aggiornato al `16 aprile 2026`.

Questo file serve a non mischiare tra loro versioni strategiche diverse.

Ogni nuova taratura deve:

1. cambiare `strategy_name` nel motore
2. lasciare traccia qui
3. essere confrontata con i dati del database solo contro la propria versione

La colonna di riferimento nel database e `paper_positions.strategy`.

## Come leggere i numeri

- `equity` da sola non basta: va sempre letta insieme a `capitale versato`
- i confronti tra versioni si fanno su:
  - `trade chiusi`
  - `PnL netto`
  - `win rate`
  - `motivi di uscita`
  - `simboli che creano o distruggono edge`
- una nuova versione non va giudicata finche non raccoglie un campione minimo sensato

## Versioni registrate

### `momentum_context_v5`

- stato: `archiviata`
- periodo osservato nei trade chiusi: `2026-03-25 -> 2026-04-08`
- universo monitorato: `BTC-EUR, ETH-EUR, SOL-EUR, XRP-EUR, ADA-EUR, DOGE-EUR`
- simboli abilitati alle entrate: `tutti i simboli monitorati`
- budget paper: `5.000 EUR`
- notional paper per trade: `1.000 EUR`
- metrica imbalance: `log_depth_pressure_v1`
- filtro imbalance ingresso: `>-5,00%`
- filtro momentum ingresso: `>0,0080%`
- filtro trend candele: `>0,0150%`
- filtro spread ingresso: `<40 bps`

#### Risultato osservato

- trade chiusi: `24`
- PnL netto: `-73,47 EUR`
- win rate: `8,33%`
- vincitori osservati: `BTC-EUR`, `SOL-EUR`
- simboli peggiori: `ADA-EUR`, `XRP-EUR`, `ETH-EUR`
- motivi di perdita dominanti:
  - `Stop loss dinamico raggiunto`
  - `Momentum invertito`

#### Lettura

La `v5` era piu permissiva del necessario. Apriva troppo spesso su segnali con follow-through debole, soprattutto fuori da `BTC-EUR` e `SOL-EUR`. Il risultato e stato un numero eccessivo di stop e inversioni di momentum.

#### Decisione presa

La `v5` non va usata come baseline corrente. Resta utile come storico per capire:

- quali simboli distruggono edge
- quali exit reason stanno pesando di piu
- come si comporta una taratura troppo larga su Revolut X spot

### `momentum_context_v6`

- stato: `archiviata`
- attivazione operativa: `8 aprile 2026`
- universo monitorato: `BTC-EUR, ETH-EUR, SOL-EUR, XRP-EUR, ADA-EUR, DOGE-EUR`
- simboli abilitati alle entrate: `BTC-EUR, SOL-EUR`
- simboli in sola osservazione: `ETH-EUR, XRP-EUR, ADA-EUR, DOGE-EUR`
- budget paper: `5.000 EUR`
- notional paper per trade: `1.000 EUR`
- metrica imbalance: `log_depth_pressure_v1`
- filtro imbalance ingresso: `>-5,00%`
- filtro momentum ingresso: `>0,0600%`
- filtro trend candele: `>0,0800%`
- filtro spread ingresso: `<40 bps`

#### Obiettivo della taratura

Ridurre le entrate deboli e ripartire da un sottoinsieme di simboli che, nei dati raccolti finora, ha mostrato segnali piu credibili.

#### Ipotesi operativa

La `v6` dovrebbe:

- fare meno trade della `v5`
- tagliare i long mediocri su `ETH/XRP/ADA/DOGE`
- alzare la qualita del momentum richiesto prima dell’ingresso

#### Regola di valutazione

La `v6` e stata superata dal passaggio strutturale a `Hyperliquid`, quindi non e piu la baseline corrente.

### `momentum_context_v7`

- stato: `archiviata`
- attivazione operativa: `8 aprile 2026`
- venue operativo: `Hyperliquid`
- universo monitorato: `BTC-USD, ETH-USD, SOL-USD, XRP-USD, ADA-USD, DOGE-USD`
- simboli abilitati alle entrate: `BTC-USD, ETH-USD, SOL-USD`
- simboli in sola osservazione: `XRP-USD, ADA-USD, DOGE-USD`
- budget paper: `5.000 USD`
- notional paper per trade: `1.000 USD`
- metrica imbalance: `log_depth_pressure_v1`
- filtro imbalance ingresso: `>-5,00%`
- filtro momentum ingresso: `>0,0600%`
- filtro trend candele: `>0,0800%`
- filtro spread ingresso: `<12 bps`
- trade minimi recenti richiesti: `8`

#### Obiettivo della taratura

Aprire una baseline nuova, separata da Revolut X, usando una venue piu liquida e piu coerente con il futuro del progetto.

#### Ipotesi operativa

La `v7` dovrebbe:

- produrre segnali piu puliti su `BTC/ETH/SOL`
- sfruttare spread e profondita piu favorevoli di `Hyperliquid`
- lasciare `XRP/ADA/DOGE` in osservazione finche non mostrano edge chiaro

#### Regola di valutazione

La `v7` e stata superata quando abbiamo deciso di trasformare il motore Hyperliquid in una baseline davvero `perps-aware`, con `short`, accounting a margine e uscite reduce-only simulate.

### `momentum_context_v8`

- stato: `archiviata`
- attivazione operativa: `9 aprile 2026`
- venue operativo: `Hyperliquid`
- universo monitorato: `BTC-USD, ETH-USD, SOL-USD, XRP-USD, ADA-USD, DOGE-USD`
- simboli abilitati alle entrate: `BTC-USD, ETH-USD, SOL-USD`
- simboli in sola osservazione: `XRP-USD, ADA-USD, DOGE-USD`
- budget paper: `5.000 USD`
- notional paper per trade: `1.000 USD`
- metrica imbalance: `log_depth_pressure_v1`
- filtro imbalance ingresso long: `>2,00%`
- filtro imbalance ingresso short: `<-2,00%`
- filtro momentum ingresso: `>|0,0600%|`
- filtro trend candele: `>|0,0800%|`
- filtro spread ingresso: `<12 bps`
- trade minimi recenti richiesti: `8`
- setup perps: `3x`, `ISOLATED`, `IOC`, `reduce-only exit`
- lato short: `attivo`

#### Obiettivo della taratura

Trasformare la baseline Hyperliquid da motore solo `long` a motore `perps-aware`, con:

- ingressi `long` e `short`
- cash accounting a margine e non piu spot-like
- report e replay side-aware
- base piu vicina a un workflow professionale su perpetuals

#### Ipotesi operativa

La `v8` dovrebbe:

- sfruttare fasi rialziste e ribassiste senza restare cieca sul lato short
- produrre un campione di trade piu bilanciato tra i regimi
- rendere finalmente leggibile il contributo di `short`, `leva` e `margine`

#### Regola di valutazione

La `v8` e stata valutata dopo `36` trade chiusi. Lettura sintetica:

- PnL netto aggregato: `-14,24 USD`
- win rate: `16,67%`
- `ETH-USD` positivo in aggregato, ma il miglior trade short e rimasto aperto circa `8h22m`, quindi non va trattato come evidenza pulita di edge continuo
- senza trade oltre tempo massimo operativo il campione scende a circa `-38,37 USD`
- `SOL-USD` ha distrutto edge sia long sia short
- `BTC-USD` e ancora negativo su entrambi i lati
- il lato short resta implementato, ma non e ancora validato come strategia autonoma

Decisione: passare a `momentum_context_v9`, concentrando le nuove entrate su `ETH-USD` long e lasciando il resto in osservazione.

### `momentum_context_v9`

- stato: `attiva`
- attivazione operativa: `16 aprile 2026`
- venue operativo: `Hyperliquid`
- universo monitorato: `BTC-USD, ETH-USD, SOL-USD, XRP-USD, ADA-USD, DOGE-USD`
- simboli abilitati alle entrate: `ETH-USD`
- simboli in sola osservazione: `BTC-USD, SOL-USD, XRP-USD, ADA-USD, DOGE-USD`
- budget paper: `5.000 USD`
- notional paper per trade: `1.000 USD`
- metrica imbalance: `log_depth_pressure_v1`
- filtro imbalance ingresso long: `>2,00%`
- filtro momentum ingresso long: `>0,0600%`
- filtro trend candele long: `>0,0800%`
- filtro spread ingresso: `<12 bps`
- trade minimi recenti richiesti: `8`
- setup perps: `3x`, `ISOLATED`, `IOC`, `reduce-only exit`
- lato short: `codice disponibile, disattivato nella taratura operativa v9`

#### Obiettivo della taratura

Ridurre rumore, fee e whipsaw dopo il campione `v8`, senza buttare via i dati raccolti sugli altri simboli. La `v9` e una taratura di conservazione capitale:

- continua a monitorare tutto l'universo liquido
- apre nuove posizioni solo dove il campione ha mostrato il segnale piu credibile
- tiene `BTC/SOL` e gli short in watch-only finche una nuova analisi non giustifica riabilitarli

#### Regola di valutazione

Non confrontare la `v9` con la `v8` guardando solo l'equity aggregata. Confrontare:

- PnL netto su `ETH-USD`
- numero di trade evitati su `BTC/SOL`
- fee risparmiate
- trade bloccati per watch-only
- eventuale miglioramento del win rate senza il supporto di outlier da bot non continuo

Script di riferimento:

```bash
python3 scripts/analyze_trade_performance.py
```

## Processo per le prossime versioni

Quando introdurremo `v10` o altre varianti:

1. aggiornare `strategy_name`
2. aggiungere una nuova sezione in questo file
3. annotare cosa cambia davvero
4. evitare confronti aggregati tra versioni diverse senza separarle
