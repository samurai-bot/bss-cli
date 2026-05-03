"""v0.16 Track 5 — Live-sandbox three-provider soak.

The "production-shape" gate per ``phases/V0_16_0.md`` §5: a hero scenario
that runs end-to-end with all three real providers in sandbox mode
(Resend, Didit, Stripe) and the eSIM simulator. Skipped unless
``BSS_NIGHTLY_SANDBOX=true`` so a normal ``make test`` never makes
external calls or burns provider quotas.

Three consecutive green nightly runs gate the v0.16 release tag. A
flake → dig in BEFORE shipping; do not paper over (spec line 285).
"""
