from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    key: str
    label: str
    description: str
    maker_fee_rate: float
    taker_fee_rate: float
    fee_model: str
    market_data: bool
    paper_supported: bool
    shadow_supported: bool
    live_supported: bool
    short_supported: bool
    import_supported: bool
    notes: str


PROVIDER_PROFILES: dict[str, ProviderProfile] = {
    "HYPERLIQUID": ProviderProfile(
        key="HYPERLIQUID",
        label="Hyperliquid",
        description="Baseline predefinita del progetto: market data Hyperliquid e fee base da venue trading-native.",
        maker_fee_rate=0.00015,
        taker_fee_rate=0.00045,
        fee_model="perp_base_tier",
        market_data=True,
        paper_supported=True,
        shadow_supported=True,
        live_supported=False,
        short_supported=True,
        import_supported=True,
        notes="Venue supporta short e perps, ma nella alpha il motore paper resta ancora long-only finche non armiamo la logica short.",
    ),
    "REVOLUT_X": ProviderProfile(
        key="REVOLUT_X",
        label="Revolut X",
        description="Profilo legacy spot retail con fee ufficiali Revolut X, mantenuto per confronto storico e import futuri.",
        maker_fee_rate=0.0,
        taker_fee_rate=0.0009,
        fee_model="spot_taker",
        market_data=True,
        paper_supported=True,
        shadow_supported=True,
        live_supported=False,
        short_supported=False,
        import_supported=False,
        notes="Utile come baseline storica spot. Non e il provider predefinito del progetto dopo il passaggio a Hyperliquid.",
    ),
    "KRAKEN_PRO": ProviderProfile(
        key="KRAKEN_PRO",
        label="Kraken Pro",
        description="Profilo alternativo per confrontare l'impatto di fee spot tipiche di un exchange retail/pro.",
        maker_fee_rate=0.0025,
        taker_fee_rate=0.0040,
        fee_model="spot_tiered",
        market_data=False,
        paper_supported=False,
        shadow_supported=False,
        live_supported=False,
        short_supported=False,
        import_supported=True,
        notes="Usato solo per simulare commissioni. Il feed dati segue il venue operativo del bot.",
    ),
    "COINBASE_ADVANCED": ProviderProfile(
        key="COINBASE_ADVANCED",
        label="Coinbase Advanced",
        description="Profilo opzionale per vedere come cambiano i conti con fee più alte su basso volume.",
        maker_fee_rate=0.0060,
        taker_fee_rate=0.0120,
        fee_model="spot_tiered",
        market_data=False,
        paper_supported=False,
        shadow_supported=False,
        live_supported=False,
        short_supported=False,
        import_supported=True,
        notes="Usato solo per simulare commissioni. Il feed dati segue il venue operativo del bot.",
    ),
}

DEFAULT_PROVIDER_KEY = "HYPERLIQUID"


def get_provider_profile(key: str | None) -> ProviderProfile:
    if key and key in PROVIDER_PROFILES:
        return PROVIDER_PROFILES[key]
    return PROVIDER_PROFILES[DEFAULT_PROVIDER_KEY]


def list_provider_profiles() -> list[dict[str, object]]:
    return [serialize_provider(profile) for profile in PROVIDER_PROFILES.values()]


def serialize_provider(profile: ProviderProfile) -> dict[str, object]:
    return {
        "key": profile.key,
        "label": profile.label,
        "description": profile.description,
        "maker_fee_rate": profile.maker_fee_rate,
        "taker_fee_rate": profile.taker_fee_rate,
        "fee_model": profile.fee_model,
        "market_data": profile.market_data,
        "paper_supported": profile.paper_supported,
        "shadow_supported": profile.shadow_supported,
        "live_supported": profile.live_supported,
        "short_supported": profile.short_supported,
        "import_supported": profile.import_supported,
        "notes": profile.notes,
    }


def provider_state_items(profile: ProviderProfile) -> dict[str, str]:
    return {
        "paper_provider_key": profile.key,
        "paper_provider_label": profile.label,
        "paper_provider_description": profile.description,
        "paper_provider_fee_model": profile.fee_model,
        "paper_provider_market_data": "true" if profile.market_data else "false",
        "paper_provider_paper_supported": "true" if profile.paper_supported else "false",
        "paper_provider_shadow_supported": "true" if profile.shadow_supported else "false",
        "paper_provider_live_supported": "true" if profile.live_supported else "false",
        "paper_provider_short_supported": "true" if profile.short_supported else "false",
        "paper_provider_import_supported": "true" if profile.import_supported else "false",
        "paper_provider_notes": profile.notes,
        "paper_maker_fee_rate": f"{profile.maker_fee_rate:.8f}",
        "paper_taker_fee_rate": f"{profile.taker_fee_rate:.8f}",
    }
