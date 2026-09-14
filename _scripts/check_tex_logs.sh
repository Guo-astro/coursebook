#!/bin/bash
# B1 (issue #238, Part B): after `make pdf`, check the LaTeX logs of the
# main book and of every chapter PDF.
#
# usage: _scripts/check_tex_logs.sh [log ...]
#   default logs: main_tagged.log (or main_wrapper.log for TAGGED=0) and
#   every <chapter>.pdf.log that order.yaml names.
#
# Fails (exit 1) on:
#   * a TeX error ("! ..." lines; latexmk -interaction=nonstopmode carries on
#     past them, so the PDF exists but may be wrong);
#   * a tagpdf error (the structure tree is wrong);
#   * a missing character: the glyph is silently left out of the PDF (this
#     is how the old T1 fonts dropped every ’ “ ” and the CJK author names).
# Reports, without failing: tagpdf warnings, overfull boxes.
set -u
logs=("$@")
if [ ${#logs[@]} -eq 0 ]; then
  for f in main_tagged.log main_wrapper.log; do [ -f "$f" ] && logs+=("$f"); done
  for d in $(sed 's/^- //; s/\r$//' order.yaml); do logs+=("$d.pdf.log"); done
fi

status=0
printf '%-36s %6s %7s %8s %8s %8s\n' log TeXerr tagErr tagWarn missing overfull
for log in "${logs[@]}"; do
  if [ ! -f "$log" ]; then
    echo "$log: missing (was the PDF built?)"; status=1; continue
  fi
  tex=$(grep -c '^! ' "$log")
  terr=$(grep -c 'tagpdf Error' "$log")
  twarn=$(grep -c 'tagpdf Warning' "$log")
  miss=$(grep -c 'Missing character' "$log")
  over=$(grep -c '^Overfull \\hbox' "$log")
  printf '%-36s %6s %7s %8s %8s %8s\n' "$log" "$tex" "$terr" "$twarn" "$miss" "$over"
  if [ "$tex" -ne 0 ] || [ "$terr" -ne 0 ] || [ "$miss" -ne 0 ]; then
    status=1
    grep -h -A3 '^! \|tagpdf Error' "$log" | head -20
    grep -h 'Missing character' "$log" | sort | uniq -c | head -10
  fi
done
if [ $status -eq 0 ]; then echo "OK: no TeX errors, tagpdf errors or missing characters"
else echo "FAIL: see above"; fi
exit $status
