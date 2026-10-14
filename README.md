# MeShell tools

A separate, source-only catalogue of community modules for [MeShell](https://github.com/ilya-bondarev/meshell). Authors contribute through GitHub forks and pull requests; users download JSON and explicitly import it into MeShell. No server account, app GitHub token or automatic installer is needed.

The validated index is published at <https://ilya-bondarev.github.io/meshell-tools/index.json>.

## Download and use

1. Open a tool directory and inspect its `README.md` and every command in `module.json`.
2. On GitHub, choose a specific commit and download the raw `module.json` from that revision.
3. In MeShell 0.9.4+, use **Modules → + → Import JSON file**, inspect the full definition and confirm. Existing modules with the same ID are replaced.
4. If a module uses `env_secrets`, create those aliases locally in MeShell's vault. Execute actions only when you intend to.

The `system-status` example has no account, network or downloaded-binary requirement. Importing saves a definition; it does not run commands.

## Export and contribute

Long-press your custom module in MeShell → **Export JSON** → **Save file** or **Copy text**. Export removes local working directories and replaces personal vault aliases with environment-variable names. Inline secrets and personal data in commands still need author review.

Fork the catalogue, create `tools/<id>/`, and add exactly these files:

```text
module.json       portable app export; no catalogue fields
catalog.json      version, author, MIT-0 license, minimum app version, requirements
README.md         behavior, setup, effects and how to test
LICENSE           copy of this project's MIT-0 license
CHANGELOG.md      changes for each submitted version
```

Use `tools/system-status` as the working example. Increase your module version when its commands change. The author must own the contributed code and agree to MIT-0. See [contributing](CONTRIBUTING.md) and [security](SECURITY.md).

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python scripts/test_catalog.py
python scripts/catalog.py --output dist/index.json
```

CI validates files and schemas and scans Git history. It **never runs submitted shell commands**, installs module dependencies or receives signing/account secrets. Reviewers check declared requirements, built-in ID collisions, side effects and inline downloads before merging. Arbitrary code in a PR is still untrusted; never enable privileged PR workflows.

## Index and updates

After an accepted change on `main`, the prepared Pages workflow serves `index.json` and the same validated module files. The index records the catalogue commit, each definition's SHA-256, versions and requirements. Prefer GitHub's commit-pinned raw URL; a hash detects changes, not author trust. Updating an installed module means downloading and inspecting a new version and confirming its import again. There is no background updater.

## Contract

`contracts/module.schema.json` is a read-only snapshot of the app-owned contract (`res/raw/module_schema.json` in [MeShell](https://github.com/ilya-bondarev/meshell)); `contracts/UPSTREAM.json` records the app commit, path and digest. Change fields in the app first, then refresh this snapshot with the matching digest. `schemas/catalog.schema.json` owns only catalogue metadata. Keep metadata out of the executable module definition.

All catalogue logic lives in `scripts/catalog.py`; see [rules](docs/CATALOG_RULES.md). Checks and focused tests guard the boundaries, not a claim of module sandboxing.

## License

[MIT-0](LICENSE), including community contributions accepted into this catalogue. No attribution requirement. External commands, tools and services retain their own licenses and terms.
