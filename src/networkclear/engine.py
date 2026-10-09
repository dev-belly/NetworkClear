"""Eisenberg–Noe clearing with exact rational arithmetic and explicit outside creditors."""

import itertools
import re
from dataclasses import dataclass
from fractions import Fraction

from .contracts import ContractError, integer


@dataclass(frozen=True)
class Network:
    ids: tuple[str, ...]
    cash: tuple[Fraction, ...]
    outside: tuple[Fraction, ...]
    liabilities: tuple[tuple[Fraction, ...], ...]  # debtor rows, creditor columns

    @property
    def total_debt(self):
        return tuple(sum(row) + outside for row, outside in zip(self.liabilities, self.outside, strict=True))

    @property
    def relative(self):
        total = self.total_debt
        return tuple(
            tuple(value / total[i] if total[i] else Fraction(0) for value in row)
            for i, row in enumerate(self.liabilities)
        )


def parse_network(data):
    if not isinstance(data, dict) or set(data) != {"schema_version", "currency", "nodes", "edges"}:
        raise ContractError("Network requires schema_version, currency, nodes and edges")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ContractError("Unsupported schema_version")
    if data["currency"] != "USD":
        raise ContractError("The input contract supports USD cents only")
    nodes, edges = data["nodes"], data["edges"]
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 50:
        raise ContractError("nodes must contain between 1 and 50 institutions")
    if not isinstance(edges, list):
        raise ContractError("edges must be a list")
    parsed = {}
    for node in nodes:
        if not isinstance(node, dict) or set(node) != {"id", "cash_cents", "outside_debt_cents"}:
            raise ContractError("Node requires id, cash_cents, outside_debt_cents")
        name = node["id"]
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}", name):
            raise ContractError("Node IDs must be safe identifiers of length 1–32")
        if name in parsed:
            raise ContractError("Duplicate node ID")
        if name == "OUTSIDE":
            raise ContractError("OUTSIDE is reserved for external creditors")
        parsed[name] = (
            Fraction(integer(node["cash_cents"], "cash_cents", 0)),
            Fraction(integer(node["outside_debt_cents"], "outside_debt_cents", 0)),
        )
    ids = tuple(sorted(parsed))
    indexes = {name: i for i, name in enumerate(ids)}
    matrix = [[Fraction(0) for _ in ids] for _ in ids]
    seen = set()
    for edge in edges:
        if not isinstance(edge, dict) or set(edge) != {"debtor", "creditor", "amount_cents"}:
            raise ContractError("Edge requires debtor, creditor and amount_cents")
        debtor, creditor = edge["debtor"], edge["creditor"]
        if not isinstance(debtor, str) or not isinstance(creditor, str):
            raise ContractError("Edge endpoints must be node IDs")
        if debtor not in indexes or creditor not in indexes or debtor == creditor:
            raise ContractError("Edge endpoints must be distinct known nodes")
        if (debtor, creditor) in seen:
            raise ContractError("Duplicate liability edge")
        seen.add((debtor, creditor))
        matrix[indexes[debtor]][indexes[creditor]] = Fraction(integer(edge["amount_cents"], "amount_cents", 1))
    cash, outside = zip(*(parsed[name] for name in ids), strict=True)
    for i, row in enumerate(matrix):
        if sum(row) > 0 and outside[i] <= 0:
            raise ContractError("Every debtor must owe a positive amount to outside creditors")
    return Network(ids, tuple(cash), tuple(outside), tuple(tuple(row) for row in matrix))


def solve_linear(matrix, rhs):
    """Exact Gaussian elimination; never treat a small floating residual as zero."""
    n = len(rhs)
    if len(matrix) != n or any(len(row) != n for row in matrix):
        raise ContractError("Linear system dimensions do not match")
    rows = [[Fraction(value) for value in row] + [Fraction(value)] for row, value in zip(matrix, rhs, strict=True)]
    for column in range(n):
        pivot = next((i for i in range(column, n) if rows[i][column]), None)
        if pivot is None:
            raise ContractError("Singular clearing regime")
        rows[column], rows[pivot] = rows[pivot], rows[column]
        divisor = rows[column][column]
        rows[column] = [value / divisor for value in rows[column]]
        for i in range(n):
            if i != column and rows[i][column]:
                factor = rows[i][column]
                rows[i] = [a - factor * b for a, b in zip(rows[i], rows[column], strict=True)]
    return tuple(row[-1] for row in rows)


def resources(network, payments):
    relative = network.relative
    return tuple(
        network.cash[i] + sum(relative[j][i] * payments[j] for j in range(len(network.ids)))
        for i in range(len(network.ids))
    )


def certificate(network, payments):
    total = network.total_debt
    if len(payments) != len(total) or any(type(p) not in {int, Fraction} for p in payments):
        raise ContractError("Certificate requires one exact payment per node")
    available = resources(network, payments)
    residuals = tuple(p - min(debt, cash) for p, debt, cash in zip(payments, total, available, strict=True))
    if any(p < 0 or p > debt for p, debt in zip(payments, total, strict=True)) or any(residuals):
        raise ContractError("Payments fail the bounded clearing fixed-point certificate")
    return residuals


def clear(network):
    """Start at nominal payments; grow the default set and solve each active sub-system."""
    total, relative = network.total_debt, network.relative
    payments, defaults, rounds = total, set(), []
    for step in range(len(total) + 1):
        available = resources(network, payments)
        detected = {i for i, debt in enumerate(total) if available[i] < debt}
        expanded = defaults | detected
        if expanded == defaults:
            certificate(network, payments)
            return {"payments": tuple(payments), "defaults": tuple(sorted(defaults)), "rounds": rounds}
        defaults = expanded
        active = sorted(defaults)
        matrix = [[Fraction(i == j) - relative[j][i] for j in active] for i in active]
        rhs = [
            network.cash[i] + sum(relative[j][i] * total[j] for j in range(len(total)) if j not in defaults)
            for i in active
        ]
        values = solve_linear(matrix, rhs)
        next_payments = list(total)
        for i, value in zip(active, values, strict=True):
            next_payments[i] = value
        if any(after > before for after, before in zip(next_payments, payments, strict=True)):
            raise ContractError("Default algorithm failed payment monotonicity")
        rounds.append(
            {"step": step + 1, "default_ids": [network.ids[i] for i in active], "payments": tuple(next_payments)}
        )
        payments = tuple(next_payments)
    raise ContractError("Default algorithm exceeded the finite node bound")


def enumerate_clearing(network):
    """Independent small-network oracle: solve ALL regimes, not the iterative default path.

    It solves a full n×n equation system for each candidate default set. Boundary
    regimes can describe the same vector, so candidates are deduplicated exactly.
    """
    n = len(network.ids)
    if n > 8:
        raise ContractError("Independent enumeration is limited to eight nodes")
    total, relative = network.total_debt, network.relative
    candidates = set()
    for mask in itertools.product((False, True), repeat=n):
        matrix, rhs = [], []
        for i in range(n):
            matrix.append([Fraction(i == j) - (relative[j][i] if mask[i] else 0) for j in range(n)])
            rhs.append(network.cash[i] if mask[i] else total[i])
        values = solve_linear(matrix, rhs)
        if any(value < 0 or value > debt for value, debt in zip(values, total, strict=True)):
            continue
        available = resources(network, values)
        if any((mask[i] and available[i] > total[i]) or (not mask[i] and available[i] < total[i]) for i in range(n)):
            continue
        # Full independent direct equation check; do not call clear or its certificate.
        if all(values[i] == min(total[i], available[i]) for i in range(n)):
            candidates.add(values)
    if len(candidates) != 1:
        raise ContractError(f"Expected one clearing vector; found {len(candidates)}")
    return candidates.pop()


def stress(network, reductions_bps, injections_cents):
    if set(reductions_bps) - set(network.ids) or set(injections_cents) - set(network.ids):
        raise ContractError("Shock or injection refers to an unknown node")
    cash = []
    for i, name in enumerate(network.ids):
        reduction = integer(reductions_bps.get(name, 0), "reduction_bps", 0)
        if reduction > 10000:
            raise ContractError("reduction_bps must be <= 10000")
        injection = integer(injections_cents.get(name, 0), "injection_cents", 0)
        cash.append(network.cash[i] * Fraction(10000 - reduction, 10000) + injection)
    return Network(network.ids, tuple(cash), network.outside, network.liabilities)
