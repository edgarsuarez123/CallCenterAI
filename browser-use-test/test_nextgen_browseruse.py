#!/usr/bin/env python3
"""
Browser-Use + Ollama validation test for NextGen EHR.

Validates that Browser-Use can drive headless Chromium to:
  Step 1 — Launch browser and load NextGen URL
  Step 2 — Login (handles MFA via terminal input)
  Step 3 — Navigate to scheduler and read next available slots
  Step 4 — Fill a preventive visit booking form (NO SUBMIT)

This is the Feature 0 validation gate equivalent for the Browser-Use migration.
Run this manually to validate before any live patient calls.

Required env vars:
  NEXTGEN_URL          — base URL of NextGen instance
  NEXTGEN_USERNAME     — login username
  NEXTGEN_PASSWORD     — login password
  EHR_LLM_PROVIDER     — must be "ollama" for this test
  OLLAMA_MODEL         — e.g. "qwen2.5:32b"

Uses browser-use 0.12+ (BrowserSession + built-in ChatOllama). No langchain-ollama required.

Uses BrowserProfile(keep_alive=True) so Agent.run() does not kill CDP between phases; one browser
session is reused for load → login → scheduler → form (cookies/session preserved).

Optional:
  OLLAMA_BASE_URL      — default: http://localhost:11434
  OLLAMA_NUM_CTX       — context length for Ollama (e.g. 8192). Lower = less RAM & often faster on
                         GPUs with limited VRAM; omit to use Ollama's default for the model.
  PLAYWRIGHT_HEADLESS  — set to "false" to watch the browser (recommended for first run)
  NEXTGEN_PROVIDER     — provider name to search (default: first available)
  NEXTGEN_ALLOWED_DOMAINS — comma-separated extra hosts/patterns for BrowserProfile.allowed_domains
                            (defaults include *.healthfusionclaims.com so post-login redirects are not blocked)

Usage:
  cd browser-use-test
  # Copy .env.test from env.example and fill in values, then:
  export $(cat .env.test | grep -v '#' | xargs)
  python test_nextgen_browseruse.py

  # Or with headed browser to watch:
  PLAYWRIGHT_HEADLESS=false python test_nextgen_browseruse.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from urllib.parse import urlparse

# ── Env helpers ──────────────────────────────────────────────────────────────


def _require_env(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        print(f"\n[ERROR] Required env var not set: {name}")
        print(f"  Set it in your .env.test file or export {name}=value\n")
        sys.exit(1)
    return val


def _optional_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _nextgen_allowed_domains(nextgen_url: str) -> list[str]:
    """Build BrowserProfile.allowed_domains: login host plus HealthFusion redirect patterns.

    Submitting the HealthFusion form navigates to hosts such as
    txn2.healthfusionclaims.com. Allowing only NEXTGEN_URL's hostname makes
    browser-use block that navigation and send the tab to about:blank.
    Patterns use browser-use semantics (e.g. *.healthfusionclaims.com).
    """
    host = urlparse(nextgen_url).hostname
    extra = _optional_env("NEXTGEN_ALLOWED_DOMAINS", "")
    extras = [x.strip() for x in extra.split(",") if x.strip()]
    out: list[str] = []
    seen: set[str] = set()

    def add(item: str) -> None:
        if item and item not in seen:
            seen.add(item)
            out.append(item)

    if host:
        add(host)
    add("*.healthfusion.com")
    add("*.healthfusionclaims.com")
    for item in extras:
        add(item)
    return out


# ── Result tracking ──────────────────────────────────────────────────────────

STEP_RESULTS: dict[str, dict] = {}


def _format_exc(exc: BaseException) -> str:
    """Human-readable message; many libraries raise exceptions with empty str()."""
    msg = str(exc).strip()
    if msg:
        return msg
    return type(exc).__name__


def _record(step: str, passed: bool, detail: str = "", elapsed: float = 0.0) -> None:
    STEP_RESULTS[step] = {"passed": passed, "detail": detail, "elapsed": elapsed}
    status = "PASS" if passed else "FAIL"
    print(f"\n{'='*70}")
    print(f"  Step {step}: {status}  ({elapsed:.1f}s)")
    if detail:
        print(f"  {detail}")
    print(f"{'='*70}")


def _history_signal(history: object) -> str:
    """Combine final result text and step errors for keyword checks."""
    parts: list[str] = []
    if hasattr(history, "final_result"):
        fr = history.final_result()
        if fr:
            parts.append(str(fr))
    if hasattr(history, "errors"):
        for err in history.errors():
            if err:
                parts.append(str(err))
    return " ".join(parts)


def _print_summary() -> None:
    print("\n" + "="*70)
    print("  BROWSER-USE + OLLAMA VALIDATION SUMMARY")
    print("="*70)
    total = len(STEP_RESULTS)
    passed = sum(1 for r in STEP_RESULTS.values() if r["passed"])
    for step, r in STEP_RESULTS.items():
        status = "✓ PASS" if r["passed"] else "✗ FAIL"
        print(f"  {status}  Step {step}  ({r['elapsed']:.1f}s)  {r['detail']}")
    print(f"\n  Result: {passed}/{total} steps passed")
    total_time = sum(r["elapsed"] for r in STEP_RESULTS.values())
    print(f"  Total time: {total_time:.1f}s")
    print("="*70)
    if passed < total:
        print("\n  NEXT STEPS:")
        print("  - Run with PLAYWRIGHT_HEADLESS=false to watch what Browser-Use does")
        print("  - Check Ollama is running: ollama list")
        print(f"  - Confirm model is pulled: ollama pull {_optional_env('OLLAMA_MODEL', 'qwen2.5:32b')}")
        print("  - Try a larger model if navigation fails (qwen2.5:72b or llama3.1:70b)")
    print()


# ── Main test steps ──────────────────────────────────────────────────────────


async def run_validation() -> None:
    # ── Read env vars ────────────────────────────────────────────────────────
    nextgen_url = _require_env("NEXTGEN_URL")
    username = _require_env("NEXTGEN_USERNAME")
    password = _require_env("NEXTGEN_PASSWORD")
    llm_provider = _optional_env("EHR_LLM_PROVIDER", "ollama")
    ollama_model = _optional_env("OLLAMA_MODEL", "qwen2.5:32b")
    ollama_base_url = _optional_env("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_num_ctx_raw = _optional_env("OLLAMA_NUM_CTX", "")
    provider_name = _optional_env("NEXTGEN_PROVIDER", "")
    headless = _optional_env("PLAYWRIGHT_HEADLESS", "true").lower() != "false"
    allowed_domains = _nextgen_allowed_domains(nextgen_url)

    ollama_num_ctx: int | None = None
    if ollama_num_ctx_raw:
        try:
            ollama_num_ctx = int(ollama_num_ctx_raw)
        except ValueError:
            print(f"\n[WARN] OLLAMA_NUM_CTX={ollama_num_ctx_raw!r} is not an integer; ignoring.\n")

    print("\n" + "="*70)
    print("  Browser-Use + NextGen EHR Validation")
    print("="*70)
    print(f"  URL:       {nextgen_url}")
    print(f"  LLM:       {llm_provider} / {ollama_model}")
    if ollama_num_ctx is not None:
        print(f"  Context:   {ollama_num_ctx} (OLLAMA_NUM_CTX)")
    print(f"  Headless:  {headless}")
    print(f"  Provider:  {provider_name or '(first available)'}")
    print(f"  Allowed:   {', '.join(allowed_domains)}")
    print("="*70)

    if llm_provider != "ollama":
        print(f"\n[WARN] EHR_LLM_PROVIDER={llm_provider} — this test is designed for Ollama.")
        print("  Set EHR_LLM_PROVIDER=ollama for local dev validation.\n")

    # ── Build LLM + browser (browser-use 0.12+: native ChatOllama, BrowserSession API) ──
    print(f"\nLoading LLM: {ollama_model} via Ollama at {ollama_base_url} ...")
    try:
        from browser_use import Agent, Browser, BrowserProfile, ChatOllama
    except ImportError as e:
        print("[ERROR] Failed to import browser-use (or a dependency).")
        print(f"  {e}")
        print("  Install: pip install browser-use")
        sys.exit(1)

    ollama_options: dict = {"temperature": 0.0}
    if ollama_num_ctx is not None:
        ollama_options["num_ctx"] = ollama_num_ctx
    llm = ChatOllama(
        model=ollama_model,
        host=ollama_base_url,
        ollama_options=ollama_options,
    )

    # keep_alive=True: Agent.close() skips browser.kill() so CDP stays up for the next Agent.run()
    browser_profile = BrowserProfile(
        headless=headless,
        allowed_domains=allowed_domains,
        keep_alive=True,
    )
    browser = Browser(browser_profile=browser_profile)

    try:
        # ── Step 1: Launch browser ───────────────────────────────────────────
        print(f"\n[Step 1] Launching browser and loading {nextgen_url} ...")
        t0 = time.time()
        try:
            # Quick navigation check using a plain Playwright page via browser-use
            # We use a minimal agent task just to verify the URL loads
            agent1 = Agent(
                task=f"Navigate to {nextgen_url} and report the page title.",
                llm=llm,
                browser=browser,
                use_vision=False,
            )
            history1 = await agent1.run(max_steps=5)
            result1 = history1.final_result() if hasattr(history1, "final_result") else str(history1)
            elapsed1 = time.time() - t0
            _record("1: Load URL", True, f"Page loaded — {result1[:80] if result1 else 'no result'}", elapsed1)
        except Exception as e:
            elapsed1 = time.time() - t0
            _record("1: Load URL", False, f"Error: {_format_exc(e)}", elapsed1)
            return  # Can't continue without a working browser

        # ── Step 2: Login ────────────────────────────────────────────────────
        print("\n[Step 2] Logging in with Browser-Use (credentials via sensitive_data) ...")
        t0 = time.time()
        login_task = (
            "CONTINUATION: The browser is already open from the previous step — you should already be on the "
            "HealthFusion / NextGen Office login page. "
            "Do NOT navigate, open a new tab, or reload unless the visible document is blank, an error page, "
            "or clearly not the login screen (then a single navigate to the configured login page is allowed). "
            "The login fields are inside an iframe (e.g. loginIframe). Only interact inside that iframe — "
            "never footer links, privacy/terms, or unrelated chrome. "
            "Minimize steps: do not explore or scroll unless a field is not visible; then scroll the login "
            "panel into view once and continue. "
            "Strict sequence: "
            "(1) Focus username/User ID and type {x_user}. "
            "(2) Focus Password and type {x_pass}. "
            "(3) Click the Log On submit for that form (e.g. userloginsubmit). "
            "If you see MFA or a verification-code page, stop immediately and your final text must contain "
            "exactly MFA_REQUIRED. "
            "After successful login (dashboard or authenticated app), finish with LOGIN_SUCCESS plus one short "
            "phrase describing where you landed."
        )
        try:
            agent2 = Agent(
                task=login_task,
                llm=llm,
                browser=browser,
                use_vision=False,
                sensitive_data={"x_user": username, "x_pass": password},
            )
            history2 = await agent2.run(max_steps=15)
            login_history = history2
            result2 = history2.final_result() if hasattr(history2, "final_result") else ""
            result2 = result2 or ""
            sig2 = _history_signal(history2)
            elapsed2 = time.time() - t0

            if "MFA_REQUIRED" in result2 or "MFA_REQUIRED" in sig2:
                print("\n  ⚡ MFA / VERIFICATION CODE REQUIRED")
                print("  Check your email or phone for the verification code.")
                try:
                    mfa_code = input("  Enter verification code: ").strip()
                except (EOFError, KeyboardInterrupt):
                    elapsed2 = time.time() - t0
                    _record(
                        "2: Login",
                        False,
                        "MFA: cancelled (Ctrl+C) or EOF — no code entered",
                        elapsed2,
                    )
                    return
                if not mfa_code:
                    _record("2: Login", False, "No MFA code entered", elapsed2)
                    return
                # Submit MFA code with a follow-up agent task
                mfa_task = (
                    "CONTINUATION: Stay on the current MFA/verification page. Do not navigate back to the login URL. "
                    f"Enter the code {mfa_code} in the verification field and submit with minimal actions (target ≤4 steps). "
                    "Finish with LOGIN_SUCCESS if you reach the dashboard or authenticated app, or MFA_FAILED if rejected."
                )
                agent_mfa = Agent(
                    task=mfa_task,
                    llm=llm,
                    browser=browser,
                    use_vision=False,
                )
                history_mfa = await agent_mfa.run(max_steps=8)
                login_history = history_mfa
                result2 = history_mfa.final_result() if hasattr(history_mfa, "final_result") else ""
                result2 = result2 or ""
                sig2 = _history_signal(history_mfa)
                elapsed2 = time.time() - t0

            combined = (result2 + " " + sig2).strip()
            if "LOGIN_SUCCESS" in combined:
                _record("2: Login", True, "Logged in successfully", elapsed2)
            elif "LOGIN_FAILED" in combined or "MFA_FAILED" in combined:
                _record("2: Login", False, f"Login failed: {combined[:200]}", elapsed2)
                return
            elif login_history.has_errors():
                _record(
                    "2: Login",
                    False,
                    f"Agent errors (no LOGIN_SUCCESS). {_history_signal(login_history)[:320]}",
                    elapsed2,
                )
                return
            else:
                _record(
                    "2: Login",
                    False,
                    f"No LOGIN_SUCCESS marker; output: {combined[:220] or '(empty)'}",
                    elapsed2,
                )
                return

        except Exception as e:
            elapsed2 = time.time() - t0
            _record("2: Login", False, f"Error: {_format_exc(e)}", elapsed2)
            return

        # ── Step 3: Read available slots ─────────────────────────────────────
        print("\n[Step 3] Navigating to scheduler and reading next available slots ...")
        t0 = time.time()
        provider_clause = f"for provider '{provider_name}'" if provider_name else "for any provider"
        slots_task = (
            "Navigate to the appointment scheduler. "
            f"Find the next available appointment slots {provider_clause}. "
            "If there is a 'find next available' or 'search available' button, click it. "
            "Otherwise page forward through the calendar until you find dates with open slots. "
            "Return the first 3 available slots as a JSON array. "
            "Each element must have 'date', 'time', and 'provider_name' fields. "
            'Example: [{"date": "2026-06-15", "time": "9:00 AM", "provider_name": "Dr. Smith"}]'
        )
        try:
            agent3 = Agent(
                task=slots_task,
                llm=llm,
                browser=browser,
                use_vision=False,
            )
            history3 = await agent3.run(max_steps=50)
            result3 = history3.final_result() if hasattr(history3, "final_result") else ""
            result3 = result3 or ""
            sig3 = _history_signal(history3)
            elapsed3 = time.time() - t0

            slot_match = re.search(r"\[.*?\]", result3 + sig3, re.DOTALL)
            if history3.has_errors() and not slot_match:
                _record("3: Read slots", False, f"Agent errors; no slot JSON. {sig3[:280]}", elapsed3)
            elif slot_match:
                try:
                    slots = json.loads(slot_match.group(0))
                    detail = f"Found {len(slots)} slot(s)"
                    if slots:
                        first = slots[0]
                        detail += f": {first.get('date')} {first.get('time')} — {first.get('provider_name')}"
                    _record("3: Read slots", True, detail, elapsed3)
                except json.JSONDecodeError:
                    _record("3: Read slots", False, f"Slots found but JSON parse failed: {result3[:150]}", elapsed3)
            else:
                _record("3: Read slots", False, f"No slot JSON in response: {(result3 + sig3)[:220]}", elapsed3)

        except Exception as e:
            elapsed3 = time.time() - t0
            _record("3: Read slots", False, f"Error: {_format_exc(e)}", elapsed3)

        # ── Step 4: Fill booking form (NO SUBMIT) ────────────────────────────
        print("\n[Step 4] Filling preventive visit booking form (will NOT submit) ...")
        t0 = time.time()
        booking_task = (
            "Navigate to the appointment scheduler. "
            "Find any available appointment slot for a preventive visit or annual wellness visit. "
            "Click on the slot to open the booking form. "
            "Fill in the patient name 'Test Patient' and select appointment type 'Preventive Care Visit' "
            "(or the closest matching type). "
            "DO NOT click submit or save — just fill the form and stop. "
            "Report 'FORM_FILLED' and describe the fields you filled in."
        )
        try:
            agent4 = Agent(
                task=booking_task,
                llm=llm,
                browser=browser,
                use_vision=False,
            )
            history4 = await agent4.run(max_steps=30)
            result4 = history4.final_result() if hasattr(history4, "final_result") else ""
            result4 = result4 or ""
            sig4 = _history_signal(history4)
            elapsed4 = time.time() - t0
            combined4 = (result4 + " " + sig4).strip()

            if "FORM_FILLED" in combined4 and not history4.has_errors():
                _record("4: Fill form", True, f"Form filled: {combined4[:180]}", elapsed4)
            elif history4.has_errors():
                _record("4: Fill form", False, f"Agent errors: {sig4[:280]}", elapsed4)
            elif "FORM_FILLED" in combined4:
                _record("4: Fill form", True, f"Form filled (with warnings): {combined4[:180]}", elapsed4)
            else:
                _record("4: Fill form", False, f"No FORM_FILLED marker: {combined4[:220] or '(empty)'}", elapsed4)

        except Exception as e:
            elapsed4 = time.time() - t0
            _record("4: Fill form", False, f"Error: {_format_exc(e)}", elapsed4)

    finally:
        try:
            # Avoid CancelledError spam when user hits Ctrl+C during shutdown: let kill finish.
            await asyncio.shield(browser.kill())
        except KeyboardInterrupt:
            raise
        except asyncio.CancelledError:
            pass
        except BaseException as cleanup_err:
            print(f"\n[WARN] Browser cleanup: {_format_exc(cleanup_err)}")

    _print_summary()


if __name__ == "__main__":
    asyncio.run(run_validation())
