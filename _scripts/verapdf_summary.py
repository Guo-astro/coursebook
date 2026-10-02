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
    """Yield (result, details, ruleSummaries) per validation result.

    Also returns the jobs veraPDF could not validate at all. Those carry a
    null validationResult, and skipping them silently is how this gate
    would pass on a PDF veraPDF never managed to parse -- so main() counts
    them and fails rather than reporting "no figure rules failing".
    """
    jobs = (report.get("report") or {}).get("jobs") or []
    results = []
    unvalidated = []
    for job in jobs:
        vr = job.get("validationResult")
        if isinstance(vr, dict):
            vr = [vr]
        if not vr:
            item = job.get("itemDetails") or {}
            unvalidated.append(item.get("name") or "<unnamed>")
            continue
        for res in vr:
            details = res.get("details") or {}
            results.append((res, details, details.get("ruleSummaries") or []))
    return results, unvalidated


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
    wrong_profile = []
    results, unvalidated = rules(report)
    for res, details, summaries in results:
        profile = res.get("profileName") or "?"
        # The figure gate below keys off PDF/UA-2 clause 8.9. Validated
        # against any other profile those rules simply never appear, and
        # "no figure rules failing" would mean nothing -- so say which
        # profile ran and fail if it is not the one we asked for.
        if "ua-2" not in profile.lower():
            wrong_profile.append(profile)
        print(f"profile: {profile}   compliant: "
              f"{res.get('compliant')}")
        print(f"rules passed {details.get('passedRules')} failed "
              f"{details.get('failedRules')};  checks passed "
              f"{details.get('passedChecks')} failed {details.get('failedChecks')}")
        failed = [r for r in summaries if r.get("status") == "failed"
                  or r.get("ruleStatus") == "FAILED"]
        failed.sort(key=lambda r: -int(r.get("failedChecks") or 0))
        for r in failed:
            fig = is_figure_rule(r)
            figure_fail |= fig
            desc = " ".join(r.get("description", "").split())
            print(f"  {r.get('specification', '')} {r.get('clause')}-"
                  f"{r.get('testNumber')}  x{r.get('failedChecks')}"
                  f"{'  [figure]' if fig else ''}\n      {desc[:220]}")
    if not results:
        print("no validation result in report (did veraPDF parse the PDF?)")
        return 2
    if unvalidated:
        print("ERROR: veraPDF produced no validation result for: "
              + ", ".join(unvalidated), file=sys.stderr)
        return 2
    if wrong_profile:
        print("ERROR: expected a PDF/UA-2 profile, got: "
              + ", ".join(sorted(set(wrong_profile))), file=sys.stderr)
        return 2
    print(f"figure/alt rules failing: {'yes' if figure_fail else 'no'}")
    return 1 if (strict and figure_fail) else 0


if __name__ == "__main__":
    sys.exit(main())
