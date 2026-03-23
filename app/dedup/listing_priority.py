"""Listing priority scoring for ISIN-based deduplication.

For each ISIN group (multiple listings of the same company), this module
selects the "primary" listing — the one most likely to be the home exchange
listing that an investor would actually trade.

This belongs to the platform layer. Do NOT import from app/predict/.
"""
from __future__ import annotations

# Primary exchange suffix for each country in our investable universe.
# US-listed tickers have no suffix; all others use the exchange suffix.
HOME_EXCHANGE_SUFFIX: dict[str, str] = {
    "US": "",
    "CA": ".TO",
    "GB": ".L",
    "AU": ".AX",
    "DE": ".DE",
    "FR": ".PA",
    "NL": ".AS",
    "JP": ".T",
    "CH": ".SW",
    "SE": ".ST",
    "KR": ".KS",
    "BR": ".SA",
    "ZA": ".JO",
    "SG": ".SI",
    "HK": ".HK",
    "NO": ".OL",
    "DK": ".CO",
    "FI": ".HE",
    "IL": ".TA",
    "NZ": ".NZ",
    "TW": ".TW",
    "IE": ".IR",
    "BE": ".BR",
    "AT": ".VI",
    # Extended — not in our 24 investable countries but appear in the DB
    "IN": ".NS",
    "CN": ".SS",
    "MY": ".KL",
    "TH": ".BK",
    "ID": ".JK",
    "MX": ".MX",
    "PL": ".WA",
    "AR": ".BA",
    "CL": ".SN",
    "CO": ".CL",
    "SA": ".SR",
    "AE": ".DFM",
    "QA": ".QA",
    "KW": ".KW",
    "TR": ".IS",
    "PH": ".PM",
    "VN": ".HM",
    "CZ": ".PR",
    "HU": ".BD",
    "GR": ".AT",
    "RO": ".BVB",
    "PT": ".LS",
    "ES": ".MC",
    "IT": ".MI",
}

# Secondary/regional exchanges — penalised in priority scoring
_REGIONAL_SUFFIXES = frozenset({".DU", ".HM", ".MU", ".SG", ".F", ".IL", ".WA"})


def listing_priority(
    ticker: str,
    country_iso2: str,
    is_adr: bool | None,
    exchange_short: str | None,
    has_fundamentals: bool,
    market_cap_usd: int | None,
) -> tuple:
    """Return a comparable tuple for max()-based selection of primary listing.

    Higher tuple = higher priority. Python tuple comparison proceeds
    left-to-right, so earlier elements dominate.

    Priority order:
    1. Home exchange match (ticker suffix matches country)
    2. Not an ADR
    3. Not an OTC foreign receipt (5+ chars, no dot, ends in F)
    4. Not a secondary/regional exchange
    5. Has fundamental data
    6. Has exchange_short populated
    7. Highest market cap
    8. Shortest ticker (home listings tend to be shorter)
    9. Alphabetically first ticker (deterministic tiebreak)
    """
    home_suffix = HOME_EXCHANGE_SUFFIX.get(country_iso2, "")

    # Home exchange match
    if home_suffix == "" and "." not in ticker:
        is_home = 1  # US-listed, no suffix
    elif home_suffix and ticker.endswith(home_suffix):
        is_home = 1
    else:
        is_home = 0

    is_not_adr = 0 if is_adr else 1

    # OTC foreign receipts: 5+ chars, no dot, ends in F
    is_not_otc_foreign = 0 if (
        len(ticker) >= 5 and "." not in ticker and ticker[-1] == "F"
    ) else 1

    # Regional/secondary exchanges
    is_not_regional = 0 if any(
        ticker.endswith(s) for s in _REGIONAL_SUFFIXES
    ) else 1

    has_fund = 1 if has_fundamentals else 0
    has_exch = 1 if exchange_short else 0
    mcap = market_cap_usd or 0

    # Prefer shorter tickers (home listings tend to be shorter)
    short_ticker = -len(ticker)

    return (
        is_home,
        is_not_adr,
        is_not_otc_foreign,
        is_not_regional,
        has_fund,
        has_exch,
        mcap,
        short_ticker,
        ticker,  # alphabetical tiebreak for determinism
    )
