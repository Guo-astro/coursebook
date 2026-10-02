#!/usr/bin/env python3

"""
Gate A4 of issue #238: report what a pandoc upgrade did to the book.

    python3 _scripts/compare_pandoc_ast.py OLD.json NEW.json \\
        [--wiki-dir _wiki] [--report-file FILE] \\
        [--old-label L] [--new-label L]

The two inputs are pandoc JSON ASTs of the *same* main.tex, captured with
the old and the new pandoc. Capture each with exactly:

    pandoc -f latex -t json main.tex -o AST.json

No filters and no --citeproc. That matters: the numbers only mean
"what the pandoc version changed" if nothing else differs between the two
captures. A capture made through --citeproc measures citeproc as well --
it splits paragraphs and adds a Link per citation -- and one made from
main_wrapper.tex measures the PDF wrapper instead. order.tex must exist
(make it with gen_order.py), or main.tex pulls in no chapters at all.

Element counts are reported for review, not required to match: the issue
expects deltas here and has them reviewed in the PR. Two things do fail:

  * the wiki's citations must render as links with real text. A citation
    that regressed to the bare key, "(#ref-foo)", is a reader-visible
    break, and counting "#ref-" substrings would not notice it because the
    broken form contains one too.
  * gen_wiki.py's glyph clean-up must still do something, or be gone.

Exit status 1 if either fails.
"""

import argparse
import json
import os
import re
import sys

# Element kinds, named as the issue's A4 list names them. "paragraphs"
# counts Para and Plain together: pandoc uses Plain for a paragraph inside
# a tight list or a figure, so counting Para alone makes an unrelated
# change of list style look like lost text.
ELEMENTS = (
    ('headers', ('Header',)),
    ('paragraphs', ('Para', 'Plain')),
    ('code blocks', ('CodeBlock',)),
    ('math', ('Math',)),
    ('tables', ('Table',)),
    ('figures', ('Figure',)),
    ('images', ('Image',)),
    ('citations', ('Cite',)),
    ('links', ('Link',)),
)

# <a href="#ref-KEY">TEXT</a>: what pandoc_wiki_filter.py writes for a
# citation link once --citeproc has rendered it.
CITE_LINK_RE = re.compile(r'<a href="#(ref-[^"]+)">(.*?)</a>', re.DOTALL)
# An unprocessed citation left in the Markdown, e.g. [@Hyman:1966:CPC].
RAW_CITE_RE = re.compile(r'\[-?@[\w:.#$%&+?<>~/-]+')
GLYPH_RE = re.compile(r'^\\\[1\\\]', re.MULTILINE)


def count_elements(path):
    """Count element kinds in a pandoc JSON AST."""
    with open(path, encoding='utf-8') as f:
        doc = json.load(f)
    counts = {name: 0 for name, _ in ELEMENTS}
    of_kind = {}
    for name, kinds in ELEMENTS:
        for kind in kinds:
            of_kind.setdefault(kind, []).append(name)
    stack = [doc]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for name in of_kind.get(node.get('t'), ()):
                counts[name] += 1
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return counts, doc.get('pandoc-api-version')


def wiki_pages(wiki_dir):
    return sorted(f for f in os.listdir(wiki_dir)
                  if f.endswith('.md') and f not in ('Home.md', '_Sidebar.md'))


def check_citations(wiki_dir):
    """Check the wiki's citations rendered. Returns (errors, lines)."""
    errors = []
    links = 0
    pages_with_links = 0
    for name in wiki_pages(wiki_dir):
        with open(os.path.join(wiki_dir, name), encoding='utf-8') as f:
            text = f.read()
        found = CITE_LINK_RE.findall(text)
        links += len(found)
        if found:
            pages_with_links += 1
        for key, label in found:
            label = re.sub(r'<[^>]+>', '', label).strip()
            # The failure this is here to catch: the link text is the
            # anchor, or the key, instead of the rendered citation.
            if not label:
                errors.append('{}: citation link to #{} has no text'.format(name, key))
            elif label.startswith('#ref-') or label == key or label == key[len('ref-'):]:
                errors.append('{}: citation link text is the key, not the rendered '
                              'citation: {!r}'.format(name, label))
        for raw in RAW_CITE_RE.findall(text):
            errors.append('{}: unprocessed citation {!r}; did --citeproc run '
                          'before the filters?'.format(name, raw))
    if links == 0:
        errors.append('{}: no citation links at all; the book cites sources on '
                      'several pages, so this means citeproc produced none'.format(wiki_dir))
    return errors, ['Wiki citations: {} rendered citation links over {} pages.'.format(
        links, pages_with_links)]


def check_glyph_cleanup(root, wiki_dir):
    """gen_wiki.py's glyph clean-up must still match, or be gone."""
    errors = []
    source = ''
    path = os.path.join(root, '_scripts', 'gen_wiki.py')
    if os.path.isfile(path):
        with open(path, encoding='utf-8') as f:
            source = f.read()
    has_cleanup = 'remove_prelude_glyph' in source or re.search(r'[\'"]sed[\'"]', source)
    left = []
    for name in wiki_pages(wiki_dir):
        with open(os.path.join(wiki_dir, name), encoding='utf-8') as f:
            head = f.read().split('\n# ', 1)[0]
        if GLYPH_RE.search(head):
            left.append(name)
    if has_cleanup and left:
        errors.append('the glyph clean-up ran but {} still start with the stray '
                      '"\\[1\\]" line'.format(', '.join(left)))
    if not has_cleanup and left:
        errors.append('no glyph clean-up in gen_wiki.py, and {} still start with '
                      'the stray "\\[1\\]" line'.format(', '.join(left)))
    note = ('present and leaving no stray glyph line' if has_cleanup
            else 'removed; no page needs it')
    return errors, ['Wiki glyph clean-up: {}.'.format(note)]


def report(old, new, old_label, new_label, old_api, new_api):
    lines = [
        '# Pandoc AST comparison (issue #238, gate A4)',
        '',
        'Source: `main.tex`, captured with `pandoc -f latex -t json main.tex`,',
        'no filters and no --citeproc. Counts are reported for review, not',
        'required to match.',
        '',
        '| Element | {} | {} | Change |'.format(old_label, new_label),
        '| --- | ---: | ---: | ---: |',
    ]
    for name, _ in ELEMENTS:
        lines.append('| {} | {} | {} | {:+d} |'.format(
            name, old[name], new[name], new[name] - old[name]))
    lines += ['', 'pandoc-types: {} then {}.'.format(old_api, new_api), '']
    return lines


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('old_json')
    ap.add_argument('new_json')
    ap.add_argument('--wiki-dir', default='_wiki',
                    help='generated wiki pages, for the citation check')
    ap.add_argument('--root', default=os.path.dirname(here),
                    help='repository root (default: the one holding this script)')
    ap.add_argument('--old-label', default='before')
    ap.add_argument('--new-label', default='after')
    ap.add_argument('--report-file', help='also write the report here')
    args = ap.parse_args(argv)

    old, old_api = count_elements(args.old_json)
    new, new_api = count_elements(args.new_json)
    lines = report(old, new, args.old_label, args.new_label, old_api, new_api)

    errors = []
    for check in (check_citations(args.wiki_dir),
                  check_glyph_cleanup(args.root, args.wiki_dir)):
        errors += check[0]
        lines += check[1]

    text = '\n'.join(lines) + '\n'
    print(text, end='')
    if args.report_file:
        with open(args.report_file, 'w', encoding='utf-8') as f:
            f.write(text)
    for e in errors:
        print('ERROR: ' + e, file=sys.stderr)
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
