#!/usr/bin/env python3
"""Append one day's repository figures to history.json on the metrics branch.

Reads the GitHub API with GITHUB_TOKEN and writes/extends a JSON array of daily records:
stars, forks, watchers, open issues, 14-day traffic (views and clones, null when the token may not read
traffic), the latest release tag, and the conclusion of the latest run of each workflow.
One record per UTC date; running twice on one day replaces that day's record.

Usage: record_metrics.py OWNER/REPO HISTORY_JSON
"""
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"


def get(path: str):
    req = urllib.request.Request(API + path, headers={
        "Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            return None
        raise


def latest_conclusion(repo: str, workflow_file: str):
    runs = get("/repos/%s/actions/workflows/%s/runs?per_page=1&status=completed" % (repo, workflow_file))
    items = (runs or {}).get("workflow_runs") or []
    return items[0]["conclusion"] if items else None


def record(repo: str) -> dict:
    info = get("/repos/" + repo) or {}
    views = get("/repos/%s/traffic/views" % repo)
    clones = get("/repos/%s/traffic/clones" % repo)
    releases = get("/repos/%s/releases?per_page=1" % repo) or []
    return {
        "date": dt.datetime.now(dt.timezone.utc).date().isoformat(),
        "stars": info.get("stargazers_count"), "forks": info.get("forks_count"),
        "watchers": info.get("subscribers_count"), "open_issues": info.get("open_issues_count"),
        "views_14d": {"count": views["count"], "uniques": views["uniques"]} if views else None,
        "clones_14d": {"count": clones["count"], "uniques": clones["uniques"]} if clones else None,
        "release": releases[0]["tag_name"] if releases else None,
        "ci": latest_conclusion(repo, "ci.yml"), "drift": latest_conclusion(repo, "drift.yml"),
    }


def main(repo: str, path: str) -> int:
    history = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else []
    rec = record(repo)
    history = [h for h in history if h["date"] != rec["date"]] + [rec]
    history.sort(key=lambda h: h["date"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(json.dumps(rec))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
