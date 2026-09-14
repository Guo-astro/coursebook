#!/usr/bin/env python3
"""Unit tests for alt_lint.py. Pure stdlib unittest, no fixtures on disk
outside a temporary directory created per test."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import alt_lint  # noqa: E402


def write(root, relpath, content):
    path = os.path.join(root, relpath)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_basic_alt_found(self):
        write(self.root, "ch/ch.tex", (
            "\\begin{figure}[H]\n"
            "\\includegraphics[width=.5\\textwidth,alt={A simple drawing.}]{ch/drawings/a.eps}\n"
            "\\caption{A}\n"
            "\\end{figure}\n"
        ))
        results = alt_lint.scan(self.root)
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertFalse(r["_missing_alt"])
        self.assertEqual(r["alt"], "A simple drawing.")
        self.assertEqual(r["caption"], "A")
        self.assertEqual(r["path"], "ch/drawings/a.eps")

    def test_multiline_options(self):
        write(self.root, "ch/ch.tex", (
            "\\includegraphics[\n"
            "  width=.5\\textwidth,\n"
            "  alt={Spans\n"
            "  multiple lines.}\n"
            "]{ch/drawings/multi.eps}\n"
        ))
        results = alt_lint.scan(self.root)
        self.assertEqual(len(results), 1)
        self.assertIn("Spans", results[0]["alt"])
        self.assertIn("multiple lines.", results[0]["alt"])
        self.assertFalse(results[0]["_missing_alt"])

    def test_nested_braces_in_alt(self):
        write(self.root, "ch/ch.tex", (
            "\\includegraphics[width=1cm,alt={Nested {braces} inside {alt {text}}.}]{ch/n.eps}\n"
        ))
        results = alt_lint.scan(self.root)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["alt"], "Nested {braces} inside {alt {text}}.")

    def test_commented_out_include_is_skipped(self):
        write(self.root, "ch/ch.tex", (
            "% \\includegraphics[alt={should not count}]{ch/skip.eps}\n"
            "\\includegraphics[alt={real one}]{ch/real.eps}\n"
        ))
        results = alt_lint.scan(self.root)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["path"], "ch/real.eps")

    def test_comment_environment_is_skipped(self):
        write(self.root, "ch/ch.tex", (
            "\\begin{comment}\n"
            "\\includegraphics[alt={should not count}]{ch/skip.eps}\n"
            "\\end{comment}\n"
            "\\includegraphics[alt={real one}]{ch/real.eps}\n"
        ))
        results = alt_lint.scan(self.root)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["path"], "ch/real.eps")

    def test_escaped_percent_is_not_a_comment(self):
        write(self.root, "ch/ch.tex", (
            "\\includegraphics[alt={100\\% correct}]{ch/pct.eps}\n"
        ))
        results = alt_lint.scan(self.root)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["_missing_alt"])
        self.assertEqual(results[0]["alt"], "100\\% correct")
        # \% is a safe escape, so no leak warning.
        self.assertEqual(results[0]["_warnings"], [])

    def test_missing_alt_fails(self):
        write(self.root, "ch/ch.tex", (
            "\\includegraphics[width=1cm]{ch/noalt.eps}\n"
        ))
        results = alt_lint.scan(self.root)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["_missing_alt"])

    def test_empty_alt_fails(self):
        write(self.root, "ch/ch.tex", (
            "\\includegraphics[alt={}]{ch/empty.eps}\n"
        ))
        results = alt_lint.scan(self.root)
        self.assertTrue(results[0]["_missing_alt"])

    def test_whitespace_only_alt_fails(self):
        write(self.root, "ch/ch.tex", (
            "\\includegraphics[alt={   }]{ch/ws.eps}\n"
        ))
        results = alt_lint.scan(self.root)
        self.assertTrue(results[0]["_missing_alt"])

    def test_alt_equal_to_caption_warns(self):
        write(self.root, "ch/ch.tex", (
            "\\begin{figure}[H]\n"
            "\\includegraphics[alt={Malloc addition}]{ch/dup.eps}\n"
            "\\caption{Malloc addition}\n"
            "\\end{figure}\n"
        ))
        results = alt_lint.scan(self.root)
        self.assertFalse(results[0]["_missing_alt"])
        self.assertTrue(any("equals the figure caption" in w for w in results[0]["_warnings"]))

    def test_generic_alt_word_warns(self):
        write(self.root, "ch/ch.tex", (
            "\\includegraphics[alt={diagram}]{ch/generic.eps}\n"
        ))
        results = alt_lint.scan(self.root)
        self.assertTrue(any("generic word" in w for w in results[0]["_warnings"]))

    def test_unsafe_macro_in_alt_warns(self):
        write(self.root, "ch/ch.tex", (
            "\\includegraphics[alt={A \\textbf{bold} claim.}]{ch/macro.eps}\n"
        ))
        results = alt_lint.scan(self.root)
        self.assertTrue(any("textbf" in w for w in results[0]["_warnings"]))

    def test_safe_escapes_do_not_warn(self):
        write(self.root, "ch/ch.tex", (
            "\\includegraphics[alt={c\\_str and a '\\textbackslash 0' terminator.}]"
            "{ch/safe.eps}\n"
        ))
        results = alt_lint.scan(self.root)
        self.assertEqual(results[0]["_warnings"], [])

    def test_allowlisted_title_duck_is_excluded(self):
        write(self.root, "title.tex", (
            "\\let\\oldgraphics\\includegraphics\n"
            "\\renewcommand{\\includegraphics}[2][]{}\n"
            "\\includegraphics[width=10cm]{_images/duck-alpha-cropped.png}\n"
            "\\let\\includegraphics\\oldgraphics\n"
        ))
        results = alt_lint.scan(self.root)
        self.assertEqual(results, [])

    def test_non_allowlisted_title_image_still_checked(self):
        write(self.root, "title.tex", (
            "\\includegraphics[alt={a real content figure}]{title/other.eps}\n"
        ))
        results = alt_lint.scan(self.root)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["path"], "title/other.eps")

    def test_book_order_used_when_order_yaml_present(self):
        write(self.root, "order.yaml", "- b/b\n- a/a\n")
        write(self.root, "a/a.tex", "\\includegraphics[alt={in a}]{a/x.eps}\n")
        write(self.root, "b/b.tex", "\\includegraphics[alt={in b}]{b/x.eps}\n")
        results = alt_lint.scan(self.root)
        self.assertEqual([r["file"] for r in results], ["b/b.tex", "a/a.tex"])

    def test_no_figure_environment_gives_null_caption(self):
        write(self.root, "ch/ch.tex", (
            "\\includegraphics[alt={standalone}]{ch/standalone.eps}\n"
        ))
        results = alt_lint.scan(self.root)
        self.assertIsNone(results[0]["caption"])


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alt_lint.py")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, self.script, "--root", self.root, *args],
            capture_output=True, text=True,
        )

    def test_passes_and_json_shape(self):
        write(self.root, "ch/ch.tex", (
            "\\begin{figure}[H]\n"
            "\\includegraphics[alt={ok}]{ch/a.eps}\n"
            "\\caption{Cap}\n"
            "\\end{figure}\n"
        ))
        proc = self.run_cli("--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(len(data), 1)
        self.assertEqual(set(data[0].keys()), {"file", "line", "path", "alt", "caption"})

    def test_fails_on_missing_alt(self):
        write(self.root, "ch/ch.tex", "\\includegraphics[width=1cm]{ch/a.eps}\n")
        proc = self.run_cli()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("missing alt text", proc.stderr)


if __name__ == "__main__":
    unittest.main()
