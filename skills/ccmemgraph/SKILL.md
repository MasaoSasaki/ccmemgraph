---
name: ccmemgraph
description: Show Claude Code's auto memory for every project on this machine as one page - which memories the next session loads from MEMORY.md, which the index silently drops, which the index never lists, how old each one is, plus a force-directed graph of [[links]]. Use when the user asks to see, graph, visualize, inspect or audit auto memory, MEMORY.md, memory links, or what Claude remembers across projects.
model: haiku
effort: low
---

# ccmemgraph

Run the generator once and report its numbers. It reads `~/.claude/projects/*/memory/`, writes one self-contained HTML file and opens it. It never writes to `~/.claude` and never touches the network.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/ccmemgraph/build.py"
```

If `python3` is not found (some Windows setups), run the same command with `python`. Add `--no-open` to skip opening the browser, `--out PATH` to choose where the HTML goes.

The script prints four lines: project/file/link counts, memories per state (visible / cut / unindexed / missing), findings per kind, and the output path. A fifth line starting with `claude code:` appears only when the running Claude Code version differs from the one the limits were measured on. Relay the lines to the user as they are. Do not read or interpret the memory files themselves; the page is the deliverable.
