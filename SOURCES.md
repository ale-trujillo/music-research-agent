# Source feasibility matrix

Probed against the golden set on 2026-09-12. Re-run before trusting any row:
these are third-party APIs and they move.

## Spotify — identity and discography only

App created under the post-2024 restricted regime for new apps.

| Endpoint | Status | Notes |
|---|---|---|
| `search` (artist, track) | ✅ | Returns a **simplified** artist object |
| `GET /artists/{id}` | ⚠️ 200 | Only `id, name, images, uri, href, external_urls`. **No `followers`, `popularity` or `genres`** |
| `GET /artists/{id}/albums` | ✅ | Full discography with release dates (52 for the test artist) |
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

## Pending probes

Last.fm and YouTube are unverified — credentials not yet available. Both are
now load-bearing, not optional (see below).

---

## Where each schema field now comes from

| Need | Original plan | Now |
|---|---|---|
| Identity | Spotify | Spotify search + Deezer |
| Audience size | Spotify `followers` ❌ | **Deezer `nb_fan`** + Last.fm listeners + YouTube subs |
| Popularity | Spotify `popularity` ❌ | Deezer `nb_fan` as proxy |
| Genre | Spotify `genres` ❌ | **Last.fm tags** |
| Discography / recent activity | Spotify albums | Spotify albums ✅ + Deezer albums ✅ |
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
