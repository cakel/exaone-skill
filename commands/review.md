---
description: Reinforce a code review with K-EXAONE 2.5 (Claude reviews first, EXAONE adds/disputes; PASS/FAIL gate)
argument-hint: '[--no-prior] [--effort low|medium|high|max] [--scope <path>] [focus text]'
disable-model-invocation: true
---

Run an EXAONE-reinforced code review of the current branch diff, following the
`exaone-skill` workflow in `${CLAUDE_PLUGIN_ROOT}/SKILL.md` (read it first).

Arguments: `$ARGUMENTS`

1. Pre-flight (SKILL Step 1).
2. Parse arguments: `--no-prior` (skip Claude's own first pass), `--effort X`,
   `--max-tokens N` (pass through as EXTRA flags), `--scope <path>`, rest = focus text.
3. Unless `--no-prior`: do your own review of the diff and write `prior.md` to a temp dir (SKILL Step 2).
4. Spawn the Haiku runner with MODE=`review` (SKILL Step 3).
5. Read OUT verbatim, handle EXIT, merge findings (SKILL Step 4). If EXAONE fails (exit 3/4/6/7),
   do not wait or retry: deliver your own review with the one-line "EXAONE 보강 실패" notice (fail-soft).

Review-only: do not edit code unless the user approves fixes from the merged list.
