"""Markdown rendering. Derived from the JSON, never written alongside it.

Data quality leads rather than trails. For an artist this small the honest
account of what could not be established is often the most decision-relevant
thing on the page, and burying it at the bottom would misrepresent the report.
"""

from __future__ import annotations

from .schema import ArtistReport, Claim, Confidence

MARK = {
    Confidence.HIGH: "●●●",
    Confidence.MEDIUM: "●●○",
    Confidence.LOW: "●○○",
    Confidence.ABSENT: "○○○",
}


def _claim(c: Claim) -> str:
    refs = ""
    if c.citations:
        seen: list[str] = []
        for cit in c.citations:
            label = cit.url or cit.source
            if label not in seen:
                seen.append(label)
        refs = " " + " ".join(f"[{s}]({u})" if u.startswith("http") else f"`{s}`"
                              for s, u in ((c.source, c.url or c.source) for c in c.citations)
                              if u in seen[:3])
    tag = "" if c.citations else " *(inference)*"
    return f"{c.text}{tag}{refs}"


def render(r: ArtistReport) -> str:
    i, dq = r.identity, r.data_quality
    L: list[str] = []
    add = L.append

    add(f"# {i.resolved_name}")
    add(f"*A&R screening report · {r.generated_at:%Y-%m-%d} · {r.duration_s}s · ${r.cost_usd}*\n")

    add("## Identity")
    add(f"Resolved with **{i.disambiguation_confidence.value}** confidence.\n")
    ids = [x for x in (f"Spotify `{i.spotify_id}`" if i.spotify_id else None,
                       f"Deezer `{i.deezer_id}`" if i.deezer_id else None) if x]
    if ids:
        add(" · ".join(ids) + "\n")
    if i.alternates_considered:
        add("Rejected candidates, so a wrong resolution stays visible:\n")
        for alt in i.alternates_considered[:5]:
            add(f"- {alt}")
        add("")

    add("## Data quality")
    add(f"Coverage **{dq.coverage_score}** · sources: {', '.join(dq.sources_used) or 'none'}")
    if dq.sources_failed:
        add(f"\nReturned nothing: {'; '.join(dq.sources_failed)}")
    if dq.ungrounded_claims:
        add("\n> **Warning — figures with no source in the evidence:**")
        for u in dq.ungrounded_claims[:10]:
            add(f"> - {u}")
    else:
        add("\nEvery figure below traces to a source.")
    if dq.caveats:
        add("\nWhat could not be established:\n")
        for c in dq.caveats:
            add(f"- {c}")
    add("")

    add("## A&R summary")
    for b in r.ar_summary:
        add(f"- {_claim(b)}")
    add("")

    s = r.signals
    add(f"## Signals {MARK[s.confidence]}")
    add(f"**Momentum:** {s.momentum}")
    if s.momentum_rationale:
        add(f"\n{_claim(s.momentum_rationale)}")
    if s.green_flags:
        add("\n**Green flags**\n")
        for c in s.green_flags:
            add(f"- {_claim(c)}")
    if s.risks:
        add("\n**Risks — what to ask before signing**\n")
        for c in s.risks:
            add(f"- {_claim(c)}")
    add("")

    p = r.positioning
    add(f"## Positioning {MARK[p.confidence]}")
    add(f"**Genre:** {p.genre_primary or '—'}"
        + (f" · {', '.join(p.genre_secondary)}" if p.genre_secondary else ""))
    if p.scene:
        add(f"\n**Scene:** {p.scene}")
    if p.sonic_descriptors:
        add("\n**Sound**\n")
        for d in p.sonic_descriptors:
            add(f"- {d}")
    for label, claim in (("Narrative", p.narrative), ("Audience", p.audience_profile),
                         ("Differentiation", p.differentiation)):
        if claim:
            add(f"\n**{label}:** {_claim(claim)}")
    add("")

    c = r.comparables
    add(f"## Comparables {MARK[c.confidence]}")
    if c.tier_peers:
        add("\n**Tier peers** — similar audience size, for benchmarking\n")
        add("| Artist | Confidence | Why |")
        add("|---|---|---|")
        for x in c.tier_peers:
            add(f"| {x.artist} | {MARK[x.confidence]} | {x.why} |")
    if c.trajectory_analogs:
        add("\n**Trajectory analogs** — artists who stood here before\n")
        for x in c.trajectory_analogs:
            add(f"- **{x.artist}** ({x.stage_matched}) — {x.why} → *{x.what_happened_next}*")
    add("")

    m = r.markets
    add(f"## Markets {MARK[m.confidence]}")
    for label, rows in (("Colombia", m.colombia_traction), ("Expansion path", m.expansion_path)):
        if rows:
            add(f"\n**{label}**\n")
            add("| Market | Strength | Evidence |")
            add("|---|---|---|")
            for x in rows:
                add(f"| {x.market} | {MARK[x.strength]} | {x.evidence_type} |")
    if m.touring_footprint:
        add(f"\n**Touring:** {', '.join(m.touring_footprint)}")
    add("")

    a = r.recent_activity
    add(f"## Recent activity {MARK[a.confidence]}")
    add(f"*Rolling {a.window_months} months*\n")
    for e in a.events:
        when = e.date.isoformat() if e.date else "undated"
        add(f"- **{when}** · {e.type} · {e.title} — {e.significance}")
    add("")

    add("## Metrics")
    add("| Metric | Value | Confidence | Source |")
    add("|---|---|---|---|")
    for mx in r.snapshot.metrics:
        unit = f" {mx.unit}" if mx.unit else ""
        src = mx.citation.url or mx.citation.source if mx.citation else "—"
        link = f"[{mx.citation.source}]({src})" if mx.citation and src.startswith("http") else src
        add(f"| `{mx.name}` | {mx.value}{unit} | {MARK[mx.confidence]} | {link} |")

    return "\n".join(L)
