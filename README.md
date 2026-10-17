# Midterm Madness Optimizer

A single page (`site/index.html`) that fills out the office pool sheet for the highest expected score, from live prediction-market odds. Every number links to its source.

## Refresh

```sh
./refresh.sh
```

1. `pipeline/fetch.py` reads every 2026 House and Senate race on Kalshi, Polymarket and PredictIt, plus margin, chamber-control, Railroad Commissioner, Iowa governor and Chicago rain markets. It writes `data/latest.json`, which includes a coverage row for every race and source.
2. `pipeline/props.py` computes the rain, Talarico tie and Collins outfit probabilities and writes `data/props.json`.
3. `pipeline/build.py` averages the venues, fits each Senate race's margin curve, adds recent polls (reference only) and writes `site/app.html`, where the simulation runs in the browser with editable assumptions. `pipeline/render_static.js` (Node) then runs that page's script once and writes `site/index.html` with every result filled in and no JavaScript, for previews that don't run scripts. Both work offline.

Every request retries with exponential backoff and jitter. Good responses are cached in `data/http_cache.json`, so a source that still fails shows its last good reading, marked stale. `data/latest.json` includes `grid`, one row per item × market type × source (winner, margin, vote share, control, seat count, props), each with a status: ok, stale, none (after a full listing search, direct lookups and Polymarket search), or why it is unusable.

Uses Python 3 standard library only (Pillow is optional, for the evidence thumbnails).

## Tie and outfit evidence

`python -m pipeline.props_media` collects YouTube frames of past speeches into `data/props/frames/` (not committed). The labels in `data/props/labels.json` were made by looking at those frames. Each label carries its video IDs so it can be checked.

## Manual sources

Cook Political Report and RealClearPolling block scripts. The sheet's points use the Cook ratings printed on it, so only the Upset Special needs a current Cook check. The page links both sites.

## Daily updates

- **GitHub Actions:** `.github/workflows/refresh.yml` runs on demand from the Actions tab. To run it daily, uncomment its `schedule`.
- **Netlify:** `netlify.toml` builds with `./refresh.sh` and publishes `site/`. For daily data, create a build hook in Netlify and call it once a day (for example from the GitHub workflow).
