# Source feasibility matrix

Probed against the golden set on 2026-09-12. Re-run before trusting any row:
these are third-party APIs and they move.

## Spotify — identity anchor only (demoted 2026-09-13)

Spotify is no longer in the collection fan-out. Its remaining contribution was a
dated discography, and Deezer returns the identical list — 33 releases with
titles, dates and formats — in one unauthenticated call with no quota, where
Spotify needed four paginated calls against an allowance that locks out for
about 22 hours once spent (`retry-after: 79893`).

**Extended quota is not available to a tool like this.** Since 15 May 2025
Spotify accepts requests only from registered companies with a launched service
and **250,000+ monthly active users**. Research and internal tooling do not
qualify, so the constraint is permanent and the fix had to be spending less
rather than asking for more.

It remains the identity anchor in `resolve()`: one search per run, for the
canonical artist ID and profile link.

### What it returned while it was in the fan-out

App created under the post-2024 restricted regime for new apps.

| Endpoint | Status | Notes |
|---|---|---|
| `search` (artist, track) | ✅ | Returns a **simplified** artist object |
| `GET /artists/{id}` | ⚠️ 200 | Only `id, name, images, uri, href, external_urls`. **No `followers`, `popularity` or `genres`** |
| `GET /artists/{id}/albums` | ✅ | Full discography with release dates. **`limit` is hard-capped at 10** -- 11 and above return 400. `offset` paging works, so walk it 10 at a time |
| `GET /artists?ids=` (batch) | ❌ 403 | Forbidden |
| `GET /artists/{id}/top-tracks` | ❌ 403 | Forbidden |
| `GET /artists/{id}/related-artists` | ❌ 403 | Forbidden |

**Consequence:** Spotify is an identity anchor and a discography source. It is
**not** a metrics source. Every follower/popularity/genre field has to come
from somewhere else.

## Deezer — the metrics substitute (no auth at all)

| Endpoint | Status | Gives |
|---|---|---|
| `search/artist` | ✅ | Exact match on all 6 of the golden set |
| `artist/{id}` | ✅ | `nb_fan` (popularity proxy), `nb_album`, link |
| `artist/{id}/albums` | ✅ | Full discography with release dates |
| `artist/{id}/top` | ✅ | Top tracks |

Best source in the stack for this use case, and it needs no credentials.

## MusicBrainz — thin for emerging LatAm artists

Found 1 of 6. For the rest it returned nothing or confidently wrong matches
(a short artist name matched an unrelated act in another country with
`score=100`). Keep it for canonical IDs when it hits; never trust its score
alone for disambiguation.

## Last.fm — listeners everywhere, genre almost nowhere

| Call | Result on the golden set |
|---|---|
| `artist.getInfo` listeners / playcount | ✅ 6 of 6 |
| `artist.getInfo` tags | ⚠️ **2 of 6** |
| `artist.getTopTags` | ❌ 0 of 6 |
| `artist.getSimilar` | ✅ 6 of 6 |
| `bio` | ❌ empty for all 6 |

Genre had to come from Deezer instead. Aggregating tags from an artist's
similar artists was tried as a fallback and produced usable output for only
one of four, with user-tag noise otherwise.

**Similarity scores are not trustworthy at this tier.** One mid-size act came
back at `match=1.0` for three unrelated artists -- co-listening inside a small
shared audience. Last.fm generates comparable *candidates*; something else has
to corroborate them before the report presents them as comparables.

## YouTube — richest traction signal, weakest identity guarantee

Deezer fan counts badly understate reach in this market. The same artists show
one to three orders of magnitude more audience on YouTube. It is the single
most informative source here -- and the most dangerous.

**The failure it nearly caused:** a short artist name matched a channel with
235,000 subscribers and 86M views run by an unrelated producer in another
country. The real artist has about 24. A name-matching adapter would have
published that with a citation attached.

**What makes it safe:** the auto-generated `<Artist> - Topic` channel is built
from the distributor's catalog, so its video titles are the artist's actual
releases. Overlapping those against releases already established by Deezer and
Spotify proves the channel belongs to this artist.

The two channel kinds answer different questions and both are collected:

| Channel | Answers | Counts mean |
|---|---|---|
| `<Artist> - Topic` | Is this really them? | Nothing -- nobody subscribes to catalog channels |
| Artist's own channel | How much reach? | Real traction, once corroborated |

An artist with a catalog channel but no verifiable artist channel is reported
as exactly that. Distributed but not building a YouTube audience is an A&R
signal, not missing data.

---

## Where each schema field now comes from

| Need | Original plan | Now |
|---|---|---|
| Identity | Spotify | Spotify search + Deezer |
| Audience size | Spotify `followers` ❌ | **Deezer `nb_fan`** + Last.fm listeners + YouTube subs |
| Popularity | Spotify `popularity` ❌ | Deezer `nb_fan` as proxy |
| Genre | Spotify `genres` ❌ | **Last.fm tags** |
| Discography / recent activity | Spotify albums | **Deezer albums** — one call, no quota |
| Top tracks | Spotify `top-tracks` ❌ | **Deezer `/top`** ✅ |
| Comparables | Spotify `related-artists` ❌ | **Last.fm `artist.getSimilar`** |

**Last.fm moved from optional to critical**: it is now the only planned source
for genre and for comparables.

---

## Disambiguation: the finding that shapes the resolver

A short artist name returned the target as an exact match, with a globally
famous act carrying a near-identical prefix ranked second at ~200,000x the
audience. **Any resolver that ranks candidates by popularity would have
produced a report on the wrong artist.**

The resolver therefore orders by: exact name match → country signal → audience
size, and surfaces the alternates it rejected in `Identity.alternates_considered`
so a reader can catch a bad resolution.

## Scale reality

Golden set audience sizes on Deezer span roughly 9 to 1,800 fans. These are
genuinely emerging artists, and reports will be sparse. That sparsity is the
A&R signal, not a system failure -- `data_quality` has to make it legible.


## Live performance — no free source (probed 2026-09-14)

| Source | Result |
|---|---|
| Bandsintown | `403` — authorisation required, an arbitrary `app_id` no longer works |
| Songkick | `401` — API key required; the program is closed to new applicants |
| MusicBrainz events | Useless here. A query for an emerging Colombian artist returned the **Taubertal-Festival** in Germany at `score=100`, a textual match on part of the surname with no relation to the artist |

Touring is where an emerging artist's traction tends to appear before it reaches
any streaming figure, so this is the most consequential gap in the source set.

The MusicBrainz result is the fourth time this project has met the same failure:
a confident, high-scoring match on a name that belongs to someone else. The
others were a global star returned for a short artist name, a German subliminal
audio channel returned for a Colombian artist, and a 105-subscriber channel
winning a country match over the artist's real one. Name matching is the
recurring hazard in this domain, and every layer here is built against it.
