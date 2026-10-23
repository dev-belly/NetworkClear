"""Scenario names must not turn review exports into spreadsheet formulas."""

import csv
import io
import tempfile
import unittest
from pathlib import Path

from networkclear.contracts import ContractError, canonical, digest, read_json
from networkclear.report import FILES, build, verify, write_report


class SpreadsheetExportTests(unittest.TestCase):
    def setUp(self):
        self.data = {
            "schema_version": 1,
            "currency": "USD",
            "nodes": [
                {"id": "A", "cash_cents": 20, "outside_debt_cents": 100},
                {"id": "B", "cash_cents": 0, "outside_debt_cents": 10},
            ],
            "edges": [{"debtor": "A", "creditor": "B", "amount_cents": 30}],
        }

    def scenarios(self, label):
        return [{"id": label, "reductions_bps": {}, "injections_cents": {}}]

    def rows(self, raw):
        return list(csv.DictReader(io.StringIO(raw.decode("utf-8"), newline=""), strict=True))

    def test_formula_control_and_locale_prefixes_are_text_in_every_export(self):
        for label in (
            "=1+1",
            "+1+1",
            "-stress",
            "@SUM(1,2)",
            " \t=1+1",
            "\tstress",
            "\rstress",
            "\nstress",
            "\x00=1+1",
            "\ufeff=1+1",
            "＝1+1",
            "＋1+1",
            "－stress",
            "＠SUM(1,2)",
        ):
            files = build(self.data, self.scenarios(label))
            for name in ("cases.csv", "payments.csv", "flows.csv", "rounds.csv"):
                rows = self.rows(files[name])
                with self.subTest(label=label, name=name):
                    self.assertTrue(rows)
                    self.assertTrue(all(row["scenario"] == "text: " + label for row in rows))
                    self.assertTrue(all(None not in row and None not in row.values() for row in rows))
            self.assertEqual(read_json(files["scenarios.json"])[0]["id"], label)
            self.assertEqual(read_json(files["analysis.json"])["cases"][0]["scenario"], label)

    def test_marker_cannot_make_distinct_labels_collide(self):
        labels = ["=1+1", "text: =1+1"]
        scenarios = [self.scenarios(label)[0] for label in labels]
        rows = self.rows(build(self.data, scenarios)["cases.csv"])
        self.assertEqual([row["scenario"] for row in rows], ["text: " + label for label in labels])

    def test_quoted_and_multiline_labels_preserve_rows_fields_and_identity(self):
        baseline = build(self.data, self.scenarios("baseline"))
        for label in ('stress, "severe"', "stress\rsevere", "stress\r\nsevere", "stress\nsevere", " stress "):
            files = build(self.data, self.scenarios(label))
            for name in ("cases.csv", "payments.csv", "flows.csv", "rounds.csv"):
                rows = self.rows(files[name])
                with self.subTest(label=label, name=name):
                    self.assertEqual(len(rows), len(self.rows(baseline[name])))
                    self.assertTrue(all(row["scenario"] == label for row in rows))
                    self.assertTrue(all(None not in row and None not in row.values() for row in rows))

    def test_exact_financial_fields_and_certificates_are_unchanged(self):
        baseline = build(self.data, self.scenarios("baseline"))
        marked = build(self.data, self.scenarios("=1+1"))
        for name in ("cases.csv", "payments.csv", "flows.csv", "rounds.csv"):
            rows = [{k: v for k, v in row.items() if k != "scenario"} for row in self.rows(marked[name])]
            expected = [{k: v for k, v in row.items() if k != "scenario"} for row in self.rows(baseline[name])]
            self.assertEqual(rows, expected)
        self.assertTrue(all(row["fixed_point_residual_cents"] == "0/1" for row in self.rows(marked["cases.csv"])))

    def test_marked_report_verifies_and_rehashed_removed_marker_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "report"
            write_report(self.data, self.scenarios("=1+1"), target)
            self.assertTrue(verify(target)["verified"])
            path = target / "cases.csv"
            path.write_bytes(path.read_bytes().replace(b"text: =1+1", b"=1+1"))
            (target / "manifest.json").write_bytes(
                canonical(
                    {
                        "schema_version": 1,
                        "files": {name: digest((target / name).read_bytes()) for name in sorted(FILES)},
                    }
                )
            )
            with self.assertRaisesRegex(ContractError, "Semantic replay"):
                verify(target)


if __name__ == "__main__":
    unittest.main()
