#!/bin/bash

set -o errexit;

if test $BUILD_FOCUS = "WIKI"
then
    echo "Generating Wiki"
    mkdir -p _wiki
    python3 _scripts/gen_wiki.py order.yaml _wiki

    # Issue #238 gates. A1: the filter unit tests. A3: every figure's alt
    # text reached the wiki.
    python3 -m unittest _scripts.test_pandoc_filters -v
    python3 _scripts/wiki_check.py _wiki
elif test $BUILD_FOCUS = "EPUB"
then
    make epub;

    # Issue #238 gates. A1: the filter unit tests. A2: every figure's alt
    # text, the cover and the accessibility metadata reached the EPUB.
    # A2b: EPUBCheck (installed by install.sh) validates the whole book.
    python3 -m unittest _scripts.test_pandoc_filters -v
    python3 _scripts/epub_check.py main.epub
    java -jar ~/epubcheck/epubcheck.jar --failonwarnings main.epub
else
    # The tagged PDF: main book and the chapter PDFs (issue #238, Part B).
    make pdf;

    # B1: no TeX errors, no tagpdf errors, no missing characters, in the
    # main log or any chapter log.
    bash _scripts/check_tex_logs.sh

    # B2: tagged, and every content figure's /Figure carries the rendered
    # text of its alt= key (the list comes from the alt-text lint, C1);
    # the title-page duck is an artifact. Then each chapter PDF, which
    # holds only its own figures and has no title page.
    python3 -m unittest _scripts.test_check_pdf_tags -v
    python3 _scripts/alt_lint.py --json > alt-expected.json
    python3 _scripts/check_pdf_tags.py main.pdf --expected alt-expected.json --json-out b2.json
    for chapter in $(sed 's/^- //; s/\r$//' order.yaml); do
        if ! python3 _scripts/check_pdf_tags.py "$chapter.pdf" --duck-page 0 \
                --expected alt-expected.json --expected-filter "$(dirname "$chapter")/" \
                > b2-chapter.txt; then
            echo "B2 failed for $chapter.pdf:"; tail -20 b2-chapter.txt; exit 1
        fi
    done
    echo "B2: main.pdf and every chapter PDF passed"
fi;
