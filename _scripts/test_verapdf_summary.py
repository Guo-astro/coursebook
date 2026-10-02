#!/usr/bin/env python3
"""Tests for verapdf_summary.py (issue #238, gate B3).

This script is a CI gate, so what matters is its exit status: 0 only when
veraPDF really validated every PDF against PDF/UA-2 and no figure or alt
rule failed. The cases below are the ways it could otherwise report
success on a build nobody actually validated.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
SUMMARY = os.path.join(SCRIPTS, 'verapdf_summary.py')


def validation_result(profile='PDF/UA-2 validation profile', summaries=()):
    return {
        'profileName': profile,
        'compliant': not summaries,
        'details': {
            'passedRules': 1727,
            'failedRules': len(summaries),
            'passedChecks': 100,
            'failedChecks': 0,
            'ruleSummaries': list(summaries),
        },
    }


def report(*jobs):
    return {'report': {'jobs': list(jobs)}}


def job(name='main.pdf', result='default'):
    if result == 'default':
        result = validation_result()
    return {'itemDetails': {'name': name}, 'validationResult': result}


def run(data, *args):
    """Run the summariser on a report, returning (exit status, output)."""
    handle, path = tempfile.mkstemp(suffix='.json')
    with os.fdopen(handle, 'w') as fh:
        json.dump(data, fh)
    try:
        proc = subprocess.run([sys.executable, SUMMARY, path, *args],
                              capture_output=True, text=True)
    finally:
        os.unlink(path)
    return proc.returncode, proc.stdout + proc.stderr


FIGURE_RULE = {'ruleStatus': 'FAILED', 'clause': '8.9', 'testNumber': 1,
               'failedChecks': 3, 'description': 'Figure needs an Alt entry'}
OTHER_RULE = {'ruleStatus': 'FAILED', 'clause': '7.21', 'testNumber': 4,
              'failedChecks': 12, 'description': 'Glyph widths must match'}


class ExitStatus(unittest.TestCase):
    def test_clean_ua2_report_passes(self):
        status, out = run(report(job()), '--strict-figures')
        self.assertEqual(status, 0, out)
        self.assertIn('figure/alt rules failing: no', out)

    def test_failing_figure_rule_fails_under_strict(self):
        data = report(job(result=validation_result(summaries=[FIGURE_RULE])))
        self.assertEqual(run(data, '--strict-figures')[0], 1)

    def test_failing_figure_rule_only_reports_without_strict(self):
        data = report(job(result=validation_result(summaries=[FIGURE_RULE])))
        status, out = run(data)
        self.assertEqual(status, 0, out)
        self.assertIn('figure/alt rules failing: yes', out)

    def test_non_figure_failure_passes_the_figure_gate(self):
        # B3 starts by requiring only the figure and alt rules to pass; the
        # rest of the report is informational.
        data = report(job(result=validation_result(summaries=[OTHER_RULE])))
        self.assertEqual(run(data, '--strict-figures')[0], 0)

    def test_unparseable_pdf_fails(self):
        status, out = run(report(job(result=None)), '--strict-figures')
        self.assertEqual(status, 2, out)

    def test_unparseable_pdf_fails_even_beside_a_good_one(self):
        # The gate must not be rescued by another job succeeding: a PDF
        # veraPDF could not read has not been validated.
        data = report(job('main.pdf'), job('background.pdf', result=None))
        status, out = run(data, '--strict-figures')
        self.assertEqual(status, 2, out)
        self.assertIn('background.pdf', out)

    def test_wrong_profile_fails(self):
        # Clause 8.9 exists only in PDF/UA-2. Validated against anything
        # else, "no figure rules failing" would be meaningless.
        data = report(job(result=validation_result(profile='PDF/A-1B validation profile')))
        status, out = run(data, '--strict-figures')
        self.assertEqual(status, 2, out)
        self.assertIn('PDF/UA-2', out)

    def test_empty_report_fails(self):
        self.assertEqual(run(report())[0], 2)

    def test_null_failed_checks_is_tolerated(self):
        rule = dict(FIGURE_RULE, failedChecks=None)
        data = report(job(result=validation_result(summaries=[rule])))
        self.assertEqual(run(data, '--strict-figures')[0], 1)


if __name__ == '__main__':
    unittest.main()
