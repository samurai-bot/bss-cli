"""v0.12 14-day soak runner.

Per phases/V0_12_0.md §5:

* ``synthetic_customer`` — one-customer-day event loop, probabilistic.
* ``corpus`` — fixed corpus of ~50 realistic chat asks (5 categories).
* ``metrics`` — DB samplers + p99 chat-latency tracker + report
  generator.
* ``run_soak`` — argparse entrypoint that spins up a clean DB,
  seeds N customers, and runs them in parallel for D simulated days.

Invocation:

    uv run python -m scenarios.soak.run_soak --customers 100 --days 14

Smoke (validates the runner end-to-end without burning the full
hour):

    uv run python -m scenarios.soak.run_soak --customers 2 --days 1

The runner expects the v0.12 stack already up (docker compose up
--build) and a clean DB (make reset-db; make seed). It does not
manage the stack itself — keeping the runner minimal is the v0.12
shape; v1.x can add `--up` / `--down` if it becomes worth it.
"""
