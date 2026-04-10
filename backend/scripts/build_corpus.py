"""
CLI script to build the BI benchmark reference corpus.

Run once before using the benchmarker, then re-run periodically to refresh.

Usage:
    python -m backend.scripts.build_corpus            # default 25 docs
    python -m backend.scripts.build_corpus --docs 40  # more docs = better patterns
"""

import argparse
import asyncio
import os
import sys

# Patch env before importing backend modules
os.environ.setdefault("DATABASE_URL", os.getenv("DATABASE_URL", ""))


async def main(max_docs: int) -> None:
    from backend.db.database import AsyncSessionLocal, create_tables
    from backend.models import benchmark as _bm  # noqa: F401 — register ORM models
    from backend.agents.corpus_builder import CorpusBuilderAgent

    print(f"Building BI corpus with up to {max_docs} documentaries...")

    await create_tables()

    async with AsyncSessionLocal() as db:
        agent = CorpusBuilderAgent(db)
        library = await agent.build(max_docs=max_docs)

    print(f"\n✓ Corpus built successfully")
    print(f"  Documents processed : {library.doc_count}")
    print(f"  Avg act count       : {library.avg_act_count:.1f}")
    print(f"  Avg act duration    : {library.avg_act_duration_seconds:.0f}s")
    print(f"  Avg stats per doc   : {library.avg_stat_count:.1f}")
    print(f"  Pattern cache       : backend/data/bi_patterns.json")
    print(f"\nBenchmarker is ready. Every new story will now be scored against BI patterns.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build BI benchmark corpus")
    parser.add_argument("--docs", type=int, default=25, help="Number of BI docs to fetch (default: 25)")
    args = parser.parse_args()
    asyncio.run(main(args.docs))
