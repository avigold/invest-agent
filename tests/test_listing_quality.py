"""Tests for app.predict.listing_quality — ADR/OTC heuristics, name normalisation, currency."""
from __future__ import annotations

import pytest

from app.predict.listing_quality import (
    is_likely_adr,
    is_junior_exchange,
    normalise_company_name,
    dollar_volume_usd,
)


# ── is_likely_adr ────────────────────────────────────────────────────────

class TestIsLikelyAdr:
    """ADR heuristic: 5+ chars, no dot, ends in Y or F."""

    def test_typical_adr_ending_y(self):
        assert is_likely_adr("SAFRY") is True
        assert is_likely_adr("TCEHY") is True
        assert is_likely_adr("ADDYY") is True
        assert is_likely_adr("TOELY") is True

    def test_typical_otc_foreign_ending_f(self):
        assert is_likely_adr("SAFRF") is True
        assert is_likely_adr("BYDDF") is True

    def test_short_us_tickers_not_filtered(self):
        """4-char tickers ending Y are real US companies."""
        assert is_likely_adr("ALLY") is False
        assert is_likely_adr("ETSY") is False
        assert is_likely_adr("CHWY") is False
        assert is_likely_adr("COPY") is False

    def test_dotted_tickers_not_filtered(self):
        """Non-US tickers (with exchange suffix) should never match."""
        assert is_likely_adr("SAF.PA") is False
        assert is_likely_adr("AAPL.L") is False
        assert is_likely_adr("SAFRY.OTC") is False

    def test_normal_us_tickers(self):
        assert is_likely_adr("AAPL") is False
        assert is_likely_adr("MSFT") is False
        assert is_likely_adr("GOOGL") is False  # 5 chars but ends in L
        assert is_likely_adr("NVDA") is False

    def test_5_char_not_ending_yf(self):
        assert is_likely_adr("GOOGL") is False
        assert is_likely_adr("AMZNN") is False


# ── is_junior_exchange ───────────────────────────────────────────────────

class TestIsJuniorExchange:
    """Junior exchange heuristic: dot suffix in {V, CN, NE}."""

    def test_tsxv(self):
        assert is_junior_exchange("TM.V") is True
        assert is_junior_exchange("BLGV.V") is True

    def test_cse(self):
        assert is_junior_exchange("BLGV.CN") is True

    def test_neo(self):
        assert is_junior_exchange("REIT.NE") is True

    def test_major_exchanges_not_filtered(self):
        assert is_junior_exchange("SAF.PA") is False
        assert is_junior_exchange("AAPL.L") is False
        assert is_junior_exchange("RIO.AX") is False
        assert is_junior_exchange("7203.T") is False

    def test_us_tickers_not_filtered(self):
        assert is_junior_exchange("AAPL") is False
        assert is_junior_exchange("MSFT") is False


# ── normalise_company_name ───────────────────────────────────────────────

class TestNormaliseCompanyName:
    """Company name normalisation for deduplication."""

    def test_safran_variants(self):
        """The motivating case: 'Safran S.A.' must match 'Safran SA'."""
        assert normalise_company_name("Safran S.A.") == normalise_company_name("Safran SA")

    def test_strips_sa(self):
        assert normalise_company_name("Safran SA") == "safran"

    def test_strips_inc(self):
        assert normalise_company_name("Apple Inc.") == "apple"
        assert normalise_company_name("Apple Inc") == "apple"

    def test_strips_corp(self):
        assert normalise_company_name("Microsoft Corporation") == "microsoft"
        assert normalise_company_name("Microsoft Corp.") == "microsoft"

    def test_strips_plc(self):
        assert normalise_company_name("Barclays PLC") == "barclays"
        assert normalise_company_name("Barclays plc") == "barclays"

    def test_strips_ltd(self):
        """Both variants normalise to the same string (dedup works)."""
        assert normalise_company_name("BHP Group Limited") == "bhp group"
        assert normalise_company_name("BHP Group Ltd.") == "bhp group"

    def test_strips_ag(self):
        assert normalise_company_name("Siemens AG") == "siemens"
        assert normalise_company_name("Siemens A.G.") == "siemens"

    def test_strips_nv(self):
        """Both variants normalise to the same string (dedup works)."""
        assert normalise_company_name("ASML Holding N.V.") == "asml holding"
        assert normalise_company_name("ASML Holding NV") == "asml holding"

    def test_strips_spa(self):
        assert normalise_company_name("Ferrari S.p.A.") == "ferrari"
        assert normalise_company_name("Ferrari SpA") == "ferrari"

    def test_strips_group_and_holdings(self):
        assert normalise_company_name("BHP Group") == "bhp"
        # Strips "Corp." first pass; "Group" remains — still matches other variants
        assert normalise_company_name("SoftBank Group Corp.") == "softbank group"

    def test_collapses_whitespace(self):
        assert normalise_company_name("  Apple   Inc.  ") == "apple"

    def test_empty_string(self):
        assert normalise_company_name("") == ""


# ── dollar_volume_usd ────────────────────────────────────────────────────

class TestDollarVolumeUsd:
    """Currency-adjusted dollar volume conversion."""

    def test_usd_passthrough(self):
        assert dollar_volume_usd(1_000_000, "USD") == 1_000_000

    def test_jpy_conversion(self):
        result = dollar_volume_usd(100_000_000, "JPY")
        # JPY rate is 0.0067, so 100M JPY ≈ $670k
        assert 500_000 < result < 1_000_000

    def test_gbp_conversion(self):
        result = dollar_volume_usd(500_000, "GBP")
        # GBP rate is 1.27, so £500k ≈ $635k
        assert 600_000 < result < 700_000

    def test_gbp_pence(self):
        """GBp (pence sterling) is 1/100th of GBP."""
        result = dollar_volume_usd(50_000_000, "GBp")
        # Rate is 0.0127, so 50M pence ≈ $635k
        assert 500_000 < result < 800_000

    def test_none_currency_assumes_usd(self):
        assert dollar_volume_usd(1_000_000, None) == 1_000_000

    def test_unknown_currency_assumes_usd(self):
        assert dollar_volume_usd(1_000_000, "XYZ") == 1_000_000
