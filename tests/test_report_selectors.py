"""Unusual scenario identities must survive a browser's HTML preprocessing."""

import json
import unittest
from html.parser import HTMLParser

from networkclear.report import build


class Selectors(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = []
        self.cases = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "option":
            self.values.append(attrs.get("value"))
        elif tag == "section":
            self.cases.append(attrs["data-case"])


class ReportSelectorTests(unittest.TestCase):
    def test_scenario_keys_preserve_cr_lf_nul_quotes_and_unicode(self):
        labels = ["stress\rone", "stress\none", "stress\x00one", "stress�one", '压力 " & <tail>']
        data = {
            "schema_version": 1,
            "currency": "USD",
            "nodes": [{"id": "A", "cash_cents": 20, "outside_debt_cents": 100}],
            "edges": [],
        }
        scenarios = [{"id": label, "reductions_bps": {}, "injections_cents": {}} for label in labels]
        html = build(data, scenarios)["index.html"].decode()
        parsed = Selectors()
        parsed.feed(html.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "�"))
        self.assertEqual([json.loads(value) for value in parsed.values], labels)
        self.assertEqual(parsed.values, parsed.cases)
        self.assertEqual(len(set(parsed.values)), len(labels))
        self.assertNotIn("<tail>", html)


if __name__ == "__main__":
    unittest.main()
