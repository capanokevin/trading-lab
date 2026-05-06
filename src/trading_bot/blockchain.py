from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChainProfile:
    key: str
    label: str
    ecosystem: str
    gas_token: str
    settlement: str
    is_evm: bool
    chain_id: int | None
    notes: str


@dataclass(frozen=True, slots=True)
class WalletProfile:
    key: str
    label: str
    wallet_type: str
    self_custody: bool
    browser_injected: bool
    api_wallet_supported: bool
    notes: str
    supported_chain_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VenueProfile:
    key: str
    label: str
    venue_type: str
    execution_style: str
    description: str
    chain_keys: tuple[str, ...]
    wallet_keys: tuple[str, ...]
    market_data: bool
    paper_supported: bool
    shadow_supported: bool
    live_supported: bool
    short_supported: bool
    derivatives_supported: bool
    import_supported: bool
    gasless_trading: bool
    api_wallet_supported: bool
    fee_hint: str
    notes: str
    best_for: str


CHAIN_PROFILES: dict[str, ChainProfile] = {
    "ETHEREUM": ChainProfile(
        key="ETHEREUM",
        label="Ethereum",
        ecosystem="EVM",
        gas_token="ETH",
        settlement="onchain",
        is_evm=True,
        chain_id=1,
        notes="Chain EVM standard. Buona per wallet compatibility, meno adatta al trading frequente per costi gas.",
    ),
    "ARBITRUM": ChainProfile(
        key="ARBITRUM",
        label="Arbitrum",
        ecosystem="EVM L2",
        gas_token="ETH",
        settlement="onchain",
        is_evm=True,
        chain_id=42161,
        notes="Chain EVM con costi piu bassi. Rilevante per GMX e dapp on-chain orientate al trading.",
    ),
    "BASE": ChainProfile(
        key="BASE",
        label="Base",
        ecosystem="EVM L2",
        gas_token="ETH",
        settlement="onchain",
        is_evm=True,
        chain_id=8453,
        notes="L2 EVM con buona UX retail e wallet compatibility alta.",
    ),
    "AVALANCHE": ChainProfile(
        key="AVALANCHE",
        label="Avalanche",
        ecosystem="EVM L1",
        gas_token="AVAX",
        settlement="onchain",
        is_evm=True,
        chain_id=43114,
        notes="Chain supportata da GMX V2 oltre ad Arbitrum.",
    ),
    "HYPERLIQUID": ChainProfile(
        key="HYPERLIQUID",
        label="Hyperliquid",
        ecosystem="HyperCore / HyperEVM",
        gas_token="USDC",
        settlement="venue_native",
        is_evm=False,
        chain_id=None,
        notes="Venue trading-native con API wallets e ottima predisposizione per automazione.",
    ),
    "DYDX_CHAIN": ChainProfile(
        key="DYDX_CHAIN",
        label="dYdX Chain",
        ecosystem="Appchain",
        gas_token="USDC",
        settlement="venue_native",
        is_evm=False,
        chain_id=None,
        notes="Venue orientata a trading e derivati, meno wallet-like di una classica chain EVM.",
    ),
}


WALLET_PROFILES: dict[str, WalletProfile] = {
    "METAMASK_EXTENSION": WalletProfile(
        key="METAMASK_EXTENSION",
        label="MetaMask",
        wallet_type="browser_wallet",
        self_custody=True,
        browser_injected=True,
        api_wallet_supported=False,
        notes="Ottimo layer wallet per onboarding, watch e conferme manuali. Non lo tratto come executor primario del bot.",
        supported_chain_keys=("ETHEREUM", "ARBITRUM", "BASE", "AVALANCHE"),
    ),
    "WALLETCONNECT": WalletProfile(
        key="WALLETCONNECT",
        label="WalletConnect",
        wallet_type="wallet_router",
        self_custody=True,
        browser_injected=False,
        api_wallet_supported=False,
        notes="Buon fallback cross-wallet per app future. Per ora lo trattiamo come preparazione a integrazioni EVM piu ampie.",
        supported_chain_keys=("ETHEREUM", "ARBITRUM", "BASE", "AVALANCHE"),
    ),
    "HYPERLIQUID_API_WALLET": WalletProfile(
        key="HYPERLIQUID_API_WALLET",
        label="Hyperliquid API Wallet",
        wallet_type="api_wallet",
        self_custody=True,
        browser_injected=False,
        api_wallet_supported=True,
        notes="Wallet agente dedicato al trading automatico. E il candidato migliore per live automation futura.",
        supported_chain_keys=("HYPERLIQUID",),
    ),
    "SERVER_SIGNER": WalletProfile(
        key="SERVER_SIGNER",
        label="Signer dedicato",
        wallet_type="server_signer",
        self_custody=True,
        browser_injected=False,
        api_wallet_supported=True,
        notes="Signer locale o server-side per venue con API wallet o signing diretto. Utile solo in setup piu avanzati.",
        supported_chain_keys=("HYPERLIQUID", "DYDX_CHAIN", "ARBITRUM", "AVALANCHE", "BASE", "ETHEREUM"),
    ),
}


VENUE_PROFILES: dict[str, VenueProfile] = {
    "REVOLUT_X": VenueProfile(
        key="REVOLUT_X",
        label="Revolut X",
        venue_type="cex_spot",
        execution_style="rest_spot",
        description="Baseline semplice per data collection e paper trading spot retail.",
        chain_keys=(),
        wallet_keys=(),
        market_data=True,
        paper_supported=True,
        shadow_supported=True,
        live_supported=False,
        short_supported=False,
        derivatives_supported=False,
        import_supported=False,
        gasless_trading=False,
        api_wallet_supported=False,
        fee_hint="maker 0,00% | taker 0,09%",
        notes="Buono per partire, limitato per strategie intraday piu aggressive o short/perps.",
        best_for="Paper research spot con UX semplice.",
    ),
    "HYPERLIQUID": VenueProfile(
        key="HYPERLIQUID",
        label="Hyperliquid",
        venue_type="perp_dex",
        execution_style="order_book_api_wallet",
        description="Venue on-chain trading-native con order book, API wallets e buona latenza per automazione.",
        chain_keys=("HYPERLIQUID",),
        wallet_keys=("HYPERLIQUID_API_WALLET", "SERVER_SIGNER", "METAMASK_EXTENSION"),
        market_data=True,
        paper_supported=True,
        shadow_supported=True,
        live_supported=True,
        short_supported=True,
        derivatives_supported=True,
        import_supported=True,
        gasless_trading=True,
        api_wallet_supported=True,
        fee_hint="fee basse + trading senza gas operativo; withdrawal fee separata",
        notes="Prima venue blockchain che integrerei davvero per automazione seria e short/perps.",
        best_for="Execution automatica, short/perps e setup multi-process con API wallet.",
    ),
    "GMX_V2": VenueProfile(
        key="GMX_V2",
        label="GMX V2",
        venue_type="perp_dex",
        execution_style="oracle_perps",
        description="Perps on-chain con execution diversa dall'order book classico e supporto SDK/API in crescita.",
        chain_keys=("ARBITRUM", "AVALANCHE"),
        wallet_keys=("METAMASK_EXTENSION", "WALLETCONNECT", "SERVER_SIGNER"),
        market_data=True,
        paper_supported=True,
        shadow_supported=True,
        live_supported=True,
        short_supported=True,
        derivatives_supported=True,
        import_supported=True,
        gasless_trading=False,
        api_wallet_supported=True,
        fee_hint="costi di protocollo + gas chain",
        notes="Ottimo per control plane e shadow su perps, ma piu complesso da modellare rispetto a un CLOB.",
        best_for="Perps on-chain con forte controllo rischio e action layer guidato.",
    ),
    "DYDX_CHAIN": VenueProfile(
        key="DYDX_CHAIN",
        label="dYdX Chain",
        venue_type="perp_dex",
        execution_style="order_book_chain",
        description="Venue derivati trading-native con stack piu vicino a un exchange di trading puro.",
        chain_keys=("DYDX_CHAIN",),
        wallet_keys=("SERVER_SIGNER",),
        market_data=True,
        paper_supported=True,
        shadow_supported=True,
        live_supported=True,
        short_supported=True,
        derivatives_supported=True,
        import_supported=True,
        gasless_trading=False,
        api_wallet_supported=True,
        fee_hint="fee da venue derivati + funding dove applicabile",
        notes="Molto interessante per fase successiva, ma piu complesso da portare bene nella alpha rispetto a Hyperliquid.",
        best_for="Desk piu trading-centric, perps e short sistematici.",
    ),
    "UNISWAP_EVM": VenueProfile(
        key="UNISWAP_EVM",
        label="Uniswap",
        venue_type="amm_spot",
        execution_style="amm_swap",
        description="Spot on-chain puro con wallet EVM, ideale per routing e manual execution, meno per intraday ad alta frequenza.",
        chain_keys=("ETHEREUM", "ARBITRUM", "BASE"),
        wallet_keys=("METAMASK_EXTENSION", "WALLETCONNECT", "SERVER_SIGNER"),
        market_data=True,
        paper_supported=True,
        shadow_supported=True,
        live_supported=True,
        short_supported=False,
        derivatives_supported=False,
        import_supported=True,
        gasless_trading=False,
        api_wallet_supported=False,
        fee_hint="price impact + slippage + gas",
        notes="Lo vedo bene come modulo opzionale spot/portfolio, non come primo motore intraday del progetto.",
        best_for="Wallet UX, swap spot e osservabilita on-chain.",
    ),
}


CHAIN_ID_TO_KEY = {
    profile.chain_id: profile.key
    for profile in CHAIN_PROFILES.values()
    if profile.chain_id is not None
}


def get_chain_profile(key: str | None) -> ChainProfile:
    if key and key in CHAIN_PROFILES:
        return CHAIN_PROFILES[key]
    return CHAIN_PROFILES["ARBITRUM"]


def get_wallet_profile(key: str | None) -> WalletProfile:
    if key and key in WALLET_PROFILES:
        return WALLET_PROFILES[key]
    return WALLET_PROFILES["METAMASK_EXTENSION"]


def get_venue_profile(key: str | None) -> VenueProfile:
    if key and key in VENUE_PROFILES:
        return VENUE_PROFILES[key]
    return VENUE_PROFILES["HYPERLIQUID"]


def serialize_chain(profile: ChainProfile) -> dict[str, object]:
    return {
        "key": profile.key,
        "label": profile.label,
        "ecosystem": profile.ecosystem,
        "gas_token": profile.gas_token,
        "settlement": profile.settlement,
        "is_evm": profile.is_evm,
        "chain_id": profile.chain_id,
        "notes": profile.notes,
    }


def serialize_wallet(profile: WalletProfile) -> dict[str, object]:
    return {
        "key": profile.key,
        "label": profile.label,
        "wallet_type": profile.wallet_type,
        "self_custody": profile.self_custody,
        "browser_injected": profile.browser_injected,
        "api_wallet_supported": profile.api_wallet_supported,
        "notes": profile.notes,
        "supported_chain_keys": list(profile.supported_chain_keys),
    }


def serialize_venue(profile: VenueProfile) -> dict[str, object]:
    return {
        "key": profile.key,
        "label": profile.label,
        "venue_type": profile.venue_type,
        "execution_style": profile.execution_style,
        "description": profile.description,
        "chain_keys": list(profile.chain_keys),
        "wallet_keys": list(profile.wallet_keys),
        "market_data": profile.market_data,
        "paper_supported": profile.paper_supported,
        "shadow_supported": profile.shadow_supported,
        "live_supported": profile.live_supported,
        "short_supported": profile.short_supported,
        "derivatives_supported": profile.derivatives_supported,
        "import_supported": profile.import_supported,
        "gasless_trading": profile.gasless_trading,
        "api_wallet_supported": profile.api_wallet_supported,
        "fee_hint": profile.fee_hint,
        "notes": profile.notes,
        "best_for": profile.best_for,
    }


def list_chain_profiles() -> list[dict[str, object]]:
    return [serialize_chain(profile) for profile in CHAIN_PROFILES.values()]


def list_wallet_profiles() -> list[dict[str, object]]:
    return [serialize_wallet(profile) for profile in WALLET_PROFILES.values()]


def list_venue_profiles() -> list[dict[str, object]]:
    return [serialize_venue(profile) for profile in VENUE_PROFILES.values()]


def recommend_onchain_stack() -> list[dict[str, str]]:
    return [
        {
            "title": "Wallet layer",
            "choice": "MetaMask",
            "reason": "Serve per onboarding, watch account e conferme manuali EVM. Non lo uso come executor primario del bot.",
        },
        {
            "title": "Prima venue automation",
            "choice": "Hyperliquid",
            "reason": "API wallets, short/perps e integrazione piu naturale per un control plane automatizzato.",
        },
        {
            "title": "Seconda venue da studiare",
            "choice": "GMX V2",
            "reason": "Perps on-chain e UX wallet forte, ma execution piu complessa da modellare rispetto a un CLOB.",
        },
        {
            "title": "Venue da rimandare",
            "choice": "Uniswap come engine intraday",
            "reason": "Buona per spot/wallet UX, meno efficiente per un bot intraday a causa di gas, slippage e MEV.",
        },
    ]
