# RFC: Hermes-core routing and effect-policy interface

**Status: Proposal**  
**Audience:** Hermes-core maintainers, host implementers, and public plugin authors

## Abstract

This RFC proposes a **generic Hermes-core** decision layer for routing an
execution request before it reaches an effect-capable boundary. The layer lets a
host select a policy that returns one of three route decisions: **allow**,
**block**, or **redirect**. It is intentionally domain-neutral: policy rules may
be supplied by a host or plugin, but the core API neither names nor privileges a
particular workflow, provider, product, or deployment.

The proposal makes decisions observable through **host-owned audit events** and
supports optional **turn requirements** and **evidence completion**. It does not
claim that these capabilities are not present today in every Hermes host; this
is a design for a common core contract.

## Goals and non-goals

Goals:

- one mandatory, structured decision point before a mediated effect;
- deterministic ordering, defined redirect loop limits, and explicit policy
  exception and fail modes;
- a route result that can carry requirements for the current turn and evidence
  expected after a successful effect;
- audit records owned, stored, and redacted by the host rather than by a policy
  plugin; and
- preservation of no-policy behavior and public plugin compatibility.

Non-goals:

- interpreting free-form shell text or proving the real-world consequence of an
  arbitrary process;
- making a policy plugin an authorization system, audit sink, or provenance
  database;
- retroactively mediating effects performed outside Hermes; or
- changing the public plugin API merely because a host adopts this feature.

## Terminology and model

An **operation** is a structured description of requested work before an effect
starts. It contains a stable `operation_id`, an `effect_kind`, an `ingress`, a
route target, and host-selected, minimally necessary metadata. An **effect** is
an externally observable or state-changing action, including a tool invocation,
job mutation, job run, delegation launch, or service request.

A **policy evaluator** receives an immutable operation view and returns a
`RouteDecision`:

| Decision | Meaning | Core action |
| --- | --- | --- |
| `allow` | Continue on the proposed route. | Dispatch only after requirements are satisfied. |
| `block` | Do not begin the effect. | Return a stable policy outcome to the caller. |
| `redirect` | Replace the proposed route with a specified compatible route. | Re-evaluate the replacement operation. |

A decision includes a stable policy identifier, rule identifier, reason code,
and optional opaque public-safe labels. A redirect also supplies a replacement
route and may narrow capabilities; it must not silently expand an operation's
effect class. Policies cannot invoke an effect while evaluating a decision.

### Requirements and completion

An allow or redirect decision may attach optional turn requirements, such as an
explicit confirmation, a capability grant, a structured field, or an earlier
turn artifact. The core checks these before dispatch. Requirements are declared
rather than implemented by policy code, so the host controls presentation and
validation.

A decision may also attach an evidence completion request describing the
non-sensitive result metadata the host should record after dispatch. Completion
is an outcome, not a promise that an external effect happened. Hosts define
retention and access controls; plugins receive no implicit access to completed
evidence.

## Evaluation semantics

1. The boundary adapter constructs one normalized operation and gives it a
   monotonic route-attempt identifier.
2. Enabled evaluators run in deterministic order: host policy first, then
   explicitly configured plugin policies sorted by priority and stable policy
   identifier. Equal priorities are invalid configuration, not an ordering
   shortcut.
3. A block terminates evaluation. An allow accumulates only compatible
   requirements and completion requests. A redirect terminates the current pass,
   produces a new normalized operation, and begins a new pass.
4. The core detects repeated route identities and enforces a small,
   host-configured redirect loop limit. A loop or exhausted limit blocks before
   dispatch with a stable reason code.
5. Once all evaluators allow the operation and requirements are fulfilled, the
   adapter dispatches exactly one mediated effect. The host emits the final audit
   event before or atomically with dispatch according to its durability model.
6. The host emits a completion audit event after dispatch returns, fails, or is
   cancelled. The event distinguishes policy authorization from execution
   outcome.

A policy exception is never converted to allow. Each policy registration states
its exception mode: `fail-closed` blocks the operation; `fail-open` records a
policy-error audit outcome and continues only when the host's deployment mode
permits it. The host may globally prohibit fail-open for selected effect kinds.
Configuration errors, malformed decisions, unknown redirect targets, and audit
serialization failures have equally explicit host-defined fail modes; the safe
default for an effect-capable boundary is fail-closed.

## Host audit contract

Audit events are **host-owned audit events**. Core defines a minimal schema:
operation and route-attempt identifiers, ingress and effect kind, selected
route identity, ordered policy outcomes, decision/reason codes, requirement and
evidence-completion status, dispatch state, and timestamps. The host controls
sinks, retention, redaction, and whether event delivery is required before an
effect. Raw prompts, arguments, result bodies, local paths, and identity data
are excluded by default and require an explicit host schema extension.

## Boundaries that require mediation

The contract applies wherever Hermes turns an ingress into an effect. Initial
adapters must cover all relevant ingress and effect boundaries:

- interactive tool calls and agent-local tools;
- dashboard/API requests that invoke or mutate work;
- plugin direct dispatch, including plugin-to-plugin calls that would otherwise
  skip the normal tool dispatcher;
- scheduler job mutation and run, including create, update, enable, trigger,
  and execution of a stored job;
- no-agent scripts launched through Hermes-managed runners;
- delegation creation, delegated tool calls, result handoff, and cancellation;
  and
- service, filesystem, process, and network adapters when the host exposes them
  as Hermes-managed effects.

An adapter may mark an operation intentionally unsupported, but it must then
reject the effect or expose that exception to policy and audit. A bare helper
that performs an effect without an adapter is a core defect, not a policy
opt-out.

## Compatibility and rollout

No-policy behavior is preserved: with no evaluators enabled, normalized
operations dispatch through the existing route with no added policy decision,
redirect, denial, or required audit sink. The integration should retain existing
result shapes and timing as far as practical.

Public plugin compatibility is preserved. Existing plugins may continue to use
the documented hook and tool interfaces unchanged. A new optional policy
provider protocol is additive; hosts must not assume a plugin implements it.
During transition, legacy hooks remain adapters at their existing boundary and
must not be represented as universal enforcement.

## Core changes versus current plugin capability

### Requires core changes

The core must provide normalized operation construction, mandatory adapters,
deterministic evaluator registration, redirect re-entry, loop accounting,
requirement validation, effect dispatch guards, audit lifecycle emission, and
cross-turn/delegation context propagation. Likely generic Hermes surfaces are
the tool dispatcher and hook lifecycle, scheduler service and worker, dashboard
and API request handlers, plugin registry and direct-dispatch interfaces,
agent runtime/local-tool bridge, script runner, delegation coordinator, and
observability abstraction. These are conceptual areas, not assertions about
current module names or layouts.

### What a current plugin can do

A current plugin can offer opt-in, bounded checks at documented hooks; return a
local allow-or-block directive when a host honors it; validate its own tools;
and emit safe local observations. It cannot make every adapter mandatory,
intercept uncooperative direct dispatch, enforce scheduler execution, carry a
route decision across delegation, redirect arbitrary core routes, or own
reliable host audit events. Therefore this RFC is not a claim of comprehensive
enforcement by the current plugin.

## Open questions

- Which capability vocabulary is stable enough for redirects across hosts?
- Should audit durability be selectable per effect kind or only per host?
- How should a delegated operation preserve its route identity across process
  boundaries without disclosing sensitive context?
- Which requirement types belong in core versus a host extension registry?
