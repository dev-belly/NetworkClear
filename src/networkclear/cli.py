"""CLI for offline, synthetic clearing experiments and independent replay."""

import argparse
import json
import sys
from importlib.resources import files
from pathlib import Path

from .contracts import ContractError, read_json
from .report import verify, write_report


def demo_inputs():
    resources = files("networkclear").joinpath("data")
    return (
        read_json(resources.joinpath("network.json").read_bytes()),
        read_json(resources.joinpath("scenarios.json").read_bytes()),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Exact debt clearing and stress evidence")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Build and independently verify the synthetic demo")
    demo.add_argument("--out", required=True)
    run = commands.add_parser("run", help="Run a saved network and explicit stress scenarios")
    run.add_argument("--network", required=True)
    run.add_argument("--scenarios", required=True)
    run.add_argument("--out", required=True)
    check = commands.add_parser("verify", help="Replay files and check small-network default regimes")
    check.add_argument("directory")
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            result = verify(args.directory)
        else:
            if args.command == "demo":
                data, scenarios = demo_inputs()
            else:
                data = read_json(Path(args.network).read_bytes())
                scenarios = read_json(Path(args.scenarios).read_bytes())
            write_report(data, scenarios, args.out)
            result = {"output": str(Path(args.out)), **verify(args.out)}
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ContractError, OSError, KeyError, AttributeError, TypeError) as exc:
        print(f"networkclear: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
