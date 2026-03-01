"""Company search and add endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import Company, User
from app.db.session import get_db
from app.ingest.company_lookup import (
    SECTickerCache,
    enrich_with_yfinance_async,
    map_country_to_iso2,
    map_sector_to_gics,
)

router = APIRouter(prefix="/v1/companies", tags=["company-search"])


# ── Pydantic schemas ────────────────────────────────────────────────────────


class SearchResult(BaseModel):
    ticker: str
    name: str
    cik: str | None = None
    country_iso2: str = "US"
    gics_code: str = ""
    market_cap: float | None = None
    already_added: bool = False


class AddCompanyEntry(BaseModel):
    ticker: str
    name: str
    cik: str | None = None
    country_iso2: str = "US"
    gics_code: str = ""


class AddCompaniesRequest(BaseModel):
    companies: list[AddCompanyEntry]


class AddCompaniesResponse(BaseModel):
    added: int
    skipped: int
    tickers_added: list[str]
    tickers_skipped: list[str]


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/search", response_model=list[SearchResult])
async def search_companies(
    q: str = Query(..., min_length=1, max_length=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Search for companies to add. Searches SEC tickers (~13K US companies)."""
    sec_results = await SECTickerCache.search(q, limit=20)

    # Check which are already in our DB
    existing_tickers: set[str] = set()
    if sec_results:
        tickers = [r.ticker for r in sec_results]
        result = await db.execute(
            select(Company.ticker).where(Company.ticker.in_(tickers))
        )
        existing_tickers = {row[0] for row in result.all()}

    return [
        SearchResult(
            ticker=entry.ticker,
            name=entry.name,
            cik=entry.cik,
            country_iso2="US",
            already_added=entry.ticker in existing_tickers,
        )
        for entry in sec_results
    ]


@router.get("/enrich", response_model=SearchResult)
async def enrich_company(
    ticker: str = Query(..., min_length=1, max_length=20),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch yfinance metadata for a specific ticker.

    Use for international tickers or to get GICS/market cap for a US ticker.
    """
    info = await enrich_with_yfinance_async(ticker)
    if info is None:
        raise HTTPException(status_code=404, detail=f"No data found for ticker '{ticker}'")

    # Check SEC for CIK (US companies)
    cik = await SECTickerCache.lookup_cik(ticker)

    # Check if already in DB
    result = await db.execute(
        select(Company.ticker).where(Company.ticker == ticker.upper())
    )
    already_added = result.scalar_one_or_none() is not None

    country_iso2 = "US" if cik else map_country_to_iso2(info.get("country"))

    return SearchResult(
        ticker=ticker.upper(),
        name=info.get("name") or ticker.upper(),
        cik=cik,
        country_iso2=country_iso2,
        gics_code=map_sector_to_gics(info.get("sector")),
        market_cap=info.get("market_cap"),
        already_added=already_added,
    )


@router.post("/add", response_model=AddCompaniesResponse)
async def add_companies(
    body: AddCompaniesRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add companies to the database.

    Does not ingest or score — user must run company_refresh afterwards.
    """
    added: list[str] = []
    skipped: list[str] = []

    # Collect existing CIKs to avoid unique constraint violations (dual share classes)
    result = await db.execute(
        select(Company.cik).where(Company.cik.isnot(None))
    )
    existing_ciks = {row[0] for row in result.all()}

    for entry in body.companies:
        ticker_upper = entry.ticker.upper()
        result = await db.execute(
            select(Company).where(Company.ticker == ticker_upper)
        )
        if result.scalar_one_or_none() is not None:
            skipped.append(ticker_upper)
            continue

        # Skip if another company with this CIK already exists
        # (e.g. GOOG vs GOOGL — same company, different share class)
        cik = entry.cik
        if cik and cik in existing_ciks:
            skipped.append(ticker_upper)
            continue

        company = Company(
            ticker=ticker_upper,
            cik=cik,
            name=entry.name,
            gics_code=entry.gics_code,
            country_iso2=entry.country_iso2,
            config_version="user_added",
        )
        db.add(company)
        if cik:
            existing_ciks.add(cik)
        added.append(ticker_upper)

    await db.commit()

    return AddCompaniesResponse(
        added=len(added),
        skipped=len(skipped),
        tickers_added=added,
        tickers_skipped=skipped,
    )
