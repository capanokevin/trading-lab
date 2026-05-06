# System Architecture

Questa e la proposta pratica per costruire il sistema senza partire subito con soldi veri.

## Risposta breve

- si, possiamo iniziare senza fare altro lato Revolut
- no, la API key Revolut X non serve solo per gli ordini
- si, all'inizio possiamo far girare tutto su questo Mac
- no, un server separato non serve subito
- si, possiamo prevedere una dashboard sempre visibile quando il Mac e acceso

## Cosa richiede davvero la API key Revolut X

### Non autenticato

Possiamo gia usare:

- `GET /public/order-book/{symbol}`
- `GET /public/last-trades`

Quindi possiamo subito:

- raccogliere dati live
- costruire segnali
- fare paper trading
- testare dashboard e automazioni locali

### Autenticato

La API key serve anche per:

- `GET /configuration/pairs`
- `GET /candles/{symbol}`
- tutti gli endpoint di account e ordini

Quindi la chiave non serve solo per fare ordini. Serve anche per alcune letture utili.

## Strategia di sviluppo consigliata

### Fase 1: data collector locale

Un processo Python legge a intervalli regolari:

- public order book
- public last trades

e salva tutto in SQLite locale.

Obiettivo:

- avere dataset nostro
- non dipendere da memoria volatile
- poter analizzare giornate e settimane dopo

### Fase 2: paper trading engine

Un modulo separato:

- legge i dati raccolti
- genera segnali deterministici
- simula ingressi e uscite
- applica fee, spread e slippage
- salva ogni decisione

Questo e il cuore reale del progetto.

### Fase 2.5: risk manager professionale

Prima di parlare di AI, il motore deve sapersi fermare da solo.

Guard rail chiave:

- massimo numero di posizioni aperte
- tetto di esposizione totale
- size massima per trade
- riserva minima di cassa
- rischio massimo per trade
- limite perdita giornaliera
- limite drawdown
- limite trade giornalieri
- stop dopo streak di perdite
- cooldown dopo chiusure
- kill switch salute sistema su errori collector

Questo e il livello minimo per non confondere una demo con un desk controllato.

### Fase 3: AI supervisor

L'AI non deve stare nel loop di esecuzione a ogni tick.

La usiamo per:

- classificare il regime di mercato
- scrivere riassunti giornalieri
- segnalare anomalie
- suggerire test offline

Il motore di esecuzione resta deterministico.

### Fase 4: live trading controllato

Solo dopo:

- almeno 2-4 settimane di paper trading
- metriche decenti dopo fee
- controllo stabile del rischio

si attiva la parte con ordini reali.

## Dove farlo girare

### Opzione A: solo questo Mac

Perfetta per adesso, soprattutto in paper trading con market data pubblica production.

Pro:

- costo quasi zero
- sviluppo veloce
- controlli tutto localmente

Contro:

- se il Mac e spento, il bot si ferma
- se la rete cade, il bot si ferma
- non e 24/7 affidabile

### Opzione B: questo Mac + avvio automatico

Buona per la fase intermedia.

Possiamo usare `launchd` su macOS per:

- far partire il collector al login
- riavviare il processo se cade
- tenere log ordinati

### Opzione C: server separato

Serve solo quando vorrai:

- operativita 24/7
- maggiore affidabilita
- separare UI e worker

Per ora non e necessario.

## Dashboard / widget

### Soluzione consigliata all'inizio

Dashboard locale web, apribile in finestra o full screen.

Motivi:

- piu veloce da costruire
- piu facile da mantenere
- ottima su Mac
- puo mostrare grafici, stato bot, PnL, log, ordini simulati
- puo includere il confronto tra diversi profili fee senza cambiare il feed dati

### Soluzione dopo

Mini app/menu bar widget per macOS con stato compatto:

- bot attivo o fermo
- pair monitorati
- ultimo segnale
- PnL paper di oggi
- alert rischio

Quando clicchi, apre la dashboard completa.

## Architettura software consigliata

### Processi

1. `collector`
2. `strategy`
3. `paper_executor`
4. `risk_manager`
5. `dashboard`
6. `ai_supervisor`

### Storage

All'inizio basta:

- SQLite per dati e log
- file JSON/CSV solo per export

Il database conserva anche:

- stato del provider commissionale simulato
- fee pagate in ingresso e uscita
- ragioni testuali delle decisioni del motore

Più avanti potremo valutare Postgres se serve.

### Schema minimo dati

- `order_book_snapshots`
- `last_trades`
- `signals`
- `paper_positions`
- `paper_fills`
- `daily_metrics`
- `events_log`

## Come gestire OpenAI in modo corretto

- se vuoi privacy e controllo, usa un progetto/account OpenAI tuo
- non cercare di nascondere il traffico al proprietario dell'account o del progetto
- non usare la stessa chiave per ambienti diversi
- non mettere chiavi in chat, repo o file Markdown
- tieni `OPENAI_API_KEY` nel file `.env` locale

Se vuoi ridurre dati condivisi:

- invia a OpenAI solo feature aggregate, non log completi inutili
- evita di passare identificativi personali
- usa l'AI solo per analisi ad alto livello

## Raccomandazione concreta

Il percorso piu sensato e questo:

1. collector pubblico senza API key Revolut
2. database SQLite
3. paper trading engine
4. dashboard locale
5. solo dopo integrazione OpenAI
6. solo dopo ancora chiavi Revolut autenticate per dati aggiuntivi e ordini

## Cosa farei adesso

Il prossimo step implementativo migliore e:

- collector live su `public/order-book` e `public/last-trades`
- salvataggio su SQLite
- prima dashboard locale con stato e metriche base

Questo ci permette di vedere subito il sistema in funzione sul tuo Mac, senza soldi veri e senza ordini live.
