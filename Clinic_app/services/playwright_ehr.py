"""
NextGen EHR automation via Browser-Use + LLM (HEDIS PRD §10).

Each EHR task (slot discovery, booking, credential test) runs a Browser-Use
Agent that navigates the EHR using natural language. No persistent browser
sessions — each task logs in, completes work, and exits. Per-clinic
asyncio.Lock prevents concurrent EHR operations for the same clinic.

HIPAA controls:
  use_vision=False        — no screenshots sent to LLM
  sensitive_data          — credentials never appear in LLM prompts
  allowed_domains         — browser locked to EHR domain only

MFA: if login triggers 2FA, sets ehr:mfa:{clinic_id}="pending" in Redis and
waits for clinic admin to submit code via POST /admin/clinics/{id}/ehr-mfa-code.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any, Optional
from urllib.parse import urlparse
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from Clinic_app.common.encryption import decrypt_phi
from Clinic_app.common.redis import get_redis
from Clinic_app.data.models.clinic_ehr_config import ClinicEHRConfig
from Clinic_app.data.models.clinic_integration import ClinicIntegration
from Clinic_app.services.ehr_llm_provider import get_ehr_llm
from Clinic_app.services.playbook_cache import get_cached_slots

logger = logging.getLogger(__name__)

# Kept for backward-compatibility with existing tests
HEARTBEAT_INTERVAL_SECONDS = 8 * 60

MAX_SLOTS_RETURNED = 5

MFA_REDIS_PREFIX = "ehr:mfa"
MFA_POLL_INTERVAL_SECONDS = 5
MFA_TIMEOUT_SECONDS = 300  # 5 minutes

BROWSERUSE_MAX_STEPS_LOGIN = 15
BROWSERUSE_MAX_STEPS_SLOTS = 50  # may page through months of booked calendar
BROWSERUSE_MAX_STEPS_BOOKING = 30
BROWSERUSE_USE_VISION = False


class PlaywrightEHRService:
    """
    Browser-Use + LLM service for NextGen EHR scheduler (slots + booking).

    Use module singleton `playwright_ehr_service` — call startup() on app boot,
    shutdown_all() on teardown. Each EHR task creates its own Browser-Use context
    and includes login in the task description. Per-clinic asyncio.Lock prevents
    concurrent EHR operations.
    """

    def __init__(self) -> None:
        self._locks: dict[UUID, asyncio.Lock] = {}
        self._bu_browser: Any = None  # browser_use.Browser (shared)
        self._started = False

    def _lock(self, clinic_id: UUID) -> asyncio.Lock:
        if clinic_id not in self._locks:
            self._locks[clinic_id] = asyncio.Lock()
        return self._locks[clinic_id]

    async def startup(self) -> None:
        """
        Launch shared Browser-Use browser and validate LLM config (fail-fast).
        Idempotent.
        """
        if self._started:
            return
        from browser_use import Browser

        headless = os.environ.get("PLAYWRIGHT_HEADLESS", "true").lower() != "false"
        # browser-use >=0.12 no longer exports BrowserConfig; configure via Browser kwargs
        self._bu_browser = Browser(headless=headless)
        # Validate LLM config early so misconfiguration is visible at startup
        try:
            get_ehr_llm()
        except RuntimeError as e:
            logger.warning("EHR LLM not configured — EHR tools will be unavailable: %s", e)
        self._started = True
        logger.info("PlaywrightEHRService: Browser-Use initialized (headless=%s)", headless)

    async def shutdown_all(self) -> None:
        """Close the shared Browser-Use browser."""
        if self._bu_browser:
            try:
                bu = self._bu_browser
                # browser-use 0.12+: Browser is BrowserSession — use kill(), not close()
                if hasattr(bu, "kill"):
                    await bu.kill()
                elif hasattr(bu, "close"):
                    closer = bu.close
                    if asyncio.iscoroutinefunction(closer):
                        await closer()
                    else:
                        closer()
                else:
                    logger.warning("Browser-Use browser has no kill()/close(); skipping teardown")
            except Exception as e:
                logger.warning("Browser-Use browser close error: %s", e)
            self._bu_browser = None
        self._started = False
        logger.info("PlaywrightEHRService: shutdown complete")

    async def initialize_session(self, db: AsyncSession, clinic_id: UUID) -> None:
        """No-op: Browser-Use manages sessions per-task. Kept for API compatibility."""

    async def shutdown_session(self, clinic_id: UUID) -> None:
        """No-op: Browser-Use manages sessions per-task. Kept for API compatibility."""

    # ── Public EHR methods ──────────────────────────────────────────────────

    async def get_available_slots(
        self,
        db: AsyncSession,
        clinic_id: UUID,
        provider_name: str,
        date: str,
    ) -> list[dict[str, Any]]:
        """
        Returns up to MAX_SLOTS_RETURNED cached slots for a provider.
        Reads from Redis — populated by SlotPrefetchWorker (60s interval).
        Returns empty list on cache miss so Retell can respond within 3 seconds.
        `date` parameter kept for API compatibility with retell.py callers.
        """
        cached = await get_cached_slots(clinic_id, provider_name)
        if cached is not None:
            return cached[:MAX_SLOTS_RETURNED]
        logger.warning(
            "Slot cache miss clinic_id=%s provider=%s — SlotPrefetchWorker may not be running",
            clinic_id,
            provider_name,
        )
        return []

    async def fetch_slots_live(
        self,
        db: AsyncSession,
        clinic_id: UUID,
        provider_name: str,
    ) -> list[dict[str, Any]]:
        """
        Uses Browser-Use to navigate NextGen and find the next available slots.
        Called by SlotPrefetchWorker every 60s — never called from Retell webhooks.
        Results are cached in Redis (90s TTL) for get_available_slots() to read.
        """
        async with self._lock(clinic_id):
            await self._ensure_browser()
            cfg = await self._load_ehr_config(db, clinic_id)
            username, password = await self._decrypt_creds(cfg)
            tz = await self._get_clinic_timezone(db, clinic_id)
            domain = urlparse(cfg.nextgen_url).hostname or cfg.nextgen_url

            task = (
                f"Navigate to {cfg.nextgen_url}. "
                "If you see a login page, login with username {x_user} and password {x_pass}. "
                "If after submitting credentials you see an MFA or verification code page, "
                "stop immediately and report 'MFA_REQUIRED'. "
                f"After login, navigate to the appointment scheduler. "
                f"Select provider '{provider_name}'. "
                "Find the next available appointment slots. "
                "If there is a 'find next available' or 'search available' button, click it. "
                "Otherwise, page forward through the calendar until you find dates with open slots. "
                "Return the first 5 available slots as a JSON array. "
                "Each element must have 'date' (YYYY-MM-DD or MM/DD/YYYY), "
                "'time' (HH:MM AM/PM), and 'provider_name' fields. "
                'Example: [{"date": "2026-06-15", "time": "9:00 AM", "provider_name": "Dr. Smith"}]'
            )

            result_text = await self._run_browser_task(
                task=task,
                domain=domain,
                sensitive_data={"x_user": username, "x_pass": password},
                max_steps=BROWSERUSE_MAX_STEPS_SLOTS,
            )

            if "MFA_REQUIRED" in (result_text or ""):
                await self._handle_mfa_flow(clinic_id)
                result_text = await self._run_browser_task(
                    task=task,
                    domain=domain,
                    sensitive_data={"x_user": username, "x_pass": password},
                    max_steps=BROWSERUSE_MAX_STEPS_SLOTS,
                )

            slots_raw = self._parse_json_slots(result_text or "", provider_name)
            return self._normalize_slots(slots_raw, provider_name, tz)

    async def book_appointment(
        self,
        db: AsyncSession,
        clinic_id: UUID,
        provider_name: str,
        slot_start: str,
        patient_name: str,
        appt_type_code: str,
    ) -> dict[str, Any]:
        """
        Book in NextGen. slot_start is ISO 8601. Returns success dict or error dict.
        Runs Browser-Use live (~15-30s) — patient is on hold while booking completes.
        """
        async with self._lock(clinic_id):
            await self._ensure_browser()
            cfg = await self._load_ehr_config(db, clinic_id)
            username, password = await self._decrypt_creds(cfg)
            domain = urlparse(cfg.nextgen_url).hostname or cfg.nextgen_url

            task = (
                f"Navigate to {cfg.nextgen_url}. "
                "If you see a login page, login with username {x_user} and password {x_pass}. "
                "If after submitting credentials you see an MFA or verification code page, "
                "stop immediately and report 'MFA_REQUIRED'. "
                "After login, navigate to the appointment scheduler. "
                f"Select provider '{provider_name}'. "
                f"Find the appointment slot at {slot_start}. "
                "Click on the slot to open the booking form. "
                f"Fill in the patient name '{patient_name}' and select appointment type '{appt_type_code}'. "
                "Submit the booking form. "
                "After submission, read the confirmation number or appointment ID from the page. "
                "If the selected slot is no longer available, report 'SLOT_UNAVAILABLE'. "
                "Return only the appointment ID or confirmation number."
            )

            try:
                result_text = await self._run_browser_task(
                    task=task,
                    domain=domain,
                    sensitive_data={"x_user": username, "x_pass": password},
                    max_steps=BROWSERUSE_MAX_STEPS_BOOKING,
                )

                if "MFA_REQUIRED" in (result_text or ""):
                    await self._handle_mfa_flow(clinic_id)
                    result_text = await self._run_browser_task(
                        task=task,
                        domain=domain,
                        sensitive_data={"x_user": username, "x_pass": password},
                        max_steps=BROWSERUSE_MAX_STEPS_BOOKING,
                    )

                if "SLOT_UNAVAILABLE" in (result_text or ""):
                    return {"success": False, "error": "slot_unavailable"}

                appt_id = self._extract_appointment_id(result_text or "")
                if appt_id:
                    return {"success": True, "ehr_appointment_id": appt_id}
                return {"success": True, "ehr_appointment_id": "NEXTGEN-PENDING"}

            except Exception as e:
                logger.exception("book_appointment failed for clinic %s", clinic_id)
                return {"success": False, "error": str(e)[:500]}

    async def test_credentials(self, db: AsyncSession, clinic_id: UUID) -> dict[str, Any]:
        """
        One-off login test using Browser-Use.
        Returns {"success": True} or {"success": False, "error": "..."}.
        """
        await self._ensure_browser()
        try:
            cfg = await self._load_ehr_config(db, clinic_id)
        except ValueError as e:
            return {"success": False, "error": str(e)}

        username, password = await self._decrypt_creds(cfg)
        domain = urlparse(cfg.nextgen_url).hostname or cfg.nextgen_url

        try:
            task = (
                f"Navigate to {cfg.nextgen_url}. "
                "Login with username {x_user} and password {x_pass}. "
                "If you see an MFA or verification code page, report 'MFA_REQUIRED'. "
                "After login, confirm you are on the main EHR dashboard. "
                "Report 'LOGIN_SUCCESS' if login worked, 'LOGIN_FAILED' if credentials were rejected."
            )
            result_text = await self._run_browser_task(
                task=task,
                domain=domain,
                sensitive_data={"x_user": username, "x_pass": password},
                max_steps=BROWSERUSE_MAX_STEPS_LOGIN,
            )
            result_text = result_text or ""
            if "LOGIN_SUCCESS" in result_text:
                return {"success": True}
            if "MFA_REQUIRED" in result_text:
                return {
                    "success": False,
                    "error": "MFA required — submit code via POST /admin/clinics/{id}/ehr-mfa-code",
                }
            return {"success": False, "error": result_text[:300] or "Unknown error"}
        except Exception as e:
            logger.exception("EHR credential test failed for clinic %s", clinic_id)
            return {"success": False, "error": str(e)[:500]}

    # ── Browser-Use task runner ─────────────────────────────────────────────

    async def _run_browser_task(
        self,
        task: str,
        domain: str,
        sensitive_data: dict[str, str],
        max_steps: int,
    ) -> Optional[str]:
        """Create a Browser-Use Agent, run the task, return the final result text."""
        from browser_use import Agent

        assert self._bu_browser is not None, "Browser not started — call startup() first"
        agent = Agent(
            task=task,
            llm=get_ehr_llm(),
            browser=self._bu_browser,
            use_vision=BROWSERUSE_USE_VISION,
            sensitive_data=sensitive_data,
            allowed_domains=[domain],
        )
        history = await agent.run(max_steps=max_steps)
        if hasattr(history, "final_result"):
            return history.final_result()
        return str(history) if history else None

    # ── MFA human-in-the-loop ───────────────────────────────────────────────

    async def _handle_mfa_flow(self, clinic_id: UUID) -> None:
        """
        Pause EHR automation and wait for clinic admin to submit MFA code via dashboard.

        Flow:
          1. Sets ehr:mfa:{clinic_id} = "pending" in Redis (5-min TTL)
          2. Dashboard polls GET /admin/clinics/{id}/ehr-status → mfa_required: true
          3. Admin submits code via POST /admin/clinics/{id}/ehr-mfa-code
          4. This method detects the code, returns (caller retries EHR task)
          5. Raises RuntimeError on timeout
        """
        r = await get_redis()
        mfa_key = f"{MFA_REDIS_PREFIX}:{clinic_id}"
        await r.set(mfa_key, "pending", ex=MFA_TIMEOUT_SECONDS)
        logger.warning(
            "MFA required for clinic %s — waiting for code via "
            "POST /admin/clinics/%s/ehr-mfa-code (timeout=%ds)",
            clinic_id,
            clinic_id,
            MFA_TIMEOUT_SECONDS,
        )
        elapsed = 0
        while elapsed < MFA_TIMEOUT_SECONDS:
            await asyncio.sleep(MFA_POLL_INTERVAL_SECONDS)
            elapsed += MFA_POLL_INTERVAL_SECONDS
            val = await r.get(mfa_key)
            if val is None:
                raise RuntimeError(f"MFA key expired for clinic {clinic_id}")
            val_str = val.decode() if isinstance(val, bytes) else str(val)
            if val_str and val_str != "pending":
                await r.delete(mfa_key)
                logger.info("MFA code received for clinic %s — resuming EHR automation", clinic_id)
                return
        await r.delete(mfa_key)
        raise RuntimeError(
            f"MFA code not provided within {MFA_TIMEOUT_SECONDS}s for clinic {clinic_id}"
        )

    # ── Config helpers ──────────────────────────────────────────────────────

    async def _ensure_browser(self) -> None:
        if not self._started or self._bu_browser is None:
            await self.startup()

    async def _load_ehr_config(self, db: AsyncSession, clinic_id: UUID) -> ClinicEHRConfig:
        r = await db.execute(select(ClinicEHRConfig).where(ClinicEHRConfig.clinic_id == clinic_id))
        row = r.scalar_one_or_none()
        if row is None:
            raise ValueError("ClinicEHRConfig not found for clinic")
        return row

    async def _decrypt_creds(self, cfg: ClinicEHRConfig) -> tuple[str, str]:
        u = decrypt_phi(cfg.nextgen_username_encrypted)
        p = decrypt_phi(cfg.nextgen_password_encrypted)
        return u, p

    async def _get_clinic_timezone(self, db: AsyncSession, clinic_id: UUID) -> Any:
        r = await db.execute(
            select(ClinicIntegration.timezone).where(ClinicIntegration.clinic_id == clinic_id)
        )
        tz_name = r.scalar_one_or_none() or "America/New_York"
        try:
            return ZoneInfo(tz_name)
        except Exception:
            return dt_timezone.utc

    # ── Slot parsing helpers ────────────────────────────────────────────────

    def _parse_json_slots(self, text: str, default_provider: str) -> list[dict[str, Any]]:
        """Extract a JSON array of slot dicts from Browser-Use agent output."""
        m = re.search(r"\[.*?\]", text, re.DOTALL)
        if not m:
            return []
        try:
            items = json.loads(m.group(0))
            if isinstance(items, list):
                return [i for i in items if isinstance(i, dict)]
        except (json.JSONDecodeError, ValueError):
            pass
        return []

    def _normalize_slots(
        self,
        slots_raw: list[dict[str, Any]],
        default_provider: str,
        tz: Any,
    ) -> list[dict[str, Any]]:
        """Convert raw slot dicts into the standard {start_time, end_time, provider_name} format."""
        out: list[dict[str, Any]] = []
        for s in slots_raw:
            d = s.get("date") or ""
            t = s.get("time") or "09:00"
            pname = s.get("provider_name") or default_provider
            try:
                start_dt = self._parse_slot_datetime(str(d), str(t), tz)
                end_dt = start_dt + timedelta(minutes=30)
                out.append(
                    {
                        "start_time": start_dt.isoformat(),
                        "end_time": end_dt.isoformat(),
                        "provider_name": pname,
                    }
                )
            except Exception as e:
                logger.debug("Skip malformed slot %s: %s", s, e)
        return out

    def _parse_slot_datetime(self, date_part: str, time_part: str, tz: Any) -> datetime:
        """Combine date + time strings into a timezone-aware datetime."""
        date_part = date_part.strip()
        time_part = time_part.strip()
        dt_formats = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y")
        tm_clean = re.sub(r"\s+", " ", time_part)
        parsed_date = None
        for fmt in dt_formats:
            try:
                parsed_date = datetime.strptime(date_part, fmt).date()
                break
            except ValueError:
                continue
        if parsed_date is None:
            raise ValueError(f"Unrecognized date: {date_part}")
        m = re.match(r"^(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)?", tm_clean)
        if not m:
            raise ValueError(f"Unrecognized time: {time_part}")
        hh, mm = int(m.group(1)), int(m.group(2))
        ap = m.group(3)
        if ap and ap.upper() == "PM" and hh < 12:
            hh += 12
        if ap and ap.upper() == "AM" and hh == 12:
            hh = 0
        return datetime(parsed_date.year, parsed_date.month, parsed_date.day, hh, mm, tzinfo=tz)

    def _extract_appointment_id(self, text: str) -> Optional[str]:
        m = re.search(r"(\d{6,}|APT[-\w]+)", text)
        return m.group(1) if m else None


playwright_ehr_service = PlaywrightEHRService()
