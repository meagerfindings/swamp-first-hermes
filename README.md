# Swamp-First Hermes

Swamp-First Hermes is a public Hermes directory plugin that exposes narrowly
scoped, read-only Swamp discovery and evidence tools.

This repository intentionally contains only reusable source material and public
documentation. It does **not** contain deployment, scheduler, or delivery
configuration; runtime state; credentials; or information about any real
environment.

## Current scope

The plugin registers these read-only tools:

- `swamp_model_search`, which runs the fixed `swamp model search --json` query;
- `swamp_workflow_search`, which runs the fixed `swamp workflow search --json`
  query.

Each tool can use its caller's `repository_path`; if omitted, the local Swamp
CLI inherits Hermes's current working directory. The optional
`SWAMP_FIRST_POLICY_MODE` supports `off`, `audit`, and `strict`. In `strict`
mode, the policy narrowly blocks detected direct scheduler bypasses in
conventional command arguments. It also blocks scheduled agent jobs created or
updated through the documented `cronjob` tool unless their `enabled_toolsets`
array explicitly includes `swamp_first`. Script-only `cronjob` calls with
`no_agent` set to `true`, and lifecycle actions other than `create` or `update`,
are not blocked by this rule. This structural check does not prove that an agent uses Swamp
and does not parse shell text. It does not comprehensively enforce all Swamp-first routing.

## Private installation

Install this source tree by copying its `swamp_first_hermes` directory into the
external Hermes plugin directory, explicitly enabling it, and verifying it with
local Swamp evidence. Keep every local path and deployment setting outside Git.
See the [private installation guide](docs/installation.md) for the documented
workflow.

## Public-boundary rules

Keep all environment-specific material outside this repository, including:

- deployment, scheduler, and delivery wiring;
- local configuration and runtime state;
- Swamp data, models, vaults, workflows, reports, and generated scripts;
- logs, credentials, tokens, and `.env` files.

The repository ignore rules provide defense in depth, but contributors remain
responsible for reviewing staged changes before publication. See [the
public-boundary policy](docs/public-boundary.md) for the full policy and review
checklist.

## Contributing safely

Use generic placeholders in documentation and tests. Do not add real
infrastructure details, identities, hostnames, paths, device labels, runtime
output, or secrets. Keep deployment-specific configuration in a private
location that is not versioned by this project.

## License

This project is licensed under the [MIT License](LICENSE).
