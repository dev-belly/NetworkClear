"""Stress scenario evidence, CSV flows, interactive HTML and independent replay."""

import html
import json
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


_REPORT_CSS = """
:root{color:#172237;background:#f1f4fa;font:15px/1.55 system-ui,sans-serif;
  --line:#dce3f0;--purple:#5543ad;--muted:#53637a}
*{box-sizing:border-box}
body{margin:0}
[hidden]{display:none!important}
header,main{max-width:1250px;margin:auto;padding-inline:clamp(16px,4vw,44px)}
header{padding-block:clamp(16px,3vw,34px) 0}
.hero{padding:clamp(20px,5vw,48px);border-radius:26px;color:white;
  background:radial-gradient(ellipse at 98% 110%,#4f45aa,transparent 64%),
  linear-gradient(115deg,#131e35,#262653);box-shadow:0 15px 32px #293a6620}
.hero a{color:#eeebff}
.brand{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.brand strong{font-size:1.05rem}
h1{font-size:clamp(2rem,5.8vw,4.05rem);letter-spacing:-.06em;line-height:1.04;margin:18px 0 10px}
h2{font-size:1.27rem;letter-spacing:-.034em;margin:0 0 12px;overflow-wrap:anywhere}
.hero p{color:#e1e6ff;margin:0;max-width:62ch}
.hero .units{font-size:.81rem;margin-top:6px;color:#d6d9ff}
main{padding-bottom:40px}
section,.toolbar,.matrix,.comparison{background:white;padding:clamp(13px,2.4vw,24px);margin:16px 0;
  border-radius:17px;border:1px solid var(--line);box-shadow:0 7px 22px #3e4f7a09;min-width:0}
.controls{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
label{display:grid;gap:5px;color:#3f506b;font-size:.84rem;font-weight:650;min-width:0}
select,input{font:inherit;min-width:0;width:100%;min-height:41px;padding:8px 10px;color:#1b2945;
  border:1px solid #cdd7ec;border-radius:9px;background:#f8faff}
select:focus-visible,input:focus-visible,a:focus-visible,summary:focus-visible{
  outline:3px solid #6654c6;outline-offset:3px}
.downloads{display:flex;gap:8px 15px;flex-wrap:wrap;margin:13px 0 0;font-size:.79rem}
a{color:#4a39a5;text-underline-offset:.18em}
.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
.cards div{background:#f1f1fc;border:1px solid #e8e7f7;border-radius:12px;padding:13px;min-width:0}
.cards div:nth-child(3){background:#271e57;color:#fff;border-color:#271e57}
.cards div:nth-child(4){background:#edf3ff;border-color:#e2eaff}
.cards strong{display:block;font-size:clamp(1.1rem,2.5vw,1.75rem);letter-spacing:-.04em;
  font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.cards span{font-size:.77rem}
.scroll{overflow:auto}
table{width:100%;border-collapse:collapse;font-size:.86rem}
td,th{padding:10px;text-align:left;border-bottom:1px solid #e7edf6;overflow-wrap:anywhere}
th{background:#f3f5fb;color:#43536d;font-size:.79rem}
td:nth-child(2),td:nth-child(3){font-variant-numeric:tabular-nums}
tr[data-default="true"]>td:nth-child(4){color:#a52c4b;font-weight:650}
section table{min-width:560px}
.matrix table{min-width:520px}
.comparison table{table-layout:fixed}
.comparison td,.comparison th{padding:8px}
.comparison th:first-child{width:37%}
.comparison td:nth-child(2){font-weight:700;color:#473794}
.recovery-bar{display:block;max-width:92px;height:4px;border-radius:999px;margin-top:5px;
  background:linear-gradient(90deg,#6961c7 var(--share),#e3e9f4 var(--share))}
#match-count{color:var(--muted);font-size:.8rem;margin:.6rem 0 0}
code{overflow-wrap:anywhere}
summary{cursor:pointer;color:var(--purple);font-size:.87rem;font-weight:650}
details{margin-top:12px}
@media(max-width:720px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}
.hero{border-radius:18px}section,.toolbar,.matrix,.comparison{margin-block:11px}}
@media(max-width:520px){.controls{grid-template-columns:minmax(0,1fr)}
.comparison td,.comparison th{padding-inline:5px}.cards div{padding:10px}}
"""


_REPORT_HEADER = """</style><header><div class='hero'><div class='brand'>
<strong>NetworkClear</strong><a href='https://github.com/dev-belly/NetworkClear'>Source on
GitHub</a>
</div><h1>Debt clearing explorer</h1>
<p>Explore how synthetic asset shocks change payments, cascade defaults and outside
creditor losses.</p><p class='units'>Exact rational clearing · Amounts in
USD</p></div></header><main>
<div class='toolbar'><div class='controls'><label>Stress scenario <select id='scenario'>"""


_REPORT_CONTROLS = """</select></label><label>Comparison scenario
<select id='compare-scenario' disabled></select></label>
<label>Institution <input id='institution' type='search' placeholder='Filter by institution ID'>
</label></div><p class='downloads'><a href='cases.csv'>Scenario CSV</a><a
href='payments.csv'>Payments</a>
<a href='flows.csv'>Debt flows</a><a href='rounds.csv'>Algorithm rounds</a>
<a href='manifest.json'>SHA-256 manifest</a></p><p id='match-count' role='status'></p></div>
<div id='comparison' class='comparison' hidden><h2>Scenario comparison</h2>
<table aria-label='Scenario comparison'><thead><tr><th scope='col'>Measure</th>
<th id='selected-title' scope='col'></th><th id='comparison-title'
scope='col'></th></tr></thead>
<tbody id='comparison-rows'></tbody></table></div>"""


_REPORT_SCRIPT = """
const byId = id => document.getElementById(id);
const select = byId("scenario");
const comparison = byId("compare-scenario");
const institution = byId("institution");
const panels = [...document.querySelectorAll("section[data-case]")];
const choices = [...select.options];
comparison.append(new Option("No comparison", ""),
  ...choices.map(option => new Option(option.text, option.value)));
comparison.disabled = choices.length < 2;
if (choices.length > 1) comparison.value = choices[1].value;

function textCell(value, tag = "td") {
  const cell = document.createElement(tag);
  cell.textContent = value;
  return cell;
}
function renderComparison(active) {
  const reference = panels.find(panel => panel.dataset.case === comparison.value);
  byId("comparison").hidden = !active || !reference;
  if (!active || !reference) return;
  byId("selected-title").textContent = active.querySelector("h2").textContent;
  byId("comparison-title").textContent = reference.querySelector("h2").textContent;
  const left = [...active.querySelector(".cards").children];
  const right = [...reference.querySelector(".cards").children];
  byId("comparison-rows").replaceChildren(...left.map((metric, index) => {
    const row = document.createElement("tr");
    const label = textCell(metric.querySelector("span").textContent, "th");
    label.scope = "row";
    row.append(label, textCell(metric.querySelector("strong").textContent),
      textCell(right[index].querySelector("strong").textContent));
    return row;
  }));
}
function refresh() {
  const active = panels.find(panel => panel.dataset.case === select.value);
  for (const panel of panels) panel.hidden = panel !== active;
  renderComparison(active);
  const query = institution.value.trim().toLowerCase();
  const rows = [...(active?.querySelectorAll("tbody tr") ?? [])];
  let shown = 0;
  for (const row of rows) {
    row.hidden = !row.cells[0].textContent.toLowerCase().includes(query);
    if (!row.hidden) shown++;
  }
  byId("match-count").textContent = shown + " of " + rows.length + " institutions";
}
for (const row of document.querySelectorAll("section[data-case] tbody tr")) {
  row.dataset.default = String(row.cells[3].textContent === "DEFAULT");
  const ratio = row.cells[2].textContent.match(/^(\\d+)\\/([1-9]\\d*)$/);
  if (!ratio) continue;
  const share = Number(BigInt(ratio[1]) * 10000n / BigInt(ratio[2])) / 100;
  const bar = document.createElement("span");
  bar.className = "recovery-bar";
  bar.setAttribute("aria-hidden", "true");
  bar.style.setProperty("--share", share + "%");
  row.cells[2].append(bar);
}
select.addEventListener("change", refresh);
comparison.addEventListener("change", refresh);
institution.addEventListener("input", refresh);
refresh();
"""


def render(analysis):
    esc = html.escape

    def identity(value):
        return esc(json.dumps(value, ensure_ascii=True), quote=True)

    options, panels = [], []
    for case in analysis["cases"]:
        name = case["scenario"]
        options.append(f"<option value='{identity(name)}'>{esc(name)}</option>")
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
            f"<section data-case='{identity(name)}'><h2>{esc(name)}</h2>"
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
        "<title>NetworkClear · debt clearing explorer</title><style>"
        + _REPORT_CSS
        + _REPORT_HEADER
        + "".join(options)
        + _REPORT_CONTROLS
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
        + _REPORT_SCRIPT
        + "</script></html>\n"
    ).encode()


def read_fraction(value):
    from fractions import Fraction

    return Fraction(value)


def csv_bytes(rows, fields):
    import csv
    import io

    stream = io.StringIO(newline="")
    # Quote embedded CR as well as LF, while retaining LF record endings.
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\r\n")

    def record(row):
        stream.seek(0)
        stream.truncate(0)
        writer.writerow({key: csv_label(value) if key == "scenario" else value for key, value in row.items()})
        return stream.getvalue()[:-2] + "\n"

    return (record(dict(zip(fields, fields, strict=True))) + "".join(record(row) for row in rows)).encode("utf-8")


def csv_label(value):
    """Keep formula-shaped scenario labels inert in spreadsheet exports."""
    prefix = "text: "
    if value.startswith((prefix, "\t", "\r", "\n", "\x00", "\ufeff")) or value.lstrip(
        " \t\r\n\v\f\x00\ufeff"
    ).startswith(("=", "+", "-", "@", "＝", "＋", "－", "＠")):
        return prefix + value
    return value


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
