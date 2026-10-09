import contextlib
import copy
import io
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from networkclear.cli import demo_inputs, main
from networkclear.contracts import ContractError, canonical, digest, read_json
from networkclear.report import FILES, analyze, build, verify, write_report


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.data, self.scenarios = demo_inputs()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name) / "report"
        write_report(self.data, self.scenarios, self.target)

    def rehash(self):
        (self.target / "manifest.json").write_bytes(
            canonical(
                {
                    "schema_version": 1,
                    "files": {name: digest((self.target / name).read_bytes()) for name in sorted(FILES)},
                }
            )
        )

    def test_full_replay_and_independent_oracle(self):
        self.assertEqual(
            verify(self.target), {"verified": True, "files": 9, "scenarios": 15, "oracle_checked_scenarios": 15}
        )
        for name, raw in build(self.data, self.scenarios).items():
            self.assertEqual((self.target / name).read_bytes(), raw)

    def test_flow_reconciliation_and_outside_loss(self):
        analysis = analyze(self.data, self.scenarios)
        case = next(c for c in analysis["cases"] if c["scenario"] == "anchor-050-pct")
        self.assertEqual(case["direct_default_ids"], ["A"])
        self.assertEqual(case["cascade_default_ids"], ["B", "C", "D"])
        self.assertEqual(Fraction(case["outside_shortfall_cents"]), 338000)
        self.assertEqual(Fraction(case["gross_unpaid_cents"]), 1202000)
        for payment in analysis["payments"]:
            outgoing = sum(
                Fraction(f["paid_cents"])
                for f in analysis["flows"]
                if f["scenario"] == payment["scenario"] and f["debtor"] == payment["node"]
            )
            self.assertEqual(outgoing, Fraction(payment["paid_cents"]))

    def test_equal_capital_budgets_are_explicit(self):
        analysis = analyze(self.data, self.scenarios)
        rescues = [c for c in analysis["cases"] if "rescue" in c["scenario"]]
        self.assertEqual([c["injection_cents"] for c in rescues], [200000, 200000])

    def test_tampered_payment_and_rehashed_manifest_fail(self):
        path = self.target / "payments.csv"
        path.write_text(path.read_text() + "fake,row\n")
        self.rehash()
        with self.assertRaisesRegex(ContractError, "Semantic replay"):
            verify(self.target)

    def test_tampered_flow_and_rehashed_manifest_fail(self):
        path = self.target / "flows.csv"
        path.write_text(path.read_text().replace("OUTSIDE", "FAKE_CREDITOR"))
        self.rehash()
        with self.assertRaisesRegex(ContractError, "Semantic replay"):
            verify(self.target)

    def test_tampered_html_and_rehashed_manifest_fail(self):
        path = self.target / "index.html"
        path.write_text(path.read_text() + "<p>Fabricated bank rating</p>")
        self.rehash()
        with self.assertRaisesRegex(ContractError, "Semantic replay"):
            verify(self.target)

    def test_manifest_mismatch_and_extra_member_fail(self):
        (self.target / "extra.txt").write_text("extra")
        with self.assertRaisesRegex(ContractError, "file set"):
            verify(self.target)
        (self.target / "extra.txt").unlink()
        (self.target / "analysis.json").write_text("{}")
        with self.assertRaisesRegex(ContractError, "manifest"):
            verify(self.target)

    def test_symlink_and_nonempty_output_fail(self):
        with self.assertRaisesRegex(ContractError, "empty"):
            write_report(self.data, self.scenarios, self.target)
        path = self.target / "payments.csv"
        path.unlink()
        path.symlink_to(self.target / "flows.csv")
        with self.assertRaisesRegex(ContractError, "symlinks"):
            verify(self.target)

    def test_cli_error_is_structured(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(main(["verify", str(self.target / "missing")]), 2)
        self.assertIn("regular directory", stderr.getvalue())

    def test_scenario_validation_and_html_escaping(self):
        for scenario_list in [
            [],
            [self.scenarios[0], self.scenarios[0]],
            [{"id": "x", "reductions_bps": [], "injections_cents": {}}],
        ]:
            with self.subTest(scenarios=scenario_list), self.assertRaises(ContractError):
                analyze(self.data, scenario_list)
        scenarios = copy.deepcopy(self.scenarios[:1])
        scenarios[0]["id"] = "<script>alert(1)</script>"
        raw = build(self.data, scenarios)["index.html"].decode()
        self.assertNotIn(scenarios[0]["id"], raw)
        self.assertIn("&lt;script&gt;", raw)

    def test_large_network_reports_oracle_not_checked(self):
        data = {
            "schema_version": 1,
            "currency": "USD",
            "nodes": [{"id": f"N{i}", "cash_cents": 100, "outside_debt_cents": 100} for i in range(9)],
            "edges": [],
        }
        scenarios = [{"id": "baseline", "reductions_bps": {}, "injections_cents": {}}]
        target = Path(self.temp.name) / "large"
        write_report(data, scenarios, target)
        self.assertEqual(verify(target)["oracle_checked_scenarios"], 0)

    def test_serialization_is_deterministic(self):
        shuffled = copy.deepcopy(self.data)
        shuffled["nodes"].reverse()
        shuffled["edges"].reverse()
        self.assertEqual(analyze(self.data, self.scenarios), analyze(shuffled, self.scenarios))
        self.assertEqual(read_json((self.target / "network.json").read_bytes()), self.data)


if __name__ == "__main__":
    unittest.main()
