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

## The one narrow runtime exception: scrubbed authoring diagnostics

This boundary also governs a runtime behavior, not only what gets committed:
by default, `swamp_first_hermes/swamp_cli.py` never surfaces a Swamp CLI
process's stderr to a caller, because stderr can carry absolute local paths
and private identifiers. That default holds for every tool except a small,
explicitly named allowlist — `model_validate`, `workflow_validate`,
`extension_quality`, `extension_fmt`, `model_method_run`, and `workflow_run` —
and even there, only on the specific failure shape where the CLI exits
non-zero with no JSON result body (`error="process_failed"`).

These commands exist specifically to report actionable problems the agent must
see to complete a swamp-first task: the authoring ones (`*_validate`,
`extension_quality`, `extension_fmt`) report a formatting diff, a lint rule
with a file/line/fix hint, or a quality-rubric failure; the execution ones
(`model_method_run`, `workflow_run`) report why a run failed — a missing or
misplaced input, a schema violation, a model-code exception. Withholding that
output entirely made an agent's own author→validate→run loop impossible to
self-correct — it could be told by Swamp's own error text to run a sibling
command, or to move an input, to fix a problem it was never allowed to see.
So, and only for these commands, that failure
path additionally returns a `diagnostics` string: the same stderr, with every
absolute filesystem path scrubbed to a repository-relative path (or an opaque
`<repo>` / `<path>` placeholder when no safe relative form is known) before
it ever leaves the process. Line numbers, lint rule names, and fix hints are
left intact — that content is the entire point of surfacing anything at all.

Every other command, and every other failure shape, is unaffected: stderr
stays fully withheld, `diagnostics` stays `None`, exactly as before this
exception existed. This is a narrowing of what one command shows the caller
that already invoked it, on a fixed, code-reviewed allowlist — not a general
loosening of what may be committed to or read from this repository, and nothing
above about local paths, credentials, or private identifiers is relaxed by it.

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
