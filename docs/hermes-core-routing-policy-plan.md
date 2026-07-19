# Hermes-core routing and effect-policy implementation plan

**Status: Implementation plan**  
**Scope:** public, generic upstream discussion and incremental core delivery

This plan implements the RFC without making a domain-specific API or claiming
that the current plugin provides universal mediation. Each phase is separately
reviewable, feature-gated, and releasable.

## Delivery principles

- Preserve no-policy behavior and existing public plugin compatibility.
- Land a small typed contract before changing a boundary adapter.
- Prefer fail-closed at effect-capable boundaries; make every exception and
  fail-open choice visible through host-owned audit events.
- Do not merge an adapter until its normal, bypass, cancellation, and failure
  paths have conformance coverage.
- Treat all relevant ingress and effect boundaries as a release criterion, not
  as an implication that the first phase covers them all.

## Phase 0 — contract and fixtures

Define stable, serializable operation, route-decision, requirement,
evidence-completion, audit-event, and policy-error types. Specify evaluator
ordering, malformed-decision handling, redirect route identity, and a default
redirect loop limit. Add golden fixtures for allow, block, redirect, repeated
redirect, requirement pending, evidence completion, policy exception,
fail-open, and fail-closed.

**Exit criteria:** types and schemas are documented; fixture tests prove stable
reason codes and deterministic ordering; the feature flag defaults off.

## Phase 1 — core evaluator and guarded dispatch

Add an optional evaluator registry to the generic tool dispatcher and hook
lifecycle conceptual area. Normalize one operation per dispatch, evaluate in
stable host/plugin order, aggregate compatible requirements, and guard dispatch
until a final allow. Re-enter evaluation after redirect, reject a redirect loop,
and emit host-owned audit events around decision and completion.

Keep the legacy hook path as a compatibility adapter. With no registered policy,
exercise the existing route and return shape.

**Exit criteria:** unit and integration tests show exactly-once mediated
dispatch, no-policy parity, block-before-effect, redirect re-evaluation,
requirement validation, and configured policy exception/fail modes.

## Phase 2 — ingress and stored-work adapters

Apply the same guard to dashboard/API request handlers, plugin direct dispatch,
and agent-local tools. Add scheduler job mutation and run adapters for create,
update, enable, trigger, worker execution, cancellation, and recovery. A stored
job must be evaluated both when it is changed and when it runs; it must not rely
on stale authorization.

**Exit criteria:** integration tests demonstrate that each adapter constructs an
operation, cannot bypass the guard through its ordinary public entry point, and
reports a distinct ingress in audit events.

## Phase 3 — scripts and delegation

Add a guarded no-agent scripts runner and delegation coordinator. Propagate a
minimal route context across delegation creation, delegated effects, result
handoff, retry, and cancellation. Revalidate on the receiving host instead of
trusting a prior allow. Define behavior for unsupported remote policy versions
and unavailable audit delivery.

**Exit criteria:** cross-process integration fixtures verify propagation,
revalidation, cancellation, retry, and rejection of looped or malformed context
without exposing payload content.

## Phase 4 — plugin provider API and adoption

Publish an additive policy-provider protocol, versioning rules, priority
configuration, and compatibility guide. Migrate one non-core sample provider
only after the core guard is available. Document that direct plugin enforcement
remains bounded when the host does not adopt the new interface.

**Exit criteria:** compatibility tests load legacy plugins unchanged, load an
optional provider, reject duplicate priorities, and prove a provider cannot
perform dispatch while it is being evaluated.

## Phase 5 — hardening and default decision

Inventory every effect adapter in supported hosts and classify it as mediated,
explicitly rejected, or unsupported with a visible audit outcome. Run load,
restart, and upgrade tests. Decide separately for each host whether to enable a
policy by default; the core feature can remain available while no-policy
behavior remains the default.

**Exit criteria:** the conformance matrix is complete for supported adapters,
operational documentation states residual boundaries, and upgrade tests preserve
no-policy behavior.

## Conformance matrix

| Area | Unit | Integration | Compatibility | Failure-mode | Required assertion |
| --- | --- | --- | --- | --- | --- |
| Evaluator order and allow/block/redirect | Yes | Yes | Yes | Yes | Stable order; block starts no effect; redirect is re-evaluated. |
| Redirect loop and invalid target | Yes | Yes | No | Yes | Limit/repetition blocks with one stable reason. |
| Turn requirements and evidence completion | Yes | Yes | Yes | Yes | Dispatch waits for requirements; completion distinguishes execution outcome. |
| Host audit events | Yes | Yes | Yes | Yes | Event ownership, redaction defaults, decision and completion sequencing. |
| Interactive dispatcher and agent-local tools | Yes | Yes | Yes | Yes | No-policy parity and guarded effect. |
| Dashboard/API | Yes | Yes | Yes | Yes | Request cannot obtain direct effect dispatch. |
| Plugin direct dispatch | Yes | Yes | Yes | Yes | Plugin-to-plugin route re-enters the guard. |
| Scheduler job mutation and run | Yes | Yes | Yes | Yes | Mutate and later run are independently evaluated. |
| No-agent scripts | Yes | Yes | Yes | Yes | Runner is guarded before process start. |
| Delegation | Yes | Yes | Yes | Yes | Receiving side revalidates propagated context. |
| Policy exception and fail modes | Yes | Yes | Yes | Yes | Fail-open is configured/audited; fail-closed prevents effect. |
| Legacy plugins and absent policy | Yes | Yes | Yes | Yes | Existing interfaces and no-policy behavior are unchanged. |

## Test execution and review gates

Every phase adds focused tests before implementation, then runs the full test
suite. Review gates include a diff check, documentation checks for bounded
claims, and a public-safety scan for local paths, identities, secrets, and
network endpoints. Tests must use neutral fixture names and synthetic metadata.

Before release, run the matrix against each supported host configuration with
policy absent, allow, block, redirect, requirement pending, evaluator exception,
audit failure, cancellation, retry, and restart. Any newly discovered direct
effect path blocks default-on adoption until it is mediated or explicitly
rejected.
