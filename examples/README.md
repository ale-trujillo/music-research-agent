# Example output

`report-ela-taubert.md` is real, unedited output — one command, 69 seconds,
$0.43. The JSON beside it is the same report in the form the pipeline actually
produces; the Markdown is derived from it.

```bash
python -m music_research_agent "Ela Taubert"
```

Worth looking at, in the report:

- **It says the artist is not the thing it was built to find.** The tool targets
  emerging artists; this one has 575,000 YouTube subscribers and 492 million
  views, and the summary leads with exactly that — "approaching an artist with
  an existing audience, not incubating one". A screening tool that cannot tell
  you it is looking at the wrong kind of prospect is not screening.
- **Every figure carries its source.** The run exited reporting that every
  number traces back to a platform. Where the model computed something instead —
  plays per listener — it says so in the sentence.
- **The absences are stated, not omitted.** No Spotify, Instagram or TikTok data
  is in the file, and the summary says commercial scale cannot be sized without
  it rather than estimating around the gap.
- **Audience shape refuses to total the platforms.** Followers, sampled
  listeners and video views measure different things; the section shows them
  side by side with what each counts and explains why no total is given.

## A note on what is published here

This example covers an artist with a large public profile, and the assessment
reads as ordinary industry commentary. Reports on very small artists are
deliberately not published: the same candour that makes the output useful
internally would be unkind attached to the name of someone with a few hundred
listeners. The tool is built for those artists — the examples are not.
