# Swamp-First Hermes

Swamp-First Hermes is a public Hermes directory plugin that exposes a
narrowly scoped set of Swamp discovery, authoring, and execution tools, with
explicit human-confirmation gates on the two irreversible actions. This
plugin is a bounded foundation for "swamp-first" governance, not comprehensive
end-to-end enforcement — see [Governance and threat
boundary](#governance-and-threat-boundary) below.

This repository intentionally contains only reusable source material and public
documentation. It does **not** contain deployment, scheduler, or delivery
configuration; runtime state; credentials; or information about any real
environment.

## Current scope

The plugin registers 19 tools, grouped below by how much they can change:

### Read-only

| Tool | Purpose |
|---|---|
| `swamp_model_search` | List Swamp models (`swamp model search --json`). |
| `swamp_model_type_search` | Search installed model types before choosing or creating an instance. |
| `swamp_model_type_describe` | Inspect a model type's methods, inputs, global arguments, and resources. |
| `swamp_workflow_search` | List Swamp workflows (`swamp workflow search --json`). |
| `swamp_extension_search` | Search the Swamp extension registry. |
| `swamp_extension_info` | Inspect an extension's content and method contracts before pulling it. |
| `swamp_model_validate` | Validate a model definition against its schema. |
| `swamp_workflow_validate` | Validate a workflow definition against its schema. |
| `swamp_extension_quality` | Score an extension manifest against the Swamp Club quality rubric. Read-only-ish: it caches a packaged tarball on disk for reuse by a later publish, but makes no registry or Swamp-state change itself. |

### Inert-write (writes a file; never itself causes anything to run)

| Tool | Purpose |
|---|---|
| `swamp_model_create` | Scaffold a new model definition file for a given type and name. |
| `swamp_workflow_create` | Scaffold a new workflow definition file. |
| `swamp_definition_write` | Write caller-supplied content into a model, workflow, report, or extension definition file, then immediately validate it. See [Authoring and confirmation gates](#authoring-and-confirmation-gates). |
| `swamp_model_set_config` | Set configuration (e.g. `globalArguments`, `tags`, vault bindings) on an existing model instance located by name — deep-merged into the instance's raw definition, then validated, reverting on failure. Identity fields (`id`, `type`, `typeVersion`, `name`, `version`) are refused. |
| `swamp_extension_fmt` | Auto-format a Swamp extension's source from its manifest path — the fix for what `swamp_extension_quality` tells you to run. |

### Mutating / execute

| Tool | Purpose |
|---|---|
| `swamp_model_method_run` | Run a method on an existing Swamp model instance. |
| `swamp_workflow_run` | Run an existing Swamp workflow by name. |
| `swamp_extension_pull` | Install an extension from the Swamp registry into the local repository. |

### Irreversible, confirmation-gated

| Tool | Purpose |
|---|---|
| `swamp_extension_push` | Publish an extension to the **public** Swamp registry. Requires `confirmed: true`. |
| `swamp_workflow_set_schedule` | Set a workflow's live cron `trigger.schedule` — the only tool that activates unattended scheduled execution. Requires `confirmed: true`. |

Every tool call can supply its own `repository_path`; if omitted, the local Swamp
CLI inherits Hermes's current working directory. The optional
`SWAMP_FIRST_POLICY_MODE` supports `off`, `audit`, and `strict`. In `strict`
mode, the policy narrowly blocks detected direct scheduler bypasses in
conventional command arguments. It also blocks scheduled agent jobs created or
updated through the documented `cronjob` tool unless their `enabled_toolsets`
array explicitly includes `swamp_first`. Script-only `cronjob` calls with
`no_agent` set to `true`, and lifecycle actions other than `create` or `update`,
are not blocked by this rule. This structural check does not prove that an agent uses Swamp
and does not parse shell text. It does not comprehensively enforce all Swamp-first routing.
This policy hook is a separate mechanism from the `confirmed: true` gates
described next — it does not inspect `swamp_definition_write`,
`swamp_extension_push`, or `swamp_workflow_set_schedule` at all.

By default, the Swamp CLI adapter never surfaces a failed process's stderr —
it can carry absolute local paths and private identifiers. The one narrow
exception is the authoring/execution allowlist — `swamp_model_validate`,
`swamp_workflow_validate`, `swamp_extension_quality`, `swamp_extension_fmt`,
`swamp_model_method_run`, and `swamp_workflow_run`: on a fatal failure with
no JSON result body, these return a `diagnostics` string — the same
stderr with every absolute filesystem path scrubbed to a repository-relative
path or an opaque placeholder — so a lint rule, file:line, missing-input, or
model-code error stays actionable without ever surfacing where the repository
lives on disk. Every other tool, and every other failure shape, keeps stderr
fully withheld. See
[docs/public-boundary.md](docs/public-boundary.md) for the full scope and
rationale.

## Authoring and confirmation gates

`swamp_definition_write` is the plugin's one general-purpose write path: it
takes a caller-supplied `content` string and writes it, via plain Python file
I/O, to a path that must resolve inside the caller's `repository_path` (no
`..` traversal, no symlink escape) and must match a known Swamp definition
convention (`models/`, `workflows/`, `extensions/models/`, `reports/`, or a
manifest-declared path). Every write is immediately followed by the matching
`swamp model validate`, `swamp workflow validate`, or `swamp extension
quality` check:

- a **model or workflow** write that fails validation is reverted to its
  previous content, or deleted if it did not exist before — the tool never
  leaves an invalid definition on disk;
- an **extension** write that fails the quality rubric is *kept*, with the
  rubric result returned, so a multi-file extension can be built up one file
  at a time without earlier progress being discarded;
- a workflow write that would set a live `trigger.schedule` value is
  **rejected outright** — writing a workflow never itself makes it run
  unattended.

That last point is why `swamp_workflow_set_schedule` exists as its own tool:
it is the *only* way to activate a workflow's live schedule, and it — along
with `swamp_extension_push`, which publishes to the public registry — requires
the caller to pass `confirmed: true`. Neither tool proceeds on a `confirmed`
value of anything else, including a missing one. These two tools are the
plugin's most safety-sensitive surface: one makes a change public and
hard to reverse, the other makes an agent-authored file start running on its
own, unattended, forever, until someone changes it again. Treat `confirmed:
true` as something that is set only after a real human has explicitly agreed
to that specific action — never inferred, defaulted, or set by policy alone.

## Community install

This repository is public and installable directly by Hermes:

```bash
hermes plugins install meagerfindings/swamp-first-hermes --enable
```

Hermes git-clones this repository into the resolved Hermes plugins home. The
nested layout — `swamp-first-hermes/swamp_first_hermes/plugin.yaml` — is what
Hermes's plugin category scan looks for; you do not need to move or flatten
anything yourself.

Alternatively, install it as a Python package so Hermes's entry-point loader
(group `hermes_agent.plugins`) registers it — clone the repository and run
`pip install .`, or install it from your own package index. This registers
`swamp_first_hermes` without a directory drop. One caveat: Hermes does not read
`plugin.yaml` for entry-point installs, so `hermes plugins list` shows a blank
version/description/tool list for a pip-installed instance (a Hermes-side
limitation) — tool and hook registration work identically. Use the same
manifest name (`swamp_first_hermes`) in config regardless of install method, so
a machine with both installs does not end up with two entries.

Installing is not the same as enabling it for a platform. Two separate
config opt-ins are still required, in the config file the running Hermes
process actually reads:

```yaml
plugins:
  enabled:
  - swamp_first_hermes

platform_toolsets:
  discord:
  - hermes-discord   # keep existing entries
  - swamp_first      # append; do not replace
```

**Caveat:** `hermes plugins install` clones into the CLI's *resolved* Hermes
home, which is not necessarily the home the running gateway process actually
uses — verify `HERMES_HOME` against the running gateway's own environment
*before* installing, the same way the [private installation
guide](docs/installation.md) warns you to before trusting any `hermes plugins
list` output. See that guide's `HERMES_HOME` decoy-home warning for the exact
failure mode and how to confirm you are looking at the real one.

The Swamp models and extensions this plugin's tools actually operate on are
**not bundled in this repository** — they are distributed separately through
the Swamp registry. Once the plugin is installed and enabled, pull whatever
your agent needs with the Swamp CLI itself, e.g. `swamp extension pull
<namespace>/<name>`, or search first with `swamp extension search <query>` (or
the plugin's own `swamp_extension_search` tool).

**Reusable playbook:** for a from-scratch, step-by-step walkthrough of locking
a Hermes deployment down to Swamp-routed tools only — disabling raw
shell/file/browser toolsets, installing a plugin like this one, standing up
the Swamp models it needs, and verifying the lockdown for real — see
[Lock Down Hermes to Swamp](docs/lock-down-your-hermes.md).

## Governance and threat boundary

Swamp-first is currently a bounded plugin capability, not comprehensive
end-to-end enforcement. The [governance and threat-boundary
contract](docs/governance-boundary.md) defines the public trust boundaries,
distinguishes off/audit/enforce concepts, and sets acceptance criteria for
future core routing and provenance support.

## Private installation

Install this source tree by copying its `swamp_first_hermes` directory into the
external Hermes plugin directory, explicitly enabling it, and verifying it with
local Swamp evidence. Keep every local path and deployment setting outside Git.
See the [private installation guide](docs/installation.md) for the documented
workflow. (For a community install directly from this public repository, see
[Community install](#community-install) above instead.)

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
