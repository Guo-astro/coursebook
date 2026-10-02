"""
Shared helpers for epub_check.py and wiki_check.py (issue #238, gates A2
and A3): the expected content-figure list, and alt-text normalisation.

The expected list comes from alt_lint.scan(), the Part C scanner, never a
hard-coded count. The normalisation here is deliberately independent of
pandoc: it spells out what a figure's alt= source should read as, so the
checks catch pandoc (or our filters) rendering it wrongly.
"""

import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import alt_lint  # noqa: E402

# LaTeX escapes that may appear in alt= text (alt_lint.SAFE_LATEX_ESCAPES)
# and the characters they render as. A control word swallows the spaces
# after it, as in LaTeX, so '\textbackslash 0' is '\0'.
_CONTROL_WORDS = {
    'textbackslash': '\\',
    'textasciitilde': '~',
    'textasciicircum': '^',
    'ldots': '\u2026',
    'dots': '\u2026',
}
_CONTROL_SYMBOLS = {'_': '_', '%': '%', '&': '&', '$': '$', '#': '#',
                    '{': '{', '}': '}'}

# Typographic variants that pandoc's smart-quote handling may produce.
_QUOTES = str.maketrans({'\u2018': "'", '\u2019': "'", '\u201c': '"',
                         '\u201d': '"', '`': "'", '\u00a0': ' '})


def latex_to_text(src):
    """Render the small subset of LaTeX allowed in alt= text to plain text."""
    out = []
    i = 0
    while i < len(src):
        c = src[i]
        if c == '\\':
            m = re.match(r'\\([A-Za-z]+)\s*', src[i:])
            if m and m.group(1) in _CONTROL_WORDS:
                out.append(_CONTROL_WORDS[m.group(1)])
                i += m.end()
                continue
            if i + 1 < len(src) and src[i + 1] in _CONTROL_SYMBOLS:
                out.append(_CONTROL_SYMBOLS[src[i + 1]])
                i += 2
                continue
            # Anything else is left as-is; it would show up as a mismatch
            # (alt_lint warns about such macros at source level).
            out.append(c)
            i += 1
        elif c == '~':
            out.append(' ')
            i += 1
        elif c in '{}':
            i += 1  # grouping braces render as nothing
        elif src.startswith('---', i):
            out.append('\u2014')
            i += 3
        elif src.startswith('--', i):
            out.append('\u2013')
            i += 2
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def normalize(text):
    """Compare-form of rendered alt text: straight quotes, one space.

    Also folds the other smart-typography pandoc may or may not apply,
    depending on whether the text went through its LaTeX reader: an
    ellipsis and ``LaTeX double quotes''.
    """
    text = text.translate(_QUOTES).replace('…', '...').replace("''", '"')
    return ' '.join(text.split())


def expected_alt(fig):
    return normalize(latex_to_text(fig['alt']))


def png_path(path):
    """The repo file the outputs actually use for a figure's path."""
    return path[:-4] + '.png' if path.endswith('.eps') else path


def content_figures(root):
    """alt_lint's content-figure list, without its private _fields.

    Refuses to hand back a list alt_lint itself would fail on: an expected
    figure list built from a broken source scan would make these checks
    compare the outputs against the wrong thing, and pass or fail for
    reasons that have nothing to do with the EPUB or the wiki.
    """
    scanned = alt_lint.scan(root)

    def where(items):
        return ', '.join('{}:{}'.format(f['file'], f['line']) for f in items)

    malformed = [f for f in scanned if f.get('_malformed')]
    if malformed:
        raise SystemExit('alt_lint reports malformed \\includegraphics: {}'.format(
            where(malformed)))
    unreachable = [f for f in scanned if f.get('_unreachable')]
    if unreachable:
        raise SystemExit('alt_lint reports figures no chapter in order.yaml '
                         'reaches: {}'.format(where(unreachable)))

    figs = [{k: v for k, v in f.items() if not k.startswith('_')} for f in scanned]
    missing = [f for f in figs if not f['alt'].strip()]
    if missing:
        raise SystemExit('alt_lint reports figures without alt text: {}'.format(
            where(missing)))
    return figs


def compare(expected, found, what):
    """Compare two Counters of (key, alt) pairs; return a list of errors."""
    errors = []
    for item, n in (expected - found).items():
        errors.append('{}: missing or wrong alt for {} (expected {!r}) x{}'.format(
            what, item[0], item[1], n))
    for item, n in (found - expected).items():
        errors.append('{}: unexpected alt for {}: {!r} x{}'.format(
            what, item[0], item[1], n))
    return errors


__all__ = ['latex_to_text', 'normalize', 'expected_alt', 'png_path',
           'content_figures', 'compare', 'Counter']
