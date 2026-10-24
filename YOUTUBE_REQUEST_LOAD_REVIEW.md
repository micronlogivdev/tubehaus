# YouTube request load: review and handoff

Reviewed the full external YOUTUBE_BLOCK_BRIEF.md against branch spatial at
85735b7. The incident counts and watchdog behavior are reported by Claude; this
review did not inspect production logs, the live watchdog, environment files,
or proxy credentials. No production requests were made for testing this change.

## Main conclusion

Reduce unnecessary player lookups first. A fresh IP restoring playback supports
an exit/session-related failure, but does not establish request volume as its
sole cause. There is no established safe requests-per-hour threshold here, and
no setting can guarantee an IP will never be challenged. Reputation/shared
provider infrastructure and session failures are competing explanations.

2,618 player POSTs / 8 hours = 327.25 per hour. The 13,306 media requests are
range/segment traffic, not 13,306 independent video extractions. Thirty test
lookups are about 1.1% of the reported player count; a ten-minute doctor probe is
at most 48 runs in that period. Neither explains the total alone. The watchdog's
video check goes directly to Invidious, bypassing TubeHaus's video cache.

The old VID_PREFETCH=4 adds up to four uncached recommendation fetches for each
cold video-info request. Removing all four would reduce that five-request group
to one (80%); that is an upper bound for this subgroup, NOT a predicted reduction
of all 2,618 calls. Invidious caching may avoid some upstream calls. Home also
fetches full video information for up to three history seeds in pages.js homeMix;
previously a cold Home visit could issue three seed lookups plus twelve warmups.

## Impact versus effort (recommended order)

| Rank | Change | Expected impact | Effort / decision |
| --- | --- | --- | --- |
| 1 | Disable speculative recommendation video-info fetches; explicit opt-in setting | High avoidable player-load reduction | Small; implemented in this commit |
| 2 | Global cap on simultaneous cold player extractions, short shared backoff on confirmed bot/429 errors, coalesced failures | High during bursts/outages; reduces retry amplification | Medium; target extraction work, never media chunks |
| 3 | Stop full player extraction merely to build Home recommendations; reuse recommendations saved after real playback | Medium to high if Home reloads are common | Medium; preserve personalized cards with cached metadata and feed/trending fallback |
| 4 | Measure cache hits/misses and lookup reason; audit semantically equivalent cache keys and bypass paths | Enables accurate prioritization; possible medium dedup gain | Small to medium; existing same-key successful VOD coalescing already works |
| 5 | Increase video-info freshness modestly, bounded by actual URL expiry and exit/session generation | Medium for repeated videos, low for a unique-video workload | Medium; do not blindly increase the two-hour hard reuse window |
| 6 | Verify egress, cache/stagger RSS and images, add RSS conditional requests | Low residential-player benefit if already direct; useful general traffic reduction | Small to medium; route changes need runtime evidence first |
| 7 | Harden existing watchdog: classify failures, quarantine unhealthy exits, reduce repeated probes, avoid session churn | Recovery improvement; does not prevent blocks | Medium; inspect its actual script separately before changing it |
| 8 | Home connection as a fallback | No guaranteed prevention; changes exit and recurring cost | Medium/high operational burden; optional, not first-line |

## Critique of the proposed ideas

### Cache / prefetch / duplicate player calls

Agree with disabling prefetch. Implemented HT_VID_PREFETCH default 0, with negative
values clamped to 0 and invalid/blank values defaulting to 0. Public mode still
suppresses warmups even when a positive setting is supplied. At zero the request
handler does not start a recommendation-warming thread. Stale requested videos
still refresh normally. Optional warmups now use the existing vid_fetch_once
coalescing helper rather than an uncoalesced fetch.

Keep token/session lifecycle under Companion's control. The tracked Compose
already schedules its session job hourly and persists companion-cache. Extending
token reuse arbitrarily does not establish that tokens remain valid. The upstream
Companion config documents the refresh job, cache settings and retry policy:
[Companion config](https://github.com/iv-org/invidious-companion/blob/master/config/config.example.toml).

Do not treat all repeated /player calls as duplicates: clients, request bodies,
video IDs, languages, live/VOD state and sessions can differ. Log only sanitized
reasons/counts, never tokens, credentials or signed media URLs. The current cache
is keyed by the complete request path; audit variants without merging requests
with genuinely different fields/options. vid_fetch_once shares successful cached
VOD results, but waiters refetch errors and noncacheable live responses. This is
a useful follow-up for an outage circuit breaker, not proof of current call counts.

### Split egress

The brief's assertion that all metadata/RSS/images use the static proxy is not
established by the checked-in configuration:

- HT_YT_PROXY builds the explicit YT opener and supplies yt-dlp's proxy.
- yt_feed_one calls the module-level get(), which uses urllib.request.urlopen,
  not YT.open. It uses normal process/system proxy behavior, if configured.
- Tracked Invidious config has no http_proxy and no network_mode routing it
  through ytproxy. Search, channels and image routes pass to Invidious.
- Companion has the explicit static proxy and handles player/media work.

Thus RSS already appears direct, and ordinary Invidious metadata/images likely
are too. Runtime overrides, process proxy variables and host routing could change
this. Verify outbound destination counts or inspect sanitized effective routing;
do not print a fully expanded Compose config containing secrets.
[Invidious's upstream config](https://github.com/iv-org/invidious/blob/master/config/config.example.yml)
explicitly separates its HTTP proxy from Companion's stream proxy. No speculative
Caddy/proxy changes are included. Direct metadata access can also be rate-limited.

### Rotation / watchdog

Rotation is recovery, not demand reduction. Do not assume a blocked exit clears
in hours or mark it healthy merely because a cooldown elapsed. Require a successful
probe, apply increasing cooldowns, distinguish one unavailable/age-restricted
video from a bot wall, and avoid repeated switches during a service outage.

Changing the exit can invalidate active signed media URLs. Besides restarting
Companion, account for TubeHaus's up-to-two-hour video-info cache and Invidious's
cached metadata; old data can still reference the prior exit/session. Prefer
explicit generation-aware invalidation over silently keeping stale URLs. Plan
for active viewers; a global proxy switch is not sticky per-video routing. Keep
player and matching media requests on a compatible session/egress path.
[Invidious error documentation](https://docs.invidious.io/youtube-errors-explained/)
distinguishes bot challenges, rate limiting and media-URL failures.

The doctor labels any non-WARP exit as a failed "WARP proxy" check even when the
static proxy works. The watchdog must not rotate on that exit status alone; the
brief says it checks Video lookup, which is the relevant distinction.

### Home exit / limits / yt-dlp

A home exit exposes the household's public IP to the service's workload and uses
its upload capacity/uptime. It can be challenged too. It is an operational option,
not evidence that purchases stop being necessary; defer until load is reduced.

Limit expensive cold extractions globally, with a small queue and fair per-user
budgets if needed. HTTP connection limits and per-IP API limits are poor proxies
for player workload (multiple users can share a NAT). Do not throttle media range
requests with the same budget. Existing Companion network retries are deliberate:
a repo comment says they were needed for token-job startup. Change retries by
error class/work type, not by disabling them globally.

The code already uses yt-dlp for live HLS fallback, but also intentionally for
other explicit tasks such as offline/download processing. Restricting it blindly
to live streams can break features; measure those paths before changing them.

## Implemented setting and deployment review

- Process setting: HT_VID_PREFETCH, default 0. Compose now passes through the same
  host variable with default 0. Standalone Python deployments use it directly.
- No .env file or secrets were read or changed. No routing, watchdog, cache TTL,
  PO-token lifecycle, player/frontend or database behavior was changed.
- No push or deployment. On the current server's Python-file bind mount, updating
  the file then restarting tubehaus loads the default-off behavior. A nondefault
  Compose environment override requires the usual container recreation. Do not
  restart the exit proxy or Companion merely for this setting.
- Verify effective VID_PREFETCH is 0; exercise a cold watch lookup, Home, a repeat
  lookup, and live playback. There should be no recommendation-prefetch log entry
  after startup. Requested video fetches and normal stale-cache refresh still work.
- Compare player calls per actual playback start and per Home load before/after,
  with cold/warm/cache-hit and retry breakdowns. Use ordinary traffic, not a burst
  of synthetic extraction probes. Compare similar usage windows.
- A first click on an unwarmed recommendation may be slower: it now fetches that
  video's data when requested. This is the intended cost of avoiding unused work.
- Local pre-change tag: `backup/pre-video-prefetch-default-off-2026-10-23`
  at `85735b735a1090661936b0e86640bc91ab87fd5b`.
- Rollback with a new git revert of this commit and restart tubehaus. Do not reset
  to the older pre-search-filters point, which would also remove the search feature.

## Validation

48 server unit tests passed, including new cases for default/invalid/positive
configuration, disabled/public prefetch, requested stale refresh with prefetch off,
and opt-in warmup limit/cache skips. Tests mocked network calls for the new cases.
The existing eight-viewer cold-request coalescing test also passed. Existing account
tests emit ResourceWarnings about file handles but pass. No live load test was run.
