---
description: Ask K-EXAONE 2.5 a question (second opinion)
argument-hint: '[--effort low|medium|high|max] <question>'
disable-model-invocation: true
---

Follow the "Consult" section of `${CLAUDE_PLUGIN_ROOT}/SKILL.md`.
Question/arguments: `$ARGUMENTS`

Short question with no files → run the client directly (one Bash call, question via heredoc on stdin).
If repo files must be attached, use the Haiku runner with MODE=`consult` and `===== FILE: <path> =====` blocks.
Show the answer verbatim under "EXAONE said:", then add your own view where you disagree.
