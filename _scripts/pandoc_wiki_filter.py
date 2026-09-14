#!/usr/bin/env python3

"""
Pandoc filter for the wiki: absolute image URLs, real alt text, figures as
plain Markdown, math and links as raw HTML.
"""

import os.path
import sys

import html

from panflute import (run_filter, Image, Math, Link, RawInline, Figure,
                      Para, Emph, CodeBlock, stringify)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from alt_text import apply_alt, fix_code_language  # noqa: E402

base_raw_url = 'https://raw.githubusercontent.com/illinois-cs241/coursebook/master/'
eps_ext = '.eps'


def replace_suffix(content, suffix_old, suffix_new):
    ret = content
    if content.endswith(suffix_old):
        ret = content[:-len(suffix_old)] + suffix_new
    return ret


def figure_to_markdown(fig):
    """Turn a pandoc 3 Figure into an image paragraph plus a caption paragraph.

    gfm has no Markdown form for a Figure, so pandoc 3 would write raw
    <figure><img><figcaption> HTML for all of them, and how that looks
    depends on GitHub's wiki sanitizer. pandoc 2.7 wrote a plain
    ![caption](url). We keep that plain Markdown shape but with the alt=
    text as the image's alt, and the caption as an italic paragraph below
    it so sighted readers still see it.

    The Images inside have already been through doc_filter (panflute walks
    children before their parent), so their URL and alt are final.
    """
    blocks = [Para(*blk.content) for blk in fig.content
              if hasattr(blk, 'content') and any(isinstance(i, Image) for i in blk.content)]
    if not blocks:
        # Not an image figure (e.g. a table in a figure env): leave it alone.
        return None
    caption_inlines = []
    for blk in fig.caption.content:
        if caption_inlines:
            caption_inlines.append(RawInline(' ', format='markdown'))
        caption_inlines.extend(blk.content)
    if stringify(fig.caption).strip():
        blocks.append(Para(Emph(*caption_inlines)))
    return blocks


def doc_filter(elem, doc):
    if isinstance(elem, Image):
        # Accessibility by default: raises NoAltTagException if there is
        # neither an alt= key nor a caption.
        apply_alt(elem)
        # Drop width= and friends: gfm can't express them, so pandoc 3
        # would write a raw <img> instead of ![alt](url). pandoc 2.7
        # dropped them too, so the wiki looks the same.
        elem.identifier = ''
        elem.classes = []
        elem.attributes = {}
        # Link to the raw user link instead of relative
        # That way the wiki and the site will have valid links automagically
        new_url = replace_suffix(elem.url, eps_ext, '.png')
        if not os.path.isfile(new_url):
            raise ValueError('{} Not found'.format(new_url))
        elem.url = base_raw_url + new_url
        return elem

    if isinstance(elem, Figure):
        return figure_to_markdown(elem)

    if isinstance(elem, CodeBlock):
        fix_code_language(elem)

    if isinstance(elem, Math):
        # Raw inline mathlinks so jekyll renders them
        content = elem.text
        escaped = "$$ {} $$".format(content)
        return RawInline(escaped)
    if isinstance(elem, Link):
        # Transform all Links into a tags
        # Reason being is github and jekyll are weird
        # About leaving html as is and markdown as parsing
        # So we change everything to avoid ambiguity
        # There is a script injection possibility here so be careful

        url = elem.url
        if url.startswith('#ref-'):
            # A citation link made by --citeproc. pandoc 3 puts the whole
            # rendered citation ("Wikibooks n.d.", "IBM 1958, P. 65")
            # inside the link, where pandoc 2.7 left the author outside
            # it. Show that text, or the wiki shows just "(#ref-key)".
            title = html.escape(stringify(elem).strip())
        else:
            # Pre-existing behaviour for ordinary links: the title, else
            # the URL itself, as the link text.
            title = str(elem.title)
        if title == "":
            title = elem.url
        link = '<a href="{}">{}</a>'.format(url, title)
        return RawInline(link)


def main(doc=None):
    return run_filter(doc_filter, doc=doc)


if __name__ == "__main__":
    main()
