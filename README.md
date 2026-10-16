# MeShell tools

The community module catalogue for [MeShell](https://github.com/ilya-bondarev/meshell). Every module is a reviewed JSON definition of shell actions with an author, declared permissions, a size, counted downloads and 1–5 ratings. Browse it in the app under **Modules → Catalogue** or on the [web page](https://ilya-bondarev.github.io/meshell-tools/).

## Use modules

1. In MeShell 0.10.0+, open **Modules → Catalogue**. Search, filter by category and sort by popularity, rating or date.
2. Open a module to see its author, permissions, actions, size, downloads, reviews and the full commands (**Show commands**).
3. Tap **Get**. MeShell lists the permissions; the module runs only after you allow them. The download is the module's GitHub release asset and must match the SHA-256 in the index.
4. Updates show on the module tile and install only when you confirm them.

Installing saves a definition; it never runs a command. Modules are shell programs with the broker's ADB-shell capabilities, not sandboxed apps: read the commands of anything you install.

## Rate and request

- **Rate** from the module's catalogue page in MeShell. With the GitHub module connected the rating is filed from your account; otherwise GitHub opens with it filled in. On GitHub, open an issue titled `[rating] <module-id>` with a line `Rating: N/5` and an optional review below it. Only your latest rating of a module counts; authors cannot rate their own modules.
- **Request** a module with an issue titled `[request] <what it should do>`. 👍 requests you want; the most wanted ones are listed for authors on the web page.
- **Report** a harmful or broken module with `[report] <module-id>`.

## Publish a module

The fastest way is from the app: long-press your module in **Modules → My modules → Publish to catalogue**, choose a category, version and description, and confirm the MIT-0 license. MeShell opens a `[submit] <id>` issue with the portable export. The catalogue checks it within a minute and comments with the result, the detected permissions and every command. A maintainer reads the commands and adds the `approved` label; the module is then committed under your GitHub account (you are its co-author) and appears in the catalogue within minutes. Publish an update the same way with a higher version.

You can also open a pull request with `tools/<id>/`:

```text
module.json       portable export from MeShell; no catalogue fields
catalog.json      version, author, github, MIT-0, min_app_version, category, requirements; optional icon and translations
README.md         behavior, effects, privacy notes
LICENSE           copy of this project's MIT-0 license
CHANGELOG.md      a "## <version>" section for every version
```

Read the [rules](CONTRIBUTING.md) first. Only the account in `catalog.json` `github` changes its module.

## How it works

Everything runs on GitHub; there is no server or account system.

- **Index**: `scripts/catalog.py` validates every tool and builds `index.json`. GitHub Pages serves it with the module files, `stats.json` and the web page.
- **Downloads**: each module version is a release `<id>@<version>` with a `module.json` asset. MeShell installs from that asset, so GitHub counts the download; previews read the Pages copy and are not counted.
- **Ratings, submissions, requests and reports** are issues. `scripts/marketplace.py` triages them in the `Marketplace` workflow, and the hourly `Publish` workflow recounts downloads and ratings, creates missing releases and redeploys Pages.

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python scripts/test_catalog.py
python scripts/test_marketplace.py
python scripts/catalog.py --output dist/index.json
```

Validation never runs submitted commands. Pull requests are checked by the rules already on `main`, without secrets. See [security](SECURITY.md) and [rules](docs/CATALOG_RULES.md).

## Contract

`contracts/module.schema.json` is a read-only snapshot of the app-owned contract (`res/raw/module_schema.json` in MeShell); `contracts/UPSTREAM.json` records the app commit, path and digest. Change fields in the app first, then refresh this snapshot. `schemas/catalog.schema.json` owns only catalogue metadata.

## License

[MIT-0](LICENSE), including community contributions accepted into this catalogue. External commands, tools and services keep their own licenses and terms.
