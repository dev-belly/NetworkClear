import copy
import random
import unittest
from fractions import Fraction

from networkclear.cli import demo_inputs
from networkclear.contracts import ContractError, read_json
from networkclear.engine import (
    Network,
    certificate,
    clear,
    enumerate_clearing,
    parse_network,
    resources,
    solve_linear,
    stress,
)


class ClearingTests(unittest.TestCase):
    def setUp(self):
        self.data, self.scenarios = demo_inputs()
        self.network = parse_network(self.data)

    def test_baseline_is_solvent(self):
        result = clear(self.network)
        self.assertEqual(result["payments"], self.network.total_debt)
        self.assertEqual(result["defaults"], ())
        self.assertEqual(result["rounds"], [])

    def test_hand_calculated_chain_shock(self):
        network = stress(self.network, {"A": 5000}, {})
        result = clear(network)
        self.assertEqual(result["payments"][:4], (500000, 450000, 410000, 378000))
        self.assertEqual(result["defaults"], (0, 1, 2, 3))
        self.assertEqual(
            [r["default_ids"] for r in result["rounds"]], [["A"], ["A", "B"], ["A", "B", "C"], ["A", "B", "C", "D"]]
        )
        self.assertEqual(certificate(network, result["payments"]), (0,) * 8)

    def test_cycle_solution_is_exact_and_matches_enumeration(self):
        network = stress(self.network, {"E": 9000, "F": 9000}, {})
        result = clear(network)
        self.assertEqual(result["payments"], enumerate_clearing(network))
        # E = 80000 + (11/15) F, F = 65000 + (3/4) E; both are below nominal debt.
        self.assertEqual(result["payments"][4], Fraction(7660000, 27))
        self.assertEqual(result["payments"][5], Fraction(2500000, 9))

    def test_boundary_regimes_deduplicate(self):
        network = parse_network(
            {
                "schema_version": 1,
                "currency": "USD",
                "nodes": [{"id": "A", "cash_cents": 100, "outside_debt_cents": 100}],
                "edges": [],
            }
        )
        self.assertEqual(enumerate_clearing(network), (100,))
        self.assertEqual(clear(network)["defaults"], ())

    def test_zero_debt_node_can_receive_payments_and_retain_equity(self):
        network = parse_network(
            {
                "schema_version": 1,
                "currency": "USD",
                "nodes": [
                    {"id": "A", "cash_cents": 100, "outside_debt_cents": 50},
                    {"id": "B", "cash_cents": 0, "outside_debt_cents": 0},
                ],
                "edges": [{"debtor": "A", "creditor": "B", "amount_cents": 50}],
            }
        )
        self.assertEqual(clear(network)["payments"], (100, 0))
        self.assertEqual(resources(network, (100, 0)), (100, 50))
        self.assertEqual(enumerate_clearing(network), (100, 0))

    def test_total_cash_wipeout_clears_to_zero(self):
        network = stress(self.network, dict.fromkeys(self.network.ids, 10000), {})
        result = clear(network)
        self.assertEqual(result["payments"], (0,) * 8)
        self.assertEqual(len(result["defaults"]), 8)
        self.assertEqual(result["payments"], enumerate_clearing(network))

    def test_shock_grid_is_monotone(self):
        previous = self.network.total_debt
        for bps in range(0, 10001, 1000):
            vector = clear(stress(self.network, {"A": bps}, {}))["payments"]
            self.assertTrue(all(after <= before for after, before in zip(vector, previous, strict=True)))
            previous = vector

    def test_injection_cannot_reduce_any_payment(self):
        network = stress(self.network, {"A": 5000}, {})
        rescue = stress(self.network, {"A": 5000}, {"A": 200000})
        before, after = clear(network)["payments"], clear(rescue)["payments"]
        self.assertTrue(all(a >= b for a, b in zip(after, before, strict=True)))

    def test_algorithm_rounds_are_monotone_and_finite(self):
        network = stress(self.network, {"A": 6000, "E": 9000, "F": 9000}, {})
        previous, defaults = network.total_debt, set()
        for row in clear(network)["rounds"]:
            self.assertTrue(defaults < set(row["default_ids"]))
            self.assertTrue(all(a <= b for a, b in zip(row["payments"], previous, strict=True)))
            previous, defaults = row["payments"], set(row["default_ids"])
        self.assertLessEqual(len(clear(network)["rounds"]), len(network.ids))

    def test_permutation_invariance(self):
        network = stress(self.network, {"A": 5000, "E": 7500, "F": 7500}, {})
        order = [5, 2, 7, 0, 3, 6, 1, 4]
        permuted = Network(
            tuple(network.ids[i] for i in order),
            tuple(network.cash[i] for i in order),
            tuple(network.outside[i] for i in order),
            tuple(tuple(network.liabilities[i][j] for j in order) for i in order),
        )
        expected = dict(zip(network.ids, clear(network)["payments"], strict=True))
        actual = dict(zip(permuted.ids, clear(permuted)["payments"], strict=True))
        self.assertEqual(actual, expected)

    def test_seeded_networks_against_independent_regimes(self):
        rng = random.Random(20261008)
        for seed_case in range(100):
            size = rng.randint(1, 5)
            nodes = [
                {"id": f"N{i}", "cash_cents": rng.randint(0, 300), "outside_debt_cents": rng.randint(1, 100)}
                for i in range(size)
            ]
            edges = [
                {"debtor": f"N{i}", "creditor": f"N{j}", "amount_cents": rng.randint(1, 100)}
                for i in range(size)
                for j in range(size)
                if i != j and rng.random() < 0.6
            ]
            with self.subTest(case=seed_case):
                network = parse_network({"schema_version": 1, "currency": "USD", "nodes": nodes, "edges": edges})
                self.assertEqual(clear(network)["payments"], enumerate_clearing(network))

    def test_wrong_payment_certificate_fails(self):
        for values in [(0,) * 8, (True,) * 8, (1.0,) * 8, (0,) * 7, (-1,) * 8]:
            with self.subTest(values=values), self.assertRaises(ContractError):
                certificate(self.network, values)

    def test_fractional_cents_are_not_quantized(self):
        network = stress(self.network, {"A": 3333}, {})
        result = clear(network)
        self.assertTrue(any(value.denominator != 1 for value in result["payments"]))
        self.assertEqual(certificate(network, result["payments"]), (0,) * 8)

    def test_exact_gaussian_elimination_and_singular_rejection(self):
        self.assertEqual(solve_linear([[2, 1], [1, 3]], [1, 2]), (Fraction(1, 5), Fraction(3, 5)))
        with self.assertRaisesRegex(ContractError, "Singular"):
            solve_linear([[1, 1], [1, 1]], [1, 2])
        with self.assertRaisesRegex(ContractError, "dimensions"):
            solve_linear([[1]], [1, 2])


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.data, _ = demo_inputs()

    def test_boolean_float_string_and_negative_amounts_fail(self):
        for value in [True, 1.5, "100", -1, None]:
            with self.subTest(value=value):
                data = copy.deepcopy(self.data)
                data["nodes"][0]["cash_cents"] = value
                with self.assertRaises(ContractError):
                    parse_network(data)

    def test_closed_debt_cycle_rejected(self):
        self.data["nodes"][4]["outside_debt_cents"] = 0
        with self.assertRaisesRegex(ContractError, "outside"):
            parse_network(self.data)

    def test_duplicate_node_and_reserved_id_rejected(self):
        for name in ["B", "OUTSIDE", "../escape", "<script>"]:
            with self.subTest(name=name):
                data = copy.deepcopy(self.data)
                data["nodes"][0]["id"] = name
                with self.assertRaises(ContractError):
                    parse_network(data)

    def test_duplicate_self_unknown_and_zero_edge_rejected(self):
        for edge in [
            self.data["edges"][0],
            {"debtor": "A", "creditor": "A", "amount_cents": 1},
            {"debtor": "A", "creditor": "Z", "amount_cents": 1},
            {"debtor": "B", "creditor": "E", "amount_cents": 0},
        ]:
            with self.subTest(edge=edge):
                data = copy.deepcopy(self.data)
                data["edges"].append(edge)
                with self.assertRaises(ContractError):
                    parse_network(data)

    def test_invalid_shock_injection_and_unknown_node(self):
        network = parse_network(self.data)
        for reductions, injections in [
            ({"A": -1}, {}),
            ({"A": 10001}, {}),
            ({"A": True}, {}),
            ({"Z": 1}, {}),
            ({}, {"A": 1.5}),
            ({}, {"A": -1}),
        ]:
            with self.subTest(reductions=reductions, injections=injections), self.assertRaises(ContractError):
                stress(network, reductions, injections)

    def test_currency_schema_and_empty_network_fail(self):
        for key, value in [("currency", "EUR"), ("schema_version", True), ("nodes", []), ("edges", {})]:
            with self.subTest(key=key):
                data = {**self.data, key: value}
                with self.assertRaises(ContractError):
                    parse_network(data)

    def test_strict_json(self):
        for raw in ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}']:
            with self.subTest(raw=raw), self.assertRaises(ContractError):
                read_json(raw)


if __name__ == "__main__":
    unittest.main()
