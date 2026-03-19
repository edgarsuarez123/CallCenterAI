"""
Feature 0 — CDP Validation Script
-----------------------------------
Connects to an already-running Chrome (via Chrome DevTools Protocol) and runs
the same login + slot-reading + form-fill validation as test_nextgen_headless.py.

Use this when headless Chromium cannot complete Google SSO on its own.
Chrome is already signed into Google, so the SSO popup works normally.

PRE-REQUISITES:
  1. Close all existing Chrome windows
  2. Relaunch Chrome with remote debugging enabled:

     & "C:\Program Files\Google\Chrome\Application\chrome.exe" `
         --remote-debugging-port=9222 `
         --user-data-dir="C:\ChromeDebug"

  3. In that Chrome window, navigate to NEXTGEN_URL if not already there.
     (The script will also attempt to navigate automatically.)

Run from project root:
    python agentql-test/test_cdp.py

Required environment variables:
    NEXTGEN_URL          Login page URL  e.g. https://login.healthfusion.com/
    NEXTGEN_USERNAME     NextGen / HealthFusion username
    NEXTGEN_PASSWORD     NextGen / HealthFusion password  (use single quotes if it contains $)
    AGENTQL_API_KEY      Your AgentQL API key

Optional:
    CDP_URL              Chrome DevTools endpoint (default: http://localhost:9222)
"""

import asyncio
import os
import sys
import logging
from urllib.parse import urlparse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

STEP_RESULTS: dict[str, str] = {}


# --------------------------------------------------------------------------- #
# Helpers (identical to test_nextgen_headless.py)                             #
# --------------------------------------------------------------------------- #

def _domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def _is_login_page(url: str) -> bool:
    path_lower = urlparse(url).path.lower()
    url_lower = url.lower()
    keywords = ("login", "signin", "sign-in", "userlogin", "auth", "sso")
    return any(k in path_lower or k in url_lower for k in keywords)


def _is_mfa_page(url: str) -> bool:
    """Heuristic: does this URL look like an MFA / verification-code page?"""
    path_lower = urlparse(url).path.lower()
    url_lower = url.lower()
    keywords = ("mfa", "otp", "verify", "verification", "two-factor", "2fa", "passcode", "totp")
    return any(k in path_lower or k in url_lower for k in keywords)


def _require_env(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        logger.error(
            f"Missing required environment variable: {name}\n"
            f"Set it with single quotes if it contains special characters:\n"
            f"  $env:{name} = 'your-value'"
        )
        sys.exit(1)
    return val


async def _handle_mfa_if_needed(page) -> bool:
    """
    Detect and handle an MFA / verification-code step after credential submission.

    Uses two signals (either is sufficient):
      1. URL keyword check via _is_mfa_page() — fast, no API call needed
      2. AgentQL field probe — catches inline MFA where the URL does not change
         after credential submit (e.g. code challenge appears on the same page)

    If a verification code field is found, pauses to prompt the admin to enter
    the code in the terminal, fills it, submits, and waits for the next page.

    Returns True if MFA was handled, False if no MFA step was detected.
    Raises RuntimeError if the admin provides an empty code.
    """
    if _is_mfa_page(page.url):
        print(f"  ⚠ MFA/verification page detected by URL: {page.url}")

    mfa_response = await page.query_elements("""
    {
        verification_form {
            verification_code_field
            submit_button
        }
    }
    """)
    form = mfa_response.verification_form
    if not form or not form.verification_code_field:
        return False

    print("\n  ⚡ VERIFICATION CODE REQUIRED")
    print(f"  Page: {await page.title()} ({page.url})")
    print("  Check your phone or email for the code sent by HealthFusion/NextGen.")
    code = input("  Enter verification code: ").strip()

    if not code:
        raise RuntimeError(
            "No verification code entered — cannot proceed past MFA.\n"
            "  Re-run the script and enter the code when prompted."
        )

    await form.verification_code_field.fill(code)
    if form.submit_button:
        await form.submit_button.click()
    else:
        await form.verification_code_field.press("Enter")

    await page.wait_for_load_state("networkidle", timeout=30_000)
    print(f"  ✓ Verification code submitted — now at: {page.url}")
    return True


def _print_summary() -> None:
    print("\n" + "=" * 60)
    print("  VALIDATION SUMMARY (CDP) — Log this in PROGRESS.txt")
    print("=" * 60)
    all_pass = True
    for step, result in STEP_RESULTS.items():
        if result.startswith("PASS"):
            status = "✓ PASS"
        elif result.startswith("PARTIAL"):
            status = "⚠ PARTIAL"
        else:
            status = "✗ FAIL"
            all_pass = False
        print(f"  {status}  {step}: {result}")

    print()
    if all_pass and len(STEP_RESULTS) == 3:
        print("  OVERALL: PASSED (CDP path)")
        print("  AgentQL queries work against NextGen.")
        print("  Next: solve headless Google SSO via save_session.py to confirm production path.")
    elif any(v.startswith("FAIL") for v in STEP_RESULTS.values()):
        print("  OVERALL: FAILED — review errors above")
    else:
        print("  OVERALL: PARTIAL — manual investigation needed")
    print("=" * 60 + "\n")


# --------------------------------------------------------------------------- #
# Main validation                                                              #
# --------------------------------------------------------------------------- #

async def validate() -> None:
    nextgen_url = _require_env("NEXTGEN_URL")
    nextgen_username = _require_env("NEXTGEN_USERNAME")
    nextgen_password = _require_env("NEXTGEN_PASSWORD")
    agentql_api_key = _require_env("AGENTQL_API_KEY")
    cdp_url = os.environ.get("CDP_URL", "http://localhost:9222").strip()

    try:
        import agentql
        agentql.configure(api_key=agentql_api_key)
    except ImportError:
        logger.error("agentql not installed. Run: pip install agentql")
        sys.exit(1)

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("playwright not installed. Run: pip install playwright && python -m playwright install chromium")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  CallCenterAI — CDP + NextGen Validation")
    print("  Connecting to existing Chrome via CDP")
    print(f"  CDP endpoint: {cdp_url}")
    print("=" * 60 + "\n")

    async with async_playwright() as p:

        # ------------------------------------------------------------------ #
        # CONNECT to existing Chrome via CDP                                  #
        # ------------------------------------------------------------------ #
        print("CONNECTING to Chrome via CDP ...")
        try:
            browser = await p.chromium.connect_over_cdp(cdp_url)
            contexts = browser.contexts
            if not contexts:
                raise RuntimeError(
                    f"No browser contexts found at {cdp_url}.\n"
                    "Make sure Chrome is running with:\n"
                    '  chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\\ChromeDebug"'
                )

            context = contexts[0]
            pages = context.pages

            # Find existing NextGen tab, or use the first available page
            nextgen_page = None
            for pg in pages:
                if "nextgen" in pg.url.lower() or "healthfusion" in pg.url.lower():
                    nextgen_page = pg
                    print(f"  ✓ Found existing NextGen tab: {pg.url}")
                    break

            if not nextgen_page:
                print(f"  ⚠ No NextGen tab found. Opening {nextgen_url} ...")
                nextgen_page = await context.new_page()

            raw_page = nextgen_page
            page = await agentql.wrap_async(raw_page)

            # Navigate to login URL if not already on a NextGen/HealthFusion page
            current_url = page.url
            if "nextgen" not in current_url.lower() and "healthfusion" not in current_url.lower():
                await page.goto(nextgen_url, wait_until="networkidle", timeout=30_000)

            print(f"  ✓ Connected. Current URL: {page.url}")
            print(f"  ✓ Page title: {await page.title()}")

        except Exception as e:
            print(f"  ✗ CONNECT FAILED: {e}")
            print(
                "\n  Is Chrome running with --remote-debugging-port=9222?\n"
                "  Run this first:\n"
                '  & "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" '
                '--remote-debugging-port=9222 --user-data-dir="C:\\ChromeDebug"'
            )
            sys.exit(1)

        # ------------------------------------------------------------------ #
        # STEP 2: Login — same multi-stage loop as test_nextgen_headless.py  #
        # ------------------------------------------------------------------ #
        print("\nSTEP 2: Logging in (same logic as headless test) ...")
        try:
            login_stages_completed = 0
            max_login_stages = 3

            while _is_login_page(page.url) and login_stages_completed < max_login_stages:
                current_url = page.url
                current_domain = _domain(current_url)
                stage_num = login_stages_completed + 1
                print(f"  → Login stage {stage_num}: {current_domain}")

                login_response = await page.query_elements("""
                {
                    login_form {
                        username_field
                        password_field
                        login_button
                    }
                }
                """)

                login = login_response.login_form
                if not login or not login.username_field:
                    raise RuntimeError(
                        f"AgentQL could not find login form on stage {stage_num}.\n"
                        f"  URL: {current_url}\n"
                        f"  Title: {await page.title()}\n"
                        "  Look at the Chrome window — the form may need a different query.\n"
                        "  If a Google SSO popup appeared, complete it manually then re-run."
                    )

                await login.username_field.fill(nextgen_username)
                await login.password_field.fill(nextgen_password)
                print(f"    ✓ Filled credentials for stage {stage_num}")
                await login.login_button.click()

                await page.wait_for_load_state("networkidle", timeout=30_000)
                new_url = page.url
                new_title = await page.title()
                print(f"    ✓ After stage {stage_num} submit:")
                print(f"      URL:   {new_url}")
                print(f"      Title: {new_title}")

                # Handle MFA/verification code BEFORE the stale-URL guard.
                # This covers both redirect-to-MFA-page and inline MFA (URL unchanged).
                # After MFA completes, new_url is refreshed to the post-MFA destination.
                await _handle_mfa_if_needed(page)
                new_url = page.url  # refresh after potential MFA redirect

                if new_url == current_url:
                    raise RuntimeError(
                        f"Login stage {stage_num} failed — URL did not change after submit.\n"
                        f"  Stuck at: {current_url}\n"
                        "  Check credentials. Look at the Chrome window for an error message."
                    )

                login_stages_completed += 1
                if _is_login_page(new_url):
                    print(f"    ⚠ Another login page detected ({_domain(new_url)}) — continuing ...")

            # If we were already past the login page on connect, that's fine too
            if login_stages_completed == 0 and not _is_login_page(page.url):
                print(f"  ✓ Already logged in — skipping login (URL: {page.url})")
                STEP_RESULTS["step_2_login"] = "PASS (already authenticated)"
            elif login_stages_completed > 0:
                print(f"\n  ✓ Login complete after {login_stages_completed} stage(s)")
                print(f"  ✓ Landed at: {page.url}")
                STEP_RESULTS["step_2_login"] = f"PASS ({login_stages_completed} login stage(s))"
            else:
                raise RuntimeError(
                    f"Could not determine login state. URL: {page.url}"
                )

        except Exception as e:
            STEP_RESULTS["step_2_login"] = f"FAIL: {e}"
            print(f"  ✗ STEP 2 FAILED: {e}")
            _print_summary()
            sys.exit(1)

        # ------------------------------------------------------------------ #
        # STEP 3: Navigate to scheduler and read available slots              #
        # ------------------------------------------------------------------ #
        print("\nSTEP 3: Reading available appointment slots ...")
        try:
            nav_response = await page.query_elements("""
            {
                navigation {
                    scheduling_link
                    appointments_link
                    schedule_appointment_link
                }
            }
            """)

            nav = nav_response.navigation
            scheduler_link = (
                nav.scheduling_link
                or nav.appointments_link
                or nav.schedule_appointment_link
            )

            if scheduler_link:
                await scheduler_link.click()
                await page.wait_for_load_state("networkidle", timeout=20_000)
                print(f"  ✓ Navigated to scheduler via AgentQL nav link")
                print(f"  ✓ Scheduler URL: {page.url}")
            else:
                print(
                    "  ⚠ AgentQL could not auto-detect scheduler nav link.\n"
                    "    Navigate to the scheduling page manually in Chrome, then press Enter."
                )
                input("    Press Enter once you are on the scheduling page ...")
                print(f"  ✓ Continuing from: {page.url}")

            slots_response = await page.query_elements("""
            {
                available_appointment_slots[] {
                    date
                    time
                    provider_name
                    appointment_type
                }
            }
            """)

            slots = slots_response.available_appointment_slots or []
            print(f"  ✓ Slots found: {len(slots)}")

            if slots:
                print("  Sample slots (first 3):")
                for slot in slots[:3]:
                    print(f"    - {slot}")
                STEP_RESULTS["step_3_read_slots"] = f"PASS ({len(slots)} slots found)"
            else:
                print(
                    "  ⚠ No slots returned.\n"
                    "    This may need provider/date selection first.\n"
                    "    Navigate to a specific provider's schedule in Chrome, then re-run."
                )
                STEP_RESULTS["step_3_read_slots"] = (
                    "PARTIAL — 0 slots. May need provider/date selection first."
                )

        except Exception as e:
            STEP_RESULTS["step_3_read_slots"] = f"FAIL: {e}"
            print(f"  ✗ STEP 3 FAILED: {e}")

        # ------------------------------------------------------------------ #
        # STEP 4: Locate and fill booking form (DO NOT SUBMIT)               #
        # ------------------------------------------------------------------ #
        print("\nSTEP 4: Locating booking form fields ...")
        try:
            form_response = await page.query_elements("""
            {
                appointment_booking_form {
                    patient_name_field
                    date_of_birth_field
                    appointment_type_dropdown
                    provider_dropdown
                    appointment_date_field
                    appointment_time_field
                }
            }
            """)

            form = form_response.appointment_booking_form
            fields_found = []

            if form:
                if form.patient_name_field:
                    fields_found.append("patient_name_field")
                    await form.patient_name_field.fill("TEST PATIENT — DO NOT SAVE")
                if form.date_of_birth_field:
                    fields_found.append("date_of_birth_field")
                    await form.date_of_birth_field.fill("01/01/1980")
                if form.appointment_type_dropdown:
                    fields_found.append("appointment_type_dropdown")
                if form.provider_dropdown:
                    fields_found.append("provider_dropdown")
                if form.appointment_date_field:
                    fields_found.append("appointment_date_field")
                if form.appointment_time_field:
                    fields_found.append("appointment_time_field")

            if fields_found:
                print(f"  ✓ Form fields found and fillable: {', '.join(fields_found)}")
                print("  ✓ Did NOT submit — validation only")
                STEP_RESULTS["step_4_form_fill"] = f"PASS (fields: {', '.join(fields_found)})"
            else:
                print(
                    "  ⚠ Booking form not found on current page.\n"
                    "    Navigate into a specific slot in Chrome, then re-run Step 4 check."
                )
                STEP_RESULTS["step_4_form_fill"] = (
                    "PARTIAL — form not found. May need slot selection first."
                )

        except Exception as e:
            STEP_RESULTS["step_4_form_fill"] = f"FAIL: {e}"
            print(f"  ✗ STEP 4 FAILED: {e}")

        # Don't close the browser — it's the user's Chrome window
        print("\n  ℹ Chrome window left open (CDP mode — not closing your browser).")

    _print_summary()


if __name__ == "__main__":
    asyncio.run(validate())
