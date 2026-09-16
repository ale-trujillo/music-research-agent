# Plan, and what shipped

**Owner:** Alejandro Trujillo · **Started:** 12 September 2026 · **MVP:** three days

This is the only planning document. A five-week roadmap preceded it and was
parked on day one when the scope became a three-day MVP; it has been deleted
rather than left to rot, because a plan nobody is following reads as a project
nobody finished.

Every box below was checked against the code, not from memory. Where something
was planned and did not ship, the box stays open and says why. For a tool whose
whole argument is that absence is a finding, a plan that hid its own gaps would
be the wrong first thing to read.

---

## Confirmed spec

| Dimension | Decision |
|---|---|
| User | A&R / signing |
| Artists | **Emerging, in Colombia** |
| Sources | Free official APIs only, no budget |
| Delivery | CLI → `report.json` + `report.md` |
| Architecture | Hybrid: deterministic pipeline, model for the qualitative |
| Scope | All six sections, **each carrying its own confidence** |
| Markets | Colombia, plus an expansion route |
| Traceability | Citations + an anti-hallucination validator |
| Language | English |
| Team | One developer, three days |

The third day bought the validator. At two days it would have shipped as a
warning with nothing behind it; the extra day made it something the report is
actually assembled through.

---

## Acceptance set

The MVP is done when it runs clean over six real emerging Colombian artists. The
list itself lives in `GOLDEN_SET.md`, outside version control — not because the
names are secret, but because the notes next to them are working judgements, not
published claims. What matters about the test design is the profiles it covers:

| Profile | What it tests |
|---|---|
| International presence | The easy case: data in every source |
| Singer-songwriter with press | Narrative and qualitative context |
| **Common name** | Hard disambiguation |
| Unusual name | Exact resolution |
| **Short or ambiguous name** | Likely search collision |
| **Low digital footprint** | Degrading gracefully |

> The three marked are the valuable ones. An agent that only works on artists
> with abundant data is no use for A&R on emerging acts.

---

## The honest tension

**Emerging Colombian artists plus free APIs equals thin reports.** An artist
with 3,000 listeners has Spotify and YouTube, little on Last.fm, nothing on
Bandsintown. The validator leaves **many fields `null`** — that is not the
system failing, it is the system being honest. The alternative, letting the
model fill the gaps with estimates, is the exact thing this design exists to
avoid.

> **Product reframe:** for emerging artists, absent data *is* the A&R signal. An
> artist with no press and no registered shows is a different profile from one
> who has them. The report makes that distinction legible instead of hiding it.

**No validation loop with a real A&R.** The MVP is validated technically — does
it run, does it cite correctly — not for usefulness. Declared debt, and it is
still open.

---

## Day 1 — the spine (citable data, no model)

- [x] Scaffold, venv, `requirements.txt`, `.env.example`
- [x] `schema.py` — the Pydantic contract, which is the product
- [x] `SourceAdapter` base: isolated failure, timeout, retry
- [x] Identity resolution, disambiguation, and a `--spotify-id` override
- [x] `EvidenceBundle` carrying `source` / `url` / `retrieved_at` / `confidence`
      per datum
- [x] Disk cache — `.cache/`, 24h for complete runs, 1h where a source failed,
      `--no-cache` to force a re-query *(planned as day 1, built after the MVP,
      once probing had burned a Spotify allowance)*

**Adapters, and how the plan changed on contact:**

- [x] **Deezer** — unplanned, and now the strongest source here. Unauthenticated,
      unmetered, complete catalogue
- [x] **YouTube Data** — channel, views, recent uploads
- [x] **Last.fm** — tags and similar artists, as expected with holes
- [x] **MusicBrainz** — canonical ID, relations, country
- [x] **Spotify** — demoted to identity anchor only. Apps created under the
      current regime return no followers, popularity or genres, and 403 on batch
      lookup. It was taken out of the fan-out; `SOURCES.md` has the probing
- [ ] **Web search for press and scene context** — never built. There is no free
      API for it worth citing, and an uncited press summary is the kind of claim
      this project refuses to make

## Day 2 — the brain

- [x] Analysis layer where the model sees **only** the bundle and never recalls a
      figure: `positioning` · `comparables` · `markets` · `recent_activity` ·
      `signals` · `ar_summary`
- [x] `confidence` and `evidence_basis` per section
- [ ] Deep-dive sub-agent for press and scene — dropped with the web search it
      depended on

## Day 3 — armour and delivery

- [x] **Anti-hallucination validator.** A cited key that resolves to nothing
      drops the claim and lands in `data_quality.ungrounded_claims`; prose is
      scanned for figures no source returned. It warns and exits 2 rather than
      refusing to write the report, so the reader sees both the report and what
      is wrong with it
- [x] Markdown renderer derived from the JSON, never written alongside it
- [x] Full CLI with `data_quality` visible in the report
- [x] Manual audit of all six → `AUDIT.md`
- [x] README and setup

---

## After the MVP

All of this was listed out of scope and shipped anyway, which is why the
original roadmap stopped being the plan.

- [x] **Web interface** — FastAPI plus a single-page front end: search, artist
      pages, catalogue breakdown, favorites, comparison, discovery
- [x] **Deployed** at [music-research-agent.vercel.app](https://music-research-agent.vercel.app),
      production on a push to `main`
- [x] **Favorites as a time series.** Saving records the figures of the day, so a
      second save produces the first trend line this system has had — the one
      thing no free source exposes
- [x] **Per-visitor favorites.** An opaque id the browser mints and keeps, with
      no account to create. The first design shared one list across the whole
      deployment, which on a public URL meant every visitor read and could
      delete the owner's shortlist
- [x] **Side-by-side comparison** over saved artists, in the web interface
- [x] **Seed-based discovery** with triage ranking, seeded by saved artists and
      by two examples for a visitor who has saved nothing
- [x] **A daily allowance on the paid action.** Report generation is the only
      call that spends money; `FREE_REPORTS_PER_DAY` bounds the day and
      `REPORT_TOKEN` skips it, checked first so the owner never eats a visitor's
      share
- [x] **Durable storage** through Vercel KV or Upstash Redis, with
      `/api/health` reporting `durable_favorites` so the gap is visible rather
      than discovered when a saved artist disappears

---

## Still open

- **No A&R has read a report.** The tool is verified correct, not verified
  useful, and that distinction should travel with any conclusion drawn from this
  repository
- **Live performance data is absent.** Bandsintown returns 403 without granted
  authorisation, Songkick's API programme is closed, and MusicBrainz has no
  meaningful coverage here. Touring is where an emerging artist's traction shows
  first, so this is a real blind spot
- **Trajectory before you started watching.** Favorites accumulate a series from
  the day you save, and nothing recovers what came before without a licensed
  provider
- `GENIUS_ACCESS_TOKEN` sits in `.env.example` and is read by nothing. Genius was
  probed and dropped; the variable should go with it

## Out of scope

Chartmetric · batch screening · TikTok and Instagram · PDF export
