"""
Alpha Vantage financial data tool.
Fetches company overviews, time series price data, and earnings reports
to enrich stories that have a financial angle.
"""

from typing import Any, Optional

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.config import settings
from backend.models.research import RawSource, SourceCredibility, SourceType

log = structlog.get_logger(__name__)

_BASE = settings.alpha_vantage_base_url


class FinancialDataTool:
    """
    Async client for the Alpha Vantage REST API.

    Example::

        tool = FinancialDataTool()
        overview = await tool.get_company_overview("AAPL")
        prices = await tool.get_daily_prices("AAPL", output_size="compact")
    """

    def __init__(self) -> None:
        self._api_key = settings.alpha_vantage_api_key

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=5, max=30),
        reraise=True,
    )
    async def _get(self, params: dict) -> dict[str, Any]:
        params["apikey"] = self._api_key
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(_BASE, params=params)
            response.raise_for_status()
            data = response.json()

        if "Note" in data:
            log.warning("alpha_vantage.rate_limited", note=data["Note"])
        if "Error Message" in data:
            raise ValueError(f"Alpha Vantage error: {data['Error Message']}")

        return data

    async def get_company_overview(self, symbol: str) -> RawSource:
        """
        Fetch fundamental company data (market cap, PE ratio, description, etc.)

        Args:
            symbol: Stock ticker symbol (e.g. "NVDA").

        Returns:
            RawSource containing a human-readable company overview.
        """
        log.info("financial_data.company_overview", symbol=symbol)
        data = await self._get({"function": "OVERVIEW", "symbol": symbol})

        description = data.get("Description", "No description available.")
        name = data.get("Name", symbol)

        # Build a readable content block for the LLM
        metrics = {
            "Market Cap": data.get("MarketCapitalization"),
            "PE Ratio": data.get("PERatio"),
            "EPS": data.get("EPS"),
            "Revenue (TTM)": data.get("RevenueTTM"),
            "Profit Margin": data.get("ProfitMargin"),
            "52-Week High": data.get("52WeekHigh"),
            "52-Week Low": data.get("52WeekLow"),
            "Analyst Target Price": data.get("AnalystTargetPrice"),
            "Sector": data.get("Sector"),
            "Industry": data.get("Industry"),
        }
        metrics_text = "\n".join(
            f"  {k}: {v}" for k, v in metrics.items() if v and v != "None"
        )

        content = f"{name} ({symbol})\n\n{description}\n\nKey Metrics:\n{metrics_text}"

        return RawSource(
            source_type=SourceType.FINANCIAL_DATA,
            url=f"https://finance.yahoo.com/quote/{symbol}",
            title=f"{name} ({symbol}) — Company Overview",
            content=content,
            credibility=SourceCredibility.HIGH,
            relevance_score=0.9,
            metadata=data,
        )

    async def get_daily_prices(
        self,
        symbol: str,
        output_size: str = "compact",  # "compact" = 100 days, "full" = 20 years
    ) -> RawSource:
        """
        Fetch adjusted daily close prices.

        Args:
            symbol: Stock ticker.
            output_size: "compact" (100 data points) or "full" (up to 20 years).

        Returns:
            RawSource with a summary of recent price performance.
        """
        log.info("financial_data.daily_prices", symbol=symbol)
        data = await self._get(
            {
                "function": "TIME_SERIES_DAILY_ADJUSTED",
                "symbol": symbol,
                "outputsize": output_size,
            }
        )

        time_series: dict = data.get("Time Series (Daily)", {})
        dates = sorted(time_series.keys(), reverse=True)[:30]  # Last 30 trading days

        rows = []
        for date in dates:
            day = time_series[date]
            rows.append(
                f"{date}: open={day['1. open']}, high={day['2. high']}, "
                f"low={day['3. low']}, close={day['4. close']}, "
                f"volume={day['6. volume']}"
            )

        content = f"Daily price data for {symbol} (last {len(rows)} trading days):\n" + "\n".join(rows)

        return RawSource(
            source_type=SourceType.FINANCIAL_DATA,
            url=f"https://finance.yahoo.com/quote/{symbol}/history",
            title=f"{symbol} — Daily Price History",
            content=content,
            credibility=SourceCredibility.HIGH,
            relevance_score=0.8,
            metadata={"symbol": symbol, "data_points": len(rows)},
        )

    async def get_earnings(self, symbol: str) -> RawSource:
        """
        Fetch historical earnings (EPS) data.

        Args:
            symbol: Stock ticker.

        Returns:
            RawSource summarising recent quarterly and annual EPS.
        """
        log.info("financial_data.earnings", symbol=symbol)
        data = await self._get({"function": "EARNINGS", "symbol": symbol})

        quarterly = data.get("quarterlyEarnings", [])[:8]  # Last 8 quarters
        annual = data.get("annualEarnings", [])[:5]

        def _format(records: list[dict], label: str) -> str:
            lines = [f"\n{label}:"]
            for r in records:
                lines.append(
                    f"  {r.get('fiscalDateEnding', 'N/A')}: "
                    f"reportedEPS={r.get('reportedEPS', 'N/A')}, "
                    f"estimatedEPS={r.get('estimatedEPS', 'N/A')}, "
                    f"surprise={r.get('surprisePercentage', 'N/A')}%"
                )
            return "\n".join(lines)

        content = (
            f"Earnings data for {symbol}:"
            + _format(quarterly, "Quarterly EPS")
            + _format(annual, "Annual EPS")
        )

        return RawSource(
            source_type=SourceType.FINANCIAL_DATA,
            url=f"https://finance.yahoo.com/quote/{symbol}/financials",
            title=f"{symbol} — Earnings History",
            content=content,
            credibility=SourceCredibility.HIGH,
            relevance_score=0.85,
            metadata={"symbol": symbol},
        )

    async def search_ticker(self, keywords: str) -> list[dict[str, str]]:
        """
        Search for ticker symbols matching a company name.

        Args:
            keywords: Company name or partial ticker.

        Returns:
            List of match dicts with keys: symbol, name, type, region, currency.
        """
        data = await self._get({"function": "SYMBOL_SEARCH", "keywords": keywords})
        return [
            {
                "symbol": m.get("1. symbol", ""),
                "name": m.get("2. name", ""),
                "type": m.get("3. type", ""),
                "region": m.get("4. region", ""),
                "currency": m.get("8. currency", ""),
            }
            for m in data.get("bestMatches", [])
        ]
