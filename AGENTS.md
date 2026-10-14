# Invariants

The catalogue domain is owned by `scripts/catalog.py` and `docs/CATALOG_RULES.md`. The app contract is a pinned, read-only snapshot; catalogue metadata has its own schema. Grep before adding a rule, do not duplicate it in tests or generated index data, and refactor separately from behavior changes.

Never execute module commands while validating a PR. Do not introduce module installers, secret-bearing PR jobs, `pull_request_target`, automatic updates or unreviewed binary fetches. Keep documentation short and functional. Pages deployment runs only from merged `main`.
