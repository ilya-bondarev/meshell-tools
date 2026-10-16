# Contributing

Anyone with a GitHub account can publish a module. Publish from MeShell (long-press a module → **Publish to catalogue**) or open a pull request with `tools/<id>/`; both are reviewed by a maintainer before the module appears in the catalogue.

## Module rules

1. **One clear task per module.** The title and description say exactly what it does; action labels say what each action does.
2. **Declare every permission** your commands need: `network`, `storage` (shared files under `/sdcard`), `screen` (screenshots, recording, UI dumps), `system` (settings, apps, input, `cmd`/`svc`), `secrets` (`env_secrets`) and `packages`. The catalogue and the app detect them from the commands and reject undeclared ones. Declare a permission the patterns miss, too.
3. **No credentials or personal data.** No passwords, tokens, keys, IP addresses, host names, account IDs or personal paths in commands. Secrets go only through `env_secrets` with ENV-name placeholders; explain the vault aliases in the README.
4. **No downloaded or hidden code.** No `curl … | sh`, `eval`, sourcing generated code, decoding hidden content (`base64 -d`), making files executable or shipping binaries. Dependencies are Termux packages listed in `packages`; MeShell installs them before the first run.
5. **Say what changes.** Actions that delete data, change settings, spend money or quota, or contact a service say so in their label and README. Network destinations are named in the README.
6. **Your own work under MIT-0.** You wrote it or have the right to license it under [MIT-0](LICENSE).
7. **Only the author updates a module.** Every update raises the version, adds a `## <version>` section to `CHANGELOG.md` and passes review again. The maintainer may fix or remove any module.
8. **No spam, malware or misleading modules.** They are removed, and their author's submissions and ratings are ignored.

Test every action on your own phone before publishing. The catalogue does not run your commands.

## Pull requests

- Create `tools/<id>/` with `module.json` (a MeShell export), `catalog.json`, `README.md`, `LICENSE` (a copy of the root license) and `CHANGELOG.md`. Use `tools/battery` as the example.
- `catalog.json` `github` is your GitHub login; `author` is the name shown in the app. `min_app_version` is the oldest MeShell your module needs, at least 0.10.0.
- Change only your own tool directories. Run `python scripts/test_catalog.py` and `python scripts/catalog.py`.

## Ratings

One rating per account and module counts: the latest. Authors' ratings of their own modules, bots and issues labelled `spam` or `invalid` do not count. The catalogue sorts by a Bayesian average, so a single 5 does not outrank many good ratings.

## Maintainer review

Read every command in the submission report or PR diff, the permissions, packages, README and license. Reject built-in ID collisions, undeclared effects, network destinations not named in the README, and anything on the list above. A passing check is not proof of safety. Approve a submission by adding the `approved` label after reading its latest report; editing the issue updates the report and removes the label. Label abuse `spam`.

Schema changes originate in the app. Review the app commit and the byte-for-byte schema snapshot before updating `contracts/UPSTREAM.json`.
