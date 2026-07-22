# Swamp-first governance and threat boundary

## Status and purpose

“Swamp-first” is a governance goal: where policy requires it, work should be
routed through Swamp-capable paths and leave suitable evidence. This public
plugin is a **bounded** foundation for that goal. Its current checks are narrow
and it is **not comprehensive** enforcement. In particular, it does not
comprehensively enforce all Swamp-first routing.

This document is a public contract for contributors, integrators, and future
core work. It describes the intended trust boundary without describing any
private environment, operational workflow, or deployment.

## Trust and execution boundary categories

A comprehensive design must state which categories it observes and controls.
The relevant boundary categories are:

- **caller input and agent-generated intent** — requests, delegated work, and
  structured arguments may not reliably express the caller's actual intent;
- **tool selection and routing** — choosing a tool is distinct from proving
  that the selected path used Swamp appropriately;
- **free-form command or process execution** — text, scripts, subprocesses, and
  indirect launches can bypass structured tool arguments;
- **filesystem and repository selection** — working directories, supplied
  repository references, and local artifacts affect what evidence means;
- **scheduler and job control** — creation, update, triggering, and execution
  of work may occur through paths outside a narrow plugin check;
- **network or remote-service access** — a tool may cause effects through an
  external interface that is not visible to local argument inspection;
- **plugin lifecycle and configuration** — discovery, enablement, updates, and
  policy configuration affect whether a check is available; and
- **evidence and provenance** — a result can be useful evidence only when its
  origin, route, policy decision, and relevant context can be attributed.

These categories are threat boundaries, not claims that this repository
currently mediates them. No documentation or test may represent a category as
covered unless the implementation and its tests demonstrate that coverage.

## Policy concepts

The following concepts are deliberately separate:

- **off**: no Swamp-first policy decision is requested; ordinary behavior
  continues without a policy warning or block from this policy.
- **audit**: policy-relevant activity is allowed while emitting an observable,
  non-sensitive decision record suitable for review.
- **enforce**: policy-relevant activity is allowed only when it satisfies the
  applicable Swamp-first rule; otherwise it is denied before execution.

These are conceptual governance states, not a promise that every execution
path has all three states today. The current public plugin exposes `off`,
`audit`, and a narrowly scoped `strict` setting. Its `strict` behavior is not a
synonym for comprehensive enforce: it covers only the documented, structured
cases and cannot establish end-to-end routing.

## Current bounded implementation

Today, the plugin supplies read-only discovery tools, scoped authoring tools
(create, validate, and write a Swamp model/workflow/extension definition,
with automatic validate-and-revert-on-failure), and execution tools (run a
model method, run a workflow, pull or push an extension, set a workflow's
live schedule) plus narrow argument-based policy checks. The two most
safety-sensitive tools — publishing an extension and activating a workflow's
live schedule — require the caller to pass an explicit `confirmed: true`
argument before they proceed.

That `confirmed: true` requirement is a **separate mechanism** from the
`pre_tool_call` policy hook described below. The hook does not inspect
`swamp_definition_write`, the extension-publish tool, or the
schedule-activation tool at all — it narrowly classifies only direct
scheduler-bypass command vectors and a documented `cronjob` tool call missing
the Swamp-first toolset. Confirmation-gating and policy-hook classification
are independent controls that happen to cover different, non-overlapping
tools; neither substitutes for the other. The plugin does not parse arbitrary
shell text, mediate every process, inspect every filesystem action, control
every scheduler path, or establish provenance for every result. A passing
check therefore means only that the implemented bounded rule passed; it does
not prove that all work was Swamp-routed.

### Local policy-decision observation

For a detected non-safe decision in `audit` or `strict` mode, the documented
`pre_tool_call` hook emits one standard Python logging event before it returns
any strict-mode block directive. The fixed event fields are the policy mode,
classification, action, and fixed reason code. The plugin does not include a
tool name, arguments, paths, prompts, task or user identifiers, results, or
exception details, and it does not add a logging handler, sink, file, network
call, or runtime state.

This logging is **local observation only**. It is **not immutable provenance**,
not a comprehensive audit, and not evidence that a tool call executed, was
routed through Swamp, or produced a particular result. Retention, access,
formatting, and any forwarding are outside this plugin and depend on the host
logging configuration. Safe decisions and all `off`-mode decisions emit no
policy-decision event.

## Future core-routing and provenance contract

Future comprehensive enforcement requires support below individual plugins.
Future core routing should provide a single, mandatory decision point before
every tool invocation and before execution-capable routing transitions. It
should apply the selected policy consistently, prevent alternate routes from
silently skipping that decision, and return a clear policy outcome.

Future provenance should associate a policy outcome with the routed action and
its resulting evidence using non-sensitive, reviewable metadata. It must make
clear whether an action was off, audit, or enforce, which rule was evaluated,
and whether execution was allowed or denied. Future core routing and provenance
are **not present today** in this repository.

## Acceptance criteria for eventual comprehensive support

A future claim of comprehensive Swamp-first enforcement is acceptable only when
all of the following are demonstrated by public, repeatable tests:

1. The core has a mandatory policy decision point for every tool invocation and
   execution-capable route, including delegated and scheduled work.
2. Each boundary category above has an explicit handling decision: mediated,
   intentionally excluded with a documented limitation, or rejected.
3. Off, audit, and enforce have distinct, tested behavior; enforce denies a
   non-compliant action before its effect begins.
4. Alternate execution paths cannot bypass core routing without an explicit,
   tested exception that is visible to policy and review.
5. Provenance records connect the policy decision, route, and resulting evidence
   without exposing private data.
6. Documentation names residual limitations and never upgrades bounded coverage
   into a comprehensive claim without the corresponding implementation and
   tests.

Until these criteria are met, public descriptions must use bounded language and
refer to comprehensive enforcement only as future core support.

## Public-safety rule

Keep this contract generic. Do not add private data, real infrastructure,
identities, local paths, credentials, endpoints, deployment configuration, or
operational records. Use neutral placeholders and reusable examples only.
