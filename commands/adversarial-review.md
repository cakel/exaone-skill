---
description: Ask K-EXAONE 2.5 to challenge the design/assumptions of the current diff
argument-hint: '[--effort low|medium|high|max] [--scope <path>] [focus text]'
disable-model-invocation: true
---

Follow `${CLAUDE_PLUGIN_ROOT}/SKILL.md` with MODE=`adversarial-review`.
Arguments: `$ARGUMENTS` (`--effort`, `--max-tokens`, `--scope`, rest = attack focus).
Claude's prior review is optional here (include it if you already have one in this session).
Read OUT verbatim, surface the `BLOCKING QUESTION:` line, then give your own assessment of each challenge.
