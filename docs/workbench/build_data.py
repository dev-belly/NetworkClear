"""Build the offline browser snapshot from the repository's saved evidence."""

import argparse
import hashlib
import json
from pathlib import Path


DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parents[1]


def read_json(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def source(label, path):
    normalized = (ROOT / path).read_text(encoding="utf-8").encode("utf-8")
    return {
        "label": label,
        "url": f"{REPOSITORY}/blob/main/{path}",
        "sha256_lf": hashlib.sha256(normalized).hexdigest(),
    }


def fact(label, value, kind=None):
    return {"label": label, "value": value, "format": kind}


def column(key, title, kind=None):
    return {"key": key, "title": title, "format": kind}


def order(key, title, descending=True):
    return {"key": key, "title": title, "id": key, "descending": descending}


def metric(label, value, note):
    return {"label": label, "value": value, "note": note}


def table(title, columns, rows, *formats):
    return {
        "title": title,
        "table": {"columns": columns, "rows": rows, "formats": formats},
    }


def theme(accent, muted, base, glow):
    return {
        "accent": accent,
        "accent-soft": muted,
        "hero-base": base,
        "hero-glow": glow,
    }


from fractions import Fraction


REPOSITORY = "https://github.com/dev-belly/NetworkClear"
INPUT = "examples/demo/analysis.json"
POSITIONS = {
    "A": (0.02, 0.20),
    "B": (0.33, 0.20),
    "C": (0.64, 0.20),
    "D": (0.98, 0.20),
    "G": (0.02, 0.70),
    "H": (0.33, 0.92),
    "E": (0.64, 0.58),
    "F": (0.98, 0.86),
}


def build():
    result = read_json(INPUT)
    scenarios = read_json("examples/demo/scenarios.json")
    assumptions = {scenario["id"]: scenario for scenario in scenarios}
    records = []
    for case in result["cases"]:
        identifier = case["scenario"]
        scenario = assumptions[identifier]
        reductions = scenario["reductions_bps"]
        injections = scenario["injections_cents"]
        if injections:
            recipients = "、".join(injections) if len(injections) < 3 else "八家等额"
            label = f"注资 {recipients} · A 冲击 {reductions['A'] / 100:g}%"
            family = "注资对照"
        elif set(reductions) == {"A"}:
            label = f"A 资产冲击 {reductions['A'] / 100:g}%"
            family = "A 冲击网格"
        else:
            label = {"broad-050-pct": "全网资产冲击 50%", "cycle-090-pct": "E / F 资产冲击 90%"}[identifier]
            family = "其他压力"
        direct = case["direct_default_ids"]
        cascade = case["cascade_default_ids"]
        payments = [row for row in result["payments"] if row["scenario"] == identifier]
        rounds = [row for row in result["rounds"] if row["scenario"] == identifier]
        flows = [row for row in result["flows"] if row["scenario"] == identifier]
        internal = [row for row in flows if row["creditor"] in POSITIONS]
        directions = {(row["debtor"], row["creditor"]) for row in internal}
        nodes = [
            {
                "id": name,
                "x": POSITIONS[name][0],
                "y": POSITIONS[name][1],
                "status": "direct" if name in direct else "cascade" if name in cascade else "solvent",
            }
            for name in result["node_ids"]
        ]
        edges = [
            {
                "from": row["debtor"],
                "to": row["creditor"],
                "short": Fraction(row["paid_cents"]) < Fraction(row["nominal_cents"]),
                "reverse": (row["creditor"], row["debtor"]) in directions,
            }
            for row in internal
        ]
        sections = [
            table(
                "节点付款与回收",
                ["机构", "实际付款", "回收率", "状态"],
                [
                    [
                        row["node"],
                        row["paid_cents"],
                        row["recovery_ratio"],
                        "直接违约" if row["node"] in direct else "传染违约" if row["node"] in cascade else "足额",
                    ]
                    for row in payments
                ],
                None,
                "rationalUsd",
                "rationalPercent",
                None,
            ),
            table(
                "逐笔精确付款（有理分）",
                ["付款方", "收款方", "名义分", "实付分"],
                [[row["debtor"], row["creditor"], row["nominal_cents"], row["paid_cents"]] for row in flows],
            ),
        ]
        if rounds:
            sections.insert(
                1,
                table(
                    "算法轮次",
                    ["轮次", "累计违约机构"],
                    [[row["step"], "、".join(row["default_ids"])] for row in rounds],
                ),
            )
        records.append(
            {
                "id": identifier,
                "title": label,
                "subtitle": identifier,
                "assumptions": scenario,
                "values": {
                    "family": family,
                    "defaults": case["default_count"],
                    "cascade": case["cascade_count"],
                    "outside": case["outside_shortfall_cents"],
                    "gross": case["gross_unpaid_cents"],
                    "outside_usd": float(Fraction(case["outside_shortfall_cents"]) / 100),
                },
                "facts": [
                    fact("直接违约", "、".join(direct) or "无"),
                    fact("传染违约", "、".join(cascade) or "无"),
                    fact("外部资产冲击", case["external_asset_shock_cents"], "rationalUsd"),
                    fact("注资预算", case["injection_cents"] / 100, "usd"),
                    fact("外部债权短缺", case["outside_shortfall_cents"], "rationalUsd"),
                    fact("外部短缺（有理分）", case["outside_shortfall_cents"]),
                    fact("总未付名义债务", case["gross_unpaid_cents"], "rationalUsd"),
                    fact("固定点残差（有理分）", case["fixed_point_residual_cents"]),
                    fact("资金守恒残差（有理分）", case["conservation_residual_cents"]),
                ],
                "charts": {
                    "recovery": [
                        {"label": row["node"], "value": float(Fraction(row["recovery_ratio"]))} for row in payments
                    ]
                },
                "graph": {
                    "nodes": nodes,
                    "edges": edges,
                    "summary": f"{label}。直接违约 {'、'.join(direct) or '无'}，传染违约 {'、'.join(cascade) or '无'}。",
                    "key": "红色节点为直接违约，橙色节点为传染违约。箭头从债务人指向债权人，红线表示机构间实付低于名义债务。",
                },
                "sections": sections,
            }
        )
    focus_case = next(case for case in result["cases"] if case["scenario"] == "anchor-050-pct")
    shortfall = Fraction(focus_case["outside_shortfall_cents"]) / 100
    return {
        "repository": REPOSITORY,
        "slug": "networkclear",
        "project": "NetworkClear",
        "mark": "NC",
        "theme": theme("#16716a", "#e8f7f4", "#122e35", "#287d73"),
        "workspace": "对手方风险",
        "title": "清算与违约传染",
        "description": "从一笔资产冲击沿债务边追踪传染，查看逐层违约、回收率与流向外部债权人的付款。",
        "dataKind": "合成清算网络 · 精确有理数证书",
        "hero": metric("外部债权短缺", f"${float(shortfall):,.0f}", "A 的外部资产下降 50% 时"),
        "metrics": [
            metric("压力情景", str(len(records)), "单点冲击、全网压力与注资对照"),
            metric("网络内机构", str(len(result["node_ids"])), "另计外部债权人"),
            metric("基准案例新增违约", str(focus_case["cascade_count"]), "A 受 50% 外部资产冲击"),
        ],
        "recordHeading": "清算情景",
        "recordLabel": "压力假设",
        "detailHeading": "清算证据",
        "searchPlaceholder": "搜索冲击比例或情景 ID",
        "initialRecord": "anchor-050-pct",
        "filters": [{"key": "family", "title": "情景类型"}],
        "columns": [
            column("defaults", "违约总数", "integer"),
            column("cascade", "新增传染", "integer"),
            {**column("outside", "外部短缺", "rationalUsd"), "exportTitle": "外部短缺（有理分）"},
            {**column("gross", "总未付债务", "rationalUsd"), "exportTitle": "总未付债务（有理分）"},
        ],
        "orders": [order("outside_usd", "外部短缺最高"), order("cascade", "新增违约最多")],
        "views": [
            {
                "id": "network",
                "label": "网络",
                "title": "所选情景的清算网络",
                "mode": "graph",
                "caption": "区分初始冲击与沿机构间债务传染的违约。选择下方情景切换。",
            },
            {
                "id": "outside",
                "label": "外部短缺",
                "title": "各情景的外部短缺",
                "metric": "outside_usd",
                "descending": True,
                "format": "usd",
                "caption": "显示外部债权短缺最高的情景及所选情景。金额保留到美元小数点后两位。",
            },
            {
                "id": "recovery",
                "label": "回收率",
                "title": "所选情景的节点回收率",
                "mode": "detail",
                "format": "percent",
                "max": 1,
                "caption": "各机构实际付款总额与名义负债的比率。",
            },
        ],
        "sourceNote": "箭头表示模型中的名义债务方向。轮次是清算算法步骤。表格展示四舍五入美元；明细和 CSV 保留有理分的原值。",
        "sources": [
            source("清算结果与方程证书", INPUT),
            source(f"{len(scenarios)} 个输入情景", "examples/demo/scenarios.json"),
            source("方法与复算", "docs/METHODOLOGY.md"),
        ],
        "records": records,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify the generated snapshot")
    args = parser.parse_args()
    document = build()
    records = document.pop("records")
    lines = ",\n".join("    " + json.dumps(record, ensure_ascii=False, allow_nan=False) for record in records)
    header = json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2)
    result = (
        "// Generated by build_data.py from repository evidence.\n"
        "window.workbenchData = " + header[:-2] + ',\n  "records": [\n' + lines + "\n  ]\n};\n"
    )
    path = DIRECTORY / "data.js"
    if args.check:
        if not path.exists() or path.read_text(encoding="utf-8") != result:
            parser.exit(1, "Snapshot differs. Run build_data.py without --check.\n")
        print(f"Verified {len(records)} records")
    else:
        path.write_text(result, encoding="utf-8", newline="\n")
        print(f"Wrote {len(records)} records")


if __name__ == "__main__":
    main()
