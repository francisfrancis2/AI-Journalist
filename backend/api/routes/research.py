"""
Research API routes — on-demand search and data-source endpoints.
Useful for testing individual tools and exploring data before running a full pipeline.
"""

from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.models.research import RawSource
from backend.tools.financial_data import FinancialDataTool
from backend.tools.news_api import NewsAPITool
from backend.tools.rss_parser import RSSParserTool
from backend.tools.web_search import WebSearchTool

log = structlog.get_logger(__name__)
router = APIRouter()

# ── Request / Response Schemas ────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=500)
    max_results: int = Field(10, ge=1, le=20)
    search_depth: str = Field("advanced", pattern="^(basic|advanced)$")
    days: Optional[int] = Field(None, ge=1, le=365)


class NewsSearchRequest(BaseModel):
    query: str = Field(..., min_length=3)
    page_size: int = Field(10, ge=1, le=50)
    from_days_ago: int = Field(30, ge=1, le=365)
    language: str = Field("en", min_length=2, max_length=2)


class FinancialRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10, description="Stock ticker symbol")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/web-search", response_model=list[RawSource])
async def web_search(request: SearchRequest) -> list[RawSource]:
    """
    Execute a Tavily web search and return structured sources.
    Useful for verifying search quality before running a full pipeline.
    """
    tool = WebSearchTool()
    log.info("research.web_search", query=request.query)
    return await tool.search(
        query=request.query,
        max_results=request.max_results,
        search_depth=request.search_depth,
        days=request.days,
    )


@router.post("/news", response_model=list[RawSource])
async def news_search(request: NewsSearchRequest) -> list[RawSource]:
    """
    Search NewsAPI for recent articles on a topic.
    """
    tool = NewsAPITool()
    log.info("research.news_search", query=request.query)
    return await tool.search_everything(
        query=request.query,
        page_size=request.page_size,
        from_days_ago=request.from_days_ago,
        language=request.language,
    )


@router.get("/news/headlines", response_model=list[RawSource])
async def top_headlines(
    query: Optional[str] = Query(None),
    category: Optional[str] = Query(None, pattern="^(business|technology|science|general|health|entertainment|sports)$"),
    country: str = Query("us", min_length=2, max_length=2),
    page_size: int = Query(10, ge=1, le=30),
) -> list[RawSource]:
    """
    Retrieve current top headlines from NewsAPI.
    """
    tool = NewsAPITool()
    return await tool.top_headlines(
        query=query,
        category=category,
        country=country,
        page_size=page_size,
    )


@router.post("/financial/overview", response_model=RawSource)
async def company_overview(request: FinancialRequest) -> RawSource:
    """
    Fetch Alpha Vantage company fundamentals for a stock ticker.
    """
    tool = FinancialDataTool()
    log.info("research.financial_overview", symbol=request.symbol)
    try:
        return await tool.get_company_overview(request.symbol.upper())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/financial/prices", response_model=RawSource)
async def daily_prices(
    request: FinancialRequest,
    output_size: str = Query("compact", pattern="^(compact|full)$"),
) -> RawSource:
    """
    Fetch daily adjusted price history from Alpha Vantage.
    """
    tool = FinancialDataTool()
    try:
        return await tool.get_daily_prices(request.symbol.upper(), output_size=output_size)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/financial/search", response_model=list[dict])
async def ticker_search(
    keywords: str = Query(..., min_length=2),
) -> list[dict]:
    """
    Search for stock ticker symbols by company name.
    """
    tool = FinancialDataTool()
    return await tool.search_ticker(keywords)


@router.get("/rss/fetch", response_model=list[RawSource])
async def fetch_rss_feed(
    url: str = Query(..., description="RSS/Atom feed URL"),
    max_entries: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = Query(None, description="Filter entries by keyword"),
) -> list[RawSource]:
    """
    Fetch and parse a single RSS/Atom feed.
    """
    tool = RSSParserTool()
    log.info("research.rss_fetch", url=url)
    return await tool.fetch_feed(url, max_entries=max_entries, keyword_filter=keyword)


@router.get("/rss/defaults", response_model=list[RawSource])
async def fetch_default_feeds(
    keyword: Optional[str] = Query(None),
    max_per_feed: int = Query(5, ge=1, le=20),
) -> list[RawSource]:
    """
    Poll all default curated RSS feeds with an optional keyword filter.
    """
    tool = RSSParserTool()
    return await tool.fetch_all_default_feeds(
        max_entries_per_feed=max_per_feed,
        keyword_filter=keyword,
    )
