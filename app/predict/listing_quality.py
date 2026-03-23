"""Listing quality filters for the ML/Parquet scoring system.

Part of the ML/Parquet system. Shared by parquet_scorer.py and
parquet_dataset.py to filter ADRs, junior exchange listings,
and apply currency-adjusted dollar volume thresholds.

Do NOT import from the deterministic system (scorer.py, strategy.py, features.py).
"""
from __future__ import annotations

import re


# ── ADR / OTC heuristic ────────────────────────────────────────────────
# In the US OTC market, 5+ character tickers ending in Y are almost always
# ADRs (American Depositary Receipts) and those ending in F are OTC foreign
# shares. Analysis of the training parquet confirms zero false positives
# among 93 Y-suffix and 119 F-suffix tickers — every single one is a
# foreign company. 4-character tickers ending Y are mostly real US
# companies (ALLY, ETSY, CHWY, etc.) and must NOT be filtered.

def is_likely_adr(ticker: str) -> bool:
    """Heuristic: ticker is likely an ADR or OTC foreign share.

    Rule: no dot (i.e. US-listed), 5+ characters, ends in Y or F.
    No country check needed — ADRs are tagged country_iso2="US" in the
    parquet, so country is unreliable for this purpose.
    """
    if "." in ticker:
        return False
    if len(ticker) < 5:
        return False
    return ticker[-1] in ("Y", "F")


# ── Junior exchange heuristic ──────────────────────────────────────────
# Tickers with these exchange suffixes are from junior/venture exchanges
# where most listed companies are micro-cap, illiquid, or speculative.

_JUNIOR_SUFFIXES = {"V", "CN", "NE"}  # .V = TSX Venture, .CN = CSE, .NE = NEO


def is_junior_exchange(ticker: str) -> bool:
    """Heuristic: ticker is from a junior or venture exchange."""
    if "." not in ticker:
        return False
    suffix = ticker.rsplit(".", 1)[1]
    return suffix in _JUNIOR_SUFFIXES


# ── Company name normalisation ─────────────────────────────────────────
# FMP uses slightly different names for the same company across listings:
# "Safran S.A." (SAF.PA) vs "Safran SA" (SAFRY). Standard dedup using
# strip().lower() fails. This normaliser strips common legal suffixes,
# removes periods, and collapses whitespace.

_LEGAL_SUFFIXES = [
    # Longest first to avoid partial matches
    "public limited company",
    "société anonyme",
    "societe anonyme",
    "corporation",
    "incorporated",
    "co., ltd.",
    "co., ltd",
    "co.,ltd.",
    "co.,ltd",
    "co. ltd.",
    "co. ltd",
    "co ltd",
    "holdings",
    "holding",
    "limited",
    "group",
    "corp.",
    "corp",
    "inc.",
    "inc",
    "ltd.",
    "ltd",
    "s.p.a.",
    "s.p.a",
    "spa",
    "s.a.",
    "s.a",
    "n.v.",
    "n.v",
    "a.g.",
    "a.g",
    "plc",
    "& co.",
    "& co",
    "co.",
    "se",
    "ag",
    "sa",
    "nv",
]

_SUFFIX_RE = re.compile(
    r"\s+(?:" + "|".join(re.escape(s) for s in _LEGAL_SUFFIXES) + r")\s*$",
    re.IGNORECASE,
)


def normalise_company_name(name: str) -> str:
    """Normalise a company name for deduplication.

    Strips common legal suffixes, removes periods, collapses whitespace.
    "Safran S.A." and "Safran SA" both normalise to "safran".
    """
    s = name.strip().lower()
    # Strip legal suffix (only one pass — suffixes don't stack meaningfully)
    s = _SUFFIX_RE.sub("", s)
    # Remove all periods
    s = s.replace(".", "")
    # Remove trailing punctuation and whitespace
    s = s.rstrip(" ,.-&")
    # Collapse multiple spaces
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ── Currency-adjusted dollar volume ────────────────────────────────────
# The dollar_volume_30d feature is computed as avg_volume × avg_price
# using LOCAL currency prices. The min_dollar_volume filter (500,000)
# must be applied in USD to be meaningful across countries.
#
# These rates are approximate — only order-of-magnitude accuracy is
# needed since the filter threshold itself is approximate.

_APPROX_USD_RATES: dict[str, float] = {
    "USD": 1.0,
    "EUR": 1.08,
    "GBP": 1.27,
    "GBp": 0.0127,   # Pence sterling (LSE convention)
    "JPY": 0.0067,
    "CHF": 1.12,
    "AUD": 0.65,
    "CAD": 0.74,
    "SEK": 0.095,
    "NOK": 0.094,
    "DKK": 0.145,
    "NZD": 0.60,
    "HKD": 0.128,
    "SGD": 0.74,
    "KRW": 0.00075,
    "TWD": 0.031,
    "BRL": 0.20,
    "ZAR": 0.055,
    "ILS": 0.27,
    "CNY": 0.14,
    "INR": 0.012,
    "MXN": 0.058,
    "PLN": 0.25,
    "TRY": 0.031,
    "THB": 0.028,
    "IDR": 0.000063,
    "MYR": 0.22,
    "PHP": 0.018,
    "VND": 0.000040,
    "CZK": 0.043,
    "HUF": 0.0027,
    "CLP": 0.0011,
    "COP": 0.00024,
    "EGP": 0.020,
    "SAR": 0.27,
    "AED": 0.27,
    "QAR": 0.27,
    "KWD": 3.26,
    "BHD": 2.65,
}


def dollar_volume_usd(
    local_volume: float,
    reported_currency: str | None,
) -> float:
    """Convert local-currency dollar volume to approximate USD.

    Unknown or missing currency defaults to 1.0 (assumes USD — won't exclude).
    """
    if not reported_currency:
        return local_volume
    rate = _APPROX_USD_RATES.get(reported_currency, 1.0)
    return local_volume * rate
