# Music Research Agent

Takes an artist name and produces a structured, source-cited A&R screening
report. Built for **emerging Colombian artists**, where the data is thin and
the failure mode that matters is a confident report about the wrong person.

```bash
python -m music_research_agent "Artist Name"
# runs/<artist-id>/<run-id>/report.json   the contract
# runs/<artist-id>/<run-id>/report.md     the readable version
```

Roughly 35-70 seconds and $0.30-0.50 per report.

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
| Spotify | Client ID + Secret | developer.spotify.com/dashboard |
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

- **Spotify apps created under the current regime** return an artist object with
  no followers, popularity, or genres, and 403 on batch lookup, top-tracks and
  related-artists. It is an identity anchor and discography source only. Album
  `limit` is hard-capped at 10; offset paging works.
- **Spotify rate limits are unforgiving in development mode.** Exhausting the
  daily allowance returns `retry-after` of roughly 22 hours.
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

See `SOURCES.md` for the full feasibility matrix and `PLAN.md` for scope.
