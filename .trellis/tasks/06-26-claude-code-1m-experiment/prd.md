# Claude Code 1M Routing Experiment

## Goal

Create an isolated Claude Code launcher experiment that tries to make the local
client recognize the MaaS-routed custom model as a 1M-context model, without
modifying or replacing the current working `claude-maas.ps1` / `.bat` flow.

## What I already know

* The current launcher calls `claude --model astron-code-latest`.
* Claude Code 2.1.187 is currently showing a 200K context window in the UI.
* Local state already contains `tengu_hawthorn_window = 200000`.
* Local state only shows an explicit `[1m]` capability marker for a known
  built-in model cache entry, not for `astron-code-latest`.
* The user wants the smallest possible experiment first, not a destructive
  change to the existing launcher chain.

## Assumptions

* Claude Code may use model-name recognition and/or Anthropic default model env
  vars when deciding whether a model is eligible for a 1M window.
* A separate experiment launcher is the safest first step because it preserves
  the current working path and makes rollback trivial.

## Open Questions

* None blocking for the first experiment.

## Requirements

* Add an isolated PowerShell experiment launcher for MaaS.
* Add an isolated batch experiment launcher for MaaS.
* Preserve the current MaaS base URL, API key, and existing traffic/caching env
  settings from the current launcher.
* Try a 1M-tagged model name and matching default-model env vars in the
  experiment launcher.
* Do not modify the existing `claude-maas.ps1` or `claude-maas.bat`.
* Provide a lightweight self-check path so the user can verify the experiment
  launcher starts correctly.

## Acceptance Criteria

* [ ] New experiment launcher files exist and do not replace the existing
      launcher files.
* [ ] The PowerShell launcher is syntactically valid and can run `--version`.
* [ ] The batch launcher is syntactically valid and can run `--version`.
* [ ] The experiment launcher clearly targets a 1M-labeled model variant.

## Definition of Done

* The experiment files are added with scoped comments where useful.
* The current launcher flow remains untouched.
* Basic invocation verification is completed and reported.

## Technical Approach

Create parallel launchers that keep the current MaaS endpoint and auth values,
but switch the requested model name to a `[1m]`-suffixed variant and export the
Anthropic default-model env vars so the client sees a consistent model identity
across primary, subagent, and role-based fallbacks.

## Out of Scope

* Replacing the current default MaaS launcher.
* Editing Codex `config.toml`.
* Reverse-engineering the full closed-source Claude Code client logic.

## Technical Notes

* Source launchers inspected:
  * `C:\Users\Administrator\claude-maas.ps1`
  * `C:\Users\Administrator\claude-maas.bat`
* Client version inspected: `claude --version` -> `2.1.187`
* Local state evidence inspected:
  * `C:\Users\Administrator\.claude.json`
