# AI Journalist

An autonomous AI system that researches topics across the web, develops documentary angles and
chapter structures, evaluates them editorially, and produces production-ready scripts for
5, 10, or 15 minute documentary films.

## Architecture

```
User Topic
    │
    ▼
┌──────────────────────────────────────────────────────┐
│  LangGraph StateGraph (journalist_graph)             │
│                                                      │
│  Research Agent ──► Angles & Hooks ──► Chapter Writer│
│          │                  │                 │      │
│          │        angle selection pause       ▼      │
│          │                  └────► Chief Editor       │
│          │                            │               │
│          │                            ▼               │
│          └────────────────────► Scriptwriter          │
│                                       │               │
│                                       ▼               │
│                         Chief Editor Script Audit     │
│                                       │               │
│                         optional targeted rewrite     │
└──────────────────────────────────────────────────────┘
                              │
                              ▼
                    FinalScript (database JSON)
```

### Agents
| Agent | Role |
|---|---|
| **ResearchAgent** | Plans benchmark-style research lanes, routes source tools, scrapes selected evidence, and packages sources |
| **AnglesAndHooksAgent** | Synthesizes research into key findings, producer-selectable angles, and hook direction |
| **ChapterWriterAgent** | Converts approved ideation into duration-fit chapter and act structures |
| **ChiefEditorEvaluatorAgent** | Reviews plans, runs benchmark analytics, audits scripts, and performs targeted rewrites |
| **ScriptwriterAgent** | Writes full narrator script act-by-act from the approved structure and research package |
| **CorpusBuilderAgent** | Admin/support agent that builds and refreshes benchmark reference corpora |

### Stack
- **LLM**: Anthropic `claude-opus-4-6` via `langchain-anthropic`
- **Orchestration**: LangGraph `StateGraph`
- **Web Search**: Tavily API
- **Web Scraping**: Playwright (headless Chromium)
- **Data Sources**: NewsAPI, Alpha Vantage, RSS/Atom feeds including Google News RSS
- **Backend**: FastAPI + SQLAlchemy (async) + PostgreSQL
- **Storage**: PostgreSQL JSON columns for generated scripts and pipeline artifacts
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
docker compose up db -d
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
│   ├── agents/          # LangGraph agents and embedded skills
│   │   ├── research.py
│   │   ├── angles_and_hooks.py
│   │   ├── chapter_writer.py
│   │   ├── chief_editor_evaluator.py
│   │   ├── scriptwriter.py
│   │   └── corpus_builder.py
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
| `GET` | `/api/v1/stories/{id}/events` | Stream live story status updates |
| `GET` | `/api/v1/stories/{id}/script` | Retrieve final script |
| `POST` | `/api/v1/stories/{id}/rewrite` | Run an audit-guided script rewrite |
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
| `GET` | `/api/v1/research/rss/defaults` | Poll all default feeds, including Google News RSS |

## Configuration

All settings live in `backend/config.py` and are loaded from `.env`:

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key |
| `TAVILY_API_KEY` | Tavily search API key |
| `NEWS_API_KEY` | NewsAPI key |
| `RSS_FETCH_TIMEOUT_SECONDS` | Per-feed RSS timeout in seconds (default: 8) |
| `ALPHA_VANTAGE_API_KEY` | Alpha Vantage key |
| `DATABASE_URL` | PostgreSQL connection string |
| `RUN_MIGRATIONS_ON_STARTUP` | Apply Alembic migrations when the backend starts (default: true) |
| `JWT_SECRET_KEY` | JWT signing secret |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | Optional first admin account; created with `must_change_password=true` and never reset automatically after creation |
| `CLAUDE_MODEL` | Defaults to `claude-sonnet-4-6` |
| `MAX_RESEARCH_ITERATIONS` | How many times the researcher can re-run (default: 3) |
| `MAX_REFINEMENT_CYCLES` | Story-plan refinement budget before scripting (default: 2) |
| `QUALITY_SCORE_THRESHOLD` | Minimum score (0–1) to approve a storyline (default: 0.70) |

### Database setup by environment

- Local Docker: `docker-compose.yml` forces the backend to use the bundled Postgres container at `db:5432`, so Neon is not needed for normal local Docker development.
- Local non-Docker backend: `.env` can still point to a local Postgres instance such as `postgresql://aijournalist:secret@localhost:5432/aijournalist`.
- Fly deployment: use a separate `.env.fly` file or exported shell variables for deploy secrets. `scripts/fly-deploy.sh` prefers `.env.fly` when present and rejects obviously local `DATABASE_URL` values. Set Fly `DATABASE_URL` to your hosted Postgres provider, for example Neon.
