# ClearTube

ClearTube is TubeHaus ([biolend83/tubehaus](https://github.com/biolend83/tubehaus)) with a few changes on top.
All of them live on the `cleartube` branch. `main` stays an untouched mirror of upstream.

## What's different from upstream

| Change | Files |
|---|---|
| Renamed TubeHaus → ClearTube (UI text, login page, home-screen name) | `web/y/lang/*.js`, `web/y/auth.html`, `web/y/main.js`, `web/y/manifest.webmanifest` |
| One library per account on the server (`STATE/users/<name>/ytlib.json`, `shorts.json`); send-to-TV only shows your own screens | `server/tubehaus_server.py` |
| Change password (`POST /api/p/auth/password`, signs out other devices) + button in Settings | `server/tubehaus_server.py`, `web/y/pages.js` |
| Sign-up page instead of basic auth, Invidious account pages closed | `deploy/Caddyfile.accounts` |
| YouTube traffic through a residential/ISP proxy instead of WARP (gost adds the proxy login) | `deploy/docker-compose.cleartube.yml`, `.env.example` |

## Deploy

```sh
git clone -b cleartube https://github.com/micronlogivdev/tubehaus /opt/tubehaus && cd /opt/tubehaus
cp .env.example .env            # domain, secrets, YT_UPSTREAM
cp deploy/docker-compose.cleartube.yml docker-compose.override.yml
docker compose pull && docker compose up -d
```

## Taking updates from upstream

```sh
git remote add upstream https://github.com/biolend83/tubehaus   # once
git fetch upstream
git log --oneline cleartube..upstream/main      # what's new upstream
git checkout cleartube
git merge upstream/main                         # take everything, or:
git cherry-pick <sha>                           # take only the commits you want
```

Conflicts usually show up only in the files listed above. New upstream text that says "TubeHaus"
needs renaming again in `web/y/lang/*.js` (change only the value after `": "`, never the Korean key).
Then on the server: `git pull && docker compose up -d` (restart `tubehaus` after server changes).


## Apple WebKit black video (spatial)

The player was built by `el()`, which parses into a `<template>`'s inert owner
document. That also creates the `<video>` in the inert document before it is
adopted into the page. This matches WebKit's template-created video painting
regression ([320979](https://bugs.webkit.org/show_bug.cgi?id=320979)): decoding
continues while the inline picture stays black. The initial watch route already
mounts the player before Shaka attaches; later same-document `append()` moves
are not needed to trigger the template creation problem.

`Player.build()` now creates the root with `document.createElement("div")` and
parses its children in the page document. The video is never template-owned;
controls, Shaka, and watch/theater/mini/Shorts moves keep their existing behavior.
No browser sniffing or stream reload is needed. Keep the TEMP Safari diagnostics
and `sfx` experiments until the owner confirms the fix on Mac and iPhone; the
existing diagnostic browser filter does not include iPhone Chrome.

Local validation: the before/after browser fixture confirms template ownership
before the fix and page-document ownership after it; both load H.264/AAC DASH
through Shaka and keep decoding after a container move in desktop Chrome.
JavaScript/Python syntax, strict translations, and all 44 server tests pass.
Native Safari automation could not start, so Apple-device confirmation is pending.

Device acceptance (still required): deploy the commit and reload without `sfx`
parameters, then test the previously failing video inline for at least 20 seconds
on Mac Safari, iPhone Safari, and iPhone Chrome. Test direct watch-page entry,
home-to-watch navigation, pause/seek/resume, fullscreen and back, mini-player and
expand, a second video, and successive Shorts. On Mac also toggle theater mode
and resize across 1000px. Picture and sound should survive each transition with
no unintended restart. Check desktop Chrome as a regression control.

## Search view-count filters

The existing search Filters panel supports Most views and Newest uploaded through
upstream search, plus Least views and Oldest uploaded over fetched videos.
Minimum/maximum view counts are inclusive and also apply only to fetched videos.
These local refinements select video results, show the matching/loaded counts,
and use an explicit Load more results button. An empty filtered page does not
end pagination; only an empty upstream response does. Unknown view counts are
excluded by a numeric range and sort last for Least views. Missing upload dates
sort last for Oldest uploaded. New pages merge, deduplicate, and re-sort all loaded
videos. No YouTube API key is required.

Filter settings are stored in the search URL (`min_views`, `max_views`,
`sort=views_asc|date_asc`); changing result type to channels/playlists/movies clears
video-only refinements. Blank bounds mean no limit; zero is a valid bound.

Validation: `node tests/test_search_filters.mjs` checks numeric bounds, unknown
metadata, zero views, inclusive ranges, and ascending sort behavior. Local browser
fixtures also covered empty-match pagination, exhaustion, range validation,
Apply/Clear, URL retention, and browser Back. Production verification should
include desktop/phone layout and real upstream search.

Pre-feature restore point: `backup/pre-search-filters-2026-10-23` at
`9816ecb5bf3064ec241fa0fb88c9162ed9669c50`. Revert the feature commit and deploy the
new revert commit to undo these controls without resetting branch history.
