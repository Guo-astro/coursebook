#!/usr/bin/env python3
"""Summarise a veraPDF JSON report (--format json) by failed rule.

usage: verapdf_summary.py report.json [--strict-figures]

--strict-figures exits 1 if any failed rule concerns figures or alternate
descriptions (PDF/UA-2 clause 8.9 "Graphics", or a rule whose description
mentions Figure / Alt), which is the first gate issue #238 asks for.
"""
import json
import sys

FIGURE_WORDS = ("figure", " alt ", "alternate description", "alt entry",
                "/alt", "actualtext")


def rules(report):
    jobs = report.get("report", {}).get("jobs", [])
    for job in jobs:
        vr = job.get("validationResult", [])
        if isinstance(vr, dict):
            vr = [vr]
        for res in vr:
            details = res.get("details", {})
            yield res, details, details.get("ruleSummaries", [])


def is_figure_rule(r):
    text = (" " + r.get("description", "") + " " + r.get("test", "") + " "
            + r.get("object", "") + " ").lower()
    return str(r.get("clause", "")).startswith("8.9") or any(
        w in text for w in FIGURE_WORDS)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    with open(sys.argv[1]) as fh:
        report = json.load(fh)
    strict = "--strict-figures" in sys.argv[2:]
    figure_fail = False
    any_result = False
    for res, details, summaries in rules(report):
        any_result = True
        print(f"profile: {res.get('profileName', '?')}   compliant: "
              f"{res.get('compliant')}")
        print(f"rules passed {details.get('passedRules')} failed "
              f"{details.get('failedRules')};  checks passed "
              f"{details.get('passedChecks')} failed {details.get('failedChecks')}")
        failed = [r for r in summaries if r.get("status") == "failed"
                  or r.get("ruleStatus") == "FAILED"]
        failed.sort(key=lambda r: -int(r.get("failedChecks", 0)))
        for r in failed:
            fig = is_figure_rule(r)
            figure_fail |= fig
            desc = " ".join(r.get("description", "").split())
            print(f"  {r.get('specification', '')} {r.get('clause')}-"
                  f"{r.get('testNumber')}  x{r.get('failedChecks')}"
                  f"{'  [figure]' if fig else ''}\n      {desc[:220]}")
    if not any_result:
        print("no validation result in report (did veraPDF parse the PDF?)")
        return 2
    print(f"figure/alt rules failing: {'yes' if figure_fail else 'no'}")
    return 1 if (strict and figure_fail) else 0


if __name__ == "__main__":
    sys.exit(main())
