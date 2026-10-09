"""Stress scenario evidence, CSV flows, interactive HTML and independent replay."""

import html
from fractions import Fraction
from pathlib import Path

from .contracts import ContractError, canonical, digest, display, exact, read_json
from .engine import certificate, clear, enumerate_clearing, parse_network, resources, stress

FILES = {
    "network.json",
    "scenarios.json",
    "analysis.json",
    "cases.csv",
    "payments.csv",
    "flows.csv",
    "rounds.csv",
    "index.html",
}


def validate_scenarios(data, network):
    if not isinstance(data, list) or not data:
        raise ContractError("Scenarios must be a nonempty list")
    seen = set()
    for scenario in data:
        if not isinstance(scenario, dict) or set(scenario) != {"id", "reductions_bps", "injections_cents"}:
            raise ContractError("Scenario requires id, reductions_bps and injections_cents")
        name = scenario["id"]
        if not isinstance(name, str) or not name or name in seen:
            raise ContractError("Scenario IDs must be nonempty and unique")
        seen.add(name)
        if not isinstance(scenario["reductions_bps"], dict) or not isinstance(scenario["injections_cents"], dict):
            raise ContractError("Shock and injection maps must be objects")
        stress(network, scenario["reductions_bps"], scenario["injections_cents"])
    return data


def analyze(data, scenarios):
    network = parse_network(data)
    validate_scenarios(scenarios, network)
    cases, payments, flows, rounds = [], [], [], []
    for scenario in scenarios:
        shocked = stress(network, scenario["reductions_bps"], scenario["injections_cents"])
        result = clear(shocked)
        vector, total = result["payments"], shocked.total_debt
        available = resources(shocked, vector)
        residuals = certificate(shocked, vector)
        direct = [shocked.ids[i] for i, cash in enumerate(resources(shocked, total)) if cash < total[i]]
        defaults = [shocked.ids[i] for i, value in enumerate(vector) if value < total[i]]
        equity = [available[i] - vector[i] for i in range(len(vector))]
        outside = [vector[i] * shocked.outside[i] / total[i] if total[i] else 0 for i in range(len(vector))]
        if sum(shocked.cash) != sum(outside) + sum(equity):
            raise ContractError("Network-wide outside payment / equity conservation failed")
        cases.append(
            {
                "scenario": scenario["id"],
                "default_ids": defaults,
                "direct_default_ids": direct,
                "cascade_default_ids": sorted(set(defaults) - set(direct)),
                "default_count": len(defaults),
                "cascade_count": len(set(defaults) - set(direct)),
                "gross_unpaid_cents": exact(sum(total) - sum(vector)),
                "outside_shortfall_cents": exact(sum(shocked.outside) - sum(outside)),
                "external_asset_shock_cents": exact(
                    sum(
                        network.cash[i] * scenario["reductions_bps"].get(name, 0) / 10000
                        for i, name in enumerate(network.ids)
                    )
                ),
                "injection_cents": sum(scenario["injections_cents"].values()),
                "algorithm_rounds": len(result["rounds"]),
                "conservation_residual_cents": "0/1",
                "fixed_point_residual_cents": "0/1",
            }
        )
        for i, name in enumerate(shocked.ids):
            payments.append(
                {
                    "scenario": scenario["id"],
                    "node": name,
                    "cash_cents": exact(shocked.cash[i]),
                    "nominal_cents": exact(total[i]),
                    "paid_cents": exact(vector[i]),
                    "paid_usd_display": display(vector[i] / 100, 2),
                    "incoming_cents": exact(available[i] - shocked.cash[i]),
                    "equity_cents": exact(equity[i]),
                    "outside_paid_cents": exact(outside[i]),
                    "recovery_ratio": exact(vector[i] / total[i]) if total[i] else "",
                    "default": name in defaults,
                    "residual_cents": exact(residuals[i]),
                }
            )
            for j, creditor in enumerate(shocked.ids):
                nominal = shocked.liabilities[i][j]
                if nominal:
                    flows.append(
                        {
                            "scenario": scenario["id"],
                            "debtor": name,
                            "creditor": creditor,
                            "nominal_cents": exact(nominal),
                            "paid_cents": exact(nominal * vector[i] / total[i]),
                        }
                    )
            if shocked.outside[i]:
                flows.append(
                    {
                        "scenario": scenario["id"],
                        "debtor": name,
                        "creditor": "OUTSIDE",
                        "nominal_cents": exact(shocked.outside[i]),
                        "paid_cents": exact(outside[i]),
                    }
                )
        for row in result["rounds"]:
            rounds.append(
                {
                    "scenario": scenario["id"],
                    "step": row["step"],
                    "default_ids": row["default_ids"],
                    "payments_cents": {
                        name: exact(value) for name, value in zip(shocked.ids, row["payments"], strict=True)
                    },
                }
            )
    return {
        "schema_version": 1,
        "currency": "USD",
        "amount_contract": "exact rational cents",
        "data_kind": "synthetic network; not observations of real institutions",
        "node_ids": list(network.ids),
        "cases": cases,
        "payments": payments,
        "flows": flows,
        "rounds": rounds,
    }


def render(analysis):
    esc = html.escape
    options, panels = [], []
    for case in analysis["cases"]:
        name = case["scenario"]
        options.append(f"<option value='{esc(name, quote=True)}'>{esc(name)}</option>")
        rows = []
        for payment in analysis["payments"]:
            if payment["scenario"] == name:
                rows.append(
                    f"<tr><td>{esc(payment['node'])}</td>"
                    f"<td>${esc(payment['paid_usd_display'])}</td>"
                    f"<td>{esc(payment['recovery_ratio'])}</td>"
                    f"<td>{'DEFAULT' if payment['default'] else 'paid in full'}</td>"
                    f"<td><code>{esc(payment['paid_cents'])}</code></td>"
                    f"<td>{esc(payment['residual_cents'])}</td></tr>"
                )
        default_ids = ", ".join(case["default_ids"]) or "none"
        cascade_ids = ", ".join(case["cascade_default_ids"]) or "none"
        panels.append(
            f"<section data-case='{esc(name, quote=True)}'><h2>{esc(name)}</h2>"
            "<div class='cards'>"
            f"<div><strong>{case['default_count']}</strong><span>Defaulting institutions</span></div>"
            f"<div><strong>{case['cascade_count']}</strong><span>Additional cascade defaults</span></div>"
            f"<div><strong>${display(read_fraction(case['outside_shortfall_cents']) / 100, 2)}</strong>"
            "<span>Outside creditor shortfall</span></div>"
            f"<div><strong>${display(read_fraction(case['gross_unpaid_cents']) / 100, 2)}</strong>"
            "<span>Gross unpaid debt (includes internal debt)</span></div></div>"
            f"<p>Defaults: {esc(default_ids)}. Cascade additions: {esc(cascade_ids)}. "
            f"Injection budget: ${display(Fraction(case['injection_cents'], 100), 2)}.</p>"
            "<div class='scroll'><table><thead><tr><th>Institution</th><th>Total paid</th>"
            "<th>Exact recovery ratio</th><th>Status</th><th>Exact cents</th>"
            "<th>Fixed-point residual</th></tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table></div><details><summary>Algorithm evidence</summary>"
            f"<p>{case['algorithm_rounds']} active-set solves. These are computation steps, "
            "not elapsed contagion time. All clearing residuals are exactly zero; "
            "external assets equal outside payments plus final equity.</p></details></section>"
        )
    matrix = []
    for debtor in analysis["node_ids"]:
        cells = []
        for creditor in analysis["node_ids"] + ["OUTSIDE"]:
            amount = next(
                (
                    flow["nominal_cents"]
                    for flow in analysis["flows"]
                    if flow["scenario"] == analysis["cases"][0]["scenario"]
                    and flow["debtor"] == debtor
                    and flow["creditor"] == creditor
                ),
                "0/1",
            )
            cells.append(f"<td>{display(read_fraction(amount) / 100, 2)}</td>")
        matrix.append(f"<tr><th>{esc(debtor)}</th>" + "".join(cells) + "</tr>")
    columns = "".join(f"<th>{esc(name)}</th>" for name in analysis["node_ids"] + ["OUTSIDE"])
    return (
        "<!doctype html><html lang='en'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>NetworkClear · debt clearing and contagion</title><style>"
        "*{box-sizing:border-box}body{margin:0;background:#f3f5fa;color:#18273b;font:15px/1.6 system-ui}"
        "header,main{max-width:1200px;margin:auto;padding:28px}header{border-bottom:4px solid #7159bf}"
        "h1{font-size:42px;margin:0}.eyebrow{color:#7159bf;font-weight:700}"
        "section,.toolbar,.matrix{background:white;padding:24px;margin:20px 0;border-radius:12px;"
        "border:1px solid #dbe1eb}h2{margin-top:0}.cards{display:grid;grid-template-columns:repeat(4,1fr);"
        "gap:12px}.cards div{background:#f2effa;border-radius:8px;padding:16px}.cards strong{display:block;"
        "font-size:28px}.cards span{font-size:13px}table{width:100%;border-collapse:collapse;font-size:13px}"
        "td,th{padding:12px;text-align:left;border-bottom:1px solid #e3e8f0}th{background:#eef0f7}"
        "select{font:inherit;padding:8px;max-width:100%}.scroll{overflow-x:auto}a{color:#6046ad}"
        "section[hidden]{display:none}code{overflow-wrap:anywhere}"
        "@media(max-width:700px){.cards{grid-template-columns:repeat(2,1fr)}h1{font-size:30px}"
        "header,main{padding:16px}}</style><header><p class='eyebrow'>DEBT NETWORK → EXACT CLEARING → CERTIFICATE</p>"
        "<h1>NetworkClear</h1><p>交易对手违约传染与债务清算。Synthetic institution networks, "
        "pro-rata repayment, exact rational payments, and independent small-network verification.</p>"
        "<p>Gross unpaid internal debt and outside creditor losses are reported separately. "
        "This model is an educational experiment, not a real-bank risk estimate.</p></header><main>"
        "<div class='toolbar'><label>Stress scenario <select id='scenario'>"
        + "".join(options)
        + "</select></label><p><a href='cases.csv'>Scenario CSV</a> · <a href='payments.csv'>Payments</a> · "
        "<a href='flows.csv'>Debt flows</a> · <a href='rounds.csv'>Algorithm rounds</a> · "
        "<a href='manifest.json'>SHA-256 manifest</a></p></div>"
        + "".join(panels)
        + "<div class='matrix'><h2>Nominal liability matrix / 债务矩阵</h2>"
        "<p>Rows owe columns. Amounts below are USD; outside creditors do not owe the network.</p>"
        "<div class='scroll'><table><thead><tr><th>Debtor ↓ / Creditor →</th>"
        + columns
        + "</tr></thead><tbody>"
        + "".join(matrix)
        + "</tbody></table></div></div>"
        "<p>Every debtor has positive outside debt. Display rounds to cents; mathematical payments "
        "can be fractional cents. <code>networkclear verify examples/demo</code> recomputes "
        "all files and exhaustively checks clearing regimes for networks of at most eight nodes. "
        "Hashes establish consistency, not authenticity.</p></main><script>"
        "const select=document.querySelector('#scenario');function refresh(){"
        "document.querySelectorAll('section').forEach(s=>{s.hidden=s.dataset.case!==select.value;});}"
        "select.addEventListener('change',refresh);refresh();</script></html>\n"
    ).encode()


def read_fraction(value):
    from fractions import Fraction

    return Fraction(value)


def csv_bytes(rows, fields):
    import csv
    import io

    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


def build(data, scenarios):
    analysis = analyze(data, scenarios)
    cases = [
        {**case, **{key: ";".join(case[key]) for key in ("default_ids", "direct_default_ids", "cascade_default_ids")}}
        for case in analysis["cases"]
    ]
    rounds = [
        {
            **row,
            "default_ids": ";".join(row["default_ids"]),
            "payments_cents": canonical(row["payments_cents"]).decode().strip(),
        }
        for row in analysis["rounds"]
    ]
    files = {
        "network.json": canonical(data),
        "scenarios.json": canonical(scenarios),
        "analysis.json": canonical(analysis),
        "index.html": render(analysis),
        "cases.csv": csv_bytes(cases, list(cases[0])),
        "payments.csv": csv_bytes(analysis["payments"], list(analysis["payments"][0])),
        "flows.csv": csv_bytes(analysis["flows"], ["scenario", "debtor", "creditor", "nominal_cents", "paid_cents"]),
        "rounds.csv": csv_bytes(rounds, ["scenario", "step", "default_ids", "payments_cents"]),
    }
    files["manifest.json"] = canonical(
        {"schema_version": 1, "files": {name: digest(raw) for name, raw in sorted(files.items())}}
    )
    return files


def write_report(data, scenarios, directory):
    files = build(data, scenarios)
    target = Path(directory)
    if target.is_symlink() or (target.exists() and any(target.iterdir())):
        raise ContractError("Output must be a new or empty directory")
    target.mkdir(parents=True, exist_ok=True)
    for name, raw in files.items():
        (target / name).write_bytes(raw)
    return read_json(files["analysis.json"])


def verify(directory):
    target = Path(directory)
    if target.is_symlink() or not target.is_dir():
        raise ContractError("Report must be a regular directory")
    if {p.name for p in target.iterdir()} != FILES | {"manifest.json"}:
        raise ContractError("Report file set does not match the schema")
    if any(p.is_symlink() or not p.is_file() for p in target.iterdir()):
        raise ContractError("Report members must be regular files, not symlinks")
    manifest = read_json((target / "manifest.json").read_bytes())
    actual = {name: digest((target / name).read_bytes()) for name in sorted(FILES)}
    if manifest != {"schema_version": 1, "files": actual}:
        raise ContractError("Report hash manifest mismatch")
    data = read_json((target / "network.json").read_bytes())
    scenarios = read_json((target / "scenarios.json").read_bytes())
    replay = build(data, scenarios)
    for name, raw in replay.items():
        if (target / name).read_bytes() != raw:
            raise ContractError(f"Semantic replay mismatch: {name}")
    network = parse_network(data)
    checked = 0
    if len(network.ids) <= 8:
        for scenario in scenarios:
            shocked = stress(network, scenario["reductions_bps"], scenario["injections_cents"])
            if clear(shocked)["payments"] != enumerate_clearing(shocked):
                raise ContractError("Independent clearing oracle mismatch")
            checked += 1
    return {"verified": True, "files": len(replay), "scenarios": len(scenarios), "oracle_checked_scenarios": checked}
