#!/bin/bash
# B4a (issue #238, Part B): the tagged and untagged PDFs, built on the same
# TeX Live, must have the same words and the same page count.
#
# usage: _scripts/compare_pdf_text.sh untagged.pdf tagged.pdf [outdir]
# Needs poppler-utils (pdftotext, pdfinfo). Writes the word lists and the
# diff to outdir (default: a temp dir). Exit 0 when identical, 1 when they
# differ, 2 when the inputs are unusable.
set -u -o pipefail
if [ $# -lt 2 ]; then echo "usage: $0 untagged.pdf tagged.pdf [outdir]"; exit 2; fi
a=$1; b=$2; out=${3:-$(mktemp -d)}
mkdir -p "$out"
for t in pdftotext pdfinfo; do
  command -v $t > /dev/null || { echo "missing $t (poppler-utils)"; exit 2; }
done

pages() { pdfinfo "$1" | awk '/^Pages:/ {print $2}'; }
tagged() { pdfinfo "$1" | awk '/^Tagged:/ {print $2}'; }
# One word per line. Tagging can change how pdftotext joins lines (real
# spaces are added with interwordspace), so compare words, not layout.
words() { pdftotext -enc UTF-8 "$1" - | tr -s '[:space:]' '\n' | sed '/^$/d'; }

pa=$(pages "$a") && pb=$(pages "$b") || { echo "pdfinfo failed"; exit 2; }
case "$pa$pb" in ''|*[!0-9]*) echo "could not read page counts ($pa, $pb)"; exit 2;; esac
# Guard against comparing a PDF with itself or a stale tagged build.
ta=$(tagged "$a"); tb=$(tagged "$b")
if [ "$ta" != no ] || [ "$tb" != yes ]; then
  echo "expected untagged then tagged, got Tagged: $ta / $tb"; exit 2
fi

words "$a" > "$out/untagged.words" && words "$b" > "$out/tagged.words" \
  || { echo "pdftotext failed"; exit 2; }
wa=$(wc -l < "$out/untagged.words"); wb=$(wc -l < "$out/tagged.words")
if [ "$wa" -eq 0 ] || [ "$wb" -eq 0 ]; then echo "no text extracted"; exit 2; fi
diff "$out/untagged.words" "$out/tagged.words" > "$out/words.diff"
nd=$(grep -c '^[<>]' "$out/words.diff" || true)
# The same words in another order (pdftotext follows the structure in the
# tagged PDF) are not a content change; count those separately.
sort "$out/untagged.words" > "$out/untagged.sorted"
sort "$out/tagged.words" > "$out/tagged.sorted"
ns=$(diff "$out/untagged.sorted" "$out/tagged.sorted" | grep -c '^[<>]' || true)

echo "pages: untagged=$pa tagged=$pb"
echo "words: untagged=$wa tagged=$wb differing-lines=$nd (ignoring order: $ns)"
echo "diff: $out/words.diff"
if [ "$pa" = "$pb" ] && [ "$nd" -eq 0 ]; then
  echo "OK: same page count and identical words"
  exit 0
fi
diff "$out/untagged.sorted" "$out/tagged.sorted" | grep '^[<>]' | sort | uniq -c | sort -rn | head -20
echo "FAIL: tagged and untagged output differ"
exit 1
