---
name: exaone-skill
description: |
  K-EXAONE 2.5 (LG AI Research, api.exaone.ai) as a second-opinion reviewer from a
  different model family. USE AS A SUPPLEMENT to Claude's own work: Claude reviews first,
  then EXAONE is called (via a Haiku runner) to find what Claude missed and dispute what
  looks wrong. Modes: review (diff review, PASS/FAIL gate), adversarial-review (design
  challenge), consult (ask anything). Trigger ONLY when the user names EXAONE explicitly:
  "exaone", "엑사원", "exaone review", "exaone 리뷰", "exaone 으로 보강", "ask exaone",
  "exaone 의견", "exaone 한테 물어봐". Code is sent to an external API (api.exaone.ai),
  so do NOT trigger on generic "second opinion"/"추가 검토" phrases. Requires EXAONE_API_KEY.
  NOT the same as Exacode (exacode-skill, LG intranet): EXAONE and Exacode are
  separate APIs with separate keys — never route an exaone request to exacode-skill or
  an exacode request here.
allowed-tools:
  - Bash
  - Read
  - Glob
  - Grep
  - AskUserQuestion
  - Agent
---

# /exaone-skill — K-EXAONE 2.5 second opinion

Calls K-EXAONE 2.5 through its OpenAI-compatible API to reinforce a code review.
Script paths use `${CLAUDE_PLUGIN_ROOT}`; Claude Code substitutes the absolute plugin
root in this text, so use them as shown (do not add a `:-` default).

| Item | Value |
|---|---|
| Endpoint | `POST https://api.exaone.ai/v1/chat/completions` |
| Model | `k-exaone_v2.5` (text only, 524,288-token context incl. output) |
| Reasoning | always on; `reasoning_effort` default **medium** (override: `--effort`, env/`.env` `EXAONE_REASONING_EFFORT`) |
| max_tokens | default 32768, **includes reasoning tokens** (`--max-tokens`, `EXAONE_MAX_TOKENS`) |
| Key | `EXAONE_API_KEY` env, else `~/.exaone-skill/.env` |
| Busy-429 retry | `EXAONE_BUSY_WAIT` (default 5s) × `EXAONE_BUSY_RETRIES` (default 5); the client retries itself — do not add retries on top |

**Data policy:** the diff and full changed files leave the machine to api.exaone.ai.
Only run when the user asked for EXAONE by name. Never send `.env`, keys, or secrets.

## Dispatch

Any mention of "exaone"/"엑사원" routes through this skill — never hand-write curl/requests
calls to the API.

**EXAONE ≠ Exacode.** They are different services and must never be mixed:

| | EXAONE (this skill) | Exacode (exacode-skill) |
|---|---|---|
| Endpoint | `https://api.exaone.ai/v1` (external, LG AI Research) | LG intranet endpoint (not this plugin's concern) |
| Model | `k-exaone_v2.5` | `Chat-EXACODE-A` / `Chat-EXACODE-Think` |
| Key / config | `EXAONE_API_KEY`, `~/.exaone-skill/.env` | `EXACODE_*`, `~/.exacode-skill/.env` |

If EXAONE fails, do NOT fall back to Exacode (or any other model) on your own; report the
failure (fail-soft below) and let the user decide. If a request mentions both, run each
skill separately and label every result with its source.

| Request | Who runs it |
|---|---|
| review / adversarial-review | **Haiku runner** (default) |
| consult with attached files | Haiku runner |
| short consult (no files) | main agent, one direct Bash call |
| setup | main agent only (needs the user) |

User opt-out of the runner: "직접", "inline", `--inline` → run the same script yourself.

## Step 1 — Pre-flight

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" --show
```
Exit 2 → no key. Tell the user to run `! python "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" --key --prompt`
(hidden input), or the repo's `setup.ps1` / `setup.sh`. Never put the key on a command line.

## Step 2 — Claude's own review first (reinforcement mode)

The purpose of this skill is to **strengthen** a review. When the user asks for an
EXAONE-reinforced review and you (Claude) have not reviewed yet, do your own review of the
diff first and write the findings to a file `prior.md` (terse: `[P1|P2] file:line — issue`).
If the user only wants EXAONE's independent view ("exaone 단독", `--no-prior`), skip it.

## Step 3 — Haiku runner

Main agent decides every parameter: MODE, BASE branch, SCOPE (pathspec, default empty),
focus text, PRIOR file (absolute path or empty), EXTRA flags (`--effort X`, `--max-tokens N`).

BASE detection:
```bash
BASE=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/origin/||')
[ -z "$BASE" ] && git rev-parse --verify origin/main >/dev/null 2>&1 && BASE=origin/main
[ -z "$BASE" ] && git rev-parse --verify main >/dev/null 2>&1 && BASE=main
[ -z "$BASE" ] && BASE=HEAD   # uncommitted-only review
```
When BASE is `HEAD`, replace `"<BASE>"...HEAD` with `HEAD` in the template (working-tree diff).

Call `Agent` with `subagent_type: "general-purpose"`, `model: "haiku"`,
`description: "EXAONE <mode> runner"`, and this prompt (fill `<…>`):

````text
You are a mechanical runner. Run the bash script below EXACTLY ONCE with the Bash tool
(timeout: 600000), then reply with ONLY the receipt. Do NOT edit/create/delete repo files,
do NOT summarize or judge the model output, do NOT retry or change flags.

```bash
set -f
cd "<REPO_ABS_PATH>"
W=$(mktemp -d)
cat > "$W/focus.txt" <<'FOCUS_EOF'
<FOCUS_TEXT_OR_EMPTY>
FOCUS_EOF
PRIOR="<PRIOR_ABS_PATH_OR_EMPTY>"
{
  echo "Repository: $(basename "$(git rev-parse --show-toplevel)")"
  echo "Branch: $(git rev-parse --abbrev-ref HEAD)  Base: <BASE>"
  git diff --stat "<BASE>"...HEAD -- <SCOPE>
  echo '```diff'; git diff "<BASE>"...HEAD -- <SCOPE>; echo '```'
  git -c core.quotepath=off diff -z --name-only "<BASE>"...HEAD -- <SCOPE> |
    while IFS= read -r -d '' f; do
      [ -f "$f" ] || continue
      printf '\n===== FILE: %s =====\n' "$f"; cat "$f"
    done
  if [ -n "$PRIOR" ] && [ -f "$PRIOR" ]; then
    printf '\n## Prior review (Claude)\n'; cat "$PRIOR"
  fi
  if [ -n "$(tr -d '[:space:]' < "$W/focus.txt")" ]; then
    printf '\nReviewer focus:\n'; cat "$W/focus.txt"
  fi
} > "$W/prompt.txt"
python "<CLIENT_ABS_PATH>" --mode <MODE> <EXTRA_FLAGS> --stdin \
  < "$W/prompt.txt" > "$W/out.txt" 2> "$W/err.txt"
EC=$?
command -v cygpath >/dev/null && W=$(cygpath -m "$W")
echo "EXIT: $EC"; echo "OUT: $W/out.txt ($(wc -c < "$W/out.txt") bytes)"
echo "STDERR:"; head -n 40 "$W/err.txt"
```

Receipt (copy the printed lines, nothing else):
EXIT: <n>
OUT: <path> (<bytes> bytes)
STDERR:
<lines>
````

`<CLIENT_ABS_PATH>` = `${CLAUDE_PLUGIN_ROOT}/scripts/exaone_client.py`.

## Step 4 — After the runner

1. `Read` the OUT file yourself and show it verbatim under "EXAONE said:". Never use the
   runner's prose as the model output. Then `rm -rf` that temp dir (holds source code).
2. Exit codes:
   | EXIT | Meaning | Action |
   |---|---|---|
   | 0 | ok | triage (item 4) |
   | 2 | no key / bad config | Step 1 |
   | 3 | HTTP error (401/403 key, 429 daily quota, other) | **fail-soft** |
   | 4 | network / stream closed by server / stalled | **fail-soft** |
   | 5 | input too large | split by `--scope` into chunks, run **sequentially**; a chunk that fails → fail-soft for that chunk |
   | 6 | truncated / empty answer | **fail-soft** |
   | 7 | service busy (429 "busy" after `EXAONE_BUSY_RETRIES` retries, `EXAONE_BUSY_WAIT`s apart; default 5×5s) | **fail-soft** |
   | any other non-zero (e.g. 1 = crash) | unexpected | **fail-soft** |

   **Fail-soft (EXAONE is a supplement, never a blocker):** do NOT auto-retry and do NOT
   wait. Deliver Claude's own review as the final result, and add one line at the top:
   `> EXAONE 보강 실패 (exit <n>): <the [ERROR] line from STDERR, incl. request_id> — Claude 단독 리뷰입니다. 나중에 /exaone-skill:review 로 재시도할 수 있습니다.`
   Retry only if the user asks. (Observed 2026-11-12: busy-429 persisted ~15 min across 4
   single-request bursts; at effort=high the server closed 2 of 3 streams without a
   terminator, at ~251s and ~334s after accept — no fixed limit identified.)
3. Surface `[WARN]` lines and the `[INFO] done …` line (time, tokens, rate-limit remaining).
4. **Merge into the review** (this is the deliverable):
   - New findings EXAONE found that Claude missed → verify each by reading the code
     (`Read` file:line). Classify: agree-and-fix / agree-but-defer / disagree (with reason).
   - `[DISPUTE]` on Claude's findings → re-check; keep, revise, or drop with a reason.
   - Report the final merged list, marking source: (Claude) / (EXAONE) / (both).
   - Do not apply fixes unless the user asks.

## Consult (short, no files)

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/exaone_client.py" --mode consult --stdin <<'Q_EOF'
<question>
Q_EOF
```

## Flags

`--effort low|medium|high|max` (all four accepted by the API, verified 2026-11-12; `high`
had 2 of 3 streams closed by the server without a terminator) · `--max-tokens N` · `--no-stream` · `--show-reasoning`
(prints `reasoning_content` to stderr).
