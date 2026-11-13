---
description: Register or inspect the EXAONE API key / default reasoning effort (~/.exaone-skill/.env)
argument-hint: '[--show | --set-effort low|medium|high|max | --set-max-tokens N | --set-busy-wait S | --set-busy-retries N]'
disable-model-invocation: true
---

Arguments: `$ARGUMENTS`

- `--show` or empty: `python "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" --show` and show the output.
- `--set-effort X` / `--set-max-tokens N` / `--set-busy-wait S` / `--set-busy-retries N`: pass through to the same script.
- Registering a key: never put the key on a command line. Ask the user to run (hidden prompt):
  `! python "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" --key --prompt`
  If the user pastes the key in chat anyway, warn that it is now in the transcript, then
  store it via stdin: `python "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" --key <<<"<key>"`.
