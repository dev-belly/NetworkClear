# Support for NetworkClear

Start with [the quick start](README.md) and [the input and model contract](docs/METHODOLOGY.md). After installation, check the saved example:

```bash
networkclear verify examples/demo
python scripts/check_demo.py
```

For a clearing discrepancy, open a [bug report](https://github.com/dev-belly/NetworkClear/issues/new/choose) with the OS/Python and revision, command, smallest synthetic network, one shock and exact expected payments. Keep debtor/creditor direction and outside debts visible; specify whether the disputed value is gross unpaid debt or outside-creditor shortfall.

The exhaustive oracle covers at most eight institutions. A report saying that the exhaustive check was not run on a larger network is expected. Computational rounds do not measure elapsed contagion time. See [CONTRIBUTING.md](CONTRIBUTING.md) for checks and evidence changes, and [SECURITY.md](SECURITY.md) for private security reporting.
