#!/bin/bash
# B3 (issue #238, Part B): validate a PDF against PDF/UA-2 with veraPDF and
# print the failures grouped by rule.
#
# usage: _scripts/check_verapdf.sh file.pdf [report.json]
#
# Runs the pinned veraPDF CLI image, so only Docker is needed (no Java on
# the host). Informational: exits 0 whether or not the PDF is compliant,
# unless veraPDF itself could not run (exit 2). Pass --strict-figures as
# a third argument to exit 1 when a figure/alt rule fails (the first rules
# the issue wants gated).
set -u
VERAPDF_IMAGE=${VERAPDF_IMAGE:-verapdf/cli:v1.30.2}
pdf=$1; report=${2:-${pdf%.pdf}.verapdf.json}; strict=${3:-}
dir=$(cd "$(dirname "$pdf")" && pwd); base=$(basename "$pdf")

docker run --rm -v "$dir":/data "$VERAPDF_IMAGE" \
  --flavour ua2 --format json "/data/$base" > "$report"
rc=$?
# veraPDF exits 1 for "not compliant"; anything else is a failure to run.
if [ $rc -ne 0 ] && [ $rc -ne 1 ]; then
  echo "veraPDF failed to run (exit $rc)"; exit 2
fi
python3 "$(dirname "$0")/verapdf_summary.py" "$report" $strict
