#!/usr/bin/env python3

"""
Pandoc filter for the EPUB build: give every image real alt text, and
point .eps figures at their pre-rendered .png counterparts.

Alt text comes from the \\includegraphics alt= key (pandoc >= 3.1.4), else
the enclosing figure's caption; see alt_text.py. No alt means no build.
"""

import os.path
import sys

import yaml

from panflute import run_filter, Image, CodeBlock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from alt_text import apply_alt, fix_code_language, NoAltTagException  # noqa: E402,F401


def replace_suffix(content, suffix_old, suffix_new):
    ret = content
    if content.endswith(suffix_old):
        ret = content[:-len(suffix_old)] + suffix_new
    return ret


def doc_filter(elem, doc):
    if isinstance(elem, CodeBlock):
        fix_code_language(elem)
        return elem

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


def metadata_file_date():
    """The edition date from epub_metadata.yaml, or '' if it sets none."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'epub_metadata.yaml')
    try:
        with open(path, encoding='utf-8') as f:
            return str(yaml.safe_load(f).get('date') or '').strip()
    except (OSError, AttributeError, yaml.YAMLError):
        return ''


def finalize(doc):
    # prelude.tex's \date{} (there for the PDF title) gives an empty date,
    # which pandoc writes as <dc:date></dc:date>, and EPUBCheck rejects
    # that (RSC-005). Deleting it is not enough: with no date at all pandoc
    # substitutes the moment of the build, so the same sources would give a
    # different EPUB every day. That empty \date{} also beats the date in
    # --metadata-file, so the metadata file alone cannot fix it either.
    #
    # So fill in the edition date from epub_metadata.yaml, which is the one
    # place it is written and the file epub_check.py compares content.opf
    # against. If that file sets no date, fall back to dropping the empty
    # one, which at least keeps EPUBCheck happy.
    date = doc.get_metadata('date', default=None)
    if date is None or not str(date).strip():
        fixed = metadata_file_date()
        if fixed:
            doc.metadata['date'] = fixed
        elif date is not None:
            del doc.metadata['date']


def main(doc=None):
    return run_filter(doc_filter, finalize=finalize, doc=doc)


if __name__ == "__main__":
    main()
