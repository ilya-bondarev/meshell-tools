# Security

Modules are shell programs, not sandboxed extensions. A command can change phone files/settings, call remote services or spend account quota with the capabilities granted to MeShell. Review every command before import and execution. Stopping does not undo completed actions.

Never publish vault contents, tokens, keystores, device logs or personal server settings. Export normalizes alias references but cannot detect all inline secrets or personal data. Gitleaks and schema checks are signature-based gates, not a guarantee.

Catalogue validation never invokes submitted commands. PR jobs have read-only repository permissions, no stored checkout credentials and no signing/provider secrets. Deployment runs only from merged `main`, with deployment-only permissions. Do not add privileged workflows for PR code or run a fork's validator on a machine containing secrets.

A commit-pinned URL and digest identify what was reviewed; they do not authenticate a module author or make a command safe. Updates remain explicit imports. Report vulnerabilities through GitHub's private vulnerability reporting. Do not put live credentials in public issues.
