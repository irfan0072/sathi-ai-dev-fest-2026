#!/usr/bin/env python3
"""Browser smoke check of the running console (desktop and phone width). Synthetic demo only.

Needs a running API and console, plus Playwright with Chromium (``pip install playwright`` and
``playwright install chromium``; not part of the project's dependencies).

    python scripts/browser_smoke.py --console http://127.0.0.1:13010 [--shots DIR]

Checks, through real clicks on the real UI against the real API (nothing is stubbed):
sign-in screen labels, supervisor sign-in, the call queue and the follow-up tab, the workflow
evidence page, the agent cash-out page, a phone-width layout with no horizontal overflow, and no
uncaught page errors. It does not place calls or send messages: the demo provider is simulated.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PHONE = {"width": 390, "height": 844}
DESKTOP = {"width": 1366, "height": 850}


def overflow(page) -> int:
    return page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth")


def sign_in(page, console: str, role_label: str) -> None:
    page.goto(console)
    page.get_by_text(role_label, exact=True).first.click()
    page.get_by_role("button", name="Sign in").last.click()
    page.wait_for_selector("header", timeout=15000)


def press(page, keys: str) -> None:
    """Tap the on-screen keypad of the simulated handset."""
    for key in keys:
        page.locator("button.h-12").filter(
            has=page.locator("span", has_text=re.compile(rf"^{re.escape(key)}$"))).first.click()


def ui_workflow(browser, console: str, shots: Path | None) -> list[str]:
    """Agent cash-out -> customer types a wrong amount twice -> supervisor sees the follow-up."""
    problems: list[str] = []
    agent = browser.new_context(viewport=DESKTOP)
    page = agent.new_page()
    sign_in(page, console, "Agent")
    page.get_by_role("button", name="Cash-out", exact=True).first.click()
    page.wait_for_function(
        "document.querySelector('select') && document.querySelector('select').value",
        timeout=15000)
    page.get_by_label("Cash given").fill("500")
    page.get_by_role("button", name="Record cash-out").click()
    page.wait_for_timeout(2500)
    text = page.inner_text("body").lower()
    for forbidden in ("suspicious", "mismatch", "duress", "follow-up"):
        if forbidden in text:
            problems.append(f"agent screen shows '{forbidden}' after a cash-out")
    agent.close()

    customer = browser.new_context(viewport=PHONE)
    page = customer.new_page()
    sign_in(page, console, "Customer")
    page.get_by_role("button", name="Answer call").wait_for(timeout=20000)
    page.get_by_role("button", name="Answer call").click()
    for _ in range(2):  # the real cash was 500; the customer types 400 twice
        press(page, "400#")
        page.wait_for_timeout(1200)
    page.wait_for_timeout(1500)
    if shots:
        page.screenshot(path=str(shots / "phone-customer-after-call.png"))
    customer.close()

    staff = browser.new_context(viewport=DESKTOP)
    page = staff.new_page()
    sign_in(page, console, "Supervisor")
    page.get_by_role("button", name="Call queue").first.click()
    page.get_by_role("tab", name="Independent follow-up").first.click()
    try:
        page.wait_for_selector("text=Independent contact needed", timeout=20000)
    except Exception:
        problems.append("supervisor follow-up tab does not show the suspicious check")
    if shots:
        page.screenshot(path=str(shots / "desktop-followup-queue.png"), full_page=True)
    staff.close()
    return problems


def run(console: str, shots: Path | None, workflow: bool = False) -> list[str]:
    problems: list[str] = []
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, size in (("desktop", DESKTOP), ("phone", PHONE)):
            context = browser.new_context(viewport=size)
            page = context.new_page()
            page.on("pageerror", lambda exc, n=name: errors.append(f"{n}: {exc}"))
            page.goto(console)
            page.wait_for_selector("text=Sign in", timeout=15000)
            body = page.inner_text("body")
            for needle in ("Hackathon concept", "synthetic"):
                if needle.lower() not in body.lower():
                    problems.append(f"{name}: sign-in screen lacks '{needle}'")
            if overflow(page) > 1:
                problems.append(
                    f"{name}: sign-in screen overflows horizontally by {overflow(page)}px")
            if shots:
                page.screenshot(path=str(shots / f"{name}-signin.png"), full_page=True)

            sign_in(page, console, "Supervisor")
            banner = page.inner_text("body")
            if "not endorsed by upay" not in banner:
                problems.append(f"{name}: concept/endorsement banner missing after sign-in")
            if name == "desktop":
                try:
                    page.wait_for_selector("[data-testid=deployment-mode]", timeout=8000)
                except Exception:
                    problems.append("desktop: 'Public simulated demo' chip missing")
                page.get_by_role("button", name="Call queue").first.click()
                page.wait_for_selector("text=Independent follow-up", timeout=15000)
                page.get_by_role("tab", name="Independent follow-up").first.click()
                page.wait_for_timeout(800)
                page.get_by_role("button", name="Workflow evidence").first.click()
                page.wait_for_selector("[data-testid=evidence-source]", timeout=15000)
                text = page.inner_text("body")
                if "field impact" not in text.lower() or "none measured" not in text.lower():
                    problems.append("desktop: evidence page does not state that no field impact "
                                    "was measured")
            else:
                for label in ("Workflow evidence", "Call queue"):
                    page.goto(console)
                    page.wait_for_selector("header", timeout=15000)
                    page.locator("label[for=sathi-drawer]").first.click()
                    page.get_by_role("button", name=label).first.click()
                    page.wait_for_timeout(1200)
                    if overflow(page) > 1:
                        problems.append(
                            f"phone: '{label}' overflows horizontally by {overflow(page)}px")
                    if shots:
                        page.screenshot(path=str(shots / f"phone-{label.replace(' ', '-')}.png"))
            if shots and name == "desktop":
                page.screenshot(path=str(shots / "desktop-evidence.png"), full_page=True)
            context.close()
        if workflow:
            problems += ui_workflow(browser, console, shots)
        browser.close()
    problems += errors
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--console", default="http://127.0.0.1:13010")
    parser.add_argument("--shots", default=None, help="directory for screenshots (optional)")
    parser.add_argument("--workflow", action="store_true",
                        help="also drive agent -> customer -> supervisor through the UI "
                             "(creates one small synthetic cash-out in the demo database)")
    args = parser.parse_args()
    shots = Path(args.shots) if args.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    problems = run(args.console, shots, args.workflow)
    if problems:
        print("BROWSER SMOKE: PROBLEMS")
        print("\n".join(f"- {p}" for p in problems))
        return 1
    print("BROWSER SMOKE: all checks passed (desktop and phone width)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
