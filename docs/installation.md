# Private installation and verification

This repository supplies a Hermes **directory plugin**. It is not a package
installer, deployment definition, scheduler, or a source of local Swamp
configuration. Keep the source checkout, Hermes state, and every target Swamp
repository separate.

## Install privately

> **Read this first — always set `HERMES_HOME` explicitly.**
>
> Every `hermes` command below, including the read-only verification ones, must
> run with `HERMES_HOME` set to the *same* value the Hermes process uses. When
> `HERMES_HOME` is unset the CLI falls back to `Path.home()/".hermes"`. If the
> service account's `HOME` is itself the Hermes home (a common container
> layout, where `HOME` and `HERMES_HOME` are the same directory), that fallback
> resolves to a **different, parallel tree** at `$HERMES_HOME/.hermes/` — with
> its own `config.yaml` and its own `plugins/` directory.
>
> That decoy tree is the single largest time sink in this project's history. It
> does not error. `hermes plugins list`, `hermes tools list`, and
> `hermes plugins enable` all succeed against it and report a completely
> coherent picture of a deployment the running gateway is not using. Confirm the
> running process's value before trusting any output:
>
> ```bash
> tr '\0' '\n' < /proc/<gateway-pid>/environ | grep HERMES_HOME
> ```

Hermes discovers a general directory plugin when a plugin directory containing
both `plugin.yaml` and `__init__.py` is placed below `$HERMES_HOME/plugins/`
(`hermes_cli/plugins.py`, user-plugin scan). The registry key is taken from the
manifest's `name:` field, not from the directory name, so the two need not
match.

Installation is **two** independent steps — a file in the right place and keys
in the right config. Either one alone loads nothing, silently.

1. Choose an external Hermes home for the deployment and set `HERMES_HOME` in
   the environment that starts Hermes. Do not point it at this source checkout
   or another Git worktree.
2. Place the plugin package below `$HERMES_HOME/plugins/`. Note that the
   installable unit is the nested `swamp_first_hermes/` package directory — it
   already carries `plugin.yaml` and `__init__.py` at its own top level. The
   repository root does not, and installing the repository root instead requires
   hand-made symlinks that no clean clone reproduces.

   Either copy it:

   ```bash
   mkdir -p "$HERMES_HOME/plugins"
   cp -R ./swamp_first_hermes "$HERMES_HOME/plugins/swamp_first_hermes"
   ```

   Or, to keep `git pull` as the update path, symlink it from a checkout. The
   directory scan and the module loader both follow symlinks:

   ```bash
   mkdir -p "$HERMES_HOME/plugins"
   ln -s /path/to/checkout/swamp_first_hermes \
         "$HERMES_HOME/plugins/swamp_first_hermes"
   ```

   If you symlink, point it at a checkout whose lifetime you control. A symlink
   into a scratch or third-party clone reintroduces exactly the failure this
   section warns about: delete the target and the plugin disappears without a
   log line.

3. Confirm the installed path contains
   `$HERMES_HOME/plugins/swamp_first_hermes/plugin.yaml` and
   `$HERMES_HOME/plugins/swamp_first_hermes/__init__.py`.
4. Enable the plugin in the config file the Hermes process actually reads.
   General user plugins are opt-in: a missing `plugins:` key is treated as "no
   plugins enabled", not as a default. Add both the enablement and the toolset
   exposure for each platform that should see the tools:

   ```yaml
   plugins:
     enabled:
     - swamp_first_hermes

   platform_toolsets:
     discord:
     - hermes-discord   # keep existing entries
     - swamp_first      # append; do not replace
   ```

   Appending a plugin toolset key does not disturb the built-in toolsets
   already listed. Plugin toolset keys are resolved separately from the
   configurable built-in ones, so adding `swamp_first` leaves the
   `hermes-discord` expansion intact.

   `hermes plugins enable swamp_first_hermes` writes these keys for you, but it
   writes them to whichever home it resolved — see the warning above. Prefer
   editing the real `config.yaml` directly, then verify by reading that exact
   file.

5. Restart the Hermes process so it re-runs plugin discovery, then verify with
   `HERMES_HOME` exported to the same value the Hermes process uses:

   ```bash
   hermes plugins list
   hermes tools list --platform discord
   ```

This copy-or-symlink-into-`$HERMES_HOME/plugins/` workflow is one Hermes
directory-plugin installation mechanism, useful when you want full control
over the checkout (e.g. a private fork, or `git pull` as your update path).
It does not use `pip install`. `hermes plugins install <owner/repo>` is a
*different*, also legitimate mechanism: it git-clones the repository straight
into the CLI's resolved home, and it is the one this project's own [README
community-install instructions](../README.md#community-install) recommend for
installing this public repository. It is not unsafe to use — the risk is not
the mechanism, it is the same `HERMES_HOME` decoy this whole section warns
about: `hermes plugins install` clones into whichever home the CLI *resolves*,
so if that resolves to the decoy tree (see the warning at the top of this
document) the command still exits successfully and every subsequent CLI
command still reports the plugin as enabled, while the running gateway never
loads it. Confirm `HERMES_HOME` against the running gateway's actual
environment before *and after* running `hermes plugins install`, exactly as
you would for the copy/symlink workflow.

Note that CLI introspection alone has repeatedly failed to detect a broken
install here. Treat `plugins list` and `tools list` as necessary but not
sufficient, and confirm end to end by invoking a tool from the actual chat
platform.

## Keep local paths and configuration private

The plugin has no private-path setting and no deployment configuration file.
It invokes the local `swamp` executable through a fixed, closed command
mapping — every tool maps to one declared CLI subcommand prefix plus a
bounded count of caller-supplied positional arguments, each passed as a
discrete `argv` element, never interpolated into a shell string. That
mapping is **not all read-only**: `swamp_model_search`,
`swamp_model_type_search`, `swamp_model_type_describe`,
`swamp_workflow_search`, `swamp_extension_search`, `swamp_extension_info`,
`swamp_model_validate`, and `swamp_workflow_validate` are read-only, but
`swamp_model_method_run`, `swamp_workflow_run`,
`swamp_extension_pull`, and `swamp_extension_push` execute or mutate, and
`swamp_workflow_set_schedule` activates unattended execution. Separately,
`swamp_definition_write` is not a `swamp` CLI call at all — it takes a
caller-supplied `content` string and writes it directly to a file on disk
with plain Python I/O (no shell, no CLI subprocess for the write itself). It
is scoped, not read-only: the target path must resolve inside the given
`repository_path` with no `..` traversal or symlink escape, and must match a
known Swamp definition convention; the write is immediately followed by the
matching `swamp` validate/quality check, and a failed model or workflow
validation reverts the previous content (or deletes a newly created file).
See [the README's tool table](../README.md#current-scope) for the full
19-tool breakdown by class. When a tool call omits `repository_path`, the
Swamp CLI inherits Hermes's current working directory. A caller may instead
supply `repository_path` for one tool call; it must be an existing directory.

Keep the actual target path in the process, caller, or private operational
configuration outside this Git repository. For example, set the deployment's
working directory before starting Hermes, or have the trusted caller provide
its local path as `repository_path`. Never add target paths, environment
values, Swamp output, credentials, tokens, runtime state, or deployment
configuration to this repository.

`SWAMP_FIRST_POLICY_MODE` is optional and is read from the Hermes process
environment. Its supported values are `off`, `audit`, and `strict`; an unset or
invalid value defaults to `off`. Set it in the private process environment,
not in a tracked file. `strict` narrowly blocks direct scheduler bypasses
expressed through conventional `command` or `argv` arguments. It also blocks
scheduled agent jobs created or updated through the documented `cronjob` tool
when their `enabled_toolsets` array does not explicitly include `swamp_first`.
A `cronjob` call with `no_agent` set to `true` is script-only and is not blocked
by this rule; actions other than `create` or `update` are also safe. This check
only validates these tool arguments: it does not prove that an agent uses
Swamp, does not parse shell text, does not call a real scheduler, and does not
read or modify scheduler state. It does not comprehensively enforce all Swamp-first routing,
and it does not infer intent from free-form text, shell pipelines, or local
metadata.

For detected non-safe decisions in `audit` or `strict` mode, the documented
`pre_tool_call` hook emits a standard Python logging event with only fixed
policy mode, classification, action, and reason-code fields. The plugin does
not configure a handler or sink, and does not log tool names, arguments,
paths, prompts, task or user identifiers, results, or exception details. This
is **local observation only**: it is **not immutable provenance**, not a comprehensive audit,
and does not show that a tool call executed or was Swamp-routed. Safe decisions
and all `off`-mode decisions emit no policy-decision event. Host logging
configuration, including retention and any forwarding, remains outside this
plugin.

## Verify with Swamp evidence

After Hermes has restarted with the plugin enabled, use the registered tools
against the intended local repository:

- `swamp_model_search` performs the fixed read-only `swamp model search --json`
  query.
- `swamp_model_type_search` finds installed model types, and
  `swamp_model_type_describe` returns their method and input contracts.
- `swamp_workflow_search` performs the fixed read-only `swamp workflow search
  --json` query.
- `swamp_extension_info` inspects a registry package before it is pulled.

For each tool, confirm that its returned JSON has `"ok": true` and that the
returned data is appropriate evidence for the local repository. If the target
is not Hermes's current working directory, invoke the tool with its private
`repository_path` at runtime rather than recording that path here. Treat the
result data as local operational evidence: review it privately and do not copy
it into issues, commits, tests, or public documentation.

### Verifying the authoring and execution tools

`"ok": true` means something different once you move past the read-only
tools:

- For `swamp_model_create` / `swamp_workflow_create`, `"ok": true` means an
  inert scaffold file was written — it does not run anything.
- For `swamp_definition_write`, `"ok": true` means the write passed its
  matching `swamp` validate/quality check; the response also carries
  `validated`, `reverted`, and `deleted` fields, so confirm you are reading
  those, not just `ok`, before assuming content landed as intended. A
  workflow write is rejected outright (`"ok": false`) if its content sets a
  live `trigger.schedule` value — that is expected, not a bug.
- For `swamp_model_method_run` / `swamp_workflow_run` / `swamp_extension_pull`,
  `"ok": true` means the underlying action actually executed against the
  target repository — verify against real Swamp state afterward
  (`swamp_model_search` / `swamp_workflow_search`), not just the response.
- For `swamp_extension_push` and `swamp_workflow_set_schedule`, the call
  short-circuits with `"ok": false` and `"error": "confirmation_required"`
  unless the caller passed `confirmed: true`. Do not verify these two by
  actually publishing to the public registry or activating a live schedule
  as a casual smoke test — confirm the confirmation-required short-circuit
  behavior instead, and only exercise the confirmed path deliberately,
  against a target you intend to change.

If discovery fails, run the following in the same private environment that
will start Hermes, with `HERMES_HOME` exported to the same value that
environment uses, then check that the directory layout and enabled name are
correct:

```bash
HERMES_PLUGINS_DEBUG=1 hermes plugins list
```

`HERMES_PLUGINS_DEBUG=1` tees plugin discovery and load detail to stderr:
which directories were scanned, which manifests parsed, `register()` results,
and tracebacks from a failed import. Plugin loading emits nothing at the
default `INFO` level, so an absent plugin looks identical to a healthy one in
ordinary logs — this flag is the fastest way to tell a plugin that failed to
load from one that was never found.

If the plugin does not appear at all, compare the two candidate homes directly
before assuming anything about the plugin's code:

```bash
ls -la "$HERMES_HOME/plugins/"          # what the running process scans
ls -la "$HERMES_HOME/.hermes/plugins/"  # the fallback tree, when HOME matches
```
