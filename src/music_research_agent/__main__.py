"""CLI entry point.

    python -m music_research_agent "Artist Name"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv

from .analysis.engine import AnalysisEngine, SECTIONS
from .assemble import Assembler
from .collect import collect
from .render import render
from .discover import expand
from .search import search_artists
from .triage import triage


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="music_research_agent",
        description="Produce a source-cited A&R screening report on an emerging artist.",
    )
    p.add_argument("artist", nargs="?", default=None,
                   help="Artist name, or a pasted profile URL (Spotify, Deezer, "
                        "YouTube, Apple Music, Last.fm, MusicBrainz)")
    p.add_argument("--search", action="store_true",
                   help="List matching artists instead of researching one")
    p.add_argument("--discover", nargs="+", metavar="SEED",
                   help="Grow a ranked candidate pool from seed artists and stop. "
                        "Costs nothing: expansion and triage use only free APIs")
    p.add_argument("--top", type=int, default=15,
                   help="How many triaged candidates to print (default 15)")
    p.add_argument("--spotify-id", help="Skip resolution and use this Spotify artist ID")
    p.add_argument("--out", type=Path, default=Path("runs"), help="Output directory")
    p.add_argument("--no-cache", action="store_true",
                   help="Re-query every source instead of reusing today's cached evidence")
    p.add_argument("--raw", action="store_true",
                   help="Collect evidence only; skip analysis and skip all model cost")
    parsed = p.parse_args(argv)
    if not parsed.artist and not parsed.discover:
        p.error("give an artist name or URL, or use --discover with seed artists")
    return parsed


async def run_discover(seeds: list[str], top: int) -> int:
    """Expand seeds into candidates and rank them, without spending anything."""
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        print(f"Expanding {len(seeds)} seed(s) across both discovery graphs", file=sys.stderr)
        candidates = await expand(seeds, client)
        if not candidates:
            print("No candidates in the seeds' league. Try a seed with more neighbours.",
                  file=sys.stderr)
            return 1
        print(f"  -> {len(candidates)} candidates in tier; triaging", file=sys.stderr)
        ranked = await triage(candidates, client)

    print(f"\n{len(ranked)} candidates ranked — expansion and triage cost nothing\n")
    print(f"{'artist':<26}{'score':>6}  {'fans':>8} {'listeners':>10}  activity   depth")
    print("-" * 88)
    for entry in ranked[:top]:
        print(entry.line())
    print(f"\nTop reasons:")
    for entry in ranked[:3]:
        print(f"  {entry.name}: {'; '.join(entry.reasons[:2])}")
    print(f"\nReporting the top 10 costs about ${10 * 0.33:.2f}; "
          f"all {len(ranked)} would cost ${len(ranked) * 0.33:.2f}.")
    print("Research one with:  python -m music_research_agent \"<name or URL>\"")
    return 0


async def run_search(query: str) -> int:
    hits = await search_artists(query, limit=10)
    if not hits:
        print(f"No artist matched {query!r}", file=sys.stderr)
        return 1
    print(f"{len(hits)} match(es) — pass a URL to research one without ambiguity:\n")
    for hit in hits:
        print(f"  {hit.label()}")
        print(f"      {hit.link or 'https://www.deezer.com/artist/' + hit.deezer_id}")
    return 0


async def run(args: argparse.Namespace) -> int:
    if args.discover:
        return await run_discover(args.discover, args.top)
    if args.search:
        return await run_search(args.artist)

    started = time.time()
    run_id = uuid.uuid4().hex[:12]

    print(f"Resolving and collecting: {args.artist}", file=sys.stderr)
    bundle = await collect(args.artist, args.spotify_id, use_cache=not args.no_cache)
    identity = bundle.identity

    print(f"  -> {identity.resolved_name} "
          f"({identity.disambiguation_confidence.value} confidence), "
          f"{len(bundle.items)} data points from {', '.join(bundle.sources_used) or 'nothing'}",
          file=sys.stderr)
    for failure in bundle.sources_failed:
        print(f"  !  {failure.source}: {failure.reason}", file=sys.stderr)

    out_dir = args.out / (identity.deezer_id or identity.spotify_id or run_id) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.raw:
        path = out_dir / "evidence.json"
        path.write_text(bundle.model_dump_json(indent=2))
        print(f"\nEvidence written to {path}", file=sys.stderr)
        return 0

    print(f"Analysing {len(SECTIONS)} sections", file=sys.stderr)
    engine = AnalysisEngine(bundle)
    drafts = await engine.run_all()

    report = Assembler(bundle).build(
        drafts, run_id=run_id, duration_s=time.time() - started, cost_usd=engine.cost_usd
    )

    (out_dir / "report.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False)
    )
    (out_dir / "report.md").write_text(render(report))

    ungrounded = report.data_quality.ungrounded_claims
    print(f"\n{out_dir}/report.md", file=sys.stderr)
    print(f"coverage {report.data_quality.coverage_score} · "
          f"{report.duration_s}s · ${report.cost_usd}", file=sys.stderr)
    if ungrounded:
        print(f"\nWARNING: {len(ungrounded)} figure(s) with no source in the evidence:",
              file=sys.stderr)
        for item in ungrounded[:5]:
            print(f"  - {item}", file=sys.stderr)
        return 2
    print("Every figure traces to a source.", file=sys.stderr)
    return 0


def main() -> int:
    load_dotenv()
    try:
        return asyncio.run(run(parse_args()))
    except ValueError as exc:
        # Bad input is the user's to fix, not a crash to debug: print what is
        # wrong and what to do instead, without a stack trace in the way.
        print(f"\n{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
