# Catalogue ownership

`scripts/catalog.py` owns catalogue validation, portable projection and index generation. It imports the standard JSON Schema validator and implements the app contract's `x-uniqueBy` and UTF-16 compact-size extensions. It never executes a module action. `scripts/test_catalog.py` calls those same functions rather than introducing another validator.

The app-owned vendored contract contains module fields and execution limits. The catalogue-owned metadata schema contains version, author, license and requirements; those are not fields of `module.json`. The portable projection reads contract annotations, so no second list of local fields or alias policy is maintained here.

Tool directories contain only definition, metadata, README, license and changelog. Reject symlinks, oversized files, unknown JSON properties, duplicate JSON keys/action identities, directory/ID mismatches and nonportable definitions. The index is derived from accepted files and records their hashes and the Git commit; generated `dist/` is not a second editable source of truth.

Builtin-ID collisions, undocumented effects and fetched-code behavior require review, while the app also rejects builtin-ID installation. A schema digest pins the vendored snapshot but is not proof that an edited snapshot was approved; reviewers must confirm the referenced app revision.
