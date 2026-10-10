import contextlib
import copy
import io
import tempfile
import unittest
from fractions import Fraction
from html.parser import HTMLParser
from pathlib import Path

from networkclear.cli import demo_inputs, main
from networkclear.contracts import ContractError, canonical, digest, read_json
from networkclear.report import FILES, analyze, build, verify, write_report


class LiabilityMatrix(HTMLParser):
    """Read displayed matrix cells independently of report formatting helpers."""

    def __init__(self):
        super().__init__()
        self.depth = 0
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "div":
            if self.depth:
                self.depth += 1
            elif dict(attrs).get("class") == "matrix":
                self.depth = 1
        if self.depth:
            if tag == "tr":
                self.row = []
            elif tag in {"th", "td"}:
                self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if self.depth:
            if tag in {"th", "td"}:
                self.row.append("".join(self.cell))
                self.cell = None
            elif tag == "tr":
                self.rows.append(self.row)
                self.row = None
            elif tag == "div":
                self.depth -= 1


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
        path.write_text(path.read_text(encoding="utf-8") + "fake,row\n", encoding="utf-8")
        self.rehash()
        with self.assertRaisesRegex(ContractError, "Semantic replay"):
            verify(self.target)

    def test_tampered_flow_and_rehashed_manifest_fail(self):
        path = self.target / "flows.csv"
        path.write_text(path.read_text(encoding="utf-8").replace("OUTSIDE", "FAKE_CREDITOR"), encoding="utf-8")
        self.rehash()
        with self.assertRaisesRegex(ContractError, "Semantic replay"):
            verify(self.target)

    def test_tampered_html_and_rehashed_manifest_fail(self):
        path = self.target / "index.html"
        path.write_text(path.read_text(encoding="utf-8") + "<p>Fabricated bank rating</p>", encoding="utf-8")
        self.rehash()
        with self.assertRaisesRegex(ContractError, "Semantic replay"):
            verify(self.target)

    def test_extra_member_fails(self):
        (self.target / "extra.txt").write_text("extra", encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "file set"):
            verify(self.target)

    def test_manifest_mismatch_fails(self):
        (self.target / "analysis.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "manifest"):
            verify(self.target)

    def test_nonempty_output_fails(self):
        with self.assertRaisesRegex(ContractError, "empty"):
            write_report(self.data, self.scenarios, self.target)

    def test_symlink_member_fails(self):
        path = self.target / "payments.csv"
        path.unlink()
        try:
            path.symlink_to(self.target / "flows.csv")
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                self.skipTest("Windows does not grant permission to create symbolic links")
            raise
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

    def test_liability_matrix_preserves_nominal_cents(self):
        for cents, expected_usd in [
            (1, "0.01"),
            (49, "0.49"),
            (50, "0.50"),
            (99, "0.99"),
            (101, "1.01"),
            (12345, "123.45"),
        ]:
            with self.subTest(cents=cents):
                data = {
                    "schema_version": 1,
                    "currency": "USD",
                    "nodes": [
                        {"id": "A", "cash_cents": 20000, "outside_debt_cents": 3},
                        {"id": "B", "cash_cents": 0, "outside_debt_cents": 7},
                    ],
                    "edges": [{"debtor": "A", "creditor": "B", "amount_cents": cents}],
                }
                scenarios = [{"id": "baseline", "reductions_bps": {}, "injections_cents": {}}]
                files = build(data, scenarios)
                matrix = LiabilityMatrix()
                matrix.feed(files["index.html"].decode())
                self.assertEqual(matrix.rows[0], ["Debtor ↓ / Creditor →", "A", "B", "OUTSIDE"])
                self.assertEqual(matrix.rows[1][2], expected_usd)
                self.assertEqual(matrix.rows[1], ["A", "0.00", expected_usd, "0.03"])
                self.assertEqual(matrix.rows[2], ["B", "0.00", "0.00", "0.07"])
                self.assertIn(f"baseline,A,B,{cents}/1,", files["flows.csv"].decode())


if __name__ == "__main__":
    unittest.main()
