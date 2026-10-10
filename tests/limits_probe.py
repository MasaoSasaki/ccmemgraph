#!/usr/bin/env python3
"""Re-read the auto-memory limits from a Claude Code binary and compare them with build.LIMITS.

The binary embeds its JavaScript source; the constants sit in one `var` statement whose identifier names
change with every build but whose shape does not. Anchors used:
  "MEMORY.md",<id>=<index_lines>,<id>=<index_chars>,<id>=<k>*<id>,<id>=<recall_scan_files>,<id>=<file_chars>;
  the last `.slice(0,<recall_per_turn>)` before `relevant_memories",memories:`
  the slug rule `replace(/[^a-zA-Z0-9]/g,"-")`

Usage: limits_probe.py [BINARY] [--json]
  BINARY defaults to $CLAUDE_CODE_EXECPATH, then the newest entry of ~/.local/share/claude/versions.
Exit 0 when every value matches build.LIMITS, 1 on a difference, 2 when an anchor is missing or no binary is found.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "ccmemgraph"))
import build  # noqa: E402

IDENT = r"[A-Za-z_$][\w$]*"
CONSTS = re.compile((r'"MEMORY\.md",%s=(\d+),(%s)=(\d+),%s=(\d+)\*\2,%s=(\d+),%s=(\d+);' % (IDENT, IDENT, IDENT, IDENT, IDENT)).encode())
PER_TURN_ANCHOR = b'relevant_memories",memories:'
SLICE = re.compile(rb"\.slice\(0,(\d+)\)")
SLUG_RULE = b'replace(/[^a-zA-Z0-9]/g,"-")'
KEYS = ("index_lines", "index_chars", "index_read_chars", "file_chars", "recall_scan_files", "recall_per_turn")


def find_binary() -> Path | None:
    exe = os.environ.get("CLAUDE_CODE_EXECPATH")
    if exe and Path(exe).is_file():
        return Path(exe)
    versions = Path.home() / ".local" / "share" / "claude" / "versions"
    found = [p for p in versions.glob("*") if p.is_file() and build.VERSION_RE.match(p.name)]
    return max(found, key=lambda p: [int(x) for x in p.name.split("-")[0].split(".")]) if found else None


def probe(data: bytes) -> dict:
    """Extract the limits from binary contents. Missing anchors are reported, never guessed."""
    out, missing = {}, []
    hits = CONSTS.findall(data)
    if len(hits) == 1:
        lines, _, chars, mult, scan, file_chars = hits[0]
        out.update(index_lines=int(lines), index_chars=int(chars), index_read_chars=int(mult) * int(chars),
                   recall_scan_files=int(scan), file_chars=int(file_chars))
    else:
        missing.append("limits statement (%d matches)" % len(hits))
    i = data.find(PER_TURN_ANCHOR)
    slices = SLICE.findall(data[max(0, i - 900):i]) if i >= 0 else []
    if slices:
        out["recall_per_turn"] = int(slices[-1])
    else:
        missing.append("per-turn cap")
    out["slug_rule"] = data.count(SLUG_RULE) > 0
    if not out["slug_rule"]:
        missing.append("slug rule")
    out["missing"] = missing
    return out


def compare(found: dict) -> list:
    return ["%s: binary %s, build.py %s" % (k, found[k], build.LIMITS[k]) for k in KEYS if k in found and found[k] != build.LIMITS[k]]


def main(argv) -> int:
    args = [a for a in argv if not a.startswith("--")]
    path = Path(args[0]) if args else find_binary()
    if path is None or not path.is_file():
        print("no Claude Code binary found; pass its path", file=sys.stderr)
        return 2
    found = probe(path.read_bytes())
    version = path.name if build.VERSION_RE.match(path.name) else "unknown"
    diffs = compare(found)
    report = {"binary": str(path), "version": version, "measured_on": build.SOURCE_VERSION, "found": found, "differences": diffs}
    if "--json" in argv:
        print(json.dumps(report, indent=1))
    else:
        print("binary %s (version %s), build.py measured on %s" % (path, version, build.SOURCE_VERSION))
        for k in KEYS:
            print("  %-18s %s" % (k, found.get(k, "-")))
        print("  slug rule          %s" % ("found" if found["slug_rule"] else "MISSING"))
        for d in diffs:
            print("DIFFERENCE %s" % d)
        for m in found["missing"]:
            print("MISSING ANCHOR %s" % m)
    return 2 if found["missing"] else (1 if diffs else 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
