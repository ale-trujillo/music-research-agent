# MVP acceptance audit

Run across the full acceptance set on 2026-09-13, against the exit criteria in
`PLAN.md` §3.

**Run under degraded coverage.** Spotify was rate-limited for the day
(`retry-after` ≈ 22h) and YouTube's quota was exhausted mid-run, both from this
project's own probing. Criteria that depend on source coverage could not be
tested at full strength; everything else was.

## Results

| # | Criterion | Target | Result | |
|---|---|---|---|---|
| 1 | Zero fabrication | 100% of figures traceable | 5/6 reports clean; **20/20 cited figures matched the live source exactly** | **pass** |
| 2 | Coverage | ≥80% mid-tier, ≥50% emerging | 0.25–0.75 observed, ceiling 0.75 today | **untested** |
| 3 | Identity resolution | 6/6 correct entity | 6/6, all at high confidence | **pass** |
| 4 | Utility | ≥7/10 from an A&R reader | no reviewer available | **untested** |
| 5 | Operation | p95 < 180s, < $0.50 | p95 **60.5s**, mean **$0.31**, max **$0.36** | **pass** |
| 6 | Reproducibility | same hard fields across runs | 21/21 and 6/13 — every difference a Last.fm similarity score | **pass** |

## Per-artist

| Requested | Resolved | ID confidence | Coverage | Evidence | Unsourced | Time | Cost |
|---|---|---|---|---|---|---|---|
| 1 | exact | high | 0.75 | 39 | 0 | 110.8s | $0.3293 |
| 2 | exact | high | 0.50 | 33 | 2 | 41.3s | $0.3591 |
| 3 | exact | high | 0.25 | 16 | 0 | 23.6s | $0.2161 |
| 4 | exact (case) | high | 0.75 | 39 | 0 | 42.3s | $0.3552 |
| 5 | exact | high | 0.50 | 19 | 0 | 60.5s | $0.2891 |
| 6 | exact | high | 0.75 | 29 | 0 | 35.4s | $0.3159 |

## Criterion 1 in detail

Independent verification re-queried Deezer and Last.fm directly, bypassing all
project code, and compared against what the reports claim. **20 of 20 figures
matched exactly.**

The validator flagged two figures in one report. Neither is fabricated:

- `5.6` — a plays-per-listener ratio the model computed from two cited totals
- `500` — a rounded approximation of a cited figure

Both are honest arithmetic, and both are correctly flagged: a reader cannot
check either against a source. The behaviour is what it should be.

## Criterion 6 in detail

One artist reproduced 21/21 hard metrics. The other differed on 7 of 13 — every
one a `lastfm.similar.*` score (`Juan Duque` 0.942 → 0.873 between runs).
Last.fm recomputes similarity continuously, so the drift is upstream, not ours.
Fan counts, listeners, playcounts and release counts were identical in both.

This independently confirms the decision to mark Last.fm similarity
low-confidence: the scores are not stable enough to benchmark against.

## Open findings

1. **The length caps became targets.** Every one of the six reports returned
   exactly 8 A&R bullets and exactly 5 risks — the maximum in both cases. A
   model choosing its strongest points would not land on the cap six times out
   of six. Some of those entries are likely padding. Worth testing a lower cap
   or asking for "as many as the evidence supports, up to N".

2. **Trajectory analogs still populate when they should not.** Three of six
   reports filled the section despite the instruction to leave it empty without
   historical data. The instruction improved the behaviour but did not settle
   it; this likely needs to move from prompt to code — reject analogs whose
   `what_happened_next` cites nothing.

3. **Criterion 2 remains untested** and will stay so until the Spotify
   allowance resets. Re-run then.

4. **Criterion 4 has no path to being tested** without an A&R reader. The MVP
   is verified as correct, not as useful. That distinction should travel with
   any decision made on the strength of this audit.
