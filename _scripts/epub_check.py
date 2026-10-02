#!/usr/bin/env python3

"""
Gate A2 of issue #238: check the alt text in a built EPUB.

    python3 _scripts/epub_check.py [main.epub] [--root REPO]

Checks:
  * every <img> in the content documents has a non-empty alt, with no
    leaked LaTeX;
  * the content images are exactly alt_lint's content figures, with the
    same count. pandoc renames images to media/fileN.png, so each <img> is
    matched to its figure by the SHA-256 of the PNG;
  * each alt equals its figure's alt= source, after normalisation
    (alt_check_common.normalize);
  * the cover (cover.xhtml) is labelled, as epub_cover_alt.py does;
  * content.opf carries exactly the accessibility metadata in
    _scripts/epub_metadata.yaml;
  * all math is MathML: no formula fell back to raw TeX.

It only reads files, so it also runs as the post-deploy smoke check on the
published EPUB. Exit status 1 if anything fails.
"""

import argparse
import hashlib
import html.parser
import os
import posixpath
import re
import sys
import zipfile

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from alt_check_common import (Counter, compare, content_figures,  # noqa: E402
                              expected_alt, normalize, png_path)

LEAK_RE = re.compile(r'\\(?:[A-Za-z]{2,}|[_%&$#{}])')

A11Y_KEYS = {
    'accessModes': 'schema:accessMode',
    'accessModeSufficient': 'schema:accessModeSufficient',
    'accessibilityFeatures': 'schema:accessibilityFeature',
    'accessibilityHazards': 'schema:accessibilityHazard',
    'accessibilitySummary': 'schema:accessibilitySummary',
}


class _Scan(html.parser.HTMLParser):
    """Collect <img>s, the cover <svg>, and math spans from an XHTML file."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.imgs = []          # (src, alt or None)
        self.svgs = []          # attrs dicts
        self.titles = []        # text of <title> inside <svg>
        self.math = 0
        self.raw_math = []      # span.math whose content isn't <math>
        self._in_svg = 0
        self._in_title = False
        self._math_span = None  # collected text of an open span.math

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'math':
            # pandoc 3 writes bare <math>; older versions wrapped it in
            # span.math. Either way a span holding <math> is fine.
            self.math += 1
            self._math_span = None
        if tag == 'img':
            self.imgs.append((a.get('src', ''), a.get('alt')))
        elif tag == 'svg':
            self._in_svg += 1
            self.svgs.append(a)
        elif tag == 'title' and self._in_svg:
            self._in_title = True
            self.titles.append('')
        elif tag == 'span' and 'math' in a.get('class', '').split():
            self._math_span = ''

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag):
        if tag == 'svg':
            self._in_svg -= 1
        elif tag == 'title':
            self._in_title = False
        elif tag == 'span' and self._math_span is not None:
            self.raw_math.append(self._math_span)
            self._math_span = None

    def handle_data(self, data):
        if self._in_title:
            self.titles[-1] += data
        if self._math_span is not None:
            self._math_span += data


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def check_opf(opf_text, metadata_file):
    errors = []
    with open(metadata_file, encoding='utf-8') as f:
        want = yaml.safe_load(f)
    for key, prop in A11Y_KEYS.items():
        found = re.findall(r'<meta property="{}">([^<]*)</meta>'.format(re.escape(prop)), opf_text)
        found = [normalize(html.unescape(x)) for x in found]
        expected = want.get(key)
        if expected is None:
            errors.append('epub_metadata.yaml has no {}'.format(key))
            continue
        if isinstance(expected, str):
            expected = [expected]
        expected = [normalize(x) for x in expected]
        if sorted(found) != sorted(expected):
            errors.append('content.opf {}: found {}, expected {}'.format(prop, found, expected))
    known = set(A11Y_KEYS.values())
    for prop in sorted(set(re.findall(r'property="(schema:access[^"]*)"', opf_text)) - known):
        errors.append('content.opf has {} but epub_metadata.yaml does not set it'.format(prop))
    if re.search(r'<dc:date[^>]*>\s*</dc:date>', opf_text):
        errors.append('content.opf has an empty <dc:date> (EPUBCheck RSC-005)')

    # <dc:language>. EPUB requires one, and a screen reader chooses its
    # voice from it; pandoc writes whatever -M lang / the metadata file say.
    found_lang = re.findall(r'<dc:language[^>]*>([^<]*)</dc:language>', opf_text)
    want_lang = want.get('lang')
    if not want_lang:
        errors.append('epub_metadata.yaml has no lang')
    elif found_lang != [want_lang]:
        errors.append('content.opf <dc:language>: found {}, expected [{!r}]'.format(
            found_lang, want_lang))

    # <dc:date>. It must be the fixed date from the sources, not the build
    # date: see the comment in epub_metadata.yaml.
    found_date = [d.strip() for d in
                  re.findall(r'<dc:date[^>]*>([^<]*)</dc:date>', opf_text)]
    want_date = str(want.get('date') or '')
    if not want_date:
        errors.append('epub_metadata.yaml has no date')
    elif found_date != [want_date]:
        errors.append('content.opf <dc:date>: found {}, expected [{!r}]; a build '
                      'timestamp here means the date metadata did not reach pandoc'.format(
                          found_date, want_date))
    return errors


def check_epub(epub_path, root):
    errors = []
    figs = content_figures(root)

    # Expected (png sha, alt) pairs, and sha -> repo path for messages.
    expected = Counter()
    sha_to_path = {}
    for fig in figs:
        path = os.path.join(root, png_path(fig['path']))
        if not os.path.isfile(path):
            errors.append('{}:{}: {} not found'.format(fig['file'], fig['line'], png_path(fig['path'])))
            continue
        with open(path, 'rb') as f:
            sha = _sha(f.read())
        sha_to_path[sha] = png_path(fig['path'])
        expected[(sha, expected_alt(fig))] += 1

    with zipfile.ZipFile(epub_path) as z:
        names = z.namelist()
        docs = sorted(n for n in names if n.endswith('.xhtml') and not n.endswith('nav.xhtml'))
        covers = [n for n in docs if posixpath.basename(n) == 'cover.xhtml']
        found = Counter()
        n_imgs = 0
        math = 0
        raw_math = []
        for name in docs:
            scan = _Scan()
            scan.feed(z.read(name).decode('utf-8'))
            math += scan.math
            raw_math += scan.raw_math
            if name in covers:
                continue
            for src, alt in scan.imgs:
                n_imgs += 1
                if alt is None or not alt.strip():
                    errors.append('{}: <img src="{}"> has no alt text'.format(name, src))
                    continue
                # A control word (\textbf) or an escape (\_) is leaked TeX;
                # a lone rendered backslash such as '\0' is not.
                if LEAK_RE.search(alt):
                    errors.append('{}: alt text leaks LaTeX: {!r}'.format(name, alt))
                target = posixpath.normpath(posixpath.join(posixpath.dirname(name), src))
                try:
                    sha = _sha(z.read(target))
                except KeyError:
                    errors.append('{}: <img src="{}"> points at nothing'.format(name, src))
                    continue
                found[(sha, normalize(alt))] += 1

        # The cover.
        if len(covers) != 1:
            errors.append('expected one cover.xhtml, found {}'.format(covers))
        else:
            scan = _Scan()
            scan.feed(z.read(covers[0]).decode('utf-8'))
            labelled = [s for s in scan.svgs
                        if s.get('role') == 'img' and (s.get('aria-label') or '').strip()]
            img_alts = [alt for _, alt in scan.imgs if alt and alt.strip()
                        and alt.strip().lower() not in ('cover image', 'image')]
            if not (labelled and scan.titles and all(t.strip() for t in scan.titles)) and not img_alts:
                errors.append('cover.xhtml: cover image has no alt text / aria-label '
                              '(run _scripts/epub_cover_alt.py)')

        opf = [n for n in names if n.endswith('.opf')]
        if len(opf) != 1:
            errors.append('expected one .opf, found {}'.format(opf))
        else:
            errors += check_opf(z.read(opf[0]).decode('utf-8'),
                                os.path.join(root, '_scripts', 'epub_metadata.yaml'))

    if n_imgs != len(figs):
        errors.append('EPUB has {} content images; alt_lint found {} content figures'.format(
            n_imgs, len(figs)))
    named = lambda c: Counter({(sha_to_path.get(s, 'unknown image ' + s[:12]), a): n
                               for (s, a), n in c.items()})
    errors += compare(named(expected), named(found), 'EPUB')

    if raw_math:
        errors.append('{} formulas are raw TeX, not MathML (first: {!r}); is --mathml set?'.format(
            len(raw_math), raw_math[0][:80]))
    if math == 0:
        errors.append('no MathML in the EPUB, but epub_metadata.yaml claims MathML')

    return errors, len(figs), n_imgs, math


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('epub', nargs='?', default='main.epub')
    ap.add_argument('--root', default='.', help='repository root (default: .)')
    args = ap.parse_args()
    errors, n_figs, n_imgs, math = check_epub(args.epub, args.root)
    for e in errors:
        print('ERROR: ' + e, file=sys.stderr)
    print('epub_check: {} content figures expected, {} content images found, '
          '{} MathML formulas, {} errors'.format(n_figs, n_imgs, math, len(errors)))
    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
