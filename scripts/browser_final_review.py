#!/usr/bin/env python3
# ruff: noqa: E501
"""Final browser verification: one coherent synthetic journey, then changed screens at
1366 px and 390 px in light and dark themes. Real UI, real API, public-demo mode, simulated
provider. Needs Playwright (not a project dependency). Saves screenshots.

    python scripts/browser_final_review.py --console http://127.0.0.1:13010 --out docs/screenshots/final

Prints one line per check; exit code 1 if any check fails. Creates a few small synthetic
cash-outs for the demo customer in the database the API points at.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

DESKTOP = {"width": 1366, "height": 850}
PHONE = {"width": 390, "height": 844}
results: list[tuple[bool, str]] = []


def check(ok: bool, text: str) -> None:
    results.append((bool(ok), text))
    print(("PASS " if ok else "FAIL ") + text)


def ctx(browser, size, theme="light"):
    context = browser.new_context(viewport=size)
    context.add_init_script(f"try{{localStorage.setItem('sathi-theme','{'sathi-dark' if theme == 'dark' else 'sathi'}')}}catch(e){{}}")
    return context


def sign_in(page, console, role):
    page.goto(console)
    page.get_by_text(role, exact=True).first.click()
    page.get_by_role("button", name="Sign in").last.click()
    page.wait_for_selector("header", timeout=15000)
    page.wait_for_timeout(700)  # let the drawer/fade transition settle


def nav(page, label, phone=False):
    if phone:
        page.locator("label[for=sathi-drawer]").first.click()
        page.wait_for_timeout(400)
    page.get_by_role("button", name=label, exact=True).first.click()
    page.wait_for_timeout(900)


def keys(page, typed):
    for key in typed:
        page.locator("button.h-12").filter(
            has=page.locator("span", has_text=re.compile(rf"^{re.escape(key)}$"))).first.click()


def overflow(page):
    return page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")


def journey(browser, console, out):
    # 1. agent records a cash-out of 700
    page = ctx(browser, DESKTOP).new_page()
    sign_in(page, console, "Agent")
    page.wait_for_function("document.querySelector('select') && document.querySelector('select').value")
    page.get_by_label("Cash given").fill("700")
    page.get_by_role("button", name="Record cash-out").click()
    page.wait_for_timeout(2500)
    body = page.inner_text("body").lower()
    check(not any(w in body for w in ("suspicious", "mismatch", "duress", "follow-up")),
          "agent screen stays neutral after the cash-out")
    page.screenshot(path=str(out / "journey-1-agent-cashout.png"), full_page=True)
    page.context.close()

    # 2. customer on a plain-phone style handset: unusable speech -> keypad only -> 0700#
    page = ctx(browser, PHONE).new_page()
    sign_in(page, console, "Customer")
    page.get_by_role("button", name="Answer call").wait_for(timeout=20000)
    page.get_by_role("button", name="Answer call").click()
    page.screenshot(path=str(out / "journey-2a-handset-call.png"), full_page=True)
    page.get_by_placeholder(re.compile("Or say it")).fill("umm ami bujhi nai")
    page.get_by_role("button", name="Say", exact=True).click()
    page.wait_for_selector("[data-testid=keypad-only]", timeout=10000)
    check(page.locator("[data-testid=keypad-only]").count() == 1
          and page.get_by_placeholder(re.compile("Or say it")).count() == 0,
          "unusable speech switches the handset to keypad-only (speech box gone)")
    page.screenshot(path=str(out / "journey-2b-keypad-only.png"), full_page=True)
    keys(page, "0700#")  # leading zero = secret help; same neutral ending as any outcome
    page.wait_for_timeout(2500)
    page.screenshot(path=str(out / "journey-2c-neutral-ending.png"), full_page=True)
    text = page.inner_text("body").lower()
    check("duress" not in text and "suspicious" not in text and "help signal" not in text,
          "customer screen is neutral after the secret-help answer")
    page.wait_for_timeout(2500)
    page.context.close()

    # 3. supervisor: urgent follow-up first
    page = ctx(browser, DESKTOP).new_page()
    sign_in(page, console, "Supervisor")
    nav(page, "Call queue")
    page.get_by_role("tab", name="Independent follow-up").first.click()
    page.wait_for_selector("text=Independent contact needed", timeout=20000)
    first_row = page.locator("tbody tr").first.inner_text().lower()
    check("urgent" in first_row, f"secret-help follow-up is urgent and first in the queue ({first_row[:40]!r})")
    page.locator("tbody tr").first.click()
    page.wait_for_selector("[data-testid=followup-panel]", timeout=10000)
    page.wait_for_timeout(600)
    page.screenshot(path=str(out / "journey-3-urgent-followup.png"), full_page=True)
    page.context.close()

    # 4. analyst: clearing is refused until an independent contact exists
    page = ctx(browser, DESKTOP).new_page()
    sign_in(page, console, "Fraud analyst")
    nav(page, "Cases to review")
    page.wait_for_timeout(1200)
    page.locator("li, tr, button").filter(has_text=re.compile("help|secretly", re.I)).first.click()
    page.wait_for_selector("[data-testid=followup-notice]", timeout=15000)
    check(page.locator("[data-testid=followup-notice]").count() >= 1,
          "analyst sees the independent-contact requirement before deciding")
    page.get_by_role("button", name="Cleared: no wrongdoing").click()
    page.wait_for_timeout(1200)
    refused = "independent" in page.inner_text("body").lower()
    check(refused, "clearing is refused without independent contact (server gate)")
    page.screenshot(path=str(out / "journey-4-clearance-refused.png"), full_page=True)
    page.context.close()


def settled_pages(browser, console, out):
    plan = [
        ("Agent", "Cash planning", "agent-cash-planning"),
        ("Agent", "Cash-out", "agent-history"),
        ("Customer", "My account", "customer-account"),
        ("Super admin", "Control center", "admin-control-center"),
        ("Super admin", "Test accounts", "admin-test-accounts"),
        ("Super admin", "Supervisors", "admin-staff"),
        ("Super admin", "All transactions", "admin-ledger"),
        ("Fraud analyst", "AI test results", "metrics"),
        ("Fraud analyst", "Agent review ranking", "agent-ranking"),
        ("Fraud analyst", "How it works", "how-it-works"),
    ]
    for theme in ("light", "dark"):
        for sname, size in (("desktop", DESKTOP), ("phone", PHONE)):
            for role, label, slug in plan:
                context = ctx(browser, size, theme)
                page = context.new_page()
                errors: list[str] = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                sign_in(page, console, role)
                try:
                    if label not in ("Cash-out", "My account"):
                        nav(page, label, phone=sname == "phone")
                    if slug == "metrics":
                        page.get_by_role("tab", name=re.compile("Extended")).first.click()
                        page.wait_for_selector("[data-testid=extended-benchmark]", timeout=15000)
                    if slug == "agent-cash-planning":
                        page.wait_for_timeout(6000)
                    page.wait_for_timeout(900)
                    over = overflow(page)
                    check(over <= 1 and not errors,
                          f"{slug} {sname}/{theme}: no page overflow ({over}px), no page errors")
                    page.screenshot(path=str(out / f"{slug}-{sname}-{theme}.png"), full_page=True)
                except Exception as exc:  # report and continue
                    check(False, f"{slug} {sname}/{theme}: {type(exc).__name__}: {str(exc)[:80]}")
                context.close()


def send_money(browser, console, out):
    page = ctx(browser, DESKTOP).new_page()
    sign_in(page, console, "Customer")
    nav(page, "Send money")
    for number, expect_alert, slug in (("01900000500", True, "alerted"), ("01901000002", False, "normal"),
                                       ("01955555555", False, "unknown")):
        page.get_by_placeholder(re.compile("01")).first.fill(number)
        page.get_by_role("button", name=re.compile("Check", re.I)).first.click()
        page.wait_for_selector("main [role=status]", timeout=10000)
        page.wait_for_timeout(700)
        text = page.locator("main [role=status]").first.inner_text().lower()
        if expect_alert:
            check("check before you send" in text or "be careful" in text, f"receiver {slug}: warning shown")
        else:
            check("guarantee" in text or "no community alerts" in text, f"receiver {slug}: neutral wording")
        green = page.locator("main [role=status]").first.get_attribute("class") or ""
        check("success" not in green, f"receiver {slug}: no green safety endorsement")
        page.screenshot(path=str(out / f"send-money-{slug}.png"), full_page=True)
    page.context.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--console", default="http://127.0.0.1:13010")
    parser.add_argument("--out", default="docs/screenshots/final")
    parser.add_argument("--steps", default="journey,send_money,settled_pages")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        chosen = set(args.steps.split(","))
        for step in (journey, send_money, settled_pages):
            if step.__name__ not in chosen:
                continue
            try:
                step(browser, args.console, out)
            except Exception as exc:
                check(False, f"{step.__name__} crashed: {type(exc).__name__}: {str(exc)[:200]}")
        browser.close()
    failed = [t for ok, t in results if not ok]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
