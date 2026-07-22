# Lock Down Hermes to Swamp — A Reusable Playbook

Use this two ways:

- **As a prompt.** Hand the whole thing to your own coding agent (Claude Code or
  similar) with access to your Hermes deployment, and let it execute the
  ordered steps, adapting the placeholders to your real environment.
- **As a checklist.** Work through it yourself by hand, step by step.

It's written generically on purpose — it assumes nothing about your hosts,
paths, or identities. Replace every `<placeholder>` with your own values as you
go, and keep those real values *out* of anything you intend to publish (a repo,
a blog post, an issue tracker).

---

## The goal

Make a self-hosted Hermes agent's real-world capability deterministic and
auditable by routing it through [Swamp](https://github.com/systeminit/swamp) —
a CLI/runtime with named models, workflows, and extensions — instead of through
Hermes's own raw shell, file, code-execution, computer-control, and broad-web
tools. When you're done, the agent should not merely be *told* not to run
arbitrary shell commands; it should not have a shell tool to reach for at all.

This is not "give the agent more guardrails in its prompt." A prompt instruction
is not a control — assume the agent will eventually be steered around any
purely textual restriction, by a bad actor, a bug, or its own improvisation.
The lockdown has to happen at the tool-availability layer.

---

## Step 1 — Disable the raw toolsets

In the Hermes config the *running* gateway actually reads (see the gotcha in
Step 5 before you trust any file you're looking at):

```yaml
agent:
  disabled_toolsets:
    - terminal
    - file
    - code_execution
    - computer_use
    - web
```

Decide deliberately, and in writing somewhere you'll see again, whether you're
keeping anything back. A narrow `browser` toolset for reading public pages is a
common compromise — just know that a browser toolset that can open `file://`
URLs and run page JavaScript is a real exfiltration path (it can read local
files and phone them out via `window.location` or similar). If you keep it,
track it explicitly as a known, temporary hole with a planned replacement
(a purpose-built fetch capability with no local file access), not as a
permanent exception.

## Step 2 — Get a Swamp-first plugin in place

You need a Hermes **directory plugin** — a small Python package that registers
a closed set of tool names backed by calls to the `swamp` CLI. You can write
your own (it doesn't need to be large — the reference implementation for this
pattern is under a dozen tool handlers) or adapt an existing one. At minimum it
should provide:

- read-only discovery tools (search models, search workflows, search the
  extension registry);
- scoped authoring (create/scaffold a definition, and *one* narrowly-scoped
  "write definition content" tool — path-restricted to inside a known
  repository, restricted to known Swamp definition locations, and followed
  immediately by validation with revert-on-failure);
- execution (run a model method, run a workflow, pull an extension) and
  publishing (push an extension) — publishing should require an explicit
  `confirmed: true` argument that only gets set after real human confirmation,
  since publishing to a public registry is usually irreversible;
- if your workflows can carry a live cron schedule, make *activating* that
  schedule a separate, also-confirmation-gated tool from merely authoring the
  workflow file. Writing a workflow definition should never, by itself, make it
  start running unattended.

Every tool handler should map to a **fixed CLI subcommand prefix** with a
**declared, bounded count of caller-supplied positional arguments**, each
passed as a discrete `argv` element — never built by interpolating a value into
a shell string. This is what keeps a "the agent can pass a model name" tool
from becoming a command-injection vector.

Install it:

```bash
mkdir -p "$HERMES_HOME/plugins"
# either a straight copy...
cp -R ./your_plugin_package "$HERMES_HOME/plugins/your_plugin_package"
# ...or a symlink into a checkout you control, so `git pull` is your update path
ln -s /path/to/your/checkout/your_plugin_package \
      "$HERMES_HOME/plugins/your_plugin_package"
```

Hermes discovers any directory under `$HERMES_HOME/plugins/` that contains both
`plugin.yaml` and `__init__.py`. The registry name comes from `plugin.yaml`'s
`name:` field, not the directory name.

## Step 3 — Enable it in config

Two separate opt-ins, both required, neither implied by the other:

```yaml
plugins:
  enabled:
    - your_plugin_manifest_name   # must match plugin.yaml's name: field

platform_toolsets:
  discord:                # or whichever platform(s) you use
    - hermes-discord        # keep whatever built-in toolset entries you already have
    - your_plugin_toolset   # append — do not replace the list
```

A missing `plugins:` key means *no plugins enabled*, not "all enabled by
default." And enabling a plugin globally does not make its tools visible on any
given chat platform until its toolset name is also appended under
`platform_toolsets.<platform>`.

## Step 4 — Stand up the Swamp models/extensions your agent actually needs

The plugin only gives the agent generic verbs. The real capability — "operate
on a git repository," "check a device," "sync a note" — has to exist as Swamp
models/extensions in a Swamp repository the CLI operates against. For each
capability you need:

1. **Search before you build.** Check local model types (`swamp model type
   search <query>`) and the community extension registry (`swamp extension
   search <query>`) first. If something already fits, pull it (`swamp extension
   pull <package>`) instead of writing your own. Vet what you pull the way
   you'd vet any dependency — test coverage, license, whether it builds
   `argv` safely instead of shelling out to formatted strings.
2. **Only author custom when nothing fits.** If you're giving the agent
   filesystem write access inside a git checkout (a very common need once raw
   `file` is off), write a narrow, purpose-built model: writes constrained to
   inside a known repository root (checked against the fully-resolved real
   path, not just a string prefix, so a symlink can't smuggle you outside it),
   with no broader filesystem reach.
3. **Know the difference between a standalone model (`export const model`) and
   an extension of an existing type (`export const extension`).** Both are
   legitimate, but they're not interchangeable, and some toolchains have sharp
   edges around a standalone-model file living in a directory convention meant
   for extensions (e.g. an auto-loader that assumes everything there is an
   extension and hard-fails on anything that isn't). If your bundler/registry
   shares a build artifact across models, understand what happens if one model
   in that shared build is malformed — you do not want one bad addition to be
   able to take down every other model's availability. Test that before you
   rely on it, in a way that lets you revert quickly if you're wrong.

## Step 5 — Watch for these gotchas

**The `HERMES_HOME` decoy.** If unset, Hermes's CLI falls back to
`Path.home()/".hermes"`. In a container where the service account's `$HOME`
happens to equal your intended `HERMES_HOME`, that fallback resolves to a
*second, parallel config+plugins tree* that the CLI will happily read from and
write to — and every CLI command will report a coherent, entirely wrong picture
of a deployment the running gateway never touches. Before trusting *any* `hermes
plugins list` / `hermes tools list` output, confirm `HERMES_HOME` in your
current shell matches what the actual running gateway process has in its
environment (read it out of the live process, e.g.
`tr '\0' '\n' < /proc/<gateway-pid>/environ | grep HERMES_HOME` on Linux — don't
assume a shell profile or a doc is still accurate). If a plugin doesn't appear
at all, compare the two candidate homes directly (`ls` both `plugins/`
directories) before assuming anything is wrong with the plugin's code.
`HERMES_PLUGINS_DEBUG=1 hermes plugins list` is worth running early — plugin
loading is otherwise silent at normal log levels, so a plugin that failed to
import looks identical to one that was never found.

**Surface real errors — don't swallow them.** If your plugin's CLI adapter
collapses a real, actionable failure message (an unknown model name, a schema
violation) down to a generic error code before returning it to the agent, a
correctly-working fail-closed safety mechanism will look indistinguishable from
broken infrastructure. Preserve the structured error body when the underlying
tool provides one; only withhold genuinely sensitive detail (raw stderr can
carry absolute local paths or private identifiers — filter that specifically,
don't collapse the whole result to an opaque code as a side effect of trying to
be safe).

**The shared-bundle/registry hazard.** If your Swamp runtime builds a shared
artifact across multiple local models, one malformed model can take the whole
registry down — and because that failure is silent until something tries to
use it, you can discover it only when a completely unrelated, previously
working capability starts failing too. Know this is possible before you add a
new model to a shared hub, and have a fast way to isolate/remove a bad addition.

**Base-image / init-system changes.** A base image bump that looks like a
routine version pin change can silently change the container's startup
contract (e.g. swapping which process supervises the main service). Any custom
entrypoint or extra long-running service (like an SSH daemon) layered on top of
the base needs to be re-verified against the *new* contract, not assumed to
still compose. Stage any such upgrade: build the new image, boot-test it in a
disposable container against throwaway state, and only cut your real deployment
over once that passes — with the previous image tagged for instant rollback and
your persistent state volume left untouched throughout, so rollback is a retag,
not a data restore.

**Keep deployment-specific inputs out of anything published.** Hosts, absolute
paths, device identifiers, schedules, and credentials belong in your private
deployment configuration — environment variables, a private config file, a
caller-supplied argument at call time — never hard-coded into a model,
extension, or plugin you intend to publish or open-source. A published
extension should accept generic, caller-supplied inputs and contain no trace of
where or how you actually run it.

## Step 6 — Verify for real

Do not stop at CLI introspection. In this kind of project, `hermes plugins
list`, `hermes tools list`, and even a passing automated test suite have all
been observed green while the live system was completely broken — a decoy
config tree, a swallowed error, a poisoned shared bundle, and a parser that
misread multi-document output all passed every offline check and only showed up
in a real conversation.

1. Confirm the **running gateway's** actual config and environment (not a file
   you assume matches it — see the `HERMES_HOME` gotcha above).
2. Restart the gateway so it picks up your changes, then re-run `hermes plugins
   list` / `hermes tools list --platform <platform>` against the confirmed-correct
   home, and check your plugin's toolset appears and the raw toolsets you
   disabled do not.
3. Send a real message through the real chat platform asking for an ordinary
   task the agent should now do via Swamp (e.g. "find the model that handles
   X and run it"). Confirm it actually uses the Swamp-backed tool, not
   something else.
4. Send a second real message asking for a capability you just removed (e.g.
   "list the files in the root directory," "run `ls /`"). Confirm the agent
   responds that it has no such tool — not that it's "not allowed to," which
   would indicate a policy telling it no rather than the capability actually
   being gone. Those are different security postures and only a live prompt
   distinguishes them.
5. Only once both of those match your design is the lockdown actually verified.
   Everything before this step is a claim; this step is proof.
