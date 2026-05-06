# Provider Short Support

Aggiornato al `16 marzo 2026`.

## Sintesi rapida

- `Revolut X REST API`: buona per spot retail, ma non e la strada giusta per abilitare short nella nostra app. Le docs pubbliche mostrano API spot con ordini `BUY`/`SELL`, market data, balances e ordini spot; non vedo una retail public derivatives/margin API equivalente per shorting.
- `Kraken`: e il candidato piu semplice da studiare dopo Revolut X se vogliamo short via API. Le docs REST ufficiali prevedono `leverage` negli ordini e la documentazione di supporto conferma margin trading per clienti verificati idonei, con restrizioni geografiche.
- `Coinbase`: per short lato API la strada realistica non e Advanced Trade spot, ma i prodotti derivatives/perpetuals nelle giurisdizioni idonee. L'accesso dipende da onboarding e paese/entita.

## Implicazione pratica per il progetto

- Oggi lasciamo `Revolut X` come provider spot per il motore paper di ricerca.
- Il lato `short` non va abilitato in modo generico finche non scegliamo un provider con accesso API chiaramente supportato per il tuo account e la tua giurisdizione.
- Se in futuro attiviamo un provider con short, conviene modellarlo come provider separato nella UI e nella logica di esecuzione.

## Fonti ufficiali

- Revolut X REST API: <https://developer.revolut.com/docs/x-api/revolut-x-crypto-exchange-rest-api>
- Revolut X place order: <https://developer.revolut.com/docs/x-api/place-order>
- Kraken REST `Add Order`: <https://docs.kraken.com/api/docs/rest-api/add-order/>
- Kraken margin trading eligibility: <https://support.kraken.com/hc/en-us/articles/360000966966-What-is-margin->
- Coinbase International perpetual futures: <https://help.coinbase.com/en/coinbase/trading-and-funding/derivatives/intx-derivatives-faq>
- Coinbase International Exchange API overview: <https://docs.cdp.coinbase.com/api-reference/international-exchange-api/rest-api/introduction>
