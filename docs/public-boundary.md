# Public package boundary

This repository is a reusable public foundation. It must remain independent of every private deployment and must be safe to inspect, fork, and publish.

## Material that belongs outside the repository

Do not commit or paste any of the following:

- deployment wiring, scheduler definitions, delivery configuration, or automation targets;
- local configuration, machine-specific settings, runtime state, or generated output;
- Swamp runtime data, models, vaults, workflows, reports, or generated scripts;
- logs, captures, exports, or diagnostic output that can reveal private context;
- credentials, access tokens, keys, certificates, `.env` files, or secret-bearing configuration;
- real hostnames, addresses, identities, device or entity labels, chat references, workflow identifiers, model identifiers, vault names, or their contents;
- absolute local paths or material copied from a private environment.

Keep this material in a private, access-controlled location outside the project. The `.gitignore` rules cover common names and directories, but they are not a substitute for review.

## What may be public

Public contributions may include generic source code, tests using synthetic values, and documentation that uses neutral placeholders. Documentation must describe capabilities accurately and must not imply that a planned feature is already implemented.

Examples should use generic labels such as `EXAMPLE_VALUE` and relative file references such as `example/config`. Never replace placeholders with values from an active environment.

## Pre-publication review

Before staging or publishing changes:

1. Inspect the staged file list and confirm that every file is reusable source or generic documentation.
2. Review text files for secrets, credential-like values, personal identifiers, hostnames, addresses, local paths, and environment-specific labels.
3. Confirm that no deployment, scheduler, delivery, Swamp runtime, runtime-state, log, or local-config artifact is present.
4. Confirm that examples contain only synthetic placeholders and that generated files are excluded.
5. Review the diff as it will be published, not only the working tree.

If a file could reveal how a particular environment is configured or operated, keep it private and do not add it to this repository.
