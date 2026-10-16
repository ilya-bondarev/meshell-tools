# Security

Modules are shell programs, not sandboxed extensions. A command can change phone files/settings, call remote services or spend account quota with the capabilities granted to MeShell. Declared permissions make a module readable and are checked against known command patterns; obfuscated commands can evade detection. Review every command before installing and running a module. Stopping does not undo completed actions.

Never publish vault contents, tokens, keystores, device logs or personal server settings. Export normalizes alias references but cannot detect all inline secrets or personal data. Gitleaks, the credential patterns and schema checks are signature-based gates, not a guarantee.

Catalogue validation never invokes submitted commands. Pull request jobs have read-only repository permissions, no stored checkout credentials and no secrets, and check contributions with the rules already on `main`. Issue triage runs only `main` code, treats issue text as data and commits a submission only after a maintainer with write access approves it and the files pass validation again. Releases and Pages deployment run only from `main`.

The SHA-256 in the index identifies the reviewed file and MeShell rejects a download that differs; it does not authenticate the author or make a command safe. Updates install only after the user confirms them. Ratings and submissions are public issues from the user's GitHub account.

Report vulnerabilities through GitHub's private vulnerability reporting. Report a harmful module with a `[report] <id>` issue. Do not put live credentials in public issues.
