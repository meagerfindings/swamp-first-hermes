# Private installation and verification

This repository supplies a Hermes **directory plugin**. It is not a package
installer, deployment definition, scheduler, or a source of local Swamp
configuration. Keep the source checkout, Hermes state, and every target Swamp
repository separate.

## Install privately

Hermes discovers a general directory plugin when a plugin directory containing
both `plugin.yaml` and `__init__.py` is placed below
`$HERMES_HOME/plugins/`. The directory name must match the plugin name in the
manifest.

1. Choose an external Hermes home for the deployment and set `HERMES_HOME` in
   the environment that starts Hermes. Do not point it at this source checkout
   or another Git worktree.
2. From a clean copy of this repository, copy only the plugin directory into
   that external home:

   ```bash
   mkdir -p "$HERMES_HOME/plugins"
   cp -R ./swamp_first_hermes "$HERMES_HOME/plugins/swamp_first_hermes"
   ```

3. Confirm the installed directory contains
   `$HERMES_HOME/plugins/swamp_first_hermes/plugin.yaml` and
   `$HERMES_HOME/plugins/swamp_first_hermes/__init__.py`.
4. Enable the discovered plugin explicitly. General user plugins are opt-in:

   ```bash
   hermes plugins enable swamp_first_hermes
   hermes plugins list
   ```

   The list should show `swamp_first_hermes` as enabled. Restart the Hermes
   process after changing its plugin files or configuration so it reloads the
   directory plugin.

This copy-to-`$HERMES_HOME/plugins/` workflow is the Hermes directory-plugin
installation mechanism. It does not use `pip install` or `hermes plugins
install` because this source tree is already a directory plugin.

## Keep local paths and configuration private

The plugin has no private-path setting and no deployment configuration file.
It invokes the local `swamp` executable with a fixed, read-only command set.
When a tool call omits `repository_path`, the Swamp CLI inherits Hermes's
current working directory. A caller may instead supply `repository_path` for
one tool call; it must be an existing directory.

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
- `swamp_workflow_search` performs the fixed read-only `swamp workflow search
  --json` query.

For each tool, confirm that its returned JSON has `"ok": true` and that the
returned data is appropriate evidence for the local repository. If the target
is not Hermes's current working directory, invoke the tool with its private
`repository_path` at runtime rather than recording that path here. Treat the
result data as local operational evidence: review it privately and do not copy
it into issues, commits, tests, or public documentation.

If discovery fails, run the following in the same private environment that
will start Hermes, then check that the directory layout and enabled name are
correct:

```bash
HERMES_PLUGINS_DEBUG=1 hermes plugins list
```
