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
