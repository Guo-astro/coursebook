#!/bin/bash

set -o errexit

if test $BUILD_FOCUS = "WIKI" || test $BUILD_FOCUS = "EPUB"
then
    # Install the Python packages we need. actions/setup-python provides
    # the interpreter (3.11 in the workflows).
    pip install -r requirements.txt

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
    # The PDF is built in the pinned TeX Live 2026 container
    # (texlive/texlive, see .github/workflows/build.yaml), not with
    # Ubuntu's apt TeX Live 2023: the tagged PDF (issue #238, Part B)
    # needs the tagging code of a current LaTeX (latex-lab, tagpdf 1.0c),
    # and cs341code.sty and cs341book.sty rely on it. The image has all of
    # TeX Live, make, git and python3; add what the build and its gates
    # still need:
    #   python3-yaml    _scripts/gen_order.py (order.tex)
    #   poppler-utils   pdfinfo/pdftotext for the B4a text comparison
    #   python3-pikepdf _scripts/check_pdf_tags.py (B2)
    # The container runs as root, so no sudo.
    SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO=sudo
    $SUDO apt-get update -qq
    $SUDO apt-get install -y --no-install-recommends \
        python3-yaml poppler-utils python3-pikepdf
    lualatex --version | head -1
fi;
