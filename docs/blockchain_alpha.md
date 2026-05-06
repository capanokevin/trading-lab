# Blockchain Alpha

Aggiornato al `24 marzo 2026`.

## Tesi architetturale

Nel progetto la blockchain entra come `control plane`, non come scorciatoia magica per fare trading.

Separiamo sempre tre livelli:

- `wallet layer`: MetaMask, WalletConnect, signer dedicati
- `venue layer`: Hyperliquid, GMX, dYdX, Uniswap
- `execution / decision layer`: risk manager, shadow mode, replay, audit, cost attribution

Questa separazione evita l'errore piu comune:

- usare il wallet browser come se fosse il motore del bot

Per noi il wallet serve a:

- onboarding
- watch account
- conferme manuali
- snapshot locali

Il motore automatico, quando arrivera davvero, dovra appoggiarsi a venue piu adatte.

## Scelte alpha attuali

### Wallet iniziale consigliato

- `MetaMask`

Perche:

- ottimo per UX EVM
- facile da collegare dal browser
- perfetto per registrare wallet watch e fare snapshot locali

### Venue on-chain primaria consigliata

- `Hyperliquid`

Perche:

- API wallet / signer dedicati
- short e perps disponibili
- venue molto piu naturale per futura automazione rispetto a un wallet browser puro

### Venue successive gia modellate

- `GMX V2`
- `dYdX`
- `Uniswap` solo come modulo wallet/spot, non come primo engine intraday

## Cosa fa gia l'app

Nella tab `Account` puoi gia:

- registrare wallet browser o signer dedicati
- collegare `MetaMask`
- caricare un preset `Hyperliquid`
- salvare wallet in `WATCH`, `SHADOW_PREP`, `API_PREP`, `LIVE_PREP`
- sincronizzare wallet registrati

Sync supportata oggi:

- `MetaMask` su chain EVM via browser snapshot
  - balance nativo
  - tx count
  - chain attiva
  - block number
- `Hyperliquid` via endpoint pubblici
  - account value
  - withdrawable
  - numero posizioni perp
  - numero balance spot

I risultati finiscono:

- nel database locale
- nel ledger eventi
- nella UI account center

## Cosa non fa ancora

- live execution on-chain armata
- custodia di private key o seed phrase
- sync cloud dei wallet
- import automatico completo da GMX o dYdX
- portfolio valuation multi-token completa

## Workflow consigliato

### Fase 1

- usa `Revolut X` per paper/shadow di base
- collega `MetaMask` per wallet watch EVM
- registra un wallet `Hyperliquid` o signer dedicato
- salva snapshot e leggi la readiness nella UI

### Fase 2

- porta `Hyperliquid` in `API_PREP`
- usa il layer blockchain per confrontare:
  - UX wallet
  - venue capability
  - live readiness
  - sync quality

### Fase 3

- solo dopo si apre il cantiere execution on-chain vera

## Input che ci serviranno dal tuo lato

Non subito, ma per sfruttare davvero il layer blockchain ci serviranno:

- almeno un wallet `MetaMask` reale
- se vuoi preparare la venue primaria, un address o signer `Hyperliquid`
- piu avanti, se vorrai venue perps diverse, il provider prioritario tra `Hyperliquid`, `GMX`, `dYdX`

## Fonti ufficiali usate per orientare il design

- [MetaMask Wallet API](https://docs.metamask.io/wallet/)
- [MetaMask provider API](https://docs.metamask.io/wallet/reference/provider-api/)
- [Hyperliquid API wallets](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/nonces-and-api-wallets)
- [Hyperliquid info endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)
- [GMX API overview](https://docs.gmx.io/docs/api/overview)
- [GMX trading docs](https://docs.gmx.io/docs/trading/)
- [dYdX docs](https://docs.dydx.xyz/)
