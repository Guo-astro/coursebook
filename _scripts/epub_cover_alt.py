#!/usr/bin/env python3

"""
Give the EPUB cover page's image alt text (issue #238, Part A step 7).

pandoc's EPUB writer hard-codes cover.xhtml, and since pandoc 3 it draws
the --epub-cover-image as an SVG <image>, which has no alt attribute. No
template or option changes that, so we rewrite cover.xhtml inside the
built EPUB instead.

The cover isn't decorative: it shows the title and the authors, so it gets
real alt text. We mark the <svg> as role="img" with an aria-label and add
an SVG <title>, the two ways assistive technology names an inline SVG.

Usage: epub_cover_alt.py main.epub   (rewrites the file in place)

Fails, instead of silently doing nothing, if the cover markup isn't the
shape we expect, so a future pandoc change surfaces in CI.
"""

import html
import os
import re
import sys
import tempfile
import zipfile

COVER_ALT = ('Cover of Coursebook, by B. Venkatesh, L. Angrave, et al.: '
             'the title and authors on a dark blue background, '
             'with a yellow rubber duck.')

COVER_NAME_RE = re.compile(r'(^|/)cover\.xhtml$')


def add_cover_alt(xhtml):
    """Return cover.xhtml text with the cover image named. Raises if no
    cover image is found."""
    alt = html.escape(COVER_ALT, quote=True)
    # pandoc >= 3: <svg ...><image .../></svg>
    svg_re = re.compile(r'<svg\b([^>]*)>')
    m = svg_re.search(xhtml)
    if m and '<image' in xhtml[m.end():]:
        attrs = m.group(1)
        if 'aria-label=' in attrs:
            return xhtml  # already done (idempotent)
        role = '' if re.search(r'\brole=', attrs) else ' role="img"'
        new_open = '<svg{}{} aria-label="{}"><title>{}</title>'.format(
            attrs, role, alt, alt)
        return xhtml[:m.start()] + new_open + xhtml[m.end():]
    # pandoc 2.x: <img src="..." alt="cover image" />
    img_re = re.compile(r'(<img\b[^>]*\balt=")[^"]*(")')
    if img_re.search(xhtml):
        return img_re.sub(lambda mm: mm.group(1) + alt + mm.group(2), xhtml, count=1)
    raise ValueError('cover.xhtml has no <svg><image> or <img alt> to label')


def rewrite_epub(path):
    with zipfile.ZipFile(path) as zin:
        infos = zin.infolist()
        covers = [i.filename for i in infos if COVER_NAME_RE.search(i.filename)]
        if len(covers) != 1:
            raise ValueError('expected exactly one cover.xhtml in {}, found {}'.format(path, covers))
        fd, tmp = tempfile.mkstemp(suffix='.epub', dir=os.path.dirname(os.path.abspath(path)))
        os.close(fd)
        try:
            # The OCF spec needs "mimetype" first and stored uncompressed;
            # copying infos in order with their own compress_type keeps that.
            with zipfile.ZipFile(tmp, 'w') as zout:
                for info in infos:
                    data = zin.read(info.filename)
                    if info.filename == covers[0]:
                        data = add_cover_alt(data.decode('utf-8')).encode('utf-8')
                    zout.writestr(info, data, compress_type=info.compress_type)
            os.replace(tmp, path)
        except BaseException:
            os.unlink(tmp)
            raise


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit('usage: epub_cover_alt.py FILE.epub')
    rewrite_epub(sys.argv[1])
