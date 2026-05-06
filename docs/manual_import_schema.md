# Manual Import Schema

Aggiornato al `17 marzo 2026`.

## Obiettivo

Questo schema serve per l'alpha `crypto trading control plane`.

Non e un importer universale. E un formato minimo per:

- review locale
- confronto limitato tra account
- audit dei costi
- journaling e replay lato control plane

## Formati supportati

- `CSV`
- `JSON`

## Campi minimi supportati

- `timestamp`
- `event_type`
- `symbol`
- `side`
- `quantity`
- `price`
- `notional`
- `fee`
- `currency`
- `notes`

## Event type supportati

- `trade`
- `deposit`
- `withdrawal`
- `fee`

## Esempio CSV

```csv
timestamp,event_type,symbol,side,quantity,price,notional,fee,currency,notes
2026-03-17T08:30:00Z,deposit,,,,500,0,EUR,deposito iniziale
2026-03-17T09:12:00Z,trade,BTC-EUR,BUY,0.0015,64200,96.30,0.09,EUR,ingresso test
2026-03-17T09:55:00Z,trade,BTC-EUR,SELL,0.0015,64540,96.81,0.09,EUR,uscita test
2026-03-17T09:55:05Z,fee,,,,,0,0.18,EUR,fee giornata
```

## Esempio JSON

```json
[
  {
    "timestamp": "2026-03-17T08:30:00Z",
    "event_type": "deposit",
    "notional": 500,
    "currency": "EUR",
    "notes": "deposito iniziale"
  },
  {
    "timestamp": "2026-03-17T09:12:00Z",
    "event_type": "trade",
    "symbol": "BTC-EUR",
    "side": "BUY",
    "quantity": 0.0015,
    "price": 64200,
    "notional": 96.30,
    "fee": 0.09,
    "currency": "EUR",
    "notes": "ingresso test"
  }
]
```

## Limiti attuali

- niente derivati
- niente funding rate
- niente margin e leverage
- niente reconciliations avanzate multi-fill
- niente FX conversion multi-valuta avanzata
