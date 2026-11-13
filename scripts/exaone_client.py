#!/usr/bin/env python3
"""EXAONE (K-EXAONE 2.5) client for the exaone-skill Claude Code plugin.

API: https://docs.exaone.ai/ko/docs/k-exaone-2.5  (OpenAI-compatible chat/completions)

Usage:
  python exaone_client.py --mode review|adversarial-review|consult --stdin < prompt.txt
  python exaone_client.py --mode consult "question text"

Options:
  --effort low|medium|high|max   reasoning_effort (default: $EXAONE_REASONING_EFFORT or "medium")
  --max-tokens N                 includes reasoning tokens (default: $EXAONE_MAX_TOKENS or 32768)
  --no-stream                    use blocking JSON instead of SSE
  --show-reasoning               also print reasoning_content to stderr

Key resolution: $EXAONE_API_KEY, then ~/.exaone-skill/.env (EXAONE_API_KEY=...).

Exit codes:
  0 success
  2 missing API key / config error
  3 HTTP error (incl. 401/403/429 after retries)
  4 network / unreachable
  5 input too large for the context window (estimate or HTTP 400 from the API)
  6 output truncated (finish_reason=length) or empty answer
  7 service busy (429 "too many concurrent requests" after all busy retries) -- server-side

Busy-429 retry: EXAONE_BUSY_WAIT (default 5s, fixed interval), EXAONE_BUSY_RETRIES (default 5).
"""
import argparse
import http.client
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

BASE_URL = os.environ.get("EXAONE_BASE_URL", "https://api.exaone.ai/v1").rstrip("/")
MODEL = os.environ.get("EXAONE_MODEL", "k-exaone_v2.5")
CONTEXT_TOKENS = 524_288           # docs: input + max_tokens <= 524,288
DEFAULT_MAX_TOKENS = 32_768        # includes reasoning tokens (docs)
DEFAULT_EFFORT = "medium"     # effort sweep 2026-11-12: see README "effort 측정"
EFFORTS = ("low", "medium", "high", "max")  # docs list low/high/max; agent page also lists medium
IDLE_TIMEOUT = int(os.environ.get("EXAONE_IDLE_TIMEOUT", "180"))  # socket read timeout (s)
PROGRESS_EVERY = 30               # seconds between [PROGRESS] lines while streaming
RETRY_STATUSES = {429, 500, 502, 503, 504}
RETRY_MAX_ATTEMPTS = 4
RETRY_BACKOFFS = [2, 5, 10]
# 429 "service is busy, too many concurrent requests(N)" is server-wide congestion, not our
# quota (2026-11-12: 4 single-request bursts all failed over ~15 min, even with 1 request in flight).
# Fixed-interval retry (user setting 2026-11-13: wait 5s, up to 5 retries), configurable via
# EXAONE_BUSY_WAIT / EXAONE_BUSY_RETRIES (env or ~/.exaone-skill/.env). When exhausted, exit 7
# so the caller can continue without EXAONE (fail-soft).
DEFAULT_BUSY_WAIT = 5      # seconds between retries on busy-429
DEFAULT_BUSY_RETRIES = 5   # retries after the first attempt
MAX_RETRY_WAIT = 60                # never sleep longer than this on retry-after

CONFIG_DIR = Path.home() / ".exaone-skill"
ENV_FILE = CONFIG_DIR / ".env"

_GROUNDING = (
    "\n\nStay grounded: every finding MUST cite a concrete file:line and quote the exact code "
    "it is about. Do NOT invent issues that are not present in the provided diff/text. If you "
    "cannot quote the code, do not raise the finding. Prefer fewer high-signal findings over "
    "many speculative ones.\n\n"
    "Output discipline (STRICT):\n"
    "- State each distinct finding EXACTLY ONCE. One issue = one entry.\n"
    "- Emit only final conclusions; no narration of your analysis in the answer.\n"
    "- Answer in the same language as the reviewer focus / question when one is given; "
    "otherwise Korean."
)

_PRIOR = (
    "\n\nIf the input contains a section headed 'Prior review (Claude)', treat it as another "
    "reviewer's findings. Do NOT restate them. Instead: (1) list issues that review MISSED, "
    "(2) mark any of its findings you believe are WRONG with [DISPUTE] and a one-line reason. "
    "Agreement needs no comment."
)

SYSTEM_PROMPTS = {
    "review": (
        "You are a senior staff engineer doing an independent code review of a git diff.\n"
        "Be direct, terse, technically precise. Catch what others miss.\n\n"
        "Output rules:\n"
        "- Group findings by file. Tag each [P1] (must-fix: bugs, data loss, security, broken "
        "contracts) or [P2] (should-fix: smells, minor risks).\n"
        "- Quote the offending code with file:line.\n"
        "- One sentence on WHY it matters (failure mode / user impact).\n"
        "- A concrete fix (one to a few lines).\n"
        "- No praise, no summary of unchanged code, no hedging.\n"
        "- You MUST end with exactly one line and NOTHING after it:\n"
        "      GATE: PASS   or   GATE: FAIL\n"
        "  PASS when there are no [P1] findings, FAIL otherwise. Mandatory even if you found "
        "nothing."
        + _PRIOR + _GROUNDING
    ),
    "adversarial-review": (
        "You are an adversarial senior architect reviewing a git diff. Do not nitpick syntax; "
        "question whether the approach, design and tradeoffs are correct.\n"
        "Attack along: simpler/safer alternatives; assumptions that break under load, edge "
        "cases, concurrency, partial failure, hostile input; how this fails in production six "
        "months from now; what the author did NOT change but should have.\n"
        "Be specific, quote code, name alternatives. You MUST end with exactly one line and "
        "NOTHING after it, prefixed with: BLOCKING QUESTION: "
        + _PRIOR + _GROUNDING
    ),
    "consult": (
        "You are a senior staff engineer giving a second opinion. Direct, terse, technically "
        "precise. Lead with the answer. Quote files/lines when relevant. If the question is "
        "ambiguous, state your interpretation in one line and answer it. No filler."
        + _GROUNDING
    ),
}
TERMINATORS = {"review": re.compile(r"GATE:\s*(PASS|FAIL)\s*$"),
               "adversarial-review": re.compile(r"BLOCKING QUESTION:.*$", re.S)}


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- config
def load_env_file(path: Path = ENV_FILE) -> dict:
    out = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return out


def resolve(var: str) -> Optional[str]:
    v = os.environ.get(var, "").strip()
    if v:
        return v
    v = load_env_file().get(var, "").strip()
    return v or None


def resolve_effort(cli: Optional[str]) -> str:
    eff = (cli or resolve("EXAONE_REASONING_EFFORT") or DEFAULT_EFFORT).strip().lower()
    if eff not in EFFORTS:
        log(f"[ERROR] invalid reasoning effort '{eff}' (allowed: {', '.join(EFFORTS)})")
        sys.exit(2)
    return eff


def _resolve_int(var: str, default: int, minimum: int = 0) -> int:
    v = resolve(var)
    if v is None:
        return default
    try:
        n = int(v)
    except ValueError:
        n = -1
    if n < minimum:
        log(f"[ERROR] {var} must be an integer >= {minimum}, got '{v}'")
        sys.exit(2)
    return n


def busy_schedule() -> list:
    """Waits (seconds) before each retry on a busy-429."""
    wait = _resolve_int("EXAONE_BUSY_WAIT", DEFAULT_BUSY_WAIT)
    retries = _resolve_int("EXAONE_BUSY_RETRIES", DEFAULT_BUSY_RETRIES)
    return [wait] * retries


def resolve_max_tokens(cli: Optional[int]) -> int:
    if cli:
        return cli
    v = resolve("EXAONE_MAX_TOKENS")
    try:
        return int(v) if v else DEFAULT_MAX_TOKENS
    except ValueError:
        log(f"[ERROR] EXAONE_MAX_TOKENS must be an integer, got '{v}'")
        sys.exit(2)


# ---------------------------------------------------------------- sizing
_CJK = re.compile(r"[가-힣ぁ-ゟ゠-ヿ一-鿿]")


def estimate_tokens(text: str) -> int:
    """Conservative token estimate (over-estimates on purpose).

    Plain code ~2.8 chars/token, CJK ~1.5 chars/token (rough; not measured on EXAONE's
    tokenizer). The API's own 400 is the authoritative limit; this only avoids a
    pointless round-trip for clearly oversize inputs.
    """
    cjk = len(_CJK.findall(text))
    return int(cjk / 1.5 + (len(text) - cjk) / 2.5) + 64


# ---------------------------------------------------------------- http
def _rate_headers(headers) -> str:
    if headers is None:
        return ""
    parts = []
    for w in ("second", "minute", "day"):
        lim = headers.get(f"x-{w}-rate-limit")
        rem = headers.get(f"x-{w}-rate-limit-remaining")
        if lim is not None or rem is not None:
            parts.append(f"{w}={rem}/{lim}")
    rid = headers.get("x-request-id")
    if rid:
        parts.append(f"request_id={rid}")
    return " ".join(parts)


def _retry_wait(headers, attempt: int) -> float:
    if headers is not None:
        ms = headers.get("retry-after-ms")
        s = headers.get("retry-after")
        try:
            if ms is not None:
                return min(float(ms) / 1000.0 + 0.1, MAX_RETRY_WAIT)
            if s is not None:
                return min(float(s) + 0.1, MAX_RETRY_WAIT)
        except ValueError:
            pass
    return RETRY_BACKOFFS[min(attempt, len(RETRY_BACKOFFS) - 1)]


def _error_text(body: str) -> str:
    try:
        j = json.loads(body)
    except Exception:
        return body.strip()[:2000]
    if isinstance(j, dict):
        if "result_code" in j or "description" in j:
            return f"result_code={j.get('result_code')} description={j.get('description')}"
        err = j.get("error")
        if isinstance(err, dict):
            return f"{err.get('type') or err.get('code')}: {err.get('message')}"
        if err:
            return str(err)
    return body.strip()[:2000]


def _is_context_error(status: int, text: str) -> bool:
    t = text.lower()
    return status in (400, 413) and any(k in t for k in ("context", "max_tokens", "too long",
                                                           "maximum", "length", "token"))


def _day_exhausted(headers) -> bool:
    return headers is not None and headers.get("x-day-rate-limit-remaining") == "0"


def post(payload: dict, api_key: str, stream: bool):
    """POST with retry. Returns (response_object) for the caller to read. Exits on failure."""
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "exaone-skill/0.1.6",
    }
    if stream:
        headers["Accept"] = "text/event-stream"
    url = f"{BASE_URL}/chat/completions"
    busy_attempt = 0
    busy_waits = busy_schedule()
    attempt = -1
    while True:
        attempt += 1
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            return urllib.request.urlopen(req, timeout=IDLE_TIMEOUT)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            text = _error_text(body)
            rh = _rate_headers(e.headers)
            if _is_context_error(e.code, text):
                log(f"[ERROR] HTTP {e.code}: input + max_tokens exceeds context ({text})")
                sys.exit(5)
            if e.code == 429 and _day_exhausted(e.headers):
                log(f"[ERROR] HTTP 429: daily quota exhausted. {rh}")
                sys.exit(3)
            busy = e.code == 429 and "busy" in text.lower()
            if busy and busy_attempt < len(busy_waits):
                wait = busy_waits[busy_attempt]
                busy_attempt += 1
                log(f"[WARN] server busy retry {busy_attempt}/{len(busy_waits)}: {text} {rh} "
                    f"retry-after={e.headers.get('retry-after')} "
                    f"retry-after-ms={e.headers.get('retry-after-ms')} -- retry in {wait}s")
                time.sleep(wait)
                continue
            if e.code in RETRY_STATUSES and not busy and attempt < RETRY_MAX_ATTEMPTS - 1:
                wait = _retry_wait(e.headers, attempt)
                log(f"[WARN] attempt {attempt + 1}/{RETRY_MAX_ATTEMPTS}: HTTP {e.code} {text} "
                    f"{rh} -- retry in {wait:.1f}s")
                time.sleep(wait)
                continue
            if busy:
                log(f"[ERROR] EXAONE unavailable: server busy after {len(busy_waits)} retries "
                    f"(~{sum(busy_waits)}s waited; EXAONE_BUSY_RETRIES/EXAONE_BUSY_WAIT): {text} {rh}")
                log(f"[DEBUG] last 429 raw body: {body.strip()[:1000]}")
                sys.exit(7)
            log(f"[ERROR] HTTP {e.code}: {text} {rh}")
            log(f"[DEBUG] raw body: {body.strip()[:1000]}")
            if e.code in (401, 403):
                log("[HINT] Check the key: python scripts/setup.py --show  (re-register with --key)")
            sys.exit(3)
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
            reason = getattr(e, "reason", e)
            if isinstance(e, (socket.timeout, TimeoutError)) or isinstance(reason, (socket.timeout, TimeoutError)):
                log(f"[ERROR] no response headers within {IDLE_TIMEOUT}s (not retried: the request "
                    f"may still be consuming quota) ({url})")
                sys.exit(4)
            if attempt < RETRY_MAX_ATTEMPTS - 1:
                wait = RETRY_BACKOFFS[min(attempt, len(RETRY_BACKOFFS) - 1)]
                log(f"[WARN] attempt {attempt + 1}/{RETRY_MAX_ATTEMPTS}: network error {e} "
                    f"-- retry in {wait}s")
                time.sleep(wait)
                continue
            log(f"[ERROR] network: {e} ({url})")
            sys.exit(4)


def read_json(resp) -> dict:
    try:
        body = resp.read().decode("utf-8", "replace")
    except (http.client.HTTPException, socket.timeout, TimeoutError, OSError) as e:
        log(f"[ERROR] response read failed: {type(e).__name__}: {e}")
        sys.exit(4)
    try:
        j = json.loads(body)
    except json.JSONDecodeError:
        log(f"[ERROR] non-JSON response: {body[:500]}")
        sys.exit(3)
    if "choices" not in j:
        log(f"[ERROR] unexpected response: {_error_text(body)}")
        sys.exit(3)
    ch = (j.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    return {"content": msg.get("content") or "",
            "reasoning": msg.get("reasoning_content") or "",
            "finish_reason": ch.get("finish_reason"),
            "usage": j.get("usage")}


def read_sse(resp, t0: float, deadline: float) -> dict:
    content, reasoning = [], []
    finish, usage = None, None
    first = None
    saw_done = False
    last_report = time.time()
    try:
        for raw in resp:
            now = time.time()
            if first is None:
                first = now
                log(f"[PROGRESS] first byte after {now - t0:.1f}s")
            if now - last_report >= PROGRESS_EVERY:
                log(f"[PROGRESS] {now - t0:.0f}s reasoning={sum(map(len, reasoning))}ch "
                    f"content={sum(map(len, content))}ch")
                last_report = now
            if deadline and now - t0 > deadline:
                log(f"[ERROR] total deadline {deadline:.0f}s exceeded "
                    f"(reasoning={sum(map(len, reasoning))}ch content={sum(map(len, content))}ch)")
                sys.exit(4)
            line = raw.decode("utf-8", "replace").strip()
            r = _sse_line(line, content, reasoning)
            if r == "done":
                saw_done = True
                break
            if isinstance(r, dict):
                usage = r.get("usage") or usage
                finish = r.get("finish") or finish
    except http.client.HTTPException as e:  # e.g. IncompleteRead on a chunked stream cut
        log(f"[ERROR] stream closed by server mid-chunk ({type(e).__name__}) after "
            f"{time.time() - t0:.0f}s; reasoning={sum(map(len, reasoning))}ch "
            f"content={sum(map(len, content))}ch")
        sys.exit(4)
    except (socket.timeout, TimeoutError, OSError) as e:
        log(f"[ERROR] stream stalled: no bytes for {IDLE_TIMEOUT}s ({e}); "
            f"elapsed {time.time() - t0:.0f}s, first byte "
            f"{'never' if first is None else f'{first - t0:.1f}s'}, "
            f"reasoning={sum(map(len, reasoning))}ch content={sum(map(len, content))}ch")
        sys.exit(4)
    if not saw_done and finish is None:
        log(f"[ERROR] stream closed by server before completion (no finish_reason, no [DONE]) "
            f"after {time.time() - t0:.0f}s; reasoning={sum(map(len, reasoning))}ch "
            f"content={sum(map(len, content))}ch. Retry, or lower --effort.")
        sys.exit(4)
    return {"content": "".join(content), "reasoning": "".join(reasoning),
            "finish_reason": finish, "usage": usage,
            "ttft": None if first is None else first - t0}


def _sse_line(line: str, content: list, reasoning: list):
    """Parse one SSE line. Returns "done", a dict {usage, finish}, or None."""
    if not line.startswith("data:"):
        if line.startswith("{"):  # error object sent without SSE framing
            log(f"[ERROR] {_error_text(line)}")
            sys.exit(3)
        return None
    data = line[5:].strip()
    if data == "[DONE]":
        return "done"
    try:
        j = json.loads(data)
    except json.JSONDecodeError:
        return None
    if ("result_code" in j or "error" in j) and "choices" not in j:
        log(f"[ERROR] {_error_text(data)}")
        sys.exit(3)
    out = {"usage": j.get("usage"), "finish": None}
    for ch in j.get("choices") or []:
        d = ch.get("delta") or {}
        if d.get("content"):
            content.append(d["content"])
        if d.get("reasoning_content"):
            reasoning.append(d["reasoning_content"])
        if ch.get("finish_reason"):
            out["finish"] = ch["finish_reason"]
    return out


# ---------------------------------------------------------------- main
def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="EXAONE second-opinion client")
    p.add_argument("--mode", required=True, choices=list(SYSTEM_PROMPTS))
    p.add_argument("--stdin", action="store_true", help="read the prompt from stdin")
    p.add_argument("--effort", choices=EFFORTS)
    p.add_argument("--max-tokens", type=int)
    p.add_argument("--no-stream", action="store_true")
    p.add_argument("--show-reasoning", action="store_true")
    p.add_argument("--deadline", type=float, default=float(os.environ.get("EXAONE_DEADLINE", "0") or 0),
                   help="abort after N seconds total (0 = none)")
    p.add_argument("text", nargs="*")
    a = p.parse_args()

    if a.stdin:
        user = sys.stdin.buffer.read().decode("utf-8", "replace")
    else:
        user = " ".join(a.text)
    if not user.strip():
        log("[ERROR] empty prompt (pass text or --stdin)")
        sys.exit(2)

    key = resolve("EXAONE_API_KEY")
    if not key:
        log(f"[ERROR] EXAONE_API_KEY not set (env or {ENV_FILE}). Run setup.py --key")
        sys.exit(2)

    effort = resolve_effort(a.effort)
    max_tokens = resolve_max_tokens(a.max_tokens)
    system = SYSTEM_PROMPTS[a.mode]
    est = estimate_tokens(system) + estimate_tokens(user)
    if est + max_tokens > CONTEXT_TOKENS:
        log(f"[ERROR] input too large: ~{est} tokens (estimate) + max_tokens {max_tokens} "
            f"> {CONTEXT_TOKENS}. Split the input.")
        sys.exit(5)

    stream = not a.no_stream and resolve("EXAONE_STREAM") != "0"
    payload = {
        "model": MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "max_tokens": max_tokens,
        "reasoning_effort": effort,
        "stream": stream,
    }
    if stream:
        payload["stream_options"] = {"include_usage": True}

    log(f"[INFO] model={MODEL} mode={a.mode} effort={effort} max_tokens={max_tokens} "
        f"stream={stream} input~{est}tok ({len(user.encode('utf-8'))} bytes)")
    t_start = time.time()
    resp = post(payload, key, stream)
    rh = _rate_headers(resp.headers)
    t0 = time.time()  # timings below are from accept (excludes retry sleeps)
    log(f"[INFO] accepted after {t0 - t_start:.1f}s (incl. retries) {rh}")
    with resp:
        r = read_sse(resp, t0, a.deadline) if stream else read_json(resp)
    dt = time.time() - t0

    u = r["usage"] or {}
    log(f"[INFO] done in {dt:.1f}s after accept (total {time.time() - t_start:.1f}s) ttft={r.get('ttft') and round(r['ttft'], 1)} finish={r['finish_reason']} "
        f"prompt={u.get('prompt_tokens')} completion={u.get('completion_tokens')} "
        f"reasoning={u.get('reasoning_tokens')} {rh}")
    if a.show_reasoning and r["reasoning"]:
        log("----- reasoning_content -----")
        log(r["reasoning"])
        log("----- end reasoning -----")

    content = r["content"].strip()
    if content:
        print(content)
    if r["finish_reason"] == "length":
        log(f"[ERROR] output truncated (finish_reason=length; max_tokens={max_tokens} includes "
            f"reasoning). Raise --max-tokens or lower --effort.")
        sys.exit(6)
    if not content:
        log("[ERROR] empty answer (content is empty)")
        sys.exit(6)
    term = TERMINATORS.get(a.mode)
    if term and not term.search(content):
        log("[WARN] Response is missing the expected terminator "
            "(GATE: PASS|FAIL / BLOCKING QUESTION:) -- verdict inconclusive")


if __name__ == "__main__":
    main()
