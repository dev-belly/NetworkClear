"""Render the README preview from verified synthetic clearing results."""

import argparse
from fractions import Fraction
from pathlib import Path

from networkclear.cli import demo_inputs
from networkclear.contracts import display
from networkclear.report import analyze


def preview():
    analysis = analyze(*demo_inputs())
    case = next(c for c in analysis["cases"] if c["scenario"] == "anchor-050-pct")
    shortfall = display(Fraction(case["outside_shortfall_cents"]) / 100, 0)
    unpaid = display(Fraction(case["gross_unpaid_cents"]) / 100, 0)
    values = [
        ("Defaulting institutions", str(case["default_count"])),
        ("Additional cascade defaults", str(case["cascade_count"])),
        ("Outside creditor shortfall · USD", shortfall),
    ]
    cards = []
    for i, (label, value) in enumerate(values):
        x = 36 + i * 304
        cards.append(
            f'<rect x="{x}" y="130" width="286" height="108" rx="12" fill="#ffffff"/>'
            f'<text x="{x + 18}" y="160" font-size="14" fill="#6c6387">{label}</text>'
            f'<text x="{x + 18}" y="207" font-size="32" font-weight="700">{value}</text>'
        )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="980" height="400" viewBox="0 0 980 400" '
        'role="img" aria-label="NetworkClear synthetic network clearing preview">'
        '<rect width="980" height="400" rx="16" fill="#f0edf8"/>'
        '<g font-family="system-ui,sans-serif" fill="#18273b">'
        '<text x="36" y="54" font-size="32" font-weight="700">NetworkClear</text>'
        '<text x="36" y="88" font-size="17">Synthetic 8-institution network · 50% external-asset shock to A</text>'
        + "".join(cards)
        + '<text x="36" y="284" font-size="17" fill="#7159bf">'
        "Direct default: A · cascade additions: B, C, D · fixed-point residual: 0</text>"
        '<text x="36" y="321" font-size="16">'
        f"Gross unpaid debt: USD {unpaid} · outside losses are counted separately</text>"
        '<text x="36" y="356" font-size="14">'
        "15 scenarios · exact rational payments · exhaustive independent clearing checks</text>"
        "</g></svg>\n"
    ).encode()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = Path(__file__).resolve().parents[1] / "docs" / "preview.svg"
    raw = preview()
    if args.check:
        if not target.is_file() or target.read_bytes() != raw:
            raise SystemExit("README preview differs from bundled evidence")
    else:
        target.write_bytes(raw)


if __name__ == "__main__":
    main()
