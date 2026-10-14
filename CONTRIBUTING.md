# Contributing

Fork, add or update `tools/<id>/`, run the local checks, and open a PR. Anyone can publish their own module; catalogue inclusion requires review. Do not commit device data or vault values.

## Author checklist

- Export through MeShell, inspect every command and remove inline credentials and personal paths.
- Keep `module.json` portable: no `cwd`, personal vault aliases, binaries or extra metadata. For secrets use `env_secrets` with matching ENV-name placeholders; explain provisioning in the README.
- Submit `catalog.json`, README, LICENSE and CHANGELOG beside it. Use a unique custom ID, not an app built-in ID. Minimum app version is a real requirement, not a compatibility test result.
- Record commands' effects, account costs, network destinations and required tools. The initial catalogue accepts plain shell definitions using existing tools; it does not accept install scripts or redistributable binaries. Reviewers reject hidden fetching/execution and privileged persistence.
- Test on your own device with your own consent. PR CI does not execute module actions.
- Confirm you own your contribution and license it under MIT-0. No CLA or new account system is added.

## Maintainer review

Require the Validate job; read the full command diff, requirements and license; reject built-in ID collisions and unsafe or undocumented side effects. A passing scan is not proof of safety. Do not use `pull_request_target` to execute contributor code.

Schema changes originate in the app owner. Review the app commit and byte-for-byte schema snapshot before updating `contracts/UPSTREAM.json`; editing the digest alone is not review. Refactor catalogue rules behavior-preservingly before adding another caller.
