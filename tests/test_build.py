"""Tests for build.py against the demo fixtures and synthetic edge cases.

Run: python3 -m unittest discover -s tests -v
"""
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "ccmemgraph"))
sys.path.insert(0, str(ROOT / "tests"))
import build  # noqa: E402

DEMO = ROOT / "fixtures" / "demo"
import datetime as dt

NOW_MS = dt.datetime(2026, 10, 10, tzinfo=dt.timezone.utc).timestamp() * 1000  # fixed clock, so ages in the demo are stable


def scan_demo(root=DEMO / "projects"):
    return build.scan(root, fs_root=str(DEMO / "fs"), home="/home/demo", now_ms=NOW_MS)


def kinds(model):
    out = {}
    for i in model["issues"]:
        out[i["kind"]] = out.get(i["kind"], 0) + 1
    return out


def copy_demo(tmp):
    dst = Path(tmp) / "projects"
    shutil.copytree(DEMO / "projects", dst)
    set_mtimes(dst)
    return dst


def set_mtimes(root):
    """Deterministic mtimes: later file name -> newer mtime, so the recall ranking is stable."""
    for i, p in enumerate(sorted(root.rglob("*.md"))):
        os.utime(p, (NOW_MS / 1000 - 100000 + i, NOW_MS / 1000 - 100000 + i))


class TruncateIndex(unittest.TestCase):
    def test_under_both_limits_keeps_everything(self):
        t = build.truncate_index("\n".join("- [n](f%d.md)" % i for i in range(200)))
        self.assertEqual(t["kept_lines"], 200)
        self.assertEqual(t["cut_lines"], 0)
        self.assertIsNone(t["cut_from_line"])

    def test_line_201_is_cut(self):
        t = build.truncate_index("\n".join("- [n](f%d.md)" % i for i in range(201)))
        self.assertEqual((t["kept_lines"], t["cut_lines"], t["cut_from_line"]), (200, 1, 201))
        self.assertTrue(t["by_lines"])
        self.assertFalse(t["by_chars"])

    def test_char_limit_cuts_at_previous_newline(self):
        line = "- [t](f.md) " + "x" * 1238  # 1250 chars per line -> 20 lines reach 25,000
        t = build.truncate_index("\n".join(line for _ in range(21)))
        self.assertTrue(t["by_chars"])
        self.assertFalse(t["by_lines"])
        self.assertEqual(t["kept_lines"], 19)  # 20 lines = 25,019 units including newlines, so the 20th goes
        self.assertEqual(t["cut_from_line"], 20)

    def test_surrogate_pairs_count_double(self):
        self.assertEqual(build.utf16_len("a\U0001F600b"), 4)
        self.assertEqual(build.utf16_index("a\U0001F600b", 3), 2)
        t = build.truncate_index("\U0001F600" * 12500 + "\n- [t](f.md)")  # 25,000 units on line 1 alone
        self.assertEqual(t["kept_lines"], 1)
        self.assertEqual(t["cut_from_line"], 2)

    def test_cut_inside_line_one(self):
        t = build.truncate_index("x" * 30000)
        self.assertEqual(t["kept_lines"], 0)
        self.assertEqual(t["cut_from_line"], 1)

    def test_empty_index(self):
        t = build.truncate_index("")
        self.assertEqual((t["total_lines"], t["kept_lines"], t["cut_lines"]), (0, 0, 0))


class Frontmatter(unittest.TestCase):
    def test_nested_metadata_type(self):
        meta, body, ok = build.parse_frontmatter("---\nname: a\nmetadata:\n  type: feedback\n  modified: 2026-01-01T00:00:00Z\n---\nbody")
        self.assertTrue(ok)
        self.assertEqual((meta["type"], meta["modified"], body), ("feedback", "2026-01-01T00:00:00Z", "body"))

    def test_top_level_wins(self):
        meta, _, _ = build.parse_frontmatter("---\ntype: user\nmetadata:\n  type: feedback\n---\n")
        self.assertEqual(meta["type"], "user")

    def test_unclosed(self):
        _, _, ok = build.parse_frontmatter("---\nname: a\n\nbody")
        self.assertFalse(ok)

    def test_no_frontmatter_is_fine(self):
        meta, body, ok = build.parse_frontmatter("# just text")
        self.assertTrue(ok)
        self.assertEqual(meta, {})


class Slugs(unittest.TestCase):
    def test_roundtrip_with_underscore_and_dot(self):
        with tempfile.TemporaryDirectory() as tmp:
            for rel in ["Users/me/Projects/pocket_ledger_mono", "Users/me/Projects/pocket-ledger", "Users/me/.claude"]:
                (Path(tmp) / rel).mkdir(parents=True)
            self.assertEqual(build.resolve_slug("-Users-me-Projects-pocket-ledger-mono", tmp), "/Users/me/Projects/pocket_ledger_mono")
            self.assertEqual(build.resolve_slug("-Users-me-Projects-pocket-ledger", tmp), "/Users/me/Projects/pocket-ledger")
            self.assertEqual(build.resolve_slug("-Users-me--claude", tmp), "/Users/me/.claude")
            self.assertIsNone(build.resolve_slug("-Users-me-Projects-gone", tmp))

    def test_display_path(self):
        self.assertEqual(build.display_path("/home/demo/Projects/alpha", "x", "/home/demo"), "~/Projects/alpha")
        self.assertEqual(build.display_path("/home/demo", "x", "/home/demo"), "~")
        self.assertEqual(build.display_path(None, "-slug", "/home/demo"), "-slug")


class DemoFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.root = copy_demo(cls.tmp)
        cls.model = scan_demo(cls.root)
        cls.kinds = kinds(cls.model)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def project(self, slug):
        return next(p for p in self.model["projects"] if p["project"] == slug)

    def test_every_kind_is_present(self):
        for kind in build.SEVERITY:
            self.assertIn(kind, self.kinds, kind)

    def test_states(self):
        self.assertEqual(self.model["states"], {"visible": 399, "cut": 14, "unindexed": 2, "missing": 2})
        self.assertEqual(self.project("-home-demo-Projects-epsilon")["index_ratio"], 165 / 200)
        beta = self.project("-home-demo-Projects-beta")
        self.assertEqual(beta["states"], {"visible": 200, "cut": 10, "unindexed": 2, "missing": 1})
        self.assertEqual((beta["index_lines"], beta["index_kept_lines"], beta["index_cut_from"]), (211, 200, 201))
        delta = self.project("-home-demo-Projects-delta")
        self.assertEqual(delta["states"]["cut"], 4)
        self.assertEqual(delta["index_lines"], 24)

    def test_labels_resolve_through_fake_fs(self):
        self.assertEqual(self.project("-home-demo-Projects-alpha")["label"], "~/Projects/alpha")
        self.assertEqual(self.project("-home-demo")["label"], "~")

    def test_recall_out_is_the_oldest_by_mtime(self):
        beta = [n for n in self.model["nodes"] if n["project"] == "-home-demo-Projects-beta" and n["state"] != "missing"]
        out = {n["file"] for n in beta if n["recall_out"]}
        oldest = {n["file"] for n in sorted(beta, key=lambda n: n["mtime_ms"])[:12]}
        self.assertEqual(out, oldest)
        self.assertEqual(self.project("-home-demo-Projects-beta")["recall_out"], 12)

    def test_age_uses_modified_then_mtime(self):
        n = next(n for n in self.model["nodes"] if n["file"] == "feedback_no_force_push.md")
        self.assertEqual(n["modified_from"], "frontmatter")
        self.assertAlmostEqual(n["age_days"], (NOW_MS - dt.datetime(2026, 3, 12, 9, tzinfo=dt.timezone.utc).timestamp() * 1000) / 86400000, places=3)
        broken = next(n for n in self.model["nodes"] if n["file"] == "broken.md")
        self.assertEqual(broken["modified_from"], "mtime")

    def test_other_store_points_at_alpha_from_home(self):
        found = [i for i in self.model["issues"] if i["kind"] == "other-store"]
        self.assertEqual([(i["project"], i["file"], i["evidence"]) for i in found], [("-home-demo", "project_alpha_release_plan.md", "~/Projects/alpha")])

    def test_each_kind_disappears_when_its_cause_is_removed(self):
        cases = {
            "index-cut": lambda r: trim_index(r / "-home-demo-Projects-beta" / "memory" / "MEMORY.md", 200) or trim_index(r / "-home-demo-Projects-delta" / "memory" / "MEMORY.md", 19),
            "index-over-limit": lambda r: trim_index(r / "-home-demo-Projects-beta" / "memory" / "MEMORY.md", 200) or trim_index(r / "-home-demo-Projects-delta" / "memory" / "MEMORY.md", 19),
            "index-near-limit": lambda r: trim_index(r / "-home-demo-Projects-epsilon" / "memory" / "MEMORY.md", 100),
            "index-missing": lambda r: drop_index_line(r / "-home-demo-Projects-beta" / "memory" / "MEMORY.md", "project_note_999.md"),
            "unindexed": lambda r: append_index(r / "-home-demo-Projects-beta" / "memory" / "MEMORY.md", ["- [s1](feedback_stray_one.md) — x", "- [s2](reference_stray_two.md) — y"]),
            "file-over-limit": lambda r: rewrite(r / "-home-demo-Projects-gamma" / "memory" / "reference_api_notes.md", lambda t: t[:1000]),
            "recall-out": lambda r: [p.unlink() for p in sorted((r / "-home-demo-Projects-beta" / "memory").glob("project_note_*.md"))[:12]],
            "dangling-link": lambda r: rewrite(r / "-home-demo" / "memory" / "reference_machine_names.md", lambda t: t.replace("[[homeserver-notes]]", "the notes")),
            "link-mismatch": lambda r: rewrite(r / "-home-demo-Projects-alpha" / "memory" / "project_release_checklist.md", lambda t: t.replace("[[feedback_no_force_push]]", "[[no-force-push]]")),
            "duplicate-identical": lambda r: (r / "-home-demo-Projects-gamma" / "memory" / "reference_ci_pipeline.md").unlink(),
            "duplicate-differs": lambda r: (r / "-home-demo" / "memory" / "reference_editor_settings.md").unlink(),
            "type-invalid": lambda r: (rewrite(r / "-home-demo-Projects-gamma" / "memory" / "ops_deploy_window.md", lambda t: t.replace("type: ops", "type: project")),
                                       (r / "-home-demo-Projects-gamma" / "memory" / "broken.md").unlink()),
            "unparsable": lambda r: (r / "-home-demo-Projects-gamma" / "memory" / "broken.md").unlink(),
            "other-store": lambda r: rewrite(r / "-home-demo" / "memory" / "project_alpha_release_plan.md", lambda t: t.replace("~/Projects/alpha", "the alpha repo")),
        }
        self.assertEqual(set(cases), set(build.SEVERITY))
        for kind, mutate in cases.items():
            with tempfile.TemporaryDirectory() as tmp:
                root = copy_demo(tmp)
                mutate(root)
                after = kinds(scan_demo(root))
                self.assertNotIn(kind, after, kind)

    def test_results_do_not_depend_on_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_demo(tmp)
            for p in root.rglob("*.md"):
                if p.name != "MEMORY.md":
                    rewrite(p, lambda t: re.sub(r"\[\[[^\]]+\]\]", "x", t))
            set_mtimes(root)
            stripped = scan_demo(root)
        link_kinds = {"dangling-link", "link-mismatch"}
        self.assertEqual(stripped["links"], [])
        self.assertEqual({k: v for k, v in kinds(stripped).items() if k not in link_kinds},
                         {k: v for k, v in self.kinds.items() if k not in link_kinds})
        real = {n["id"]: (n["state"], round(n["age_days"] or 0, 6), n["recall_out"]) for n in self.model["nodes"] if n["file"]}
        after = {n["id"]: (n["state"], round(n["age_days"] or 0, 6), n["recall_out"]) for n in stripped["nodes"] if n["file"]}
        self.assertEqual(real, after)

    def test_render_is_self_contained(self):
        html = build.render(self.model, ROOT / "skills" / "ccmemgraph")
        self.assertNotIn("__DATA__", html)
        self.assertNotIn("__D3__", html)
        self.assertEqual(re.findall(r"<(?:script|link)[^>]+(?:src|href)=\"https?://", html), [])
        self.assertIn("ccmemgraph", html)


class Robustness(unittest.TestCase):
    def test_empty_and_odd_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "-a" ).mkdir()                       # project without memory dir
            (root / "-b" / "memory").mkdir(parents=True)  # empty memory dir
            (root / "-c" / "memory").mkdir(parents=True)  # memory without index
            (root / "-c" / "memory" / "x.md").write_text("no frontmatter at all")
            model = build.scan(root, fs_root=tmp, home="/nowhere", now_ms=NOW_MS)
            self.assertEqual(len(model["projects"]), 2)
            self.assertEqual(model["states"], {"visible": 0, "cut": 0, "unindexed": 1, "missing": 0})
            self.assertEqual(build.summary_lines(model, Path("/o.html"))[0], "projects=2 files=1 links=0")

    def test_missing_root_is_said_not_hidden(self):
        model = build.scan_empty(Path("/does/not/exist"))
        self.assertEqual(model["projects"], [])
        self.assertTrue(model["root_missing"])
        self.assertIn("root: /does/not/exist does not exist; nothing was scanned", build.summary_lines(model, Path("/o.html")))
        self.assertIn('"root_missing": true', build.render(model, ROOT / "skills" / "ccmemgraph"))
        self.assertIn('"root_missing": false', build.render(scan_demo(), ROOT / "skills" / "ccmemgraph"))

    def test_default_root_follows_claude_config_dir(self):
        with unittest.mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/cfg/work"}):
            self.assertEqual(build.default_projects_root(), Path("/cfg/work/projects"))
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(build.default_projects_root(), Path.home() / ".claude" / "projects")


def rewrite(path, fn):
    path.write_text(fn(path.read_text(encoding="utf-8")), encoding="utf-8")


def trim_index(path, keep):
    lines = path.read_text(encoding="utf-8").split("\n")
    path.write_text("\n".join(lines[:keep]) + "\n", encoding="utf-8")


def drop_index_line(path, needle):
    rewrite(path, lambda t: "\n".join(l for l in t.split("\n") if needle not in l))


def append_index(path, lines):
    rewrite(path, lambda t: t.rstrip("\n") + "\n" + "\n".join(lines) + "\n")


if __name__ == "__main__":
    unittest.main()


class ClaudeCodeVersionTests(unittest.TestCase):
    """The limits are measured on one Claude Code version; the page must say so and the probe must still read them."""

    def test_running_version_comes_from_execpath(self):
        with unittest.mock.patch.dict(os.environ, {"CLAUDE_CODE_EXECPATH": "/x/versions/2.1.300"}):
            self.assertEqual(build.running_claude_code_version(), "2.1.300")

    def test_summary_mentions_running_version_only_when_it_differs(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = build.scan(Path(tmp), fs_root=tmp, home="/nowhere", now_ms=NOW_MS)
        model["claude_code"] = build.claude_code_info(build.SOURCE_VERSION)
        self.assertEqual(len(build.summary_lines(model, Path("o"))), 4)
        model["claude_code"] = build.claude_code_info("9.9.9")
        lines = build.summary_lines(model, Path("o"))
        self.assertEqual(len(lines), 5)
        self.assertIn("running 9.9.9, limits measured on " + build.SOURCE_VERSION, lines[3])

    def test_docs_state_the_measured_version(self):
        self.assertIn("Claude Code " + build.SOURCE_VERSION, (ROOT / "README.md").read_text())
        plugin = (ROOT / ".claude-plugin" / "plugin.json").read_text()
        version = re.search(r'"version":\s*"([^"]+)"', plugin).group(1)
        self.assertIn("## [%s]" % version, (ROOT / "CHANGELOG.md").read_text())

    def test_skill_defines_every_state_and_finding_kind(self):
        """The skill answers "what does this mean" from SKILL.md, so every state and kind needs a definition there."""
        skill = (ROOT / "skills" / "ccmemgraph" / "SKILL.md").read_text(encoding="utf-8")
        for state in build.STATES:
            self.assertRegex(skill, r"(?m)^- `%s`: " % state, msg=state)
        for kind, severity in build.SEVERITY.items():
            self.assertRegex(skill, r"(?m)^- `%s` \(%s\): " % (kind, severity), msg=kind)

    def test_probe_reads_a_synthetic_limits_statement(self):
        import limits_probe
        src = (b'xx;var Qz="MEMORY.md",aB=210,cD=26000,eF=4*cD,gH=150,iJ=5000;function f(){}'
               b'.filter(z).slice(0,7),[a,b]=await q();return[...a.length>0?[{type:"relevant_memories",memories:a}]:[]]'
               b'replace(/[^a-zA-Z0-9]/g,"-")')
        found = limits_probe.probe(src)
        self.assertEqual((found["index_lines"], found["index_chars"], found["index_read_chars"], found["recall_scan_files"],
                          found["file_chars"], found["recall_per_turn"], found["slug_rule"], found["missing"]),
                         (210, 26000, 104000, 150, 5000, 7, True, []))
        self.assertEqual(len(limits_probe.compare(found)), 6)
        self.assertEqual(limits_probe.probe(b"nothing here")["missing"], ["limits statement (0 matches)", "per-turn cap", "slug rule"])

    def test_installed_claude_code_still_has_the_measured_limits(self):
        import limits_probe
        binary = limits_probe.find_binary()
        if binary is None:
            self.skipTest("no Claude Code binary on this machine")
        found = limits_probe.probe(binary.read_bytes())
        self.assertEqual(found["missing"], [], "anchors not found in %s" % binary)
        self.assertEqual(limits_probe.compare(found), [], "limits in %s differ from build.py" % binary)


class PerformanceTests(unittest.TestCase):
    """N-3: 1,000 memory files / 5 MB must scan and render within one second."""

    def test_thousand_files_render_within_one_second(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "projects"
            for p in range(10):
                d = root / ("-home-demo-Projects-p%d" % p) / "memory"
                d.mkdir(parents=True)
                index = []
                for i in range(100):
                    body = ("---\nname: note-%d\ndescription: d\nmetadata:\n  type: project\n  modified: 2026-09-01T00:00:00Z\n---\n" % i
                            + ("x" * 100 + " [[note-%d]]\n" % ((i + 1) % 100)) * 48)  # ~5.5 KB per file
                    (d / ("project_note_%d.md" % i)).write_text(body, encoding="utf-8")
                    index.append("- [n%d](project_note_%d.md) — d" % (i, i))
                (d / "MEMORY.md").write_text("\n".join(index) + "\n", encoding="utf-8")
            start = time.perf_counter()
            model = build.scan(root, fs_root=tmp, home="/home/demo", now_ms=NOW_MS)
            build.render(model, ROOT / "skills" / "ccmemgraph")
            elapsed = time.perf_counter() - start
        self.assertEqual(len(model["nodes"]), 1000)
        self.assertLess(elapsed, 1.0, "scan + render took %.2fs" % elapsed)
