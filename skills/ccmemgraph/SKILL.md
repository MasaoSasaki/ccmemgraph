---
name: ccmemgraph
description: Show Claude Code's auto memory for every project on this machine as one page - which memories the next session loads from MEMORY.md, which the index silently drops, which the index never lists, how old each one is, plus a force-directed graph of [[links]]. Use when the user asks to see, graph, visualize, inspect or audit auto memory, MEMORY.md, memory links, or what Claude remembers across projects.
model: haiku
effort: low
---

# ccmemgraph

Run the generator once and report its numbers. It reads every project's memory directory under the Claude Code config directory (`~/.claude/projects`, or `$CLAUDE_CONFIG_DIR/projects` when that variable is set), writes one self-contained HTML file and opens it. It never writes to the config directory and never touches the network.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/ccmemgraph/build.py"
```

If `python3` is not found (some Windows setups), run the same command with `python`. Add `--no-open` to skip opening the browser, `--out PATH` to choose where the HTML goes, `--root DIR` to scan a different projects directory.

The script prints one line each for project/file/link counts, memories per state, findings per kind, and the output path. Two more lines appear only when they apply: `claude code:` when the running Claude Code version differs from the one the limits were measured on, and `root:` when the projects directory does not exist. Relay the lines to the user as they are. Do not read or interpret the memory files themselves; the page is the deliverable.

When the user asks what a state or a finding means, answer from the definitions below and point at the page's Checks panel, which lists the affected files and lines. Do not guess beyond them.

States, judged from the files as they are now, so they describe the next session:

- `visible`: listed in MEMORY.md within the load window (the first 200 lines / 25,000 characters); the session knows it exists at start.
- `cut`: listed in MEMORY.md beyond the load window; the file exists but the session never hears of it.
- `unindexed`: on disk, not listed in MEMORY.md; only memory recall can surface it.
- `missing`: MEMORY.md or a `[[link]]` points at a file that does not exist.

Findings (`error`: content is lost; `warning`: content is not seen; `info`: cosmetic or an estimate):

- `index-over-limit` (error): MEMORY.md is longer than the load window, so its tail is cut off.
- `index-near-limit` (warning): MEMORY.md is at 80% or more of the load window.
- `index-cut` (warning): a memory listed beyond the load window (state `cut`).
- `unindexed` (warning): a memory not listed in MEMORY.md (state `unindexed`).
- `index-missing` (warning): a MEMORY.md line points at a file that does not exist.
- `file-over-limit` (warning): the file is longer than 4,096 characters; memory recall shows only the first 4,096. Its MEMORY.md line is unaffected.
- `recall-out` (warning): not among the project's 200 newest files by mtime, which is all memory recall scans.
- `dangling-link` (warning): a `[[link]]` with no file under any spelling.
- `duplicate-differs` (warning): the same file name in a project and one nested inside it, with different content.
- `unparsable` (warning): the frontmatter could not be read; the file is still shown under its file name.
- `link-mismatch` (info): a `[[link]]` spelled differently from the target's `name`.
- `duplicate-identical` (info): the same file, byte for byte, in several projects.
- `type-invalid` (info): `type` missing or not one of user / feedback / project / reference.
- `other-store` (info): the text mentions another project's directory, so it may have been written into the wrong project's store. An estimate.
