# Changelog

All notable changes to ccmemgraph are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). The version here
matches `version` in `.claude-plugin/plugin.json`.

## [1.0.0] - 2026-10-10

### Added

- `/ccmemgraph` skill: renders every project's auto memory under
  `~/.claude/projects/*/memory` as one HTML page and opens it.
- Graph view: one node per memory file, colour is age, a red or yellow ring
  marks files the next session will not see in `MEMORY.md` (cut by the
  200-line / 25,000-character limit, or not indexed), dashed circles are
  missing files, size is in-links.
- Checks panel: the load window per project with the exact lines Claude Code
  cuts, plus findings for files over the 4,096-character recall limit,
  memories outside the recall scan, broken `[[links]]`, duplicates across
  projects, invalid `type` values and memories written into another
  project's store.
- Table panel: the same data sortable by age, size, links and project.
- Light and dark mode, no network access, D3 7.9.0 bundled into the page.
- Python 3.9+ standard library only; tested on 3.9 and 3.13.

[1.0.0]: https://github.com/MasaoSasaki/ccmemgraph/releases/tag/v1.0.0
