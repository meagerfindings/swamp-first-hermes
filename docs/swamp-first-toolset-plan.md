# Swamp-first toolset and authoring plan

**Status: Adopted plan.**
**Supersedes:** [hermes-core-routing-policy-rfc.md](hermes-core-routing-policy-rfc.md)
and [hermes-core-routing-policy-plan.md](hermes-core-routing-policy-plan.md)
for this deployment.

## Why this replaces the core-routing RFC

The RFC proposed a mandatory, Hermes-core mediation chokepoint before every
effect-capable action. A concrete feasibility scoping against the real
upstream project (`NousResearch/hermes-agent`) found:

- Phase 0–2 (the RFC's own minimum for real mandatory mediation) would take
  an estimated 2–4 person-months for someone already fluent in a 200k+-line
  monorepo.
- The files a fork would touch (`model_tools.py`, `hermes_cli/plugins.py`,
  `cron/`, `tools/delegate_tool.py`) saw roughly one relevant upstream commit
  every 1–2 days over the prior 90 days — a standing rebase tax, not a
  one-time cost.
- The RFC's central premise — one mandatory decision point — is already
  false today: the ACP (Zed IDE) adapter has its own, entirely independent
  permission system with zero connection to `pre_tool_call`. There are at
  least two ingress/effect surfaces already, before finishing an audit of the
  dashboard/API server.

Deployment-level toolset scoping reaches the same practical goal —
Hermes cannot take an effect outside Swamp — without touching Hermes core at
all, using a command (`hermes tools disable`) that already ships today. It
converts the problem from "mediate every internal code path" (open-ended,
chases new adapters forever) to "the non-Swamp-routed tools don't exist in
this deployment" (closed, verifiable by listing what's enabled).

## Completed

- **Closed the unauthenticated gateway API.** The deployment's
  `API_SERVER_ENABLED` setting was removed from its container configuration,
  the change was deployed, and it was verified: container inspection showed
  the env var absent and the API's listening port was no longer open. This
  was attack-surface reduction (who can reach the agent), not swamp-first
  enforcement (what the agent can do) — the two are separate concerns and
  this plan is about the second one.
- **Confirmed the live tool inventory.** `hermes tools list` on the running
  deployment shows the base toolset includes `terminal`, `file`, `browser`,
  `code_execution`, `computer_use`, `homeassistant`, `delegation`, and
  `messaging` — none Swamp-routed, none inspected by the existing
  `swamp_first_hermes` policy hook (which only checks the `cronjob` tool's
  arguments). This is the actual swamp-first gap: everything Hermes does via
  its one real channel (Discord) passes through these tools today with no
  Swamp involvement unless the agent happens to choose to.

## Toolset restrictions (pending)

Disable outright via `hermes tools disable`:

- `terminal`, `file`, `browser`, `code_execution`, `computer_use`

Open, deferred to a separate decision:

- `homeassistant` — direct home-automation control. Keep as a deliberately
  excluded, separately trusted domain, or eventually wrap it in a Swamp
  model?
- `delegation` — sub-agents inherit the parent's toolset
  (`inherit_mcp_toolsets: true`), so stripping the parent likely cascades
  safely, but worth confirming before deciding whether to also disable it
  outright.

## Plugin extensions needed (not yet built)

Extend `swamp_first_hermes` following the existing closed-command-allowlist
pattern in `swamp_cli.py` (fixed argv, `cwd`-only path injection, no
interpolated arguments, JSON-only output). New allowed commands:

- `model create <type> <name>`, `model validate [name]`, `model method run
  <model> <method>`
- `workflow create <name>`, `workflow validate [name]`, `workflow run <name>`
- `extension search <query>`, `extension pull <extension>`, `extension
  quality <manifest-path>`, `extension push <manifest-path>`

`extension push` publishes to a shared registry — public and hard to
reverse — so it requires an explicit manual confirmation regardless of
`extension quality`'s score, never an automatic call.

## The scoped content-write tool

`swamp model edit` / `swamp workflow edit` are interactive editors with no
non-interactive content flag, so there is no CLI command to wrap for
actually authoring a definition's content. This needs one new, carefully
scoped tool, split into two so that "author a thing" and "make a thing run
unattended forever" are never the same action:

**`swamp_definition_write(repository_path, relative_path, content)`**

- Resolves `relative_path` against `repository_path`; rejects `..`
  traversal, absolute paths, and any resolved (symlink-following) real path
  landing outside the repo root.
- Restricts `relative_path` to the known Swamp definition conventions
  (`models/`, `extensions/models/`, `workflows/`, `reports/`, or root-level
  `model.ts` / `*_report.ts` / `manifest.yaml` patterns — confirm the
  canonical set against the swamp-model/swamp-extension skill docs rather
  than the two example repos inspected while designing this).
- Writes via plain Python file I/O — no shell involved in the write itself,
  so the entire command-injection risk category that made raw `terminal`
  dangerous doesn't apply here.
- Snapshots the previous content before overwriting. After writing, runs the
  relevant `swamp model validate` / `swamp workflow validate` / `swamp
  extension quality` automatically. On failure, restores the snapshot and
  returns the validation errors so the agent can retry — never leaves a
  broken definition on disk.
- Deliberately inert: a valid write does not cause anything to run.

**`swamp_workflow_set_schedule(repository_path, workflow_name, cron_expression)`**

- The *only* way to set a workflow's live `trigger.schedule`.
  `swamp_definition_write` refuses to accept a live schedule value directly.
- Gated behind the same manual-confirmation pattern Hermes already uses for
  destructive shell (`approvals.mode: manual`, `destructive_slash_confirm:
  true`). "Build me a nightly disk-check workflow" always produces a
  validated, inert file; "start running that at 5am tonight" is always a
  separate yes/no.

## Two-lane execution model

No agent-callers inside Swamp. An earlier draft of this plan considered
wrapping an LLM call (via extensions like `@sntxrr/openrouter` or
`@keeb/ollama`) inside a Swamp model step to replicate "agent interpretation"
for scheduled jobs running independently of Hermes. Rejected: that
duplicates what Hermes already is, in a second place, with its own prompt
logic to maintain. The split instead:

- **Lane A — pure deterministic, Swamp-native.** Workflows with
  `trigger.schedule`, run by `swamp serve`'s native scheduler. No agent
  involvement, by design. For checks, collection, and aggregation with no
  judgment call in them (backups, threshold checks, structured data
  pipelines).
- **Lane B — anything needing real interpretation or judgment.** Stays
  exactly what it is today: Hermes' own native `cronjob` mechanism
  triggering an agent turn. The only change is that turn's toolset is the
  swamp-first-restricted one (search/create/validate/run Swamp things, plus
  the scoped write tool — no raw shell/file/browser/code_execution/
  computer_use). Hermes still reasons freely; it just cannot *act* outside
  Swamp when it decides to do something. This is a deliberate, documented
  exception — the trigger isn't Swamp-native, the effect capability still
  is — not a silent gap.

## Open questions

1. `homeassistant` toolset: keep as an excluded trusted domain, or eventually
   route it through a Swamp model?
2. `delegation` toolset: disable outright, or rely on toolset inheritance
   cascading the restriction to sub-agents?
3. Hot-reload semantics for locally authored (non-pulled) workflow/model
   files under a live `swamp serve` process are unconfirmed. The
   `--hot-reload` / `swamp serve reload` machinery observed in the CLI help
   text appears scoped to *pulled extension bundles* specifically. Whether a
   freshly written local `workflows/*.yaml` with a schedule trigger is
   picked up automatically on its next tick, or needs an explicit reload,
   needs verifying against real `swamp serve` behavior before treating "no
   schedule field = inert" as a reliable safety property.
4. Canonical directory conventions for `swamp_definition_write`'s path
   allowlist — confirm against swamp-model/swamp-extension skill guidance.

## Next steps

1. Resolve open questions 3 and 4 above.
2. Implement the plugin extensions (new command wrappers, the write tool,
   the schedule-set tool) with tests, following the existing `swamp_cli.py`
   pattern and test coverage style.
3. Decide `homeassistant` and `delegation`.
4. Apply `hermes tools disable terminal file browser code_execution
   computer_use` on the live deployment.
5. Deploy and verify, mirroring the disable/verify pattern already used for
   `API_SERVER_ENABLED` (confirm via `docker inspect` and `hermes tools
   list`, not just the config file).
