"""
CLI script to build the benchmark reference corpus.

Run once before using the benchmarker, then re-run periodically to refresh.

Usage:
    python -m backend.scripts.build_corpus                 # default combined corpus
    python -m backend.scripts.build_corpus --docs 40       # docs per component corpus
    python -m backend.scripts.build_corpus --library vox   # rebuild one component corpus
"""

import argparse
import asyncio
import os
import sys

# Patch env before importing backend modules
os.environ.setdefault("DATABASE_URL", os.getenv("DATABASE_URL", ""))


async def main(max_docs: int, library_key: str) -> None:
    from backend.models import benchmark as _bm  # noqa: F401 — register ORM models
    from backend.services.benchmarking import run_benchmark_rebuild

    print(f"Building benchmark corpus '{library_key}' with up to {max_docs} docs per library...")
    print("Ensure database migrations are current first: alembic upgrade head")

    await run_benchmark_rebuild(library_key=library_key, max_docs=max_docs)

    print("\n✓ Corpus rebuild completed")
    print("\nBenchmarker is ready. Every new story will now be scored against benchmark patterns.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build benchmark corpus")
    parser.add_argument("--docs", type=int, default=25, help="Number of docs per component library (default: 25)")
    parser.add_argument(
        "--library",
        default="combined",
        help="Library to rebuild: combined, bi, cnbc, vox, or jh (default: combined)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.docs, args.library))
