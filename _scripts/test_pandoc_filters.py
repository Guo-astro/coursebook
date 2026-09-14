#!/usr/bin/env python3

"""
Gate A1 of issue #238: unit tests for the pandoc image filters.

Tiny LaTeX fixtures go through `pandoc -f latex -t json` and then each
filter, in-process, so the tests exercise the real pandoc AST (Figure,
alt= handling) and panflute version the build uses. A few end-to-end
cases also run the filters through `pandoc --filter`, as the build does.

Needs pandoc and requirements.txt. Run from anywhere:
    python3 -m unittest _scripts.test_pandoc_filters -v
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

# pandoc_header_filter reads this at import time.
_cache = tempfile.NamedTemporaryFile(suffix='.yaml', delete=False)
_cache.close()
os.unlink(_cache.name)
os.environ.setdefault('LINK_CACHE_FILE_NAME', _cache.name)

import panflute as pf  # noqa: E402

import alt_text  # noqa: E402
import alt_check_common  # noqa: E402
import epub_cover_alt  # noqa: E402
import gen_wiki  # noqa: E402
import pandoc_epub_filter  # noqa: E402
import pandoc_header_filter  # noqa: E402
import pandoc_wiki_filter  # noqa: E402

# A real figure, so the filters' "does the .png exist" check passes.
EPS = 'malloc/drawings/heap_empty.eps'
PNG = 'malloc/drawings/heap_empty.png'


def latex_doc(body):
    return ('\\documentclass{book}\n\\usepackage{graphicx}\n'
            '\\begin{document}\n' + body + '\n\\end{document}\n')


def figure(options, caption=None, path=EPS):
    cap = '\\caption{' + caption + '}\n' if caption is not None else ''
    return ('\\begin{figure}[H]\n\\centering\n\\includegraphics[' + options
            + ']{' + path + '}\n' + cap + '\\end{figure}\n')


def to_doc(body):
    out = subprocess.run(['pandoc', '-f', 'latex', '-t', 'json'],
                         input=latex_doc(body), capture_output=True,
                         text=True, check=True, cwd=ROOT)
    return pf.load(io.StringIO(out.stdout))


def images(doc):
    found = []
    doc.walk(lambda e, d: found.append(e) if isinstance(e, pf.Image) else None)
    return found


class FilterTestCase(unittest.TestCase):
    def setUp(self):
        # The filters check image paths relative to the repo root.
        self._cwd = os.getcwd()
        os.chdir(ROOT)

    def tearDown(self):
        os.chdir(self._cwd)

    def run_epub(self, body):
        return pf.run_filter(pandoc_epub_filter.doc_filter,
                             finalize=pandoc_epub_filter.finalize,
                             doc=to_doc(body))

    def run_wiki(self, body):
        return pf.run_filter(pandoc_wiki_filter.doc_filter, doc=to_doc(body))

    def run_header(self, body):
        return pf.run_filter(pandoc_header_filter.output_yaml, doc=to_doc(body))

    def all_filters(self):
        return (('epub', self.run_epub), ('wiki', self.run_wiki),
                ('header', self.run_header))


class TestAltSource(FilterTestCase):
    def test_alt_key_wins_over_caption(self):
        body = figure('width=.5\\textwidth,alt={Seven heap blocks}', 'Empty heap')
        for name, run in self.all_filters():
            with self.subTest(filter=name):
                doc = run(body)
                if name == 'header':  # validates only
                    continue
                (img,) = images(doc)
                self.assertEqual(pf.stringify(img), 'Seven heap blocks')

    def test_caption_used_when_no_alt_key(self):
        body = figure('width=.5\\textwidth', 'Empty heap blocks')
        for name, run in self.all_filters():
            with self.subTest(filter=name):
                doc = run(body)
                if name == 'header':
                    continue
                (img,) = images(doc)
                self.assertEqual(pf.stringify(img), 'Empty heap blocks')

    def test_no_alt_no_caption_raises(self):
        for body in (figure('width=.5\\textwidth'),        # figure, no caption
                     '\\includegraphics{' + EPS + '}'):    # bare, pandoc says "image"
            for name, run in self.all_filters():
                with self.subTest(filter=name, body=body):
                    with self.assertRaises(alt_text.NoAltTagException):
                        run(body)

    def test_whitespace_or_placeholder_alt_raises(self):
        for alt in ('{ }', '{image}', '{Image}'):
            body = '\\includegraphics[alt=' + alt + ']{' + EPS + '}'
            for name, run in self.all_filters():
                with self.subTest(filter=name, alt=alt):
                    with self.assertRaises(alt_text.NoAltTagException):
                        run(body)

    def test_placeholder_alt_falls_back_to_caption(self):
        doc = self.run_epub(figure('alt={image}', 'Real caption'))
        (img,) = images(doc)
        self.assertEqual(pf.stringify(img), 'Real caption')

    def test_latex_escapes_rendered_not_leaked(self):
        body = figure("alt={7 boxes for c\\_str and the terminating '\\textbackslash 0', 50\\%}",
                      'Person')
        for name, run in (('epub', self.run_epub), ('wiki', self.run_wiki)):
            with self.subTest(filter=name):
                (img,) = images(run(body))
                alt = pf.stringify(img)
                self.assertIn('c_str', alt)
                self.assertNotIn('\\_', alt)
                self.assertNotIn('textbackslash', alt)
                self.assertIn('\\0', alt)
                self.assertIn('50%', alt)

    def test_multiline_alt_collapses_whitespace(self):
        (img,) = images(self.run_epub(figure('alt={one\n  two}', 'Cap')))
        self.assertEqual(pf.stringify(img), 'one two')


class TestUrls(FilterTestCase):
    def test_epub_eps_becomes_png(self):
        (img,) = images(self.run_epub(figure('alt={x y}', 'Cap')))
        self.assertEqual(img.url, PNG)

    def test_wiki_eps_becomes_absolute_png(self):
        (img,) = images(self.run_wiki(figure('alt={x y}', 'Cap')))
        self.assertEqual(img.url, pandoc_wiki_filter.base_raw_url + PNG)

    def test_missing_png_raises(self):
        body = figure('alt={x y}', 'Cap', path='malloc/drawings/no_such_figure.eps')
        for name, run in (('epub', self.run_epub), ('wiki', self.run_wiki)):
            with self.subTest(filter=name):
                with self.assertRaises(ValueError):
                    run(body)


class TestWikiFigure(FilterTestCase):
    def test_figure_becomes_image_and_caption_paragraphs(self):
        doc = self.run_wiki(figure('alt={Seven heap blocks}', 'Empty \\emph{heap}'))
        self.assertFalse(any(isinstance(b, pf.Figure) for b in doc.content))
        img_para, cap_para = doc.content
        self.assertIsInstance(img_para, pf.Para)
        self.assertIsInstance(img_para.content[0], pf.Image)
        self.assertIsInstance(cap_para.content[0], pf.Emph)
        self.assertEqual(pf.stringify(cap_para).strip(), 'Empty heap')

    def test_gfm_output_is_markdown_not_html(self):
        # width= matters: an Image with attributes makes gfm write <img>.
        md = pf.convert_text(self.run_wiki(figure('width=.9\\textwidth,alt={Seven heap blocks}',
                                                  'Empty heap')),
                             input_format='panflute', output_format='gfm+raw_html',
                             standalone=False)
        self.assertIn('![Seven heap blocks](' + pandoc_wiki_filter.base_raw_url + PNG + ')', md)
        self.assertIn('*Empty heap*', md)
        self.assertNotIn('<figure', md)


class TestPandoc3FixUps(FilterTestCase):
    def test_capital_c_listing_is_c_not_objectivec(self):
        body = '\\begin{lstlisting}[language=C]\nint x;\n\\end{lstlisting}\n'
        for name, run in (('epub', self.run_epub), ('wiki', self.run_wiki)):
            with self.subTest(filter=name):
                (block,) = run(body).content
                self.assertEqual(block.classes, ['c'])

    def test_wiki_citation_link_keeps_its_text(self):
        doc = pf.Doc(pf.Para(pf.Cite(
            pf.Link(pf.Str('IBM'), pf.Space(), pf.Str('1958,'), pf.Space(), pf.Str('P.'),
                    pf.Space(), pf.Str('65'), url='#ref-ibm709'),
            citations=[pf.Citation('ibm709')])))
        doc = pf.run_filter(pandoc_wiki_filter.doc_filter, doc=doc)
        raw = doc.content[0].content[0].content[0]
        self.assertEqual(raw.text, '<a href="#ref-ibm709">IBM 1958, P. 65</a>')

    def test_wiki_ordinary_link_unchanged(self):
        doc = pf.Doc(pf.Para(pf.Link(pf.Str('issue'), url='https://example.com/x')))
        doc = pf.run_filter(pandoc_wiki_filter.doc_filter, doc=doc)
        self.assertEqual(doc.content[0].content[0].text,
                         '<a href="https://example.com/x">https://example.com/x</a>')


class TestEndToEnd(FilterTestCase):
    """Through `pandoc --filter`, as the Makefile and gen_wiki.py run them."""

    def pandoc(self, body, to, filt):
        with tempfile.NamedTemporaryFile('w', suffix='.tex', delete=False) as f:
            f.write(latex_doc(body))
        try:
            return subprocess.run(
                ['pandoc', '-f', 'latex', '-t', to, '--filter', filt, f.name],
                capture_output=True, text=True, check=True, cwd=ROOT).stdout
        finally:
            os.unlink(f.name)

    def test_epub_filter_html_alt(self):
        out = self.pandoc(figure("alt={c\\_str's 7 boxes}", 'Person'),
                          'html', '_scripts/pandoc_epub_filter.py')
        self.assertIn('alt="c_str’s 7 boxes"', out)
        self.assertIn('src="' + PNG + '"', out)

    def test_wiki_filter_gfm(self):
        out = self.pandoc(figure('alt={Seven heap blocks}', 'Empty heap'),
                          'gfm+raw_html', '_scripts/pandoc_wiki_filter.py')
        self.assertIn('![Seven heap blocks](', out)
        self.assertNotIn('<figure', out)

    def test_filter_failure_fails_pandoc(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.pandoc('\\includegraphics{' + EPS + '}', 'html',
                        '_scripts/pandoc_epub_filter.py')


class TestEpubMetadataAndCover(unittest.TestCase):
    def test_empty_date_removed(self):
        doc = pf.Doc(metadata={'date': pf.MetaInlines()})
        pandoc_epub_filter.finalize(doc)
        self.assertNotIn('date', doc.metadata)

    def test_real_date_kept(self):
        doc = pf.Doc(metadata={'date': pf.MetaInlines(pf.Str('2020'))})
        pandoc_epub_filter.finalize(doc)
        self.assertEqual(doc.get_metadata('date'), '2020')

    def test_cover_svg_labelled(self):
        src = ('<div id="cover-image">\n<svg xmlns="http://www.w3.org/2000/svg" version="1.1">\n'
               '<image width="1" height="1" xlink:href="../media/file0.png" />\n</svg>\n</div>')
        out = epub_cover_alt.add_cover_alt(src)
        self.assertIn('role="img"', out)
        self.assertIn('aria-label="Cover of Coursebook', out)
        self.assertIn('<title>Cover of Coursebook', out)
        self.assertEqual(out, epub_cover_alt.add_cover_alt(out))  # idempotent

    def test_cover_img_labelled(self):
        out = epub_cover_alt.add_cover_alt('<img src="../media/cover.png" alt="cover image" />')
        self.assertIn('alt="Cover of Coursebook', out)

    def test_cover_missing_raises(self):
        with self.assertRaises(ValueError):
            epub_cover_alt.add_cover_alt('<p>no cover</p>')


class TestWikiGlyph(unittest.TestCase):
    def run_on(self, text):
        with tempfile.NamedTemporaryFile('w', suffix='.md', delete=False, encoding='utf-8') as f:
            f.write(text)
        try:
            gen_wiki.remove_prelude_glyph(f.name)
            with open(f.name, encoding='utf-8') as g:
                return g.read()
        finally:
            os.unlink(f.name)

    def test_pandoc3_shape(self):
        self.assertEqual(self.run_on('- [A](#a)\n\n\\[1\\]\n\n# A\n'), '- [A](#a)\n\n\n# A\n')

    def test_pandoc27_shape(self):
        self.assertEqual(self.run_on('\\[1\\] <span> </span>\n# A\n'), '# A\n')

    def test_body_untouched(self):
        text = '# A\n\n\\[1\\]\n'
        self.assertEqual(self.run_on(text), text)


class TestCheckNormalisation(unittest.TestCase):
    def test_latex_to_text(self):
        f = alt_check_common.latex_to_text
        self.assertEqual(f("c\\_str and '\\textbackslash 0'"), "c_str and '\\0'")
        self.assertEqual(f('a~b -- c 50\\%'), 'a b \u2013 c 50%')

    def test_normalize_quotes(self):
        self.assertEqual(alt_check_common.normalize('’\\0’  x\n y'), "'\\0' x y")

    def test_normalize_smart_typography(self):
        n = alt_check_common.normalize
        self.assertEqual(n('wait… “so”'), n(alt_check_common.latex_to_text("wait... ``so''")))

    def test_invalid_latex_alt_raises_cleanly(self):
        with self.assertRaises(alt_text.NoAltTagException):
            alt_text.render_latex_alt('broken {brace')

    def test_leak_regex(self):
        import epub_check
        self.assertIsNone(epub_check.LEAK_RE.search("the terminating '\\0'"))
        self.assertIsNotNone(epub_check.LEAK_RE.search('c\\_str'))
        self.assertIsNotNone(epub_check.LEAK_RE.search('\\textbf{x}'))

    def test_expected_matches_filter_rendering(self):
        # The checks' independent normaliser must agree with what the
        # filter actually produces, for every alt= in the book.
        for fig in alt_check_common.content_figures(ROOT):
            with self.subTest(fig='{}:{}'.format(fig['file'], fig['line'])):
                self.assertEqual(alt_check_common.normalize(alt_text.render_latex_alt(fig['alt'])),
                                 alt_check_common.expected_alt(fig))


if __name__ == '__main__':
    unittest.main()
