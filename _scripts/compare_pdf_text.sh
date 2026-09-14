#!/bin/bash
# B4a (issue #238, Part B): the tagged PDF (the default `make pdf`) and
# the untagged one (`make pdf TAGGED=0`), built on the same TeX Live, must
# have the same words and the same page count.
#
# usage: _scripts/compare_pdf_text.sh untagged.pdf tagged.pdf [outdir]
# Needs poppler-utils (pdftotext, pdfinfo). Writes the word lists and the
# diffs to outdir (default: a temp dir). Exit 0 when the page counts and
# the words match, 1 when they differ, 2 when the inputs are unusable.
#
# What is compared: pdftotext's words, with a hyphen at the end of a line
# joined to the next line, as a multiset (order ignored). Two things
# differ between the two PDFs that are not content:
#  * order: pdftotext follows the structure tree of a tagged PDF, so page
#    numbers, running heads and figure labels come out in other places;
#  * line-end hyphens: pdftotext rejoins "argu-" / "ments:" in the tagged
#    PDF (tagging marks where a line was broken) but not in the untagged.
# The in-order diff is still written and counted, for review.
set -u -o pipefail
if [ $# -lt 2 ]; then echo "usage: $0 untagged.pdf tagged.pdf [outdir]"; exit 2; fi
a=$1; b=$2; out=${3:-$(mktemp -d)}
mkdir -p "$out"
for t in pdftotext pdfinfo; do
  command -v $t > /dev/null || { echo "missing $t (poppler-utils)"; exit 2; }
done

pages() { pdfinfo "$1" | awk '/^Pages:/ {print $2}'; }
tagged() { pdfinfo "$1" | awk '/^Tagged:/ {print $2}'; }
# One word per line, with line-end hyphens joined (see above).
words() {
  pdftotext -enc UTF-8 "$1" - \
    | perl -0777 -pe 's/-\n//g' \
    | tr -s '[:space:]' '\n' | sed '/^$/d'
}

pa=$(pages "$a") && pb=$(pages "$b") || { echo "pdfinfo failed"; exit 2; }
case "$pa$pb" in ''|*[!0-9]*) echo "could not read page counts ($pa, $pb)"; exit 2;; esac
# Guard against comparing a PDF with itself or a stale build.
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
LC_ALL=C sort "$out/untagged.words" > "$out/untagged.sorted"
LC_ALL=C sort "$out/tagged.words" > "$out/tagged.sorted"
diff "$out/untagged.sorted" "$out/tagged.sorted" > "$out/sorted.diff"
ns=$(grep -c '^[<>]' "$out/sorted.diff" || true)

echo "pages: untagged=$pa tagged=$pb"
echo "words: untagged=$wa tagged=$wb; differing (order ignored): $ns; in-order diff lines: $nd"
echo "diffs: $out/sorted.diff $out/words.diff"
if [ "$pa" = "$pb" ] && [ "$ns" -eq 0 ]; then
  echo "OK: same page count and the same words"
  exit 0
fi
grep '^[<>]' "$out/sorted.diff" | sort | uniq -c | sort -rn | head -20
echo "FAIL: tagged and untagged output differ"
exit 1
