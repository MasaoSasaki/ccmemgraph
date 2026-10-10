#!/usr/bin/env python3
"""Generate the demo data set under fixtures/demo.

The output is committed; this script documents how it was produced and lets it
be regenerated after a format change. Run: python3 fixtures/generate_demo.py

Layout mimics ~/.claude/projects with a fake file system for slug resolution:
  fixtures/demo/projects/<slug>/memory/...   (what build.py --root scans)
  fixtures/demo/fs/home/demo/...             (what build.py --fs-root walks)
"""
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEMO = HERE / "demo"
PROJECTS = DEMO / "projects"
FS = DEMO / "fs"
HOME = "/home/demo"


def memory(slug: str, name: str, type_: str, desc: str, body: str, modified: str, fname: str = None) -> str:
    fname = fname or f"{type_}_{name.replace('-', '_')}.md"
    text = f"---\nname: {name}\ndescription: {desc}\ntype: {type_}\nmodified: {modified}\n---\n\n{body}\n"
    (PROJECTS / slug / "memory" / fname).write_text(text, encoding="utf-8")
    return fname


def index(slug: str, lines: list) -> None:
    (PROJECTS / slug / "memory" / "MEMORY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    if DEMO.exists():
        shutil.rmtree(DEMO)
    for rel in ["home/demo/Projects/alpha", "home/demo/Projects/beta", "home/demo/Projects/gamma", "home/demo/Projects/delta", "home/demo/Projects/epsilon"]:
        (FS / rel).mkdir(parents=True)
        (FS / rel / ".keep").write_text("")
    for slug in ["-home-demo", "-home-demo-Projects-alpha", "-home-demo-Projects-beta", "-home-demo-Projects-gamma", "-home-demo-Projects-delta", "-home-demo-Projects-epsilon"]:
        (PROJECTS / slug / "memory").mkdir(parents=True)

    # alpha: a healthy project with links; one link spelled with the file stem instead of the name
    a = "-home-demo-Projects-alpha"
    entries = []
    f = memory(a, "release-checklist", "project", "Steps before tagging a release", "Run the suite, bump the version, update the changelog. See [[ci-pipeline]] and [[feedback_no_force_push]].", "2026-09-28T09:00:00Z")
    entries.append(f"- [Release checklist](%s) — steps before tagging" % f)
    f = memory(a, "ci-pipeline", "reference", "Where CI runs and how to read it", "GitHub Actions at .github/workflows/ci.yml; artifacts expire after 7 days.", "2026-08-15T09:00:00Z")
    entries.append(f"- [CI pipeline](%s) — where CI runs" % f)
    f = memory(a, "no-force-push", "feedback", "Never force-push shared branches", "The user rebases locally but never wants history rewritten on main.\n\n**Why:** a force-push lost a teammate's commit in 2026-03.", "2026-03-12T09:00:00Z")
    entries.append(f"- [No force push](%s) — shared branches are append-only" % f)
    f = memory(a, "owner-role", "user", "Solo maintainer, prefers small PRs", "Maintains alpha alone; reviews happen async.", "2026-01-20T09:00:00Z")
    entries.append(f"- [Owner role](%s) — solo maintainer" % f)
    f = memory(a, "dashboard", "reference", "Grafana board for alpha", "https://grafana.example/d/alpha — latency and error rate. Related: [[ci-pipeline]].", "2026-10-01T09:00:00Z")
    entries.append(f"- [Dashboard](%s) — Grafana board" % f)
    memory(a, "editor-settings", "reference", "Shared editor settings", "Two-space indent, LF, trailing newline.", "2026-07-01T09:00:00Z", fname="reference_editor_settings.md")
    entries.append("- [Editor settings](reference_editor_settings.md) — indent and line endings")
    index(a, ["# alpha memory index"] + entries)

    # home: the catch-all store; one memory talks about alpha's directory, one duplicates alpha's file with different content
    h = "-home-demo"
    f = memory(h, "machine-names", "reference", "Host names for the two laptops", "orion is the personal Mac, lyra the work Mac. Power-down order is in [[homeserver-notes]].", "2026-09-26T09:00:00Z")
    hl = [f"- [Machine names](%s) — orion / lyra" % f]
    f = memory(h, "alpha-release-plan", "project", "Plan for alpha 2.0", "Decided in ~/Projects/alpha to ship 2.0 after the CI migration. Written while the session sat in the home directory.", "2026-10-05T09:00:00Z")
    hl.append(f"- [Alpha release plan](%s) — 2.0 after CI migration" % f)
    memory(h, "editor-settings", "reference", "Editor settings (older copy)", "Four-space indent.", "2025-11-01T09:00:00Z", fname="reference_editor_settings.md")
    hl.append("- [Editor settings](reference_editor_settings.md) — indent")
    index(h, hl)

    # beta: 210 memories listed in order, so the last 10 index lines fall outside the load window;
    # two files are not indexed and one index entry points nowhere
    b = "-home-demo-Projects-beta"
    bl = []
    for i in range(1, 211):
        f = memory(b, f"note-{i:03d}", "project", f"Working note {i}", f"Note {i} about beta.", f"2026-{(i % 9) + 1:02d}-{(i % 27) + 1:02d}T09:00:00Z")
        bl.append(f"- [Note {i}](%s) — working note {i}" % f)
    bl.append("- [Deleted note](project_note_999.md) — this file was removed")
    memory(b, "stray-one", "feedback", "Never indexed", "Prefers tabs in Makefiles.", "2026-09-30T09:00:00Z")
    memory(b, "stray-two", "reference", "Never indexed either", "Runbook lives in the wiki.", "2026-09-29T09:00:00Z")
    index(b, bl)

    # gamma: no links at all; one oversized file, one broken frontmatter, one invalid type, one exact copy of an alpha file
    g = "-home-demo-Projects-gamma"
    gl = []
    f = memory(g, "api-notes", "reference", "Everything about the gamma API", ("The gamma API has many endpoints. " * 160).strip(), "2026-06-01T09:00:00Z")
    gl.append(f"- [API notes](%s) — endpoints" % f)
    (PROJECTS / g / "memory" / "broken.md").write_text("---\nname: broken\ndescription: frontmatter never closes\n\nBody text.\n", encoding="utf-8")
    gl.append("- [Broken](broken.md) — frontmatter never closes")
    f = memory(g, "deploy-window", "ops", "Deploys happen Tuesday mornings", "Tuesday 09:00–11:00 JST.", "2026-09-02T09:00:00Z")
    gl.append(f"- [Deploy window](%s) — Tuesdays" % f)
    (PROJECTS / g / "memory" / "reference_ci_pipeline.md").write_text((PROJECTS / a / "memory" / "reference_ci_pipeline.md").read_text(encoding="utf-8"), encoding="utf-8")
    gl.append("- [CI pipeline](reference_ci_pipeline.md) — copied from alpha")
    f = memory(g, "team", "user", "Three engineers, one on-call", "Rotation is weekly.", "2026-04-10T09:00:00Z")
    gl.append(f"- [Team](%s) — three engineers" % f)
    index(g, gl)

    # delta: few lines but very long index entries, so the character limit cuts before the line limit
    d = "-home-demo-Projects-delta"
    dl = []
    for i in range(1, 25):
        f = memory(d, f"topic-{i:02d}", "reference", f"Topic {i}", f"Topic {i} body.", f"2026-05-{(i % 28) + 1:02d}T09:00:00Z")
        dl.append(f"- [Topic {i}](%s) — " % f + ("long hook text " * 80).strip())
    index(d, dl)
    # epsilon: 165 memories, so the index sits at 82% of the line limit (near, not over)
    e = "-home-demo-Projects-epsilon"
    el = []
    for i in range(1, 166):
        f = memory(e, f"item-{i:03d}", "reference", f"Item {i}", f"Item {i} of epsilon.", f"2026-{(i % 9) + 1:02d}-{(i % 27) + 1:02d}T09:00:00Z")
        el.append(f"- [Item {i}](%s) — item {i}" % f)
    index(e, el)
    print("demo written to", DEMO)


if __name__ == "__main__":
    main()
