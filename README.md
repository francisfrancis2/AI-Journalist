# AI Journalist

An autonomous AI system that researches topics across the web, develops documentary storylines,
evaluates them editorially, and produces production-ready scripts for 10–15 minute documentary films
in the style of Business Insider, Bloomberg, and CNBC Make It.

## Architecture

```
User Topic
    │
    ▼
┌──────────────────────────────────────────────────────┐
│  LangGraph StateGraph (journalist_graph)             │
│                                                      │
│  Researcher ──► Analyst ──► Storyline Creator        │
│      ▲                           │                   │
│      │                           ▼                   │
│      └──── (needs more data) Evaluator               │
│                        │          │                  │
│                        │  (approved)                 │
│                        ▼          ▼                  │
│               Refine Storyline  Scriptwriter         │
└──────────────────────────────────────────────────────┘
                              │
                              ▼
                    FinalScript (JSON + S3)
```

### Agents
| Agent | Role |
|---|---|
| **Researcher** | Tavily web search + NewsAPI + RSS polling + Playwright scraping + Alpha Vantage financial data |
| **Analyst** | Synthesises sources into key findings, narrative angles, notable quotes |
| **Storyline Creator** | Generates 2 multi-act documentary proposals; selects the strongest |
| **Evaluator** | Scores across 6 editorial criteria; approves or requests refinement |
| **Scriptwriter** | Writes full narrator script act-by-act with b-roll cues and interview prompts |

### Stack
- **LLM**: Anthropic `claude-opus-4-6` via `langchain-anthropic`
- **Orchestration**: LangGraph `StateGraph`
- **Web Search**: Tavily API
- **Web Scraping**: Playwright (headless Chromium)
- **Data Sources**: NewsAPI, Alpha Vantage, RSS/Atom feeds
- **Backend**: FastAPI + SQLAlchemy (async) + PostgreSQL
- **Storage**: AWS S3 (LocalStack for local dev)
- **Frontend**: Next.js 15 + React Query + Tailwind CSS

---

## Quick Start

### 1. Prerequisites
- Python 3.11+
- Node.js 20+
- Docker + Docker Compose
- API keys for Anthropic, Tavily, NewsAPI, Alpha Vantage

### 2. Environment Setup
```bash
cp .env.example .env
# Edit .env and add your API keys
```

### 3. Start Infrastructure
```bash
docker compose up db localstack -d
```

### 4. Install & Run Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

uvicorn backend.api.main:app --reload --port 8000
```

### 5. Install & Run Frontend
```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) — submit a topic and watch the pipeline run.

API docs available at [http://localhost:8000/docs](http://localhost:8000/docs).

---

## Running with Docker Compose (full stack)
```bash
docker compose up --build
```

---

## Project Structure

```
AI-Journalist/
├── backend/
│   ├── agents/          # Five LangGraph agent nodes
│   │   ├── researcher.py
│   │   ├── analyst.py
│   │   ├── storyline_creator.py
│   │   ├── evaluator.py
│   │   └── scriptwriter.py
│   ├── graph/
│   │   ├── state.py             # JournalistState TypedDict
│   │   └── journalist_graph.py  # StateGraph assembly + routing
│   ├── tools/           # Data source connectors
│   │   ├── web_search.py    # Tavily
│   │   ├── web_scraper.py   # Playwright
│   │   ├── news_api.py      # NewsAPI
│   │   ├── financial_data.py # Alpha Vantage
│   │   └── rss_parser.py    # feedparser
│   ├── models/
│   │   ├── story.py     # Story ORM + Pydantic schemas
│   │   └── research.py  # Research/Analysis pipeline models
│   ├── api/
│   │   ├── main.py      # FastAPI app factory
│   │   └── routes/
│   │       ├── stories.py   # CRUD + pipeline trigger
│   │       └── research.py  # On-demand tool endpoints
│   ├── db/database.py   # Async SQLAlchemy engine
│   └── config.py        # Pydantic Settings
└── frontend/
    ├── app/
    │   ├── page.tsx         # Dashboard + story creation
    │   └── stories/page.tsx # Story list + script detail
    ├── components/
    │   ├── StoryCard.tsx    # Story status card
    │   └── ScriptViewer.tsx # Full script reader UI
    └── lib/api.ts           # Typed axios API client
```

## API Endpoints

### Stories
| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/stories/` | Create story + launch pipeline |
| `GET` | `/api/v1/stories/` | List all stories |
| `GET` | `/api/v1/stories/{id}` | Get story details + status |
| `GET` | `/api/v1/stories/{id}/script` | Retrieve final script |
| `DELETE` | `/api/v1/stories/{id}` | Delete a story |

### Research Tools
| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/research/web-search` | Tavily search |
| `POST` | `/api/v1/research/news` | NewsAPI search |
| `GET` | `/api/v1/research/news/headlines` | Top headlines |
| `POST` | `/api/v1/research/financial/overview` | Alpha Vantage company overview |
| `POST` | `/api/v1/research/financial/prices` | Stock price history |
| `GET` | `/api/v1/research/financial/search` | Ticker symbol search |
| `GET` | `/api/v1/research/rss/fetch` | Parse a single RSS feed |
| `GET` | `/api/v1/research/rss/defaults` | Poll all default feeds |

## Configuration

All settings live in `backend/config.py` and are loaded from `.env`:

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key |
| `TAVILY_API_KEY` | Tavily search API key |
| `NEWS_API_KEY` | NewsAPI key |
| `ALPHA_VANTAGE_API_KEY` | Alpha Vantage key |
| `DATABASE_URL` | PostgreSQL connection string |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | AWS credentials (use `test`/`test` with LocalStack) |
| `CLAUDE_MODEL` | Defaults to `claude-opus-4-6` |
| `MAX_RESEARCH_ITERATIONS` | How many times the researcher can re-run (default: 3) |
| `MAX_REFINEMENT_CYCLES` | Evaluator→refinement loops before forcing output (default: 2) |
| `QUALITY_SCORE_THRESHOLD` | Minimum score (0–1) to approve a storyline (default: 0.75) |
