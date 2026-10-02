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
            "\\includegraphics[alt={c\\_str is 100\\% of it \\& more\\ldots}]"
            "{ch/safe.eps}\n"
        ))
        results = alt_lint.scan(self.root)
        self.assertEqual(results[0]["_warnings"], [])

    def test_escapes_that_leak_into_pdf_alt_warn(self):
        # Tagging copies these into /Alt as typed ("\\textbackslash 0").
        for esc in ("\\textbackslash", "\\textasciitilde", "\\textasciicircum"):
            with self.subTest(esc=esc):
                write(self.root, "ch/ch.tex", (
                    "\\includegraphics[alt={the terminating '" + esc + " 0'.}]"
                    "{ch/leak.eps}\n"
                ))
                results = alt_lint.scan(self.root)
                self.assertTrue(any(esc in w for w in results[0]["_warnings"]),
                                results[0]["_warnings"])

    def test_tex_quotes_dashes_and_math_warn(self):
        for alt, what in (("a ``quoted'' word", "TeX quotes"),
                          ("pages 1--2", "TeX dash"),
                          ("costs $n^2$", "inline math")):
            with self.subTest(alt=alt):
                write(self.root, "ch/ch.tex",
                      "\\includegraphics[alt={" + alt + "}]{ch/lit.eps}\n")
                results = alt_lint.scan(self.root)
                self.assertTrue(any(what in w for w in results[0]["_warnings"]),
                                results[0]["_warnings"])

    def test_escaped_dollar_is_not_math(self):
        write(self.root, "ch/ch.tex",
              "\\includegraphics[alt={costs \\$5}]{ch/dollar.eps}\n")
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

    def test_extra_whitespace_around_equals(self):
        write(self.root, "ch/ch.tex", (
            "\\includegraphics[width=1cm,alt  =  {A real description}]{ch/a.eps}\n"
        ))
        results = alt_lint.scan(self.root)
        self.assertFalse(results[0]["_missing_alt"])
        self.assertEqual(results[0]["alt"], "A real description")

    def test_duplicate_key_last_one_wins(self):
        write(self.root, "ch/ch.tex", (
            "\\includegraphics[alt={stale},alt={fresh}]{ch/a.eps}\n"
        ))
        results = alt_lint.scan(self.root)
        self.assertEqual(results[0]["alt"], "fresh")

    def test_starred_includegraphics_is_scanned(self):
        write(self.root, "ch/ch.tex", (
            "\\includegraphics*[width=1cm,alt={starred works}]{ch/a.eps}\n"
        ))
        results = alt_lint.scan(self.root)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["alt"], "starred works")

    def test_caption_with_short_title_is_found(self):
        write(self.root, "ch/ch.tex", (
            "\\begin{figure}[H]\n"
            "\\includegraphics[alt={x}]{ch/a.eps}\n"
            "\\caption[Short]{The long caption}\n"
            "\\end{figure}\n"
        ))
        results = alt_lint.scan(self.root)
        self.assertEqual(results[0]["caption"], "The long caption")

    def test_caption_with_space_before_brace_is_found(self):
        write(self.root, "ch/ch.tex", (
            "\\begin{figure}[H]\n"
            "\\includegraphics[alt={x}]{ch/a.eps}\n"
            "\\caption {The caption}\n"
            "\\end{figure}\n"
        ))
        results = alt_lint.scan(self.root)
        self.assertEqual(results[0]["caption"], "The caption")

    def test_two_image_caption_pairs_in_one_figure(self):
        write(self.root, "ch/ch.tex", (
            "\\begin{figure}[H]\n"
            "\\includegraphics[alt={Before}]{ch/a.eps}\n"
            "\\caption{Before}\n"
            "\\includegraphics[alt={After}]{ch/b.eps}\n"
            "\\caption{After}\n"
            "\\end{figure}\n"
        ))
        results = alt_lint.scan(self.root)
        self.assertEqual(len(results), 2)
        by_path = {r["path"]: r for r in results}
        self.assertEqual(by_path["ch/a.eps"]["caption"], "Before")
        self.assertEqual(by_path["ch/b.eps"]["caption"], "After")

    def test_commented_out_comment_marker_does_not_eat_real_include(self):
        # A `% \begin{comment}` is a dead marker (the % comments it out),
        # not a live environment start -- it must not cause everything up
        # to the next literal "\end{comment}" (live or not) to be blanked.
        write(self.root, "ch/ch.tex", (
            "% \\begin{comment}\n"
            "\\includegraphics[width=1cm]{ch/real.eps}\n"
            "% \\end{comment}\n"
        ))
        results = alt_lint.scan(self.root)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["path"], "ch/real.eps")
        self.assertTrue(results[0]["_missing_alt"])

    def test_lstlisting_body_is_not_scanned(self):
        write(self.root, "ch/ch.tex", (
            "\\begin{lstlisting}\n"
            "\\includegraphics{demo-figure.eps}\n"
            "\\end{lstlisting}\n"
        ))
        results = alt_lint.scan(self.root)
        self.assertEqual(results, [])

    def test_book_order_expands_input_chain(self):
        write(self.root, "order.yaml", "- ch/ch\n")
        write(self.root, "ch/ch.tex", (
            "\\input{ch/first.tex}\n"
            "\\input{ch/second.tex}\n"
        ))
        write(self.root, "ch/first.tex", "\\includegraphics[alt={one}]{ch/1.eps}\n")
        write(self.root, "ch/second.tex", "\\includegraphics[alt={two}]{ch/2.eps}\n")
        results = alt_lint.scan(self.root)
        self.assertEqual([r["file"] for r in results], ["ch/first.tex", "ch/second.tex"])

    def test_zero_tex_files_raises(self):
        with self.assertRaises(RuntimeError):
            alt_lint.scan(self.root)

    def test_unterminated_option_list_is_reported(self):
        # The truncated `[` swallows the alt= key, so skipping this in
        # silence (as the scanner used to) hides the figure from the gate.
        write(self.root, "ch/ch.tex", (
            "\\includegraphics[width=1cm,alt={A drawing.}{ch/a.eps}\n"
        ))
        results = alt_lint.scan(self.root)
        self.assertEqual(len(results), 1)
        self.assertIn("unterminated [...] option list", results[0]["_malformed"])
        self.assertEqual(results[0]["path"], "")

    def test_missing_path_group_is_reported(self):
        write(self.root, "ch/ch.tex", "\\includegraphics[width=1cm]\n\\par\n")
        results = alt_lint.scan(self.root)
        self.assertEqual(len(results), 1)
        self.assertIn("no {path} group", results[0]["_malformed"])

    def test_unterminated_path_group_is_reported(self):
        write(self.root, "ch/ch.tex", "\\includegraphics[alt={ok}]{ch/a.eps\n")
        results = alt_lint.scan(self.root)
        self.assertEqual(len(results), 1)
        self.assertIn("unterminated {path} group", results[0]["_malformed"])

    def test_title_macro_hacks_are_not_malformed(self):
        # title.tex mentions \includegraphics without calling it; those are
        # not includes at all and must not be reported as malformed.
        write(self.root, "title.tex", (
            "\\let\\oldgraphics\\includegraphics\n"
            "\\renewcommand{\\includegraphics}[2][]{}\n"
            "\\let\\includegraphics\\oldgraphics\n"
        ))
        results = alt_lint.scan(self.root)
        self.assertEqual(results, [])

    def test_unbraced_macro_definition_is_not_malformed(self):
        # \newcommand\includegraphics[2][]{}: the [2] is the argument count,
        # not an option list, so this definition is not a call.
        for definition in ("\\newcommand\\includegraphics[2][]{}",
                           "\\renewcommand\\includegraphics[2][]{}",
                           "\\providecommand\\includegraphics[2][]{}",
                           "\\def\\includegraphics[2]{}"):
            with self.subTest(definition=definition):
                write(self.root, "ch/ch.tex", definition + "\n")
                self.assertEqual(alt_lint.scan(self.root), [])

    def test_star_after_space_is_scanned(self):
        # LaTeX's \@ifstar skips spaces, so this is a legal starred call and
        # must not slip past the gate unscanned.
        write(self.root, "ch/ch.tex",
              "\\includegraphics *[alt={A drawing.}]{ch/a.eps}\n")
        results = alt_lint.scan(self.root)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["path"], "ch/a.eps")
        self.assertEqual(results[0]["alt"], "A drawing.")
        self.assertIsNone(results[0]["_malformed"])

    def test_order_yaml_entry_with_comment_or_quotes_or_suffix(self):
        # All three are valid YAML for the same chapter. Reading them
        # literally used to invent a chapter name no file matched, which
        # then failed every real figure in that chapter as unreachable.
        for entry in ("- ch/ch # the intro chapter\n", '- "ch/ch"\n',
                      "- 'ch/ch'\n", "- ch/ch.tex\n"):
            with self.subTest(entry=entry):
                write(self.root, "order.yaml", entry)
                write(self.root, "ch/ch.tex",
                      "\\includegraphics[alt={ok}]{ch/a.eps}\n")
                results = alt_lint.scan(self.root)
                self.assertEqual(len(results), 1)
                self.assertIsNone(results[0]["_unreachable"])

    def test_missing_chapter_file_does_not_orphan_real_ones(self):
        write(self.root, "order.yaml", "- ch/gone\n- ch/ch\n")
        write(self.root, "ch/ch.tex", "\\includegraphics[alt={ok}]{ch/a.eps}\n")
        results = alt_lint.scan(self.root)
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0]["_unreachable"])

    def test_file_reached_only_through_main_tex_is_reachable(self):
        # main.tex \include's title.tex, which no chapter reaches; a figure
        # there is still in the PDF and the EPUB.
        write(self.root, "order.yaml", "- ch/ch\n")
        write(self.root, "main.tex", "\\include{extra}\n\\input{order.tex}\n")
        write(self.root, "ch/ch.tex", "\\includegraphics[alt={ok}]{ch/a.eps}\n")
        write(self.root, "extra.tex", "\\includegraphics[alt={logo}]{ch/b.eps}\n")
        results = alt_lint.scan(self.root)
        by_file = {r["file"]: r for r in results}
        self.assertIsNone(by_file["extra.tex"]["_unreachable"])
        self.assertIsNone(by_file["ch/ch.tex"]["_unreachable"])

    def test_unreachable_figure_is_reported(self):
        write(self.root, "order.yaml", "- ch/ch\n")
        write(self.root, "ch/ch.tex", "\\includegraphics[alt={in the book}]{ch/a.eps}\n")
        write(self.root, "orphan/orphan.tex", "\\includegraphics[alt={orphan}]{orphan/b.eps}\n")
        results = alt_lint.scan(self.root)
        by_file = {r["file"]: r for r in results}
        self.assertIsNone(by_file["ch/ch.tex"]["_unreachable"])
        self.assertIn("order.yaml", by_file["orphan/orphan.tex"]["_unreachable"])

    def test_figure_reached_through_input_chain_is_reachable(self):
        write(self.root, "order.yaml", "- ch/ch\n")
        write(self.root, "ch/ch.tex", "\\input{ch/sub.tex}\n")
        write(self.root, "ch/sub.tex", "\\includegraphics[alt={deep}]{ch/a.eps}\n")
        results = alt_lint.scan(self.root)
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0]["_unreachable"])

    def test_no_order_yaml_skips_reachability(self):
        # Without order.yaml there is nothing to be reachable from, so the
        # check has to stay quiet rather than fail every figure.
        write(self.root, "ch/ch.tex", "\\includegraphics[alt={ok}]{ch/a.eps}\n")
        results = alt_lint.scan(self.root)
        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0]["_unreachable"])


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

    def test_fails_on_malformed_include(self):
        write(self.root, "ch/ch.tex", "\\includegraphics[alt={x}{ch/a.eps}\n")
        proc = self.run_cli()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("malformed", proc.stderr)

    def test_fails_on_unreachable_figure(self):
        write(self.root, "order.yaml", "- ch/ch\n")
        write(self.root, "ch/ch.tex", "\\includegraphics[alt={ok}]{ch/a.eps}\n")
        write(self.root, "orphan/orphan.tex", "\\includegraphics[alt={orphan}]{orphan/b.eps}\n")
        proc = self.run_cli()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("order.yaml", proc.stderr)

    def test_malformed_include_absent_from_json(self):
        write(self.root, "ch/ch.tex", (
            "\\includegraphics[alt={good}]{ch/a.eps}\n"
            "\\includegraphics[alt={bad}{ch/b.eps}\n"
        ))
        proc = self.run_cli("--json")
        self.assertEqual(proc.returncode, 1)
        data = json.loads(proc.stdout)
        self.assertEqual([d["path"] for d in data], ["ch/a.eps"])


if __name__ == "__main__":
    unittest.main()
