#!/usr/bin/env python3

"""
Gate A3 of issue #238: check the alt text in the generated wiki pages.

    python3 _scripts/wiki_check.py [_wiki] [--root REPO]

pandoc_wiki_filter.py turns every figure into a Markdown image
![alt](url) followed by an italic caption paragraph (issue step 4). This
checks:
  * each chapter page's images are exactly alt_lint's content figures for
    that chapter, and each alt equals its alt= source after normalisation;
  * the total matches alt_lint's count (no hard-coded 48);
  * no page has raw <figure> HTML, an <img> without alt, YAML front
    matter, or the stray "\\[1\\]" line gen_wiki.py removes;
  * every <img> on the landing page (Home.md, _Sidebar.md) has an alt
    attribute, and one that is a link's only content has non-empty alt.

It only reads files, so it also runs as the post-deploy smoke check on a
clone of the published wiki. Exit status 1 if anything fails.
"""

import argparse
import html
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from alt_check_common import (Counter, compare, content_figures,  # noqa: E402
                              expected_alt, normalize, png_path)

BASE_RAW_URL = 'https://raw.githubusercontent.com/illinois-cs241/coursebook/master/'

# ![alt](url): the alt may wrap across lines and contain \-escapes.
MD_IMAGE_RE = re.compile(r'!\[((?:[^\]\\]|\\.)*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)', re.DOTALL)
MD_ESCAPE_RE = re.compile(r'\\([!-/:-@\[-`{-~])')
IMG_TAG_RE = re.compile(r'<img\b[^>]*>', re.IGNORECASE | re.DOTALL)
ALT_ATTR_RE = re.compile(r'\balt\s*=\s*("([^"]*)"|\'([^\']*)\')', re.IGNORECASE)
LINKED_IMG_RE = re.compile(r'\[\s*(<img\b[^>]*>)\s*\]\(', re.IGNORECASE | re.DOTALL)
GLYPH_RE = re.compile(r'^\\\[1\\\]')


def page_name(tex_file):
    """gen_wiki.py's page name for a chapter .tex file."""
    return os.path.splitext(os.path.basename(tex_file))[0].title() + '.md'


def chapter_pages(root):
    """Map each chapter directory to its wiki page, from order.yaml.

    A chapter's figures can live in files it \\input's (introc/pointers.tex
    is part of introc/introc.tex's page), so figures are assigned to pages
    by directory, not by file name.
    """
    with open(os.path.join(root, 'order.yaml'), encoding='utf-8') as f:
        order = yaml.safe_load(f)
    pages = {}
    for entry in order:
        d = os.path.dirname(entry)
        if d in pages:
            raise SystemExit('order.yaml: two chapters in {!r}; wiki_check maps '
                             'figures to pages by directory'.format(d))
        pages[d] = page_name(entry + '.tex')
    return pages


def img_alt(tag):
    m = ALT_ATTR_RE.search(tag)
    if not m:
        return None
    return html.unescape(m.group(2) if m.group(2) is not None else m.group(3))


def check_page_hygiene(name, text):
    errors = []
    if text.startswith('---\n'):
        errors.append('{}: starts with YAML front matter'.format(name))
    head = text.split('\n# ', 1)[0]
    if any(GLYPH_RE.match(line) for line in head.splitlines()):
        errors.append('{}: stray "\\[1\\]" line before the first heading'.format(name))
    if re.search(r'<figure\b', text, re.IGNORECASE):
        errors.append('{}: raw <figure> HTML (figures should be Markdown images)'.format(name))
    for tag in IMG_TAG_RE.findall(text):
        if img_alt(tag) is None:
            errors.append('{}: <img> without alt: {}'.format(name, tag[:100]))
    return errors


def check_wiki(wiki_dir, root):
    errors = []
    figs = content_figures(root)

    pages_by_dir = chapter_pages(root)
    expected = {}
    for fig in figs:
        page = pages_by_dir.get(os.path.dirname(fig['file']))
        if page is None:
            errors.append('{}:{}: figure is not in any chapter in order.yaml'.format(
                fig['file'], fig['line']))
            continue
        expected.setdefault(page, Counter())[
            (png_path(fig['path']), expected_alt(fig))] += 1

    # Only the pages gen_wiki.py writes. A clone of the published wiki can
    # also hold older, hand-made pages that aren't ours to check.
    ours = set(pages_by_dir.values()) | {'Home.md', '_Sidebar.md'}
    pages = sorted(f for f in os.listdir(wiki_dir) if f in ours)
    if 'Home.md' not in pages:
        errors.append('{}: no Home.md'.format(wiki_dir))
    total = 0
    for name in pages:
        with open(os.path.join(wiki_dir, name), encoding='utf-8') as f:
            text = f.read()
        errors += check_page_hygiene(name, text)
        if name in ('Home.md', '_Sidebar.md'):
            for tag in LINKED_IMG_RE.findall(text):
                if not (img_alt(tag) or '').strip():
                    errors.append('{}: linked <img> needs alt text: {}'.format(name, tag[:100]))
            continue
        found = Counter()
        for alt, url in MD_IMAGE_RE.findall(text):
            total += 1
            alt = MD_ESCAPE_RE.sub(r'\1', alt)
            if not alt.strip():
                errors.append('{}: image {} has empty alt'.format(name, url))
            path = url[len(BASE_RAW_URL):] if url.startswith(BASE_RAW_URL) else url
            found[(path, normalize(alt))] += 1
        errors += compare(expected.get(name, Counter()), found, name)

    for name in sorted(set(expected) - set(pages)):
        errors.append('{}: page missing, but alt_lint lists figures in it'.format(name))
    if total != len(figs):
        errors.append('wiki has {} images; alt_lint found {} content figures'.format(total, len(figs)))
    return errors, len(figs), total


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('wiki_dir', nargs='?', default='_wiki')
    ap.add_argument('--root', default='.', help='repository root (default: .)')
    args = ap.parse_args()
    errors, n_figs, n_imgs = check_wiki(args.wiki_dir, args.root)
    for e in errors:
        print('ERROR: ' + e, file=sys.stderr)
    print('wiki_check: {} content figures expected, {} wiki images found, {} errors'.format(
        n_figs, n_imgs, len(errors)))
    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
