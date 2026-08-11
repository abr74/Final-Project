# YouFeelings — Results page

`results_preview.html` is a standalone mockup. Open it in a browser; no build
step, no server. It renders the exact response shape `yf-v2-fusion-recommender`
returns, using a real payload (user 00e67b59, 109 recognised channels).

## The design idea

The taste fingerprint is the signature element, and it is deliberately the
first thing on the page. It is also the only thing here YouTube cannot show
you — so it leads, and the recommendation list follows from it rather than
the other way round.

- **One hue per aspect**, used consistently: the fingerprint band, the tag on
  each card, and the signal mix all reference the same five colours. Colour
  carries meaning rather than decoration.
- **The band widths are the profile.** Nothing is normalised for looks; a 5.8%
  aspect renders as a 5.8% sliver.
- **The signal mix** under each score shows which models contributed
  (bert / ncf / content) at their normalised strengths, so a cold-start user
  can see that collaborative data is absent rather than being told nothing.
- Ranks are `01`, `02`… because the list genuinely is ordered by score.

## Copy

Explanations are rewritten from the Lambda's raw `explanation` string into
plain language: "Channels you watch skew toward substance, and this one scores
0.94 on that" rather than "you favour informativeness and this channel scores
0.94 there". Same fact, reads like a product.

## Wiring it to the real API

Replace the hard-coded `data` object at the bottom of the file with:

```js
const res = await fetch(`${RECOMMENDATIONS_API}?userId=${uploadId}`);
const data = await res.json();
```

Everything below that line already works against the live shape.

## Known rough edge

Match percentages saturate near the top (99.9%, 98.4%) because min-max
normalisation stretches the range once watched channels are excluded. Before
a demo, consider either capping the displayed figure or using a softer
transform — "99.9% match" invites a question the current label quality cannot
answer.

---

## `demo.html` — the stakeholder demo

Open in a browser. No build, no server, no backend.

**Why it's built this way:** the pitch for an explainable recommender is hard to
make in prose — "it personalises" is what every recommender claims. So this page
runs the *actual scoring function* client-side over a sample of the live
catalogue. A stakeholder drags a slider and the list reorders in front of them.
That is the demonstration.

**The flow:** drop a `.zip` (or click "Use a sample viewer") -> the six
pipeline stages run with live progress -> results reveal. The stage labels are
the real ones, so a stakeholder watching sees what the system actually does
rather than a spinner.

Set `API_BASE` at the top of the script to your API Gateway stage to run
against the live backend. Left empty it walks the same steps locally, so the
flow can be presented anywhere with no deployment.

What it does:
- **Three real viewer profiles** (drawn from live pipeline output) — switching
  re-ranks the whole list, proving results depend on the person, not the catalogue
- **Five live aspect sliders** — recompute BERT match, normalise, re-fuse, reorder
- **Per-recommendation attribution** — bar widths show what each signal
  contributed; collaborative data is visibly absent for a new viewer rather than
  silently zero
- **Checkable explanations** — "stands out on creator, 0.90 against a 0.76
  catalogue average, and this profile weights it at 26%"

The aspect tag uses spread-normalised lift: how far the channel deviates from
the catalogue mean on that aspect, divided by the aspect's own spread, weighted
by preference. Without dividing by spread, informativeness wins every time
purely because it varies more across channels than production does.

Swap `CHANNELS` and `VIEWERS` for live API data when you want it reading
production instead of a sample.
