"""Unit tests for check_pdf_tags.py's alt-text normalisation (B2).

The expected /Alt is the rendered form of the source alt= text, so an
escape that tagging copies through as typed is a mismatch. These run where
pikepdf is installed (the PDF CI job); elsewhere they are skipped.
"""
import unittest

try:
    import pikepdf  # noqa: F401
except ImportError:  # pragma: no cover
    pikepdf = None


@unittest.skipIf(pikepdf is None, "check_pdf_tags.py needs pikepdf")
class SourceToText(unittest.TestCase):
    def setUp(self):
        from _scripts import check_pdf_tags
        self.c = check_pdf_tags

    def check(self, source, rendered):
        self.assertEqual(self.c.source_to_text(source), rendered)

    def test_clean_escapes(self):
        self.check(r"c\_str is 100\% of a \& b, \$5, \#1, \{x\}", "c_str is 100% of a & b, $5, #1, {x}")

    def test_backslash_tilde_caret(self):
        self.check(r"'\textbackslash 0'", "'\\0'")
        self.check(r"\textasciitilde{}/x", "~/x")
        self.check(r"2\textasciicircum{}3", "2^3")

    def test_tie_is_a_space_but_textasciitilde_stays_a_tilde(self):
        self.check(r"a~b \textasciitilde", "a b ~")

    def test_quotes_dashes_ellipsis(self):
        self.check("a ``q'' b--c d---e \\ldots", "a \u201cq\u201d b\u2013c d\u2014e \u2026")

    def test_formatting_macros_keep_their_text(self):
        self.check(r"\emph{x} and \texttt{y}", "x and y")

    def test_whitespace_is_collapsed(self):
        self.check("a\n   b\tc", "a b c")

    def test_leaked_macro_is_detected(self):
        self.assertTrue(self.c.LEAK.search("the terminating '\\textbackslash 0'"))
        self.assertIsNone(self.c.LEAK.search("the terminating null byte"))


if __name__ == "__main__":
    unittest.main()
