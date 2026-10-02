#!/bin/bash

set -o errexit

# Install the Python packages we need. actions/setup-python provides the
# interpreter (3.11 in the workflows).
pip install -r requirements.txt

if test $BUILD_FOCUS = "WIKI" || test $BUILD_FOCUS = "EPUB"
then
    # pandoc, pinned exactly. Ubuntu's apt pandoc is too old for us.
    #
    # Why this version (issue #238, Part A):
    #   >= 3.1.4  reads graphicx's alt= key into the image's alt text
    #   >= 3.1.12 writes EPUB accessibility metadata (_scripts/epub_metadata.yaml)
    # pandoc 3 builds citeproc in (--citeproc); the separate
    # pandoc-citeproc binary is gone. panflute is pinned to match in
    # requirements.txt: panflute 2.3.x speaks pandoc-types 1.23, which
    # pandoc 3.x uses. Change the two together.
    #
    # Rollback: this was pandoc 2.7 from
    # https://github.com/jgm/pandoc/releases/download/2.7/pandoc-2.7-1-amd64.deb
    # with panflute 1.12.5; revert the upgrade commit to restore it.
    PANDOC_VERSION=3.10.2
    PANDOC_DEB=pandoc-${PANDOC_VERSION}-1-amd64.deb
    PANDOC_SHA256=6c06b69b49ae95087573631a6fcafb233ab7ab51e5cfa73f7539d6c964a2640d
    pushd ~
    wget -q https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/${PANDOC_DEB}
    echo "${PANDOC_SHA256}  ${PANDOC_DEB}" | sha256sum -c -
    sudo dpkg -i ${PANDOC_DEB}
    popd
    pandoc --version | head -1
fi;

if test $BUILD_FOCUS = "EPUB"
then
    # EPUBCheck, the W3C EPUB validator (gate A2b), pinned exactly.
    # script.sh runs it on main.epub. It needs Java 11 or later: GitHub's
    # ubuntu runners ship one, and anywhere else we install a headless JRE.
    EPUBCHECK_VERSION=5.4.0
    EPUBCHECK_ZIP=epubcheck-${EPUBCHECK_VERSION}.zip
    EPUBCHECK_SHA256=33350c61038e71dfb3d45a76aed04bf5481e6d5500cb780f6e98db8bbd15a28c
    if ! command -v java > /dev/null
    then
        sudo apt-get update -qq
        sudo apt-get install -y --no-install-recommends default-jre-headless
    fi
    pushd ~
    wget -q https://github.com/w3c/epubcheck/releases/download/v${EPUBCHECK_VERSION}/${EPUBCHECK_ZIP}
    echo "${EPUBCHECK_SHA256}  ${EPUBCHECK_ZIP}" | sha256sum -c -
    unzip -q -o ${EPUBCHECK_ZIP}
    # A versionless path, so script.sh and deploy.yaml don't repeat the version.
    ln -sfn ~/epubcheck-${EPUBCHECK_VERSION} ~/epubcheck
    popd
    java -jar ~/epubcheck/epubcheck.jar --version
fi;

if test $BUILD_FOCUS = "PDF"
then
    # texlive-full drags in 455 packages / 4.0 GB -- every language pack,
    # ConTeXt, Metapost, the lot. The book needs 68 packages / 768 MB,
    # listed below.
    #
    # Which package provides what (checked with apt-file on Ubuntu 24.04):
    #   latex-base        book.cls fontenc geometry graphicx color hyperref
    #                     natbib fancyhdr longtable grfext epstopdf-base
    #   latex-recommended microtype listings xcolor setspace float chapterbib
    #   latex-extra       mdframed mfirstuc comment framed glossaries titlesec
    #                     tocloft wrapfig changepage csquotes epigraph fncychap
    #   pictures          pgffor
    #   fonts-recommended Charter type1 (bchr8a.pfb), Latin Modern
    #   fonts-extra       mathdesign / mdbch. 614 MB of the 768 MB, so
    #                     most of the remaining install time, but it is
    #                     the only place mathdesign lives and it sets the
    #                     book's body font. Dropping it changes every page.
    #   luatex            lualatex, which the Makefile builds with
    #   font-utils        epstopdf, for the 47 .eps drawings
    #   latexmk           every build in the Makefile goes through latexmk
    #   ghostscript       epstopdf's backend
    sudo apt-get update -qq
    sudo apt-get install -y --no-install-recommends \
        texlive-latex-base \
        texlive-latex-recommended \
        texlive-latex-extra \
        texlive-fonts-recommended \
        texlive-fonts-extra \
        texlive-pictures \
        texlive-luatex \
        texlive-font-utils \
        latexmk \
        ghostscript
fi;
