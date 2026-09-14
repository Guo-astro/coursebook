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
    make pdf;
fi;
