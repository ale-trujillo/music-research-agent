# Music Research Agent

Takes an artist name and produces a structured, source-cited A&R screening
report. Built for **emerging Colombian artists**, where the data is thin and
the failure mode that matters is a confident report about the wrong person.

**Live: [music-research-agent.vercel.app](https://music-research-agent.vercel.app)**
— search, artist pages and discovery work on arrival, discovery running from a
pair of example artists until you save your own to steer it. A comparison needs
two saved. All of that is free. The full report sits behind a button on a shared
allowance of 20 per day, because it is the only action that spends money.

```bash
# By name
python -m music_research_agent "Artist Name"

# By pasted profile URL — Spotify, Deezer, YouTube, Apple Music, Last.fm,
# MusicBrainz. Preferred: the platform already identified the artist, so
# nothing is ranked and nothing can resolve to the wrong person.
python -m music_research_agent "https://open.spotify.com/artist/68LgpW..."

# Find the artist first when the name is ambiguous
python -m music_research_agent --search "akuo"

# runs/<artist-id>/<run-id>/report.json   the contract
# runs/<artist-id>/<run-id>/report.md     the readable version
```

Search is proxied live against Deezer rather than served from an index of our
own. An index has to be populated and kept fresh, and the open alternative —
MusicBrainz — covers emerging Latin American artists poorly: one of six on the
acceptance set. Deezer's catalogue is complete, current, unauthenticated and
unmetered, so the catalogue stays its problem. Results are re-ranked by name
match before audience size, which is why typing a small artist's exact name
surfaces them above the famous act they resemble.

Roughly 35-70 seconds and $0.30-0.50 per report.

## Example output

[`examples/report-ela-taubert.md`](examples/report-ela-taubert.md) — real,
unedited output from one command. See [`examples/`](examples/) for what to look
at in it.

## Setup

```bash
python -m venv .venv && ./.venv/bin/pip install -e .
cp .env.example .env      # then fill it in
```

All sources are free. Only `ANTHROPIC_API_KEY` costs money — every music API
in the stack bills nothing.

| Source | Credential | Notes |
|---|---|---|
| Deezer | none | Strongest source here. Audience size and genre |
| MusicBrainz | none | User-Agent only |
| Spotify | Client ID + Secret | Identity anchor only — one search per run |
| Last.fm | API key | last.fm/api/account/create |
| YouTube | API key | console.cloud.google.com, 10,000 units/day |

## What it does

```
resolve → collect → analyse → assemble → render
```

**Resolve** ranks candidates by name match, never by audience size. Searching a
short artist name returns the target alongside a globally famous act with
200,000x the following, and a popularity-ranked resolver reports confidently on
the wrong person. Rejected candidates travel with the report.

**Collect** fans out to every source. Sources that join on stable IDs run first;
sources that identify an artist only by display name run second and must
corroborate a candidate against releases the first wave established. A source
returning nothing is recorded, cited, and shown to the model — for an emerging
artist, absence is a finding, not a gap.

**Analyse** gives the model the evidence and nothing else. It cannot write a
citation: it returns evidence keys, and the assembler resolves them. Six
sections run concurrently.

**Assemble** enforces grounding. A key that resolves to nothing drops the
claim's confidence and lands in `data_quality.ungrounded_claims`. Prose is
scanned for figures no source returned, since a number can be invented inside a
sentence without citing anything.

**Render** derives the Markdown from the JSON — never written alongside it.

## Reading a report

`data_quality` is a section of the report, not debug output. These artists have
audiences in the hundreds; the honest account of what could not be established
is often the most decision-relevant thing on the page.

Confidence: `●●●` from an official API · `●●○` derived or secondary ·
`●○○` proxy or inference from sparse evidence · `○○○` no evidence found.

A claim with no citation is tagged `*(inference)*`. A `WARNING` on exit means
the report shipped with a figure no source returned; exit code is 2.

## Known constraints

- **Spotify is an identity anchor and nothing more.** Apps created under the
  current regime return an artist object with no followers, popularity or
  genres, and 403 on batch lookup, top-tracks and related-artists. The
  discography it could still serve costs four paginated calls (album `limit` is
  capped at 10) against an allowance that returns `retry-after` of roughly 22
  hours once spent. Deezer returns the same discography in one unauthenticated
  call, so Spotify was taken out of the fan-out.
- **Extended quota mode cannot fix this.** Since 15 May 2025 Spotify grants it
  only to registered companies with a launched service and 250,000+ monthly
  active users. A research tool will not qualify; plan around the limit.
- **Evidence is cached to disk** (`.cache/`, 24h for complete runs, 1h for runs
  where a source failed). Iterating on prompts re-collects the same artist
  repeatedly, which is how this project spent its own Spotify allowance.
  `--no-cache` forces a re-query.
- **YouTube** costs ~105 quota units per artist against 10,000/day — about 95
  artists. `search.list` costs 100 and `playlistItems.list` costs 1, which is
  why channel uploads are read from the playlist rather than searched.
- **Last.fm similarity is unreliable at this scale.** A mid-size act came back
  at `match=1.0` for three unrelated artists — co-listening inside a small
  shared audience. It generates candidates; something else must corroborate.
- **MusicBrainz covers emerging Latin American artists poorly** — one of six on
  the acceptance set, with confident wrong matches for the rest.
- Sections run concurrently and cannot see each other, so a point may be made
  twice across sections. That is the price of 35 seconds instead of four
  minutes.

## What a solid version would require

These are not a backlog. Each one is a property of what public data can do, and
each was established by trying rather than assumed.

**Trajectory, not snapshots.** Every free source returns a point-in-time figure:
followers now, listeners now. Nothing exposes history, which is why every report
says momentum describes release cadence rather than audience movement. Saved
favorites record their figures on each save, so a series accumulates — but it
starts the day you start watching, and no amount of engineering recovers what
came before. Reading an artist's inflection points, the moment a trajectory bent,
needs either months of your own tracking or a licensed data provider that kept
the history for you. This is the gap that most limits the product, and it cannot
be closed retroactively.

**Audience demographics and geography.** No public source exposes listeners by
country or city, let alone by age or gender. Not an oversight: it is personal
data under GDPR and Colombia's Ley 1581, and commercially sensitive besides — a
label would pay to see a competitor's conversion. Everything the reports say
about markets is a proxy inferred from artist adjacency, and the reports label it
as such. Real geography comes from the artist's own platform analytics, which
requires their consent, or from a licensed aggregator, which requires a budget.
There is no third path, and a tool that implied otherwise would be lying.

**Live performance.** Absent entirely, and not for want of trying. Bandsintown
returns 403 without granted authorisation, Songkick's API program is closed, and
MusicBrainz has no meaningful coverage of emerging Latin American artists — a
query for one returned a German festival with a similar name at a perfect match
score. Touring is where an emerging artist's real traction shows first, so this
is a substantive blind spot rather than a missing nice-to-have.

**Verified correct, not verified useful.** The acceptance audit measured whether
the tool is accurate, reproducible and honest about its gaps. It could not
measure whether an A&R reader finds a report worth their time, because no A&R
reader has reviewed one. That distinction should travel with any conclusion drawn
from this repository.

## Running the interface

```bash
pip install -e ".[web]"
uvicorn music_research_agent.api:app --reload
```

Search, an artist page, saved favorites with movement over time, a side-by-side
comparison, and seed-based discovery. The full report sits behind an explicit
button — it is the only part of the system that spends money.

## Deploying

```bash
vercel login && vercel        # first deploy, and preview builds thereafter
git push origin main          # production: GitHub triggers it, ~30 seconds
```

Set the source credentials as environment variables in the Vercel project —
`ANTHROPIC_API_KEY` is the only one that costs anything; everything else is a
free key. `GET /api/health` reports which of them arrived and what the
deployment can do without them.

**Report generation is the only paid action, and a public URL needs a control on
it.** A shared daily allowance (`FREE_REPORTS_PER_DAY`, default 20) lets a visitor
see the thing work without a password on the one button worth pressing, and
bounds the day's exposure whatever happens. `REPORT_TOKEN` skips the allowance,
and is checked first so the owner never consumes a visitor's share. Everything
else — search, artist pages, catalogue breakdown, comparison, discovery — stays
open and costs nothing.

**Favorites need a key-value store.** A deployed function has no durable
filesystem, so add Vercel KV or an Upstash Redis project and the store picks it
up from either service's variable names. Without one, favorites fall back to
`/tmp` and last only as long as the instance — `/api/health` reports
`durable_favorites: false` so the gap is visible rather than discovered when a
saved artist disappears.

**Favorites are per visitor, and there is no account to create.** The browser
mints an opaque id, keeps it in `localStorage` and sends it as `x-visitor`. The
server uses it only to tell two visitors apart and never learns who anyone is.
The first design kept a single list for the whole deployment, which on a public
URL meant every visitor read — and could delete from — the owner's shortlist; a
list of artists someone is quietly evaluating is exactly the thing they would
not publish. A request arriving without an id reads an empty list and cannot
write at all, rather than falling into a shared one. The trade for needing no
sign-up is that the id is the only handle on a list: clearing site data, or
opening the page in another browser, starts a fresh one.

Reports take 35 to 80 seconds. Vercel's Hobby plan allows 300, which is why
serverless works here at all — but Hobby is non-commercial, so a tool a team
depends on belongs on a paid plan or a small container elsewhere.

## Tests

```bash
pytest tests/
```

The suite is built around the failures this project actually hit, because they
are the ones that recur: resolving a short artist name to a famous act instead
of the target, a validator crying wolf on date fragments until nobody reads it,
and an unreachable source scoring identically to an artist with nothing to show.

The newest set covers the one that reached production. Favorites were written to
a bucket shared by every visitor whenever the header identifying them was
missing, because an absent id was read as a default rather than as an answer.
One tab left open across a deploy was enough to put a private shortlist on a
public endpoint, and the symptom looked like favorites disappearing.

## More

`SOURCES.md` — the feasibility matrix, written from probing rather than docs.
`AUDIT.md` — acceptance results, including the two criteria that could not be
tested and why. `PLAN.md` — the plan and what shipped, with every box checked
against the code and the ones that did not ship left open with the reason.
