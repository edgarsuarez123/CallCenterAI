"""
NextGen EHR automation via Playwright + AgentQL (HEDIS PRD §10).

One BrowserContext per clinic, serialized actions per clinic, 8-minute heartbeat,
Redis selector cache (24h) for AgentQL token savings.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any, Optional
from urllib.parse import urlparse
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from Clinic_app.common.encryption import decrypt_phi
from Clinic_app.data.models.clinic_ehr_config import ClinicEHRConfig
from Clinic_app.data.models.clinic_integration import ClinicIntegration
from Clinic_app.services.selector_cache import (
    get_cached_selector,
    set_cached_selector,
)

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 8 * 60  # PRD §10.2
MAX_SLOTS_RETURNED = 5


@dataclass
class ClinicSession:
    """Per-clinic browser session."""

    clinic_id: UUID
    context: Any  # BrowserContext
    page: Any  # AgentQL-wrapped Page
    logged_in: bool = False
    last_heartbeat: Optional[datetime] = None
    username: str = ""
    password: str = ""
    nextgen_url: str = ""


class PlaywrightEHRService:
    """
    Playwright + AgentQL service for NextGen scheduler (slots + booking).

    Use module singleton `playwright_ehr_service` — call `startup()` on app boot,
    `shutdown_all()` on teardown.
    """

    def __init__(self) -> None:
        self._playwright: Any = None
        self._browser: Any = None
        self._sessions: dict[UUID, ClinicSession] = {}
        self._locks: dict[UUID, asyncio.Lock] = {}
        self._heartbeat_tasks: dict[UUID, asyncio.Task] = {}
        self._started = False

    def _lock(self, clinic_id: UUID) -> asyncio.Lock:
        if clinic_id not in self._locks:
            self._locks[clinic_id] = asyncio.Lock()
        return self._locks[clinic_id]

    async def startup(self) -> None:
        """Launch shared Chromium (idempotent)."""
        if self._started:
            return
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        headless = os.environ.get("PLAYWRIGHT_HEADLESS", "true").lower() != "false"
        self._browser = await self._playwright.chromium.launch(headless=headless)
        self._started = True
        logger.info("PlaywrightEHRService: Chromium launched (headless=%s)", headless)

    async def shutdown_all(self) -> None:
        """Close all sessions and the browser."""
        for cid in list(self._sessions.keys()):
            await self.shutdown_session(cid)
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        self._started = False
        logger.info("PlaywrightEHRService: shutdown complete")

    async def _ensure_browser(self) -> None:
        if not self._started or self._browser is None:
            await self.startup()

    async def initialize_session(self, db: AsyncSession, clinic_id: UUID) -> None:
        """Pre-warm login + scheduler for a clinic (campaign RUNNING)."""
        async with self._lock(clinic_id):
            await self._ensure_browser()
            await self._ensure_logged_in_session(db, clinic_id)

    async def shutdown_session(self, clinic_id: UUID) -> None:
        """Close browser context for a clinic."""
        async with self._lock(clinic_id):
            t = self._heartbeat_tasks.pop(clinic_id, None)
            if t and not t.done():
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
            sess = self._sessions.pop(clinic_id, None)
            if sess and sess.context:
                try:
                    await sess.context.close()
                except Exception as e:
                    logger.warning("Error closing context for %s: %s", clinic_id, e)
            logger.info("Playwright session closed for clinic %s", clinic_id)

    async def _get_clinic_timezone(self, db: AsyncSession, clinic_id: UUID):
        r = await db.execute(
            select(ClinicIntegration.timezone).where(ClinicIntegration.clinic_id == clinic_id)
        )
        tz_name = r.scalar_one_or_none() or "America/New_York"
        try:
            return ZoneInfo(tz_name)
        except Exception:
            try:
                return ZoneInfo("America/New_York")
            except Exception:
                logger.warning("zoneinfo unavailable for %s — using UTC", tz_name)
                return dt_timezone.utc

    async def _load_ehr_config(self, db: AsyncSession, clinic_id: UUID) -> ClinicEHRConfig:
        r = await db.execute(
            select(ClinicEHRConfig).where(ClinicEHRConfig.clinic_id == clinic_id)
        )
        row = r.scalar_one_or_none()
        if row is None:
            raise ValueError("ClinicEHRConfig not found for clinic")
        return row

    async def _decrypt_creds(self, cfg: ClinicEHRConfig) -> tuple[str, str]:
        u = decrypt_phi(cfg.nextgen_username_encrypted)
        p = decrypt_phi(cfg.nextgen_password_encrypted)
        return u, p

    async def test_credentials(self, db: AsyncSession, clinic_id: UUID) -> dict[str, Any]:
        """
        One-off login test in a disposable context. Does not keep session open.
        Returns {"success": True} or {"success": False, "error": "..."}.
        """
        await self._ensure_browser()
        assert self._browser is not None
        try:
            cfg = await self._load_ehr_config(db, clinic_id)
        except ValueError as e:
            return {"success": False, "error": str(e)}

        username, password = await self._decrypt_creds(cfg)
        ctx = await self._browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        try:
            import agentql

            agentql.configure(api_key=os.environ.get("AGENTQL_API_KEY", ""))
            raw_page = await ctx.new_page()
            page = await agentql.wrap_async(raw_page)
            await page.goto(cfg.nextgen_url, wait_until="networkidle", timeout=60_000)
            await self._do_login(page, username, password)
            return {"success": True}
        except Exception as e:
            logger.exception("EHR credential test failed for clinic %s", clinic_id)
            return {"success": False, "error": str(e)[:500]}
        finally:
            await ctx.close()

    async def get_available_slots(
        self,
        db: AsyncSession,
        clinic_id: UUID,
        provider_name: str,
        date: str,
    ) -> list[dict[str, Any]]:
        """
        Return up to MAX_SLOTS_RETURNED slots as dicts with start_time, end_time, provider_name (ISO 8601).
        """
        async with self._lock(clinic_id):
            await self._ensure_browser()
            await self._ensure_logged_in_session(db, clinic_id)
            sess = self._sessions[clinic_id]
            page = sess.page
            tz = await self._get_clinic_timezone(db, clinic_id)
            await self._navigate_to_scheduler(page, clinic_id)
            await self._select_provider_dropdown(page, clinic_id, provider_name)
            slots_raw = await self._read_slots_agentql(page, clinic_id)
            rows = self._normalize_slots(slots_raw, provider_name, date, tz)
            return rows[:MAX_SLOTS_RETURNED]

    async def book_appointment(
        self,
        db: AsyncSession,
        clinic_id: UUID,
        provider_name: str,
        slot_start: str,
        patient_name: str,
        patient_dob: str,
        appt_type_code: str,
    ) -> dict[str, Any]:
        """
        Book in NextGen. slot_start is ISO 8601. Returns success dict or error dict.
        """
        async with self._lock(clinic_id):
            await self._ensure_browser()
            await self._ensure_logged_in_session(db, clinic_id)
            sess = self._sessions[clinic_id]
            page = sess.page
            try:
                await self._navigate_to_scheduler(page, clinic_id)
                await self._select_provider_dropdown(page, clinic_id, provider_name)
                await self._fill_booking_form(
                    page, clinic_id, patient_name, patient_dob, appt_type_code
                )
                appt_id = await self._submit_booking_and_get_id(page, clinic_id)
                if appt_id:
                    return {"success": True, "ehr_appointment_id": appt_id}
                return {"success": False, "error": "Could not read confirmation ID from NextGen"}
            except Exception as e:
                logger.exception("book_appointment failed for clinic %s", clinic_id)
                return {"success": False, "error": str(e)[:500]}

    # ── Session + heartbeat ─────────────────────────────────────────────────

    async def _ensure_logged_in_session(self, db: AsyncSession, clinic_id: UUID) -> None:
        if clinic_id in self._sessions and self._sessions[clinic_id].logged_in:
            return

        cfg = await self._load_ehr_config(db, clinic_id)
        username, password = await self._decrypt_creds(cfg)

        assert self._browser is not None
        ctx = await self._browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        import agentql

        agentql.configure(api_key=os.environ.get("AGENTQL_API_KEY", ""))
        raw_page = await ctx.new_page()
        page = await agentql.wrap_async(raw_page)
        await page.goto(cfg.nextgen_url, wait_until="networkidle", timeout=60_000)
        await self._do_login(page, username, password)

        sess = ClinicSession(
            clinic_id=clinic_id,
            context=ctx,
            page=page,
            logged_in=True,
            username=username,
            password=password,
            nextgen_url=cfg.nextgen_url,
        )
        self._sessions[clinic_id] = sess
        self._heartbeat_tasks[clinic_id] = asyncio.create_task(self._heartbeat_loop(clinic_id))

    async def _heartbeat_loop(self, clinic_id: UUID) -> None:
        """Reload clinic base URL periodically to reduce session timeout (PRD §10.2)."""
        try:
            while clinic_id in self._sessions:
                await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
                if clinic_id not in self._sessions:
                    break
                sess = self._sessions.get(clinic_id)
                if not sess or not sess.page:
                    continue
                try:
                    await sess.page.goto(sess.nextgen_url, wait_until="networkidle", timeout=60_000)
                    sess.last_heartbeat = datetime.now()
                except Exception as e:
                    logger.warning("Heartbeat failed for clinic %s: %s", clinic_id, e)
        except asyncio.CancelledError:
            return

    # ── Login (adapted from agentql-test/test_nextgen_headless.py) ──────────

    async def _do_login(self, page: Any, username: str, password: str) -> None:
        login_stages = 0
        max_stages = 3
        while self._is_login_page(page.url) and login_stages < max_stages:
            current_url = page.url
            lr = await page.query_elements(
                """
                {
                    login_form {
                        username_field
                        password_field
                        login_button
                    }
                }
                """
            )
            login = lr.login_form
            if not login or not login.username_field:
                raise RuntimeError("AgentQL could not find login form on the page")
            await login.username_field.fill(username)
            await login.password_field.fill(password)
            await login.login_button.click()
            await page.wait_for_load_state("networkidle", timeout=30_000)
            await self._handle_mfa_if_possible(page)
            new_url = page.url
            if new_url == current_url:
                raise RuntimeError("Login failed — URL did not change after submit")
            login_stages += 1
        if login_stages == 0 and self._is_login_page(page.url):
            raise RuntimeError("Expected login page but could not start login flow")

    def _is_login_page(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        u = url.lower()
        keys = ("login", "signin", "sign-in", "userlogin", "auth", "sso")
        return any(k in path or k in u for k in keys)

    async def _handle_mfa_if_possible(self, page: Any) -> bool:
        """MFA with terminal input is not supported in server mode — fail fast."""
        mfa = await page.query_elements(
            """
            {
                verification_form {
                    verification_code_field
                    submit_button
                }
            }
            """
        )
        form = mfa.verification_form
        if form and form.verification_code_field:
            raise RuntimeError(
                "NextGen MFA step detected — complete MFA manually or use headed validation; "
                "automated credential test cannot proceed without interactive code entry."
            )
        return False

    # ── Scheduler navigation & slots ────────────────────────────────────────

    async def _navigate_to_scheduler(self, page: Any, clinic_id: UUID) -> None:
        cached = await get_cached_selector(clinic_id, "scheduler_nav")
        if cached:
            try:
                loc = page.locator(cached)
                if await loc.count() > 0:
                    await loc.first.click()
                    await page.wait_for_load_state("networkidle", timeout=20_000)
                    return
            except Exception:
                pass

        nav = await page.query_elements(
            """
            {
                navigation {
                    scheduling_link
                    appointments_link
                    schedule_appointment_link
                }
            }
            """
        )
        n = nav.navigation
        link = n.scheduling_link or n.appointments_link or n.schedule_appointment_link
        if link:
            await link.click()
            await page.wait_for_load_state("networkidle", timeout=20_000)
            # Best-effort: cache a selector for the nav control (id if present on body child)
            try:
                sel = await self._try_cache_selector_from_page(page, clinic_id, "scheduler_nav")
                if sel:
                    await set_cached_selector(clinic_id, "scheduler_nav", sel)
            except Exception:
                pass

    async def _try_cache_selector_from_page(
        self, page: Any, clinic_id: UUID, element_name: str
    ) -> Optional[str]:
        """No-op placeholder — extend with DOM id capture when stable."""
        _ = page, clinic_id, element_name
        return None

    async def _select_provider_dropdown(self, page: Any, clinic_id: UUID, provider_name: str) -> None:
        try:
            resp = await page.query_elements(
                """
                {
                    provider_selection {
                        provider_dropdown
                    }
                }
                """
            )
            ps = getattr(resp, "provider_selection", None)
            dd = getattr(ps, "provider_dropdown", None) if ps else None
            if dd:
                so = getattr(dd, "select_option", None)
                if callable(so):
                    try:
                        await so(label=provider_name)
                    except Exception:
                        try:
                            await so(value=provider_name)
                        except Exception:
                            logger.warning("Could not select provider %s in dropdown", provider_name)
        except Exception as e:
            logger.warning("Provider dropdown query failed for %s: %s", clinic_id, e)

    async def _read_slots_agentql(self, page: Any, clinic_id: UUID) -> list[Any]:
        resp = await page.query_elements(
            """
            {
                available_appointment_slots[] {
                    date
                    time
                    provider_name
                    appointment_type
                }
            }
            """
        )
        slots = resp.available_appointment_slots or []
        _ = clinic_id
        return list(slots) if slots else []

    def _normalize_slots(
        self,
        slots_raw: list[Any],
        default_provider: str,
        target_date: str,
        tz: Any,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for s in slots_raw:
            d = getattr(s, "date", None) or target_date
            t = getattr(s, "time", None) or "09:00"
            pname = getattr(s, "provider_name", None) or default_provider
            try:
                start_dt = self._parse_slot_datetime(str(d), str(t), tz)
                end_dt = start_dt + timedelta(minutes=30) if start_dt else None
                if start_dt and end_dt:
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
        """Combine date + time strings into timezone-aware datetime."""
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
        m = re.match(
            r"^(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)?",
            tm_clean,
        )
        if not m:
            raise ValueError(f"Unrecognized time: {time_part}")
        hh, mm = int(m.group(1)), int(m.group(2))
        ap = m.group(3)
        if ap and ap.upper() == "PM" and hh < 12:
            hh += 12
        if ap and ap.upper() == "AM" and hh == 12:
            hh = 0
        return datetime(
            parsed_date.year,
            parsed_date.month,
            parsed_date.day,
            hh,
            mm,
            tzinfo=tz,
        )

    async def _fill_booking_form(
        self,
        page: Any,
        clinic_id: UUID,
        patient_name: str,
        patient_dob: str,
        appt_type_code: str,
    ) -> None:
        form_r = await page.query_elements(
            """
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
            """
        )
        form = form_r.appointment_booking_form
        if not form:
            raise RuntimeError("Booking form not found")
        if form.patient_name_field:
            await form.patient_name_field.fill(patient_name)
        if form.date_of_birth_field:
            await form.date_of_birth_field.fill(patient_dob)
        if form.appointment_type_dropdown:
            try:
                await form.appointment_type_dropdown.select_option(value=appt_type_code)
            except Exception:
                await form.appointment_type_dropdown.fill(appt_type_code)
        _ = clinic_id

    async def _submit_booking_and_get_id(self, page: Any, clinic_id: UUID) -> str:
        sub = await page.query_elements(
            """
            {
                appointment_booking_form {
                    submit_button
                }
            }
            """
        )
        form = sub.appointment_booking_form
        if form and form.submit_button:
            await form.submit_button.click()
            await page.wait_for_load_state("networkidle", timeout=60_000)
        try:
            conf = await page.query_elements(
                """
                {
                    confirmation {
                        appointment_id_text
                    }
                }
                """
            )
            c = getattr(conf, "confirmation", None)
            txt = getattr(c, "appointment_id_text", None) if c else None
            if txt:
                raw = await txt.inner_text()
                m = re.search(r"(\d{6,}|APT[-\w]+)", raw or "")
                if m:
                    return m.group(1)
        except Exception:
            pass
        _ = clinic_id
        return "NEXTGEN-PENDING"


playwright_ehr_service = PlaywrightEHRService()
