"""
Shared alt-text logic for the pandoc image filters (issue #238, Part A).

Used by pandoc_epub_filter.py and pandoc_header_filter.py (and, through the
Figure rewrite, the wiki). pandoc >= 3.1.4 reads graphicx's alt={...} key
into the Image's own inline content, so that is the preferred source. When
a figure has no alt= key, pandoc 3 leaves the Image's content empty and the
text lives in the enclosing Figure's caption instead; we fall back to that
so a caption-only figure still gets *some* alt text, exactly as pandoc 2.7
used to give every figure.

The alt= value arrives as a single raw Str holding the LaTeX source, e.g.
"c\\_str" or "'\\textbackslash 0'": pandoc does not parse it. We render it
through pandoc's own LaTeX reader so escapes become the characters they
stand for instead of leaking into what a screen reader announces.
"""

import panflute as pf

DEFAULT_IMAGE_ALT = 'image'

# Characters that can change meaning when the alt= text is read as LaTeX.
# Anything without one of these renders to itself, so we skip the pandoc
# subprocess for it. The quote/dash entries are there because pandoc's
# LaTeX reader turns '...' and -- into typographic quotes and dashes, and
# the figure's caption (which pandoc does parse) gets the same treatment;
# rendering both the same way keeps them consistent.
_LATEX_SPECIALS = set('\\~{}$&%#^_\'`"-')


class NoAltTagException(Exception):
    pass


def normalize_space(text):
    """Collapse runs of whitespace (including newlines) to single spaces."""
    return ' '.join(text.split())


def render_latex_alt(text):
    """Render raw LaTeX alt text to plain text, the way pandoc would.

    Returns the text unchanged if it contains nothing LaTeX treats
    specially, so the common case costs no subprocess.
    """
    if not any(c in _LATEX_SPECIALS for c in text):
        return normalize_space(text)
    try:
        doc = pf.convert_text(text, input_format='latex',
                              output_format='panflute', standalone=True)
    except Exception as e:  # e.g. unbalanced braces: name the culprit
        raise NoAltTagException('alt text is not valid LaTeX: {!r} ({})'.format(text, e))
    return normalize_space(pf.stringify(doc))


def enclosing_figure(elem):
    """Return the nearest pf.Figure ancestor of elem, or None.

    Walks .parent rather than using ancestor(n), which only takes a fixed
    depth. Today the nesting is Figure > Plain|Para > Image, but a caption
    with a wrapper Div (or a future pandoc) should not break this.
    """
    node = elem.parent
    while node is not None:
        if isinstance(node, pf.Figure):
            return node
        node = getattr(node, 'parent', None)
    return None


def resolve_alt(img):
    """Return the rendered alt text for a pf.Image, or raise.

    Order: the Image's own content (from alt=), then the enclosing Figure's
    caption. Raises NoAltTagException if the result is empty, whitespace,
    or pandoc's "image" placeholder (what pandoc emits for a bare
    \\includegraphics with no alt= and no caption).
    """
    alt = render_latex_alt(pf.stringify(img))
    if not alt or alt.lower() == DEFAULT_IMAGE_ALT:
        fig = enclosing_figure(img)
        alt = normalize_space(pf.stringify(fig.caption)) if fig is not None else ''
    if not alt or alt.lower() == DEFAULT_IMAGE_ALT:
        raise NoAltTagException(img.url)
    return alt


def fix_code_language(code_block):
    """Undo pandoc 3's listings-language mapping of C to Objective-C.

    pandoc 3.10 reads \\begin{lstlisting}[language=C] (capital C, 396
    blocks in this book) as class "objectivec"; pandoc 2.7 and a lowercase
    language=c both give "c". The book has no Objective-C, so the class
    only mislabels the code for highlighters and the wiki's ``` fences.
    (Not alt text, but both image filters are where the pandoc 3 fix-ups
    live.)
    """
    code_block.classes = ['c' if c == 'objectivec' else c
                          for c in code_block.classes]
    return code_block


def apply_alt(img):
    """Resolve img's alt text and store it back as the Image's content.

    Storing the rendered string (rather than leaving pandoc's raw Str) is
    what makes the writers emit c_str instead of c\\_str, and gives a
    caption-only figure a real alt attribute instead of an empty one.
    """
    alt = resolve_alt(img)
    img.content = [pf.Str(alt)]
    return alt
