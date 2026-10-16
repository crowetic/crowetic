#!/usr/bin/env python3
"""Update a GitHub profile from public Gitea + GitHub API activity.

Only reads anonymous Gitea endpoints and public GitHub events. No Gitea token
is needed, and private activities are explicitly excluded from output/cache.
Uses stdlib only and retains older snapshots when a source fails.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
GITEA_ORIGIN = "https://gitea.qortal.link"
GITEA_USER = "crowetic"
GITHUB_USER = "crowetic"
GITEA_API = f"{GITEA_ORIGIN}/api/v1"
GITHUB_API = "https://api.github.com"
START = "<!-- CROWETIC:ACTIVITY:START -->"
END = "<!-- CROWETIC:ACTIVITY:END -->"
ALLOWED_REPO = re.compile(r"^[A-Za-z0-9_.-]{1,128}/[A-Za-z0-9_.-]{1,128}$")
UTC = dt.timezone.utc
IMPORTANT_GITEA = {
    "commit_repo": "Pushed code",
    "create_repo": "Created repository",
    "create_pull_request": "Opened pull request",
    "merge_pull_request": "Merged pull request",
    "publish_release": "Published release",
    "create_issue": "Opened issue",
    "push_tag": "Pushed tag",
}
IMPORTANT_GITHUB = {
    "PushEvent": "Pushed code",
    "PullRequestEvent": "Pull request activity",
    "ReleaseEvent": "Published release",
    "IssuesEvent": "Issue activity",
    "CreateEvent": "Created branch or tag",
}


def utcnow() -> dt.datetime:
    return dt.datetime.now(UTC)


def iso(instant: dt.datetime) -> str:
    return instant.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_date(value: str | int | float | None) -> dt.datetime | None:
    if isinstance(value, (float, int)):
        try:
            return dt.datetime.fromtimestamp(value, tz=UTC)
        except (ValueError, OverflowError, OSError):
            return None
    if not isinstance(value, str) or not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def get_json(url: str, token: str | None = None) -> object:
    headers = {
        "User-Agent": "Crowetic-Profile-PublicActivity/1.0",
        "Accept": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=12) as response:
        payload = response.read(3_000_001)
    if len(payload) > 3_000_000:
        raise ValueError("Refusing unexpectedly large API response")
    return json.loads(payload)


def safe_repo(value: object) -> str | None:
    if isinstance(value, str) and ALLOWED_REPO.fullmatch(value):
        return value
    return None


def is_public_repo(repo: dict) -> bool:
    # Gitea's activity feed can report public events from private repos,
    # so conservatively treat unspecified privacy as NOT public.
    return repo.get("private") is False and repo.get("internal") is not True


def normalize_gitea_event(raw: dict) -> dict | None:
    if raw.get("is_private") is True:
        return None
    actor = raw.get("act_user") or {}
    if not isinstance(actor, dict) or str(actor.get("login", "")).lower() != GITEA_USER:
        return None
    repo = raw.get("repo") or {}
    if not isinstance(repo, dict) or not is_public_repo(repo):
        return None
    slug = safe_repo(repo.get("full_name"))
    operation = raw.get("op_type")
    when = parse_date(raw.get("created"))
    if not slug or operation not in IMPORTANT_GITEA or when is None:
        return None
    event_id = raw.get("id")
    if not isinstance(event_id, int) or event_id < 0:
        return None
    return {
        "key": f"gitea:{event_id}",
        "source": "Gitea",
        "repo": slug,
        "action": IMPORTANT_GITEA[operation],
        "at": iso(when),
        "url": f"{GITEA_ORIGIN}/{slug}",
    }


def normalize_github_event(raw: dict) -> dict | None:
    if raw.get("public") is not True:
        return None
    actor = raw.get("actor") or {}
    if not isinstance(actor, dict) or str(actor.get("login", "")).lower() != GITHUB_USER:
        return None
    repo = raw.get("repo") or {}
    if not isinstance(repo, dict):
        return None
    slug = safe_repo(repo.get("name"))
    operation = raw.get("type")
    when = parse_date(raw.get("created_at"))
    if not slug or slug.lower() == "crowetic/crowetic" or operation not in IMPORTANT_GITHUB or when is None:
        return None
    event_id = raw.get("id")
    if not isinstance(event_id, (str, int)) or not str(event_id).isdigit():
        return None
    return {
        "key": f"github:{event_id}",
        "source": "GitHub",
        "repo": slug,
        "action": IMPORTANT_GITHUB[operation],
        "at": iso(when),
        "url": f"https://github.com/{slug}",
    }


def list_from_pages(url_template: str, *, max_pages: int, token: str | None = None) -> list:
    result: list = []
    for page in range(1, max_pages + 1):
        data = get_json(url_template.format(page=page), token=token)
        if not isinstance(data, list):
            raise ValueError("Expected an API list")
        result.extend(data)
        if len(data) < 100:
            break
    return result


def fetch_gitea_events(today: dt.date) -> list[dict]:
    """Use Gitea's date-scoped activity endpoint for 8 recent UTC dates.

    This intentionally covers organization repos to which crowetic contributed;
    GET /users/crowetic/repos alone would miss NuQloud-Public changes.
    """
    events: dict[str, dict] = {}
    for ago in range(8):
        day = today - dt.timedelta(days=ago)
        for page in (1, 2):
            params = urllib.parse.urlencode({
                "date": day.isoformat(),
                "only-performed-by": "true",
                "page": page,
                "limit": 50,
            })
            uri = f"{GITEA_API}/users/{GITEA_USER}/activities/feeds?{params}"
            data = get_json(uri)
            if not isinstance(data, list):
                raise ValueError("Unexpected Gitea activity response")
            for row in data:
                if isinstance(row, dict):
                    item = normalize_gitea_event(row)
                    if item:
                        events[item["key"]] = item
            if len(data) < 50:
                break
    return list(events.values())


def fetch_gitea_heatmap() -> dict[str, int]:
    uri = f"{GITEA_API}/users/{GITEA_USER}/heatmap"
    data = get_json(uri)
    if not isinstance(data, list):
        raise ValueError("Unexpected Gitea heatmap response")
    counts: dict[str, int] = {}
    for row in data:
        if not isinstance(row, dict):
            continue
        when = parse_date(row.get("timestamp"))
        count = row.get("contributions")
        if when is None or not isinstance(count, int) or count < 0:
            continue
        day = when.date().isoformat()
        counts[day] = counts.get(day, 0) + count
    return counts


def fetch_github_events() -> list[dict]:
    token = os.environ.get("GITHUB_TOKEN")
    uri = f"{GITHUB_API}/users/{GITHUB_USER}/events/public?per_page=100&page={{page}}"
    data = list_from_pages(uri, max_pages=3, token=token)
    return [normalized for row in data if isinstance(row, dict)
            if (normalized := normalize_github_event(row))]


def unique_recent(items: list[dict], now: dt.datetime) -> list[dict]:
    since = now - dt.timedelta(days=30)
    dedup: dict[str, dict] = {}
    for item in items:
        when = parse_date(item.get("at"))
        if when and since <= when <= now + dt.timedelta(minutes=10):
            dedup[item["key"]] = item
    return sorted(dedup.values(), key=lambda x: x["at"], reverse=True)[:500]


def sanitize_old_events(items: object, source: str) -> list[dict]:
    # Cache might be manually edited. Revalidate before exposing data as Markdown.
    if not isinstance(items, list):
        return []
    host = GITEA_ORIGIN if source == "Gitea" else "https://github.com"
    safe: list[dict] = []
    for item in items:
        if not isinstance(item, dict) or item.get("source") != source:
            continue
        slug = safe_repo(item.get("repo"))
        when = parse_date(item.get("at"))
        if slug and when and isinstance(item.get("key"), str) and item.get("action") in set(IMPORTANT_GITEA.values()) | set(IMPORTANT_GITHUB.values()):
            safe.append({"key": item["key"], "source": source, "repo": slug, "at": iso(when),
                         "action": item["action"], "url": f"{host}/{slug}"})
    return safe


def load_cache(path: Path) -> dict:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(parsed, dict):
            return parsed
    except (FileNotFoundError, ValueError, OSError):
        pass
    return {}


def sync(cache: dict, now: dt.datetime, offline: bool = False) -> dict:
    current = {}
    for host in ("gitea", "github"):
        snapshot = cache.get(host, {}) if isinstance(cache.get(host), dict) else {}
        current[host] = dict(snapshot)
        current[host]["events"] = unique_recent(sanitize_old_events(snapshot.get("events"), host.title()), now)
    # Don't keep showing old repository names indefinitely if their visibility
    # changes while an API is unavailable. Cached event metadata expires after
    # 72 hours without a successful source refresh.
    for host in ("gitea", "github"):
        last_refresh = parse_date(current[host].get("feed_updated_at"))
        if last_refresh is None or now - last_refresh > dt.timedelta(hours=72):
            current[host]["events"] = []
    if offline:
        return current
    try:
        fresh = fetch_gitea_events(now.date())
        current["gitea"]["events"] = unique_recent(fresh, now)
        current["gitea"]["feed_updated_at"] = iso(now)
        print(f"Gitea: received {len(fresh)} eligible public events")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as err:
        print(f"WARNING: Gitea activity unavailable; keeping cached snapshot: {err}", file=sys.stderr)
    try:
        heatmap = fetch_gitea_heatmap()
        current["gitea"]["heatmap"] = heatmap
        current["gitea"]["heatmap_updated_at"] = iso(now)
        print(f"Gitea: heatmap {len(heatmap)} days")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as err:
        print(f"WARNING: Gitea heatmap unavailable; keeping cached snapshot: {err}", file=sys.stderr)
    try:
        fresh = fetch_github_events()
        current["github"]["events"] = unique_recent(fresh, now)
        current["github"]["feed_updated_at"] = iso(now)
        print(f"GitHub: received {len(fresh)} eligible public events")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as err:
        print(f"WARNING: GitHub activity unavailable; keeping cached snapshot: {err}", file=sys.stderr)
    return current


def activity_lines(cache: dict) -> str:
    ge = cache["gitea"]
    gh = cache["github"]
    g_ts = parse_date(ge.get("feed_updated_at"))
    h_ts = parse_date(gh.get("feed_updated_at"))
    if not g_ts and not h_ts:
        return "_Awaiting first successful public API sync. [See Gitea activity](https://gitea.qortal.link/crowetic?tab=activity) or [GitHub](https://github.com/crowetic)._"
    def stamped(when: dt.datetime | None) -> str:
        return when.strftime("%Y-%m-%d %H:%M UTC") if when else "not yet fetched"
    events = sorted(ge.get("events", []) + gh.get("events", []), key=lambda x: x["at"], reverse=True)[:7]
    out = [
        f"**Last fetched:** Gitea {stamped(g_ts)} · GitHub {stamped(h_ts)}",
        "",
        "| Date (UTC) | Forge | Public activity | Repository |",
        "|:---|:---|:---|:---|",
    ]
    for item in events:
        day = item["at"][:10]
        out.append(f"| {day} | **{item['source']}** | {item['action']} | [{item['repo']}]({item['url']}) |")
    if not events:
        out.append("| — | — | No recent public activity in the fetched window | — |")
    out.extend([
        "",
        "<sub>Gitea includes public work in organizations such as NuQloud-Public."
        " GitHub's public events endpoint covers recent activity (at most 30 days / 300 events)."
        " These are events, not an accurate cross-host commit count.</sub>",
    ])
    return "\n".join(out)


def replace_activity(markdown: str, replacement: str) -> str:
    if markdown.count(START) != 1 or markdown.count(END) != 1:
        raise ValueError("README must have exactly one start and end activity marker")
    before, rest = markdown.split(START, 1)
    _, after = rest.split(END, 1)
    return f"{before}{START}\n{replacement}\n{END}{after}"


def svg_escape(s: object) -> str:
    from xml.sax.saxutils import escape
    return escape(str(s), {'"': '&quot;'})


def color_for(count: int | None, source: str) -> str:
    if count is None:
        return "#132B3A"
    if count <= 0:
        return "#143342"
    if source == "Gitea":
        return ["#2B8DAB", "#21AFCE", "#35CDEE", "#90F1FF"][min(3, int(math.log2(count + 1)) - 1)]
    return ["#326E9B", "#498EC1", "#73B4E9", "#B1DEFF"][min(3, int(math.log2(count + 1)) - 1)]


def render_svg(cache: dict, now: dt.datetime) -> str:
    days = [(now.date() - dt.timedelta(days=27-i)).isoformat() for i in range(28)]
    g = cache["gitea"]
    h = cache["github"]
    heatmap = g.get("heatmap", {}) if isinstance(g.get("heatmap"), dict) else {}
    g_ts = parse_date(g.get("heatmap_updated_at"))
    h_ts = parse_date(h.get("feed_updated_at"))
    g_fetched = bool(g_ts and dt.timedelta(0) <= now - g_ts <= dt.timedelta(hours=72))
    h_fetched = bool(h_ts and dt.timedelta(0) <= now - h_ts <= dt.timedelta(hours=72))
    github_counts = {day: 0 for day in days}
    for ev in h.get("events", []):
        day = ev["at"][:10]
        if day in github_counts:
            github_counts[day] += 1
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="285" viewBox="0 0 1120 285" role="img" aria-label="Gitea and GitHub public activity strips, 28 days">',
        '<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#071520"/><stop offset="1" stop-color="#0A2735"/></linearGradient></defs>',
        '<rect x="1" y="1" width="1118" height="283" rx="20" fill="url(#bg)" stroke="#205064" stroke-width="2"/>',
        '<rect x="38" y="31" width="8" height="28" rx="4" fill="#40D6F9"/>',
        '<text x="60" y="51" fill="#DFF9FF" font-size="24" font-family="DejaVu Sans, Arial, sans-serif" font-weight="700" letter-spacing="2">PUBLIC ACTIVITY / 28 DAYS</text>',
        '<text x="60" y="75" fill="#7CB5CB" font-size="14" font-family="Arial, sans-serif">Different measures across two code hosts; neither is a total commit count</text>',
    ]
    def add_strip(name: str, subtitle: str, y: int, counts: list[int | None]):
        parts.append(f'<text x="50" y="{y+17}" fill="#E1F3FF" font-size="19" font-family="Arial, sans-serif" font-weight="700">{name}</text>')
        parts.append(f'<text x="50" y="{y+37}" fill="#83ABC1" font-size="14" font-family="Arial, sans-serif">{subtitle}</text>')
        for index, count in enumerate(counts):
            x = 395 + index * 24
            day = days[index]
            fill = color_for(count, name)
            parts.append(f'<rect x="{x}" y="{y}" width="18" height="32" rx="4" fill="{fill}"><title>{day}: {"unavailable" if count is None else count}</title></rect>')
    add_strip("Gitea", "Public contributions", 103, [max(0,int(heatmap.get(day,0))) if g_fetched else None for day in days])
    add_strip("GitHub", "Public API events", 173, [github_counts[day] if h_fetched else None for day in days])
    parts.extend([
        f'<text x="395" y="244" fill="#88B5C4" font-size="14" font-family="Arial, sans-serif">{svg_escape(days[0])}</text>',
        f'<text x="1050" y="244" text-anchor="end" fill="#88B5C4" font-size="14" font-family="Arial, sans-serif">{svg_escape(days[-1])}</text>',
        '<text x="50" y="269" fill="#668C9E" font-size="12" font-family="Arial, sans-serif">Refreshes via GitHub Actions. Blank/low activity does not imply no development.</text>',
        '</svg>',
    ])
    result = "\n".join(parts) + "\n"
    ET.fromstring(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", help="Build from existing cache without network calls")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    cache_file = root / "data" / "sync-cache.json"
    readme_file = root / "README.md"
    svg_file = root / "assets" / "activity.svg"
    now = utcnow()
    old = load_cache(cache_file)
    state = sync(old, now, offline=args.offline)
    original = readme_file.read_text(encoding="utf-8")
    modified = replace_activity(original, activity_lines(state))
    readme_file.write_text(modified, encoding="utf-8")
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(state, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    svg_file.parent.mkdir(parents=True, exist_ok=True)
    svg_file.write_text(render_svg(state, now), encoding="utf-8")
    print(f"Updated {readme_file.relative_to(root)}, {svg_file.relative_to(root)}")

if __name__ == "__main__":
    main()
