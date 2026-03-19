"""
Feature 0 — Playwright Validation Gate
---------------------------------------
Manual validation script. NOT a pytest test.

Run from project root:
    python agentql-test/test_nextgen_headless.py

Required environment variables (set these in your shell — NEVER hardcode credentials):
    NEXTGEN_URL          Base URL of the pilot clinic's NextGen instance
                         e.g. https://login.healthfusion.com/
    NEXTGEN_USERNAME     NextGen / HealthFusion login username
    NEXTGEN_PASSWORD     NextGen / HealthFusion login password
    AGENTQL_API_KEY      Your AgentQL API key

Optional environment variables:
    PLAYWRIGHT_HEADLESS  Set to "false" to show the browser window (default: "true")
                         Headed mode adds 800ms slow-motion so you can follow each step.

PowerShell example — headed mode (recommended for first run):
    $env:NEXTGEN_URL        = "https://login.healthfusion.com/"
    $env:NEXTGEN_USERNAME   = "..."
    $env:NEXTGEN_PASSWORD   = "..."
    $env:AGENTQL_API_KEY    = "..."
    $env:PLAYWRIGHT_HEADLESS = "false"
    python agentql-test/test_nextgen_headless.py

What this validates (per HEDIS_PRD_v2.md §10.6):
    Step 1 — Chromium launches and loads NextGen URL
    Step 2 — Playwright fills and submits the login form (handles multi-stage auth)
    Step 3 — AgentQL reads available appointment slots from the scheduler
    Step 4 — AgentQL locates and fills the booking form (does NOT submit)

Log results in PROGRESS.txt before any Feature 5 work begins.
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


def _domain(url: str) -> str:
    """Extract netloc (hostname) from a URL for comparison."""
    return urlparse(url).netloc.lower()


def _is_login_page(url: str) -> bool:
    """Heuristic: does this URL look like a login/auth page?"""
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
    """Exit early with a clear message if a required env var is missing."""
    val = os.environ.get(name, "").strip()
    if not val:
        logger.error(
            f"Missing required environment variable: {name}\n"
            f"Set it in your shell before running this script.\n"
            f"See the docstring at the top of this file for instructions."
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


async def validate() -> None:
    nextgen_url = _require_env("NEXTGEN_URL")
    nextgen_username = _require_env("NEXTGEN_USERNAME")
    nextgen_password = _require_env("NEXTGEN_PASSWORD")
    agentql_api_key = _require_env("AGENTQL_API_KEY")

    # Configure AgentQL with API key
    try:
        import agentql
        agentql.configure(api_key=agentql_api_key)
    except ImportError:
        logger.error(
            "agentql package not installed.\n"
            "Run: pip install agentql"
        )
        sys.exit(1)

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error(
            "playwright package not installed.\n"
            "Run: pip install playwright && playwright install chromium"
        )
        sys.exit(1)

    # Headed mode: set PLAYWRIGHT_HEADLESS=false to watch the browser
    headless = os.environ.get("PLAYWRIGHT_HEADLESS", "true").lower() != "false"
    slow_mo = 800 if not headless else 0
    mode_label = "headless" if headless else "HEADED (browser window visible)"

    print("\n" + "=" * 60)
    print("  CallCenterAI — Playwright + NextGen Validation")
    print("  HEDIS PRD §10.6 — Feature 0 Gate")
    print(f"  Mode: {mode_label}")
    print("=" * 60 + "\n")

    async with async_playwright() as p:
        # ------------------------------------------------------------------ #
        # STEP 1: Launch Chromium and load NextGen URL                        #
        # ------------------------------------------------------------------ #
        print(f"STEP 1: Launching Chromium ({mode_label}) ...")
        try:
            browser = await p.chromium.launch(headless=headless, slow_mo=slow_mo)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )
            raw_page = await context.new_page()
            page = await agentql.wrap_async(raw_page)
            await page.goto(nextgen_url, wait_until="networkidle", timeout=30_000)
            title = await page.title()
            initial_domain = _domain(page.url)
            print(f"  ✓ Loaded: {page.url}")
            print(f"  ✓ Page title: {title}")
            print(f"  ✓ Domain: {initial_domain}")
            STEP_RESULTS["step_1_launch"] = "PASS"
        except Exception as e:
            STEP_RESULTS["step_1_launch"] = f"FAIL: {e}"
            print(f"  ✗ STEP 1 FAILED: {e}")
            _print_summary()
            await browser.close()
            sys.exit(1)

        # ------------------------------------------------------------------ #
        # STEP 2: Log in — handles multi-stage auth (e.g. HealthFusion →      #
        #         NextGen Office two-step flow)                               #
        # ------------------------------------------------------------------ #
        print("\nSTEP 2: Logging in ...")
        try:
            login_stages_completed = 0
            max_login_stages = 3  # safety limit

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
                        "  If in headed mode, look at the browser window to see what's there.\n"
                        "  The form fields may have non-standard labels — update the AgentQL query."
                    )

                await login.username_field.fill(nextgen_username)
                await login.password_field.fill(nextgen_password)
                print(f"    ✓ Filled credentials for stage {stage_num}")
                await login.login_button.click()

                # Wait for the next page to settle
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

                # Detect if we made no progress (same exact URL = credentials rejected)
                if new_url == current_url:
                    raise RuntimeError(
                        f"Login stage {stage_num} failed — URL did not change after submit.\n"
                        f"  Stuck at: {current_url}\n"
                        "  Check NEXTGEN_USERNAME and NEXTGEN_PASSWORD.\n"
                        "  In headed mode, look for an error message on the page."
                    )

                login_stages_completed += 1
                if _is_login_page(new_url):
                    new_domain = _domain(new_url)
                    print(f"    ⚠ Redirected to another login page ({new_domain}) — continuing ...")

            if login_stages_completed == 0:
                raise RuntimeError(
                    f"URL does not appear to be a login page: {page.url}\n"
                    "  Check NEXTGEN_URL — it should point to the HealthFusion or NextGen login."
                )

            final_url = page.url
            final_title = await page.title()
            print(f"\n  ✓ Login complete after {login_stages_completed} stage(s)")
            print(f"  ✓ Landed at: {final_url}")
            print(f"  ✓ Page title: {final_title}")
            STEP_RESULTS["step_2_login"] = f"PASS ({login_stages_completed} login stage(s))"

        except Exception as e:
            STEP_RESULTS["step_2_login"] = f"FAIL: {e}"
            print(f"  ✗ STEP 2 FAILED: {e}")
            if not headless:
                print("  → Browser window is still open — inspect it before it closes.")
                print("  → Press Ctrl+C to keep the window open, or wait for script to exit.")
            _print_summary()
            await browser.close()
            sys.exit(1)

        # ------------------------------------------------------------------ #
        # STEP 3: Navigate to scheduler and read available slots               #
        # ------------------------------------------------------------------ #
        print("\nSTEP 3: Reading available appointment slots ...")
        try:
            # Use AgentQL to find the scheduling / appointment navigation
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
            else:
                print(
                    "  ⚠ AgentQL could not auto-detect scheduler nav link.\n"
                    "    Attempting to continue — slots may still be on current page."
                )

            # Query available appointment slots
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
                # Not necessarily a failure — may need to select a provider/date first
                print(
                    "  ⚠ No slots returned from initial query.\n"
                    "    This may be expected if NextGen requires selecting a provider/date first.\n"
                    "    Manual check: navigate to the scheduler tab in the browser snapshot below."
                )
                STEP_RESULTS["step_3_read_slots"] = (
                    "PARTIAL — page loaded but 0 slots returned. "
                    "May need to select provider/date first (manual investigation needed)."
                )

        except Exception as e:
            STEP_RESULTS["step_3_read_slots"] = f"FAIL: {e}"
            print(f"  ✗ STEP 3 FAILED: {e}")
            # Do not exit — Step 4 (form fill) can still be attempted

        # ------------------------------------------------------------------ #
        # STEP 4: Locate and fill the booking form (DO NOT SUBMIT)            #
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
                print("  ✓ Did NOT submit form — validation only")
                STEP_RESULTS["step_4_form_fill"] = f"PASS (fields: {', '.join(fields_found)})"
            else:
                print(
                    "  ⚠ Booking form not found on current page.\n"
                    "    This may be expected if NextGen requires navigating into a slot first.\n"
                    "    Manual investigation needed to find correct booking form URL/flow."
                )
                STEP_RESULTS["step_4_form_fill"] = (
                    "PARTIAL — form not found on current page. "
                    "May need slot selection before form appears (manual investigation needed)."
                )

        except Exception as e:
            STEP_RESULTS["step_4_form_fill"] = f"FAIL: {e}"
            print(f"  ✗ STEP 4 FAILED: {e}")

        await browser.close()

    _print_summary()


def _print_summary() -> None:
    print("\n" + "=" * 60)
    print("  VALIDATION SUMMARY — Log this in PROGRESS.txt")
    print("=" * 60)
    all_pass = True
    for step, result in STEP_RESULTS.items():
        status = "✓ PASS" if result.startswith("PASS") else ("⚠ PARTIAL" if result.startswith("PARTIAL") else "✗ FAIL")
        print(f"  {status}  {step}: {result}")
        if result.startswith("FAIL"):
            all_pass = False

    print()
    if all_pass and len(STEP_RESULTS) == 4:
        print("  OVERALL: PASSED — Architecture path: Server-side Playwright")
        print("  Next step: Begin Feature 1 pre-HEDIS fixes")
    elif any(v.startswith("FAIL") for v in STEP_RESULTS.values()):
        print("  OVERALL: FAILED — Review errors above")
        print("  If NextGen blocks headless: pivot to Chrome Extension architecture")
        print("  See HEDIS_CAMPAIGN_IMPLEMENTATION.md for Chrome Extension fallback")
    else:
        print("  OVERALL: PARTIAL — Manual investigation needed for PARTIAL steps")
        print("  Update PROGRESS.txt with findings before proceeding to Feature 5")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(validate())
