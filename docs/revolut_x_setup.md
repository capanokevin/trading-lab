# Revolut X Setup

Questa e la guida operativa minima per collegare la repo a Revolut X senza confonderci in futuro.

Nota pratica:

- per la v1 simulata pubblica questa guida e opzionale
- serve quando vogliamo aggiungere dati autenticati o ordini

## Fonti ufficiali

- Main docs: <https://developer.revolut.com/docs/x-api/revolut-x-crypto-exchange-rest-api>
- OpenAPI spec: <https://github.com/revolut-engineering/revolut-openapi/blob/master/json/revolut-x.json>
- Order placement: <https://developer.revolut.com/docs/x-api/place-order>

## Cose confermate il 12 marzo 2026

- Server production: `https://revx.revolut.com/api/1.0`
- Server dev con test data: `https://revx.revolut.codes/api/1.0`
- Endpoint pubblici verificati senza autenticazione:
  - `GET /public/order-book/{symbol}`
  - `GET /public/last-trades`
- Endpoint autenticati utili subito:
  - `GET /configuration/pairs`
  - `GET /candles/{symbol}`
  - `POST /orders`
- Il simbolo usa il formato `BTC-USD`, non `BTC/USD`
- `GET /public/order-book/{symbol}` restituisce fino a 5 livelli di book
- `GET /public/last-trades` restituisce gli ultimi 100 trade
- `GET /candles/{symbol}` supporta fino a 1000 candele per richiesta
- `POST /orders` ha una nota ufficiale di rate limit per i limit order: `1000 requests/day`

## Autenticazione

Per le richieste autenticate servono tre header:

- `X-Revx-API-Key`
- `X-Revx-Timestamp`
- `X-Revx-Signature`

La firma usa Ed25519 e va costruita cosi:

`timestamp + HTTP_METHOD + request_path_from_/api + query_string_without_question_mark + minified_json_body`

Esempio logico:

- timestamp: `1746007718237`
- metodo: `GET`
- path: `/api/1.0/candles/BTC-USD`
- query string: `interval=5`
- body: vuoto

Stringa da firmare:

```text
1746007718237GET/api/1.0/candles/BTC-USDinterval=5
```

Per una `POST` con body JSON, il body va minificato.

## Passi pratici

### 1. Genera le chiavi

Le docs ufficiali mostrano questi comandi:

```bash
openssl genpkey -algorithm ed25519 -out private.pem
openssl pkey -in private.pem -pubout -out public.pem
```

Nella repo abbiamo gia uno script che salva tutto in `secrets/revolut_x/`:

```bash
./scripts/generate_revolut_x_keys.sh
```

### 2. Crea la API key in Revolut X

- apri <https://exchange.revolut.com/>
- entra nella sezione API del profilo
- carica la `public.pem`
- genera la API key

### 3. Configura la repo

```bash
cp .env.example .env
```

Poi compila:

- `REVOLUT_X_API_KEY`
- `REVOLUT_X_PRIVATE_KEY_PATH`
- opzionalmente `REVOLUT_X_BASE_URL`

### 4. Verifica senza credenziali

```bash
python3 scripts/smoke_test.py
```

Questo testa:

- order book pubblico
- last trades pubblici

### 5. Verifica con credenziali

```bash
python3 scripts/smoke_test.py --authenticated
```

Questo prova anche:

- lista pair configurate
- candles storiche

## Convenzioni di sicurezza

- non scrivere mai la API key vera in file `.md`
- non committare `private.pem`
- conserva nei documenti solo:
  - dove si trova la chiave
  - quando e stata creata
  - quando va ruotata
  - quale ambiente usa il bot

## Prossimo step consigliato

Dopo il smoke test, il passo sensato e costruire un modulo di paper trading locale che:

- legge `order-book` e `last-trades`
- salva snapshot e segnali
- simula fee, spread e slippage
- non invia ordini reali
