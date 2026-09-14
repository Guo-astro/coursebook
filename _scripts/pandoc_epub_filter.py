#!/usr/bin/env python3

"""
Pandoc filter for the EPUB build: give every image real alt text, and
point .eps figures at their pre-rendered .png counterparts.

Alt text comes from the \\includegraphics alt= key (pandoc >= 3.1.4), else
the enclosing figure's caption; see alt_text.py. No alt means no build.
"""

import os.path
import sys

from panflute import run_filter, Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from alt_text import apply_alt, NoAltTagException  # noqa: E402,F401


def replace_suffix(content, suffix_old, suffix_new):
    ret = content
    if content.endswith(suffix_old):
        ret = content[:-len(suffix_old)] + suffix_new
    return ret


def doc_filter(elem, doc):
    if isinstance(elem, Image):
        # Accessibility by default: raises NoAltTagException if there is
        # neither an alt= key nor a caption.
        apply_alt(elem)

        # EPUB readers can't show .eps, so use the committed .png.
        new_url = replace_suffix(elem.url, '.eps', '.png')
        if not os.path.isfile(new_url):
            raise ValueError('{} Not found'.format(new_url))
        elem.url = new_url
        return elem


def main(doc=None):
    return run_filter(doc_filter, doc=doc)


if __name__ == "__main__":
    main()
