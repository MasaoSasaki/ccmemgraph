#!/usr/bin/env python3
"""ccmemgraph: render Claude Code's auto memory for every project as one HTML page.

For each project under ~/.claude/projects the script reads <project>/memory/,
works out which memories the next session will see (the MEMORY.md load window),
how old each memory is, and which structural problems the directory has.
The page is a single self-contained HTML file; nothing leaves the machine.

Usage: build.py [--root DIR] [--out PATH] [--no-open]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

if sys.version_info < (3, 9):
    sys.exit("ccmemgraph needs Python 3.9 or newer (found %d.%d)" % sys.version_info[:2])

# Load limits. Docs (https://code.claude.com/docs/en/memory) say "200 lines or 25KB"; the exact behaviour
# below was read from the Claude Code binary of SOURCE_VERSION. tests/limits_probe.py re-reads them from any
# binary and a weekly workflow runs it against the latest release, so SOURCE_VERSION is the last version the
# values were measured on, not a compatibility promise.
SOURCE_VERSION = "2.1.296"
LIMITS = {
    "index_lines": 200,          # lines of MEMORY.md kept at session start
    "index_chars": 25000,        # UTF-16 code units of MEMORY.md kept (JS string length, not bytes)
    "index_read_chars": 100000,  # how much of MEMORY.md is read from disk before truncation
    "file_chars": 4096,          # memory recall shows only the first 4096 chars of a file
    "recall_scan_files": 200,    # recall scans the newest 200 files by mtime
    "recall_per_turn": 5,        # recall attaches at most 5 memories per turn
    "source_version": SOURCE_VERSION,
    "source": "Claude Code " + SOURCE_VERSION,
}
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[\w.]+)?$")


def running_claude_code_version() -> str | None:
    """Version of the Claude Code this process runs under, or None when it cannot be told.

    Inside a session Claude Code exports CLAUDE_CODE_EXECPATH, whose last path component is the version of
    the binary actually running (the `claude` on PATH may already be newer). Outside a session fall back to
    `claude --version`; any failure means None, never a guess.
    """
    exe = os.environ.get("CLAUDE_CODE_EXECPATH", "")
    if exe and VERSION_RE.match(Path(exe).name):
        return Path(exe).name
    try:
        out = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"\d+\.\d+\.\d+(?:-[\w.]+)?", out)
    return m.group(0) if m else None


def claude_code_info(running: str | None = None) -> dict:
    return {"measured": SOURCE_VERSION, "running": running}
TYPES = ("user", "feedback", "project", "reference")
STATES = ("visible", "cut", "unindexed", "missing")
SEVERITY = {  # error: content is actually lost; warning: content is not seen; info: cosmetic or an estimate
    "index-over-limit": "error", "index-cut": "warning", "index-missing": "warning", "unindexed": "warning",
    "index-near-limit": "warning", "file-over-limit": "warning", "recall-out": "warning", "dangling-link": "warning",
    "duplicate-differs": "warning", "unparsable": "warning",
    "link-mismatch": "info", "duplicate-identical": "info", "type-invalid": "info", "other-store": "info",
}

LINK = re.compile(r"\[\[([^\]|#]+)")
INDEX_ENTRY = re.compile(r"\]\(([^)\s]+\.md)\)")
FM_KEY = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*)$")
FM_SUBKEY = re.compile(r"^\s{2,}([A-Za-z_][\w-]*):\s*(.*)$")
TYPE_PREFIX = re.compile(r"^(feedback|project|reference|user)[_-]")


# ---------------------------------------------------------------- text helpers

def utf16_len(s: str) -> int:
    """Length in UTF-16 code units, which is how Claude Code (JavaScript) measures the index."""
    return len(s) + sum(1 for c in s if ord(c) > 0xFFFF)


def utf16_index(s: str, units: int) -> int:
    """Python index of the position `units` UTF-16 code units into `s` (len(s) if past the end)."""
    n = 0
    for i, c in enumerate(s):
        if n >= units:
            return i
        n += 2 if ord(c) > 0xFFFF else 1
    return len(s)


def sanitize(text: str) -> str:
    """Normalise newlines and replace control characters the way Claude Code does before measuring."""
    text = re.sub(r"\r\n?|[  ]", "\n", text)
    return "".join(c if c in "\t\n" or not (ord(c) < 32 or 127 <= ord(c) <= 159) else "�" for c in text)


def truncate_index(text: str) -> dict:
    """Apply the MEMORY.md load window and report what survives.

    Mirrors Claude Code: trim, keep the first `index_lines` lines, then if the
    result is still longer than `index_chars` UTF-16 units cut at the last newline
    before that position. Line numbers are 1-based within the trimmed text.
    """
    n = sanitize(text[: LIMITS["index_read_chars"]]).strip()
    total_lines = n.count("\n") + 1 if n else 0
    total_chars = utf16_len(n)
    by_lines = total_lines > LIMITS["index_lines"]
    by_chars = total_chars > LIMITS["index_chars"]
    w = "\n".join(n.split("\n")[: LIMITS["index_lines"]]) if by_lines else n
    if utf16_len(w) > LIMITS["index_chars"]:
        cut = utf16_index(w, LIMITS["index_chars"])
        j = w.rfind("\n", 0, cut)
        w = w[:j] if j > 0 else w[:cut]
    truncated = by_lines or by_chars
    if not truncated:
        kept_lines = total_lines
    elif len(w) == len(n) or n[len(w)] == "\n":
        kept_lines = w.count("\n") + 1 if w else 0
    else:
        kept_lines = 0  # the cut fell inside line 1
    return {
        "text": n, "kept_text": w, "total_lines": total_lines, "total_chars": total_chars,
        "kept_lines": kept_lines, "cut_lines": total_lines - kept_lines if truncated else 0,
        "cut_from_line": kept_lines + 1 if truncated else None,
        "by_lines": by_lines, "by_chars": by_chars,
    }


def parse_frontmatter(text: str) -> tuple:
    """Return (meta, body, ok). Reads one level of `key: value` plus two-space-indented keys under `metadata:`."""
    if not text.startswith("---"):
        return {}, text, True
    lines = text.split("\n")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, text, False
    meta, nested, parent = {}, {}, None
    for raw in lines[1:end]:
        m = FM_KEY.match(raw)
        if m:
            parent = m.group(1) if m.group(2).strip() == "" else None
            meta[m.group(1)] = m.group(2).strip().strip('"\'')
            continue
        m = FM_SUBKEY.match(raw)
        if m and parent:
            nested.setdefault(parent, {})[m.group(1)] = m.group(2).strip().strip('"\'')
    for key in ("type", "name", "description", "modified"):
        if key not in meta and key in nested.get("metadata", {}):
            meta[key] = nested["metadata"][key]
    ok = bool(meta) or bool(nested)
    return meta, "\n".join(lines[end + 1:]), ok


def parse_modified(value) -> float | None:
    """ISO 8601 `modified` stamp -> epoch milliseconds, or None when absent or unreadable."""
    if not value:
        return None
    v = str(value).strip().replace("Z", "+00:00")
    try:
        d = dt.datetime.fromisoformat(v)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.timestamp() * 1000


# ---------------------------------------------------------------- project names

def slugify(path: str) -> str:
    """Claude Code's project directory name for a working directory."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def resolve_slug(slug: str, fs_root: str = "/") -> str | None:
    """Recover the working directory a project slug came from by walking real directories.

    Every non-alphanumeric character became "-", so the slug alone is ambiguous
    (pocket_ledger vs pocket-ledger, a.b vs a/b). Walking the file system from
    `fs_root` and matching slugified entry names resolves it where the
    directories still exist. Returns None otherwise.
    """
    if not slug.startswith("-"):
        return None
    rest = slug[1:]

    def walk(dirpath: str, rest: str) -> str | None:
        if rest == "":
            return dirpath
        try:
            entries = [e.name for e in os.scandir(dirpath) if e.is_dir(follow_symlinks=False)]
        except OSError:
            return None
        for name in sorted(entries, key=len, reverse=True):  # longer names first: "pocket_ledger_mono" before "match"
            s = slugify(name)
            if rest == s:
                return os.path.join(dirpath, name)
            if rest.startswith(s + "-"):
                found = walk(os.path.join(dirpath, name), rest[len(s) + 1:])
                if found:
                    return found
        return None

    found = walk(fs_root, rest)
    if found and fs_root != "/":
        found = "/" + os.path.relpath(found, fs_root).replace(os.sep, "/")
    return found


def display_path(path: str | None, slug: str, home: str) -> str:
    if path is None:
        return slug
    if path == home:
        return "~"
    if path.startswith(home + "/"):
        return "~" + path[len(home):]
    return path


# ---------------------------------------------------------------- scanning

def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def issue(kind, project, file="", line=None, message="", evidence=""):
    return {"kind": kind, "severity": SEVERITY[kind], "project": project, "file": file, "line": line,
            "message": message, "evidence": evidence}


def scan(root: Path, fs_root: str = "/", home: str | None = None, now_ms: float | None = None) -> dict:
    """Read every <project>/memory under `root` and build the page model."""
    home = home or str(Path.home())
    now_ms = now_ms or dt.datetime.now(dt.timezone.utc).timestamp() * 1000
    nodes, links, issues, projects = {}, [], [], []
    for mem in sorted(p for p in root.glob("*/memory") if p.is_dir()):
        slug = mem.parent.name
        path = resolve_slug(slug, fs_root)
        label = display_path(path, slug, home)
        files = sorted(p for p in mem.rglob("*.md") if p.is_file() and not (p.parent == mem and p.name == "MEMORY.md"))
        index_path = mem / "MEMORY.md"
        index = truncate_index(read_text(index_path)) if index_path.is_file() else truncate_index("")

        # index entries: relative path -> (line number, whether that line survives the load window)
        listed = {}
        for i, line in enumerate(index["text"].split("\n") if index["text"] else [], start=1):
            for rel in INDEX_ENTRY.findall(line):
                rel = os.path.normpath(rel).replace(os.sep, "/")
                listed.setdefault(rel, (i, i <= index["kept_lines"]))

        by_name, aliases, outgoing, local_nodes = {}, {}, [], []
        for p in files:
            rel = p.relative_to(mem).as_posix()
            text = read_text(p)
            meta, body, ok = parse_frontmatter(text)
            name = meta.get("name") or p.stem
            nid = f"{slug}::{rel}"
            mtime_ms = p.stat().st_mtime * 1000
            modified_ms = parse_modified(meta.get("modified"))
            entry = listed.get(rel)
            state = "unindexed" if entry is None else ("visible" if entry[1] else "cut")
            node = {
                "id": nid, "name": name, "file": rel, "project": slug, "label": label,
                "type": meta.get("type") or "", "state": state, "desc": meta.get("description", ""),
                "chars": utf16_len(text), "md5": hashlib.md5(text.encode("utf-8")).hexdigest(),
                "mtime_ms": mtime_ms, "modified_ms": modified_ms if modified_ms is not None else mtime_ms,
                "modified_from": "frontmatter" if modified_ms is not None else "mtime",
                "age_days": max(0.0, (now_ms - (modified_ms if modified_ms is not None else mtime_ms)) / 86400000),
                "index_line": entry[0] if entry else None, "indeg": 0, "outdeg": 0, "recall_out": False, "body": body,
            }
            nodes[nid] = node
            local_nodes.append(node)
            by_name.setdefault(name, nid)
            bare = TYPE_PREFIX.sub("", p.stem)
            for alias in {p.stem, bare, p.stem.replace("_", "-"), bare.replace("_", "-")}:
                aliases.setdefault(alias, nid)
            if not ok:
                issues.append(issue("unparsable", slug, rel, 1, "frontmatter could not be read", text.split("\n")[0][:80]))
            if node["type"] not in TYPES:
                issues.append(issue("type-invalid", slug, rel, None,
                                    "type is %s" % (repr(node["type"]) if node["type"] else "missing"), "allowed: " + " / ".join(TYPES)))
            if node["chars"] > LIMITS["file_chars"]:
                issues.append(issue("file-over-limit", slug, rel, None,
                                    "%d chars; recall shows only the first %d" % (node["chars"], LIMITS["file_chars"])))
            if state == "cut":
                issues.append(issue("index-cut", slug, rel, entry[0], "listed on MEMORY.md line %d, beyond the load window" % entry[0]))
            elif state == "unindexed":
                issues.append(issue("unindexed", slug, rel, None, "not listed in MEMORY.md"))
            for i, bl in enumerate(body.split("\n"), start=text.count("\n") - body.count("\n") + 1):
                for tgt in LINK.findall(bl):
                    outgoing.append((nid, rel, i, tgt.strip()))

        # index entries whose file is gone
        for rel, (line_no, kept) in listed.items():
            if not (mem / rel).is_file():
                nid = f"{slug}::{rel}"
                nodes[nid] = {"id": nid, "name": Path(rel).stem, "file": rel, "project": slug, "label": label, "type": "",
                              "state": "missing", "desc": "", "chars": 0, "md5": "", "mtime_ms": None, "modified_ms": None,
                              "modified_from": None, "age_days": None, "index_line": line_no, "indeg": 0, "outdeg": 0,
                              "recall_out": False, "body": ""}
                issues.append(issue("index-missing", slug, rel, line_no, "MEMORY.md line %d points to a file that does not exist" % line_no))

        # links: exact name first, then the spellings Claude Code also uses (file stem, without type prefix, - for _)
        for src, src_rel, line_no, tgt in outgoing:
            tid = by_name.get(tgt)
            if tid is None:
                tid = aliases.get(tgt)
                if tid is not None:
                    issues.append(issue("link-mismatch", slug, src_rel, line_no,
                                        "[[%s]] resolves to %s whose name is %s" % (tgt, nodes[tid]["file"], nodes[tid]["name"])))
            if tid is None:
                tid = f"{slug}::[[{tgt}]]"
                if tid not in nodes:
                    nodes[tid] = {"id": tid, "name": tgt, "file": "", "project": slug, "label": label, "type": "",
                                  "state": "missing", "desc": "", "chars": 0, "md5": "", "mtime_ms": None, "modified_ms": None,
                                  "modified_from": None, "age_days": None, "index_line": None, "indeg": 0, "outdeg": 0,
                                  "recall_out": False, "body": ""}
                    issues.append(issue("dangling-link", slug, src_rel, line_no, "[[%s]] has no file under any spelling" % tgt))
            nodes[src]["outdeg"] += 1
            nodes[tid]["indeg"] += 1
            links.append({"source": src, "target": tid})

        # recall scans the newest files by mtime and stops at the cap
        for rank, node in enumerate(sorted(local_nodes, key=lambda n: n["mtime_ms"], reverse=True)):
            if rank >= LIMITS["recall_scan_files"]:
                node["recall_out"] = True
                issues.append(issue("recall-out", slug, node["file"], None,
                                    "ranked %d by mtime; recall scans only the newest %d" % (rank + 1, LIMITS["recall_scan_files"])))

        ratio = max(index["total_lines"] / LIMITS["index_lines"], index["total_chars"] / LIMITS["index_chars"])
        if index["by_lines"] or index["by_chars"]:
            issues.append(issue("index-over-limit", slug, "MEMORY.md", index["cut_from_line"],
                                "%d of %d lines are cut off, starting at line %d" % (index["cut_lines"], index["total_lines"], index["cut_from_line"]),
                                "%d lines (limit %d), %d chars (limit %d)" % (index["total_lines"], LIMITS["index_lines"], index["total_chars"], LIMITS["index_chars"])))
        elif ratio >= 0.8:
            issues.append(issue("index-near-limit", slug, "MEMORY.md", None, "at %d%% of the load window" % round(ratio * 100),
                                "%d lines (limit %d), %d chars (limit %d)" % (index["total_lines"], LIMITS["index_lines"], index["total_chars"], LIMITS["index_chars"])))

        counts = {s: sum(1 for n in nodes.values() if n["project"] == slug and n["state"] == s) for s in STATES}
        projects.append({
            "project": slug, "label": label, "path": path, "files": len(files),
            "index_lines": index["total_lines"], "index_chars": index["total_chars"],
            "index_kept_lines": index["kept_lines"], "index_cut_lines": index["cut_lines"], "index_cut_from": index["cut_from_line"],
            "index_ratio": ratio, "recall_out": sum(1 for n in local_nodes if n["recall_out"]), "states": counts,
        })

    issues += duplicate_issues(nodes, projects)
    issues += other_store_issues(nodes, projects, home)
    for n in nodes.values():
        del n["body"]
    for p in projects:
        p["issues"] = sum(1 for i in issues if i["project"] == p["project"])
    return {
        "nodes": list(nodes.values()), "links": links, "issues": issues,
        "projects": sorted(projects, key=lambda p: p["label"]),
        "states": {s: sum(1 for n in nodes.values() if n["state"] == s) for s in STATES},
        "limits": LIMITS, "claude_code": claude_code_info(),
        "generated": dt.datetime.now().astimezone().isoformat(timespec="minutes"),
        "root": str(root), "home": home,
    }


def duplicate_issues(nodes: dict, projects: list) -> list:
    """Same relative file name in several projects: identical content is a copy, differing content a collision."""
    out, by_file = [], {}
    path_of = {p["project"]: p["path"] for p in projects}
    for n in nodes.values():
        if n["file"] and n["state"] != "missing":
            by_file.setdefault(n["file"], []).append(n)
    for fname, ns in by_file.items():
        if len(ns) < 2:
            continue
        identical = len({n["md5"] for n in ns}) == 1
        related = any(a is not b and is_ancestor(path_of.get(a["project"]) or a["project"], path_of.get(b["project"]) or b["project"])
                      for a in ns for b in ns)
        if identical or related:
            kind = "duplicate-identical" if identical else "duplicate-differs"
            labels = ", ".join(n["label"] for n in ns)
            for n in ns:
                out.append(issue(kind, n["project"], fname, None,
                                 "same file name in %d projects, %s content" % (len(ns), "identical" if identical else "different"), labels))
    return out


def is_ancestor(a: str, b: str) -> bool:
    return a != b and (b.startswith(a.rstrip("/") + "/") or b.startswith(a + "-"))


def other_store_issues(nodes: dict, projects: list, home: str) -> list:
    """A memory whose body names another project's working directory may have been written into the wrong store."""
    out = []
    paths = [p["path"] for p in projects if p["path"]]
    # a directory that contains other projects (the home directory, ~/Projects) is not evidence of one specific project
    targets = [(p["project"], p["path"]) for p in projects if p["path"] and not any(is_ancestor(p["path"], q) for q in paths)]
    path_of = {p["project"]: p["path"] for p in projects}
    for n in nodes.values():
        own = path_of.get(n["project"])
        if n["state"] == "missing" or not n["body"] or own is None:
            continue
        for slug, path in targets:
            if slug == n["project"] or is_ancestor(path, own):
                continue
            forms = [path] + (["~" + path[len(home):]] if path.startswith(home + "/") else [])
            for form in forms:
                m = re.search(re.escape(form) + r"(?=[/\s)\]'\"`,.;:]|$)", n["body"])
                if m:
                    line_no = n["body"].count("\n", 0, m.start()) + 1
                    out.append(issue("other-store", n["project"], n["file"], line_no,
                                     "mentions another project's directory; written into the wrong store?", form))
                    break
            else:
                continue
            break
    return out


# ---------------------------------------------------------------- output

def render(model: dict, here: Path) -> str:
    template = read_text(here / "template.html")
    d3 = read_text(here / "vendor" / "d3.min.js")
    data = json.dumps(model, ensure_ascii=False).replace("</", "<\\/")
    return template.replace("__D3__", d3, 1).replace("__DATA__", data, 1)


def summary_lines(model: dict, out: Path) -> list:
    kinds = {}
    for i in model["issues"]:
        kinds[i["kind"]] = kinds.get(i["kind"], 0) + 1
    files = sum(1 for n in model["nodes"] if n["state"] != "missing")
    lines = [
        "projects=%d files=%d links=%d" % (len(model["projects"]), files, len(model["links"])),
        "state: " + " ".join("%s=%d" % (s, model["states"][s]) for s in STATES),
        "issues: " + (" ".join("%s=%d" % kv for kv in sorted(kinds.items())) or "none"),
    ]
    cc = model["claude_code"]
    if cc["running"] and cc["running"] != cc["measured"]:
        lines.append("claude code: running %s, limits measured on %s (not re-verified on this version)"
                     % (cc["running"], cc["measured"]))
    lines.append("out: %s" % out)
    return lines


def open_in_browser(path: Path) -> None:
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        elif sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", str(path)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=str(Path.home() / ".claude" / "projects"), help="projects directory to scan")
    ap.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "ccmemgraph" / "ccmemgraph.html"), help="HTML output path")
    ap.add_argument("--no-open", action="store_true", help="do not open the page in a browser")
    ap.add_argument("--fs-root", default="/", help=argparse.SUPPRESS)  # resolve project slugs against this tree (fixtures)
    ap.add_argument("--home", default=str(Path.home()), help=argparse.SUPPRESS)  # home directory shown as ~ (fixtures)
    a = ap.parse_args(argv)
    root = Path(a.root).expanduser()
    model = scan(root, fs_root=a.fs_root, home=a.home) if root.is_dir() else scan_empty(root)
    model["claude_code"] = claude_code_info(running_claude_code_version())
    out = Path(a.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(model, Path(__file__).resolve().parent), encoding="utf-8")
    print("\n".join(summary_lines(model, out)))
    if not a.no_open:
        open_in_browser(out)
    return 0


def scan_empty(root: Path) -> dict:
    return {"nodes": [], "links": [], "issues": [], "projects": [], "states": {s: 0 for s in STATES}, "limits": LIMITS,
            "claude_code": claude_code_info(), "generated": dt.datetime.now().astimezone().isoformat(timespec="minutes"),
            "root": str(root), "home": str(Path.home())}


if __name__ == "__main__":
    sys.exit(main())
