#!/bin/bash
# B4a (issue #238, Part B): the tagged and untagged PDFs, built on the same
# TeX Live, must have the same words and the same page count.
#
# usage: _scripts/compare_pdf_text.sh untagged.pdf tagged.pdf [outdir]
# Needs poppler-utils (pdftotext, pdfinfo). Writes the word lists and the
# diff to outdir (default: a temp dir). Exit 0 when identical, 1 otherwise.
set -u
a=$1; b=$2; out=${3:-$(mktemp -d)}
mkdir -p "$out"

pages() { pdfinfo "$1" | awk '/^Pages:/ {print $2}'; }
# One word per line. Tagging can change how pdftotext joins lines (real
# spaces are added with interwordspace), so compare words, not layout.
words() { pdftotext -enc UTF-8 "$1" - | tr -s '[:space:]' '\n' | sed '/^$/d'; }

pa=$(pages "$a"); pb=$(pages "$b")
words "$a" > "$out/untagged.words"
words "$b" > "$out/tagged.words"
diff "$out/untagged.words" "$out/tagged.words" > "$out/words.diff"
nd=$(grep -c '^[<>]' "$out/words.diff")

echo "pages: untagged=$pa tagged=$pb"
echo "words: untagged=$(wc -l < "$out/untagged.words") tagged=$(wc -l < "$out/tagged.words") differing-lines=$nd"
echo "diff: $out/words.diff"
if [ "$pa" = "$pb" ] && [ "$nd" -eq 0 ]; then
  echo "OK: same page count and identical words"
  exit 0
fi
head -40 "$out/words.diff"
echo "FAIL: tagged and untagged output differ"
exit 1
