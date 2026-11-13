#!/usr/bin/env python3
"""Manage exaone-skill config in ~/.exaone-skill/.env

  python setup.py --show                    show key (masked), effort, path
  python setup.py --key  < keyfile          store EXAONE_API_KEY read from stdin (never argv)
  python setup.py --key --prompt            prompt for the key without echo (interactive)
  python setup.py --set-effort high         store default reasoning effort (low|medium|high|max)
  python setup.py --set-max-tokens 32768    store default max_tokens
  python setup.py --set-busy-wait 5         seconds between retries when the server is busy (429)
  python setup.py --set-busy-retries 5      max retries when the server is busy (429)
"""
import argparse
import getpass
import os
import sys
from pathlib import Path

CONFIG_DIR = Path.home() / ".exaone-skill"
ENV_FILE = CONFIG_DIR / ".env"
EFFORTS = ("low", "medium", "high", "max")


def read_env() -> dict:
    out = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def write_env(env: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text("".join(f"{k}={v}\n" for k, v in env.items()), encoding="utf-8")
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass


def mask(v: str) -> str:
    return "(not set)" if not v else (v[:4] + "..." + v[-4:] if len(v) > 12 else "****")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--show", action="store_true")
    p.add_argument("--key", action="store_true", help="read API key from stdin")
    p.add_argument("--prompt", action="store_true", help="with --key: hidden interactive prompt")
    p.add_argument("--set-effort", choices=EFFORTS)
    p.add_argument("--set-max-tokens", type=int)
    p.add_argument("--set-busy-wait", type=int, help="seconds between busy-429 retries")
    p.add_argument("--set-busy-retries", type=int, help="max retries on busy-429")
    a = p.parse_args()
    env = read_env()
    changed = False

    if a.key:
        if a.prompt:
            key = getpass.getpass("EXAONE API key (input hidden): ")
        else:
            key = sys.stdin.readline()
        key = key.strip()
        if key.lower().startswith("bearer "):
            key = key[7:].strip()
        if not key:
            print("[ERROR] empty key; nothing stored", file=sys.stderr)
            sys.exit(2)
        env["EXAONE_API_KEY"] = key
        changed = True
    if a.set_effort:
        env["EXAONE_REASONING_EFFORT"] = a.set_effort
        changed = True
    if a.set_max_tokens:
        env["EXAONE_MAX_TOKENS"] = str(a.set_max_tokens)
        changed = True
    for opt, var in (("set_busy_wait", "EXAONE_BUSY_WAIT"), ("set_busy_retries", "EXAONE_BUSY_RETRIES")):
        v = getattr(a, opt)
        if v is not None:
            if v < 0:
                print(f"[ERROR] {var} must be >= 0", file=sys.stderr)
                sys.exit(2)
            env[var] = str(v)
            changed = True
    if changed:
        write_env(env)
        print(f"[OK] saved to {ENV_FILE}")

    if a.show or not changed:
        env_key = os.environ.get("EXAONE_API_KEY", "")
        print(f"config file : {ENV_FILE} ({'exists' if ENV_FILE.exists() else 'missing'})")
        print(f"API key     : {mask(env_key or env.get('EXAONE_API_KEY', ''))}"
              f"{'  (from environment)' if env_key else ''}")
        print(f"effort      : {os.environ.get('EXAONE_REASONING_EFFORT') or env.get('EXAONE_REASONING_EFFORT') or 'medium (default)'}")
        print(f"max_tokens  : {os.environ.get('EXAONE_MAX_TOKENS') or env.get('EXAONE_MAX_TOKENS') or '32768 (default)'}")
        print(f"busy retry  : wait {os.environ.get('EXAONE_BUSY_WAIT') or env.get('EXAONE_BUSY_WAIT') or '5 (default)'}s x "
              f"{os.environ.get('EXAONE_BUSY_RETRIES') or env.get('EXAONE_BUSY_RETRIES') or '5 (default)'} retries")
        if not (env_key or env.get("EXAONE_API_KEY")):
            sys.exit(2)


if __name__ == "__main__":
    main()
