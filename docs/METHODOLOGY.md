# Clearing contracts

Let `L[i,j]` denote debtor `i`'s debt to creditor `j`, `s[i]` outside debt and `x[i]` external cash. Total debt is `b[i] = sum_j L[i,j] + s[i]`; relative liabilities are `P[i,j] = L[i,j]/b[i]`, or zero for a zero-debt node.

$$p_i = \min\left(b_i,\ x_i + \sum_j P_{ji}p_j\right).$$

Rows owe columns. Outside creditors do not return payments to the network. Positive outside debt makes every positive-debt internal row sum strictly less than one: a deliberately strong sufficient condition for unique clearing and nonsingular active systems. Zero-debt nodes pay zero and retain incoming assets as equity.

The main solver starts at nominal payments, expands the default set and solves the reduced linear system with rational Gaussian elimination. Payments weakly decrease and no more than `n` default sets are solved. Rounds are computational diagnostics, not elapsed default time.

The independent oracle enumerates every default mask and solves a full system, checks regime inequalities, and deduplicates identical boundary vectors. It does not call the iterative solver or its certificate; it shares the linear algebra helper. This exhaustive check is limited to eight nodes. Larger reports retain certificates and conservation checks and explicitly return `oracle_checked_scenarios: 0`.

## Input schema

```json
{
  "schema_version": 1,
  "currency": "USD",
  "nodes": [
    {"id": "A", "cash_cents": 100, "outside_debt_cents": 50},
    {"id": "B", "cash_cents": 0, "outside_debt_cents": 50}
  ],
  "edges": [{"debtor": "A", "creditor": "B", "amount_cents": 50}]
}
```

Scenarios are an array of objects such as `{ "id": "shock", "reductions_bps": {"A": 5000}, "injections_cents": {} }`. IDs are unique. Cash, debt and injections are nonnegative integer USD cents; edges must be strictly positive, unique and between distinct known nodes. Booleans, floats and numeric strings fail. `OUTSIDE` is reserved; networks have 1–50 nodes.

Shocks are integer basis points in `[0,10000]`; injections apply after asset reductions and debts remain fixed. All outputs preserve exact rational cents, even when the model produces fractions of a cent. Decimal display uses isolated half-even rounding.

The nominal liability matrix displays USD with two decimal places, including outside debt and zero cells. A one-cent debt appears as `0.01`, matching the exact nominal cents in `flows.csv`; nominal inputs are integral cents and have no rounding loss in this view. Cleared payments can still be fractional cents, so their exact fractions remain authoritative.

## Losses and verification

Gross unpaid debt sums all `b-p`, including internal exposures. Outside shortfall sums unpaid outside debt only. Network accounting cancels internal transfers, giving **external assets = outside payments + equity**. Direct defaults cannot pay even assuming full nominal counterparty payments; cascade defaults are additional final defaults. This is a model diagnostic, not empirical causal identification.

Replay checks the fixed report member set, rejects symlinks, verifies hashes and recomputes every member. It detects output-only corruption with updated hashes, not a coordinated rewrite of the input and all regenerated evidence.

The source model is [Eisenberg & Noe (2001)](https://pubsonline.informs.org/doi/10.1287/mnsc.47.2.236.9835). Synthetic exposures do not estimate real-bank risk. Seniority, collateral, bankruptcy costs, fire sales, uncertain assets and dynamic liquidity are outside scope.
