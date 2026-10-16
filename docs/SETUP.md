# Crowetic GitHub + Gitea profile — setup

## Publish

1. Sign into **github.com/crowetic** and create a **public** repository named **`crowetic`**. Do not add a license, .gitignore, or a generated README through the web form if you intend to push this prepared repo.
2. Extract this bundle and run:

   ```bash
   cd crowetic-profile
   git init -b main
   git add .
   git commit -m "Create Crowetic developer profile"
   git remote add origin git@github.com:crowetic/crowetic.git
   git push -u origin main
   ```

   Use the HTTPS remote if you prefer. If you initialized the repository with files on GitHub already, reconcile the histories rather than force pushing.
3. In the new repository go to **Actions → Sync public profile activity → Run workflow**. The job also runs automatically twice daily (scheduled jobs may be delayed).
4. If the commit step is rejected with permission denied, check **Settings → Actions → General → Workflow permissions** and whether repository/organization policies allow write access for `GITHUB_TOKEN`. The workflow explicitly requests `contents: write`.
5. Confirm the updated README has an activity table and `assets/activity.svg`. Check the logs if either source remains unfetched.

## What the integration does

- Reads **public** Gitea actions, including `crowetic`'s activity in `NuQloud-Public`, with `GET /api/v1/users/crowetic/activities/feeds` using `date=YYYY-MM-DD&only-performed-by=true`. It fetches the most recent eight UTC dates, up to 100 activities per date. It also reads `GET /api/v1/users/crowetic/heatmap` for the Gitea contributions strip.
- Reads `GET https://api.github.com/users/crowetic/events/public` for recent GitHub public events (GitHub documents a maximum of 300, and only events from the past 30 days).
- Produces a short combined *activity feed*, plus two **separate** strips: Gitea's contribution heatmap data and GitHub public API event counts. These are not the same measure, so **they are not added together**.
- Keeps the last successful snapshot in `data/sync-cache.json` and preserves it when one API is temporarily unavailable. Timestamp labels indicate when each feed was last fetched.
- Reads public data only; never includes Gitea private repository data, names, commit messages, or activity details. It does **not** mirror code.

## Important first-run validation

The Gitea web profile is publicly reachable, but external access to its JSON API has **not been verified from a GitHub Actions runner**. Run the workflow once and inspect its logs. A proxy, firewall, Cloudflare rule, or Gitea API access setting may block public JSON requests even if HTML pages load. If blocked, allow public GETs to `/api/v1/users/crowetic/activities/feeds` and `/api/v1/users/crowetic/heatmap` from GitHub runners, or run the same script from a trusted runner with Gitea access. Avoid broad unrestricted API exposure as a workaround.

The first rendered `activity.svg` in the bundle is an **empty-state placeholder**, not fabricated live statistics. The workflow updates it after fetching real source data.

## Change the look

- `assets/hero.png` is the ready-to-use static banner. `assets/hero-background.png` and `scripts/build_banner.py` are included to allow a local rebuild. Running `build_banner.py` requires Pillow (`pip install Pillow`) and a local font selection compatible with the script; Pillow is not needed for the automated sync.
- Change curated project links/text directly in `README.md`, outside the `CROWETIC:ACTIVITY` markers. The scheduled sync will only replace content between those markers.
- Theme colors and spacing for the activity graphic are defined in `scripts/sync_profile.py` in `render_svg()`.
- Regenerate from the last cache without making requests: `python scripts/sync_profile.py --offline`.

## Security and scope

- No Gitea token is required and no secrets are written into your README/cache.
- GitHub's auto-created `GITHUB_TOKEN` is used by the action to read public data with higher rate limits and push only to the profile repository, subject to Actions permissions.
- The public feed only exposes repo slugs and action categories; commit messages and usernames other than `crowetic` are intentionally excluded.
- There is no claim that private Gitea commits become GitHub contributions.
- If you later want aggregated private-activity **counts**, design that separately on your own trusted host and publish only explicitly approved aggregates. Do not hand a private-repo token to a broad-profile renderer.

## Troubleshooting

### No live Gitea data

1. From a machine that can reach the host, test:

   ```bash
   curl -i 'https://gitea.qortal.link/api/v1/users/crowetic/activities/feeds?date=2026-10-15&only-performed-by=true&limit=3'
   curl -i 'https://gitea.qortal.link/api/v1/users/crowetic/heatmap'
   ```

2. Check for a JSON array and HTTP 200. An HTML login page/403 is not an API response. The date query is only an example; replace it with the current date to test current activity.
3. Check run logs for Gitea warnings. The sync temporarily preserves earlier data when a source fails; cached event entries expire after 72 hours.

### Not seeing activity in organizations

The Gitea activity feed is for the `crowetic` **actor**, not merely the repositories owned by that account. Events in public `NuQloud-Public` repos will appear when the server reports them on that user's public activity feed.

### GitHub activity strip looks sparse

GitHub's public Events API is *not* the GitHub contributions calendar. It intentionally excludes private events and is subject to API pagination/windowing and propagation delay.
