# Per-Script Cost Model Assumptions

This model is based on the current application code in `backend/agents/` and `backend/tools/`.

## Pipeline assumptions

- One completed script normally triggers:
- 1 Anthropic call in `ResearcherAgent` for query planning
- 1 Anthropic call in `AnalystAgent`
- 1 Anthropic call in `StorylineCreatorAgent`
- 1 Anthropic call in `EvaluatorAgent`
- 3 to 6 Anthropic calls in `ScriptwriterAgent`, depending on number of acts

## Search and data-source assumptions

- Tavily:
- Current code uses `search_depth="advanced"` in config
- Typical story assumes 8 searches total
- At advanced depth, each search costs 2 Tavily credits

- NewsAPI:
- Current code searches the first 2 primary queries only
- Typical story assumes 2 NewsAPI requests
- The CSV uses overage pricing only, not a share of the monthly base subscription

- Alpha Vantage:
- Current code may call up to 2 endpoints per symbol:
- `get_company_overview`
- `get_daily_prices`
- Typical story assumes 1 symbol = 2 calls
- High story assumes 3 symbols = 6 calls
- Alpha Vantage pricing is better treated as a monthly fixed cost:
- `$49.99/month` for the smallest listed premium plan
- The CSV therefore models Alpha Vantage as `49.99 / scripts_per_month`
- This avoids inventing a request-level overage price that Alpha Vantage does not publish

## Storage assumptions

- S3:
- 1 JSON upload per completed story
- 300 KB object retained for 1 month
- No meaningful data transfer cost at this size

## Pricing sources used

- Anthropic pricing:
- https://docs.anthropic.com/en/docs/about-claude/pricing

- Tavily pricing and credits:
- https://docs.tavily.com/guides/api-credits

- NewsAPI pricing:
- https://newsapi.org/pricing

- Alpha Vantage premium pricing:
- https://www.alphavantage.co/premium/

- AWS S3 pricing:
- https://aws.amazon.com/s3/pricing/

## Important caveat

This model is a cash-cost estimate per completed script, not full profitability accounting.

It does not include:

- engineering time
- hosting for FastAPI / Next.js / database
- CPU or RAM consumed by Playwright scrapes
- networking
- observability
- retries due to failures
- unused monthly subscription minimums

If you want a fully loaded unit economics model next, add fixed monthly costs and divide by expected scripts per month.
