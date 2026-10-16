# Catalogue ownership

`scripts/catalog.py` owns catalogue validation, portable projection, permission inference, catalogue policy, pull request ownership and index generation. It imports the standard JSON Schema validator and implements the app contract's `x-uniqueBy`, `x-permissions`, `x-impliesPermission`, `x-permissionPatterns` and UTF-16 compact-size extensions. It never executes a module action. `scripts/marketplace.py` owns the GitHub side: releases, statistics, the issue protocol, submissions and the web page. Both test files call those functions rather than introducing another validator.

The app-owned vendored contract contains module fields, permissions and execution limits. The catalogue-owned metadata schema contains version, author, GitHub login, license, minimum app version, category, icon, requirements and translations; those are not fields of `module.json`. Permission inference reads the contract annotations, so no second list of patterns is maintained here; it must give the same result as `ModuleDefinition.required` in the app.

## Tool directories

Tool directories contain only definition, metadata, README, license and changelog. Reject symlinks, oversized files, unknown JSON properties, duplicate JSON keys/action identities, directory/ID mismatches, app built-in IDs, nonportable definitions, undeclared permissions, `min_app_version` below 0.10.0 and a changelog without a section for the version. The catalogue policy (`FORBIDDEN`) rejects piping text into a shell or interpreter, `eval`, sourcing generated code, running downloaded code, decoding hidden content, making files executable and credential-like strings. Patterns detect common forms, not every one.

## Index and releases

The index (format 2) is derived from accepted files on `main`: entry metadata, effective permissions, packages, action labels, size, SHA-256, the Pages path, the release download URL, the last change date and the README without its title. Each version is published once as release `<id>@<version>` with the exact `module.json` bytes; the release is never replaced, so changed bytes need a higher version. Generated `dist/` is not a second editable source of truth.

## Issue protocol

MeShell's `MarketRules` writes this protocol; people can write it by hand.

- `[rating] <id>` with lines `Module: <id>`, `Version: <x.y.z>`, `Rating: N/5` (or five ★/☆), then an optional review after a blank line. Statistics count each account's latest rating per module and ignore bots, the module's own author and issues labelled `spam` or `invalid`. Reviews keep the newest ten texts, 500 characters each.
- `[submit] <id>` with a fenced `json` block `{"format": 1, "module": <portable export>, "catalog": {"version", "category", "license", "min_app_version", optional "icon", "translations", "requirements"}, "readme", optional "changes"}`. The `github` field is the issue author; `author` is their GitHub display name; `min_app_version` is the catalogue minimum. A submission for an existing ID must come from its owner and raise the version. A maintainer with write access approves with the `approved` label; the bot re-validates, commits the files on `main` with the author as co-author and closes the issue.
- `[request] <text>` lists a wanted module; 👍 reactions order the list. `[report] <id>` is kept open for a maintainer.

Triage runs the `main` code on issue events and never interpolates issue text into a shell. Commits by the workflow token do not trigger workflows, so triage dispatches `Publish` after a change.

## Ownership

`catalog.json` `github` owns a tool directory. A pull request from another account may not change it, a contributor may change only `tools/`, and changed `module.json` bytes require a higher version. Only the maintainer transfers ownership. Pull requests are checked with the base branch's `catalog.py`.

A schema digest pins the vendored snapshot but is not proof that an edited snapshot was approved; reviewers must confirm the referenced app revision.
