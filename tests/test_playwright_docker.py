"""
Feature 0 — Integration tests: Playwright runtime environment
--------------------------------------------------------------
These tests verify that Playwright and AgentQL are correctly installed
and that headless Chromium can launch in this environment (local or Docker).

They do NOT connect to NextGen — they only confirm the runtime is available.

Run locally:
    pytest tests/test_playwright_docker.py -v -m integration

Run inside Docker container (verifies production environment):
    docker compose -f docker-compose.dev.yaml run --rm app \
        pytest tests/test_playwright_docker.py -v -m integration

If playwright or agentql are not yet installed, tests are skipped with a
clear install instruction — they do not fail the suite.
"""

import pytest


# --------------------------------------------------------------------------- #
# Playwright runtime checks                                                   #
# --------------------------------------------------------------------------- #

@pytest.mark.integration
@pytest.mark.slow
class TestPlaywrightRuntime:
    """
    Confirms Playwright + Chromium are installed and launchable.
    These tests are the gate before running test_nextgen_headless.py manually.
    """

    @pytest.mark.asyncio
    async def test_playwright_package_is_importable(self):
        """playwright Python package must be importable."""
        try:
            from playwright.async_api import async_playwright  # noqa: F401
        except ImportError:
            pytest.fail(
                "playwright is not installed.\n"
                "Run: pip install playwright && playwright install chromium"
            )

    @pytest.mark.asyncio
    async def test_chromium_launches_headlessly(self):
        """
        Playwright can launch headless Chromium and load about:blank.
        This is the minimum viability check for server-side EHR automation.
        Confirms PLAYWRIGHT_BROWSERS_PATH is set correctly in Docker.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            pytest.skip(
                "playwright not installed — run: pip install playwright && playwright install chromium"
            )

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto("about:blank")
            title = await page.title()
            await browser.close()

        assert title == "", f"Expected empty title for about:blank, got: '{title}'"

    @pytest.mark.asyncio
    async def test_chromium_can_load_external_url(self):
        """
        Playwright can reach an external URL from inside the container.
        Confirms Docker networking is not blocking outbound HTTPS (needed for NextGen).
        Uses example.com — stable, no auth, fast.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            pytest.skip("playwright not installed")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            response = await page.goto("https://example.com", timeout=15_000)
            status = response.status if response else None
            await browser.close()

        assert status == 200, (
            f"Could not reach example.com (status={status}). "
            "Check outbound HTTPS connectivity from this environment."
        )

    @pytest.mark.asyncio
    async def test_playwright_browser_context_has_correct_viewport(self):
        """Browser context can be created with the viewport we'll use for NextGen."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            pytest.skip("playwright not installed")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )
            page = await context.new_page()
            viewport = page.viewport_size
            await browser.close()

        assert viewport is not None
        assert viewport["width"] == 1280
        assert viewport["height"] == 900


# --------------------------------------------------------------------------- #
# AgentQL runtime checks                                                      #
# --------------------------------------------------------------------------- #

@pytest.mark.integration
class TestAgentQLRuntime:
    """
    Confirms AgentQL is installed and has the async API we depend on.
    Does not make any AgentQL API calls — just checks the package interface.
    """

    def test_agentql_package_is_importable(self):
        """agentql Python package must be importable."""
        try:
            import agentql  # noqa: F401
        except ImportError:
            pytest.fail(
                "agentql is not installed.\n"
                "Run: pip install agentql"
            )

    def test_agentql_has_wrap_async(self):
        """agentql must expose wrap_async() — the async page wrapper we use in PlaywrightEHRService."""
        try:
            import agentql
        except ImportError:
            pytest.skip("agentql not installed")

        assert hasattr(agentql, "wrap_async"), (
            "agentql.wrap_async not found. "
            "Check agentql version — this is the async API required by PlaywrightEHRService."
        )

    def test_agentql_has_configure(self):
        """agentql must expose configure() for API key injection."""
        try:
            import agentql
        except ImportError:
            pytest.skip("agentql not installed")

        assert hasattr(agentql, "configure"), (
            "agentql.configure not found. "
            "API key must be injected via agentql.configure(api_key=...) before any query."
        )

    @pytest.mark.asyncio
    async def test_agentql_wraps_playwright_page(self):
        """
        agentql.wrap_async() must accept a Playwright Page and return a
        wrapped page that exposes query_elements().
        """
        try:
            import agentql
            from playwright.async_api import async_playwright
        except ImportError:
            pytest.skip("playwright or agentql not installed")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            raw_page = await browser.new_page()

            wrapped_page = await agentql.wrap_async(raw_page)
            assert hasattr(wrapped_page, "query_elements"), (
                "Wrapped page missing query_elements(). "
                "agentql API may have changed — check agentql docs."
            )

            await browser.close()
