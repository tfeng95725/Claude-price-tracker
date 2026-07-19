"""
Price & size-availability checker.

Reads items.json (what to track), visits each URL with a headless browser,
extracts price + size availability, compares against data.json (last known
state), and emails you when there's real news (a price drop or a size
becoming available).

If a page can't be read, this tries multiple times with different browser
settings before giving up. Only after all attempts fail does it log the
failure to failures.json — those get emailed as one weekly digest by
weekly_digest.py, not one-by-one.
"""

import json
import os
import re
import smtplib
import ssl
import sys
import time
import traceback
from datetime import datetime, timezone
from email.mime.text import MIMEText

from playwright.sync_api import sync_playwright

ITEMS_FILE = "items.json"
DATA_FILE = "data.json"
FAILURES_FILE = "failures.json"

MAX_ATTEMPTS = 4

# Rotate between a couple of realistic browser fingerprints across retries,
# since a fresh look sometimes gets past a block that a repeated one won't.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

BLOCK_INDICATORS = [
    "captcha",
    "are you a human",
    "access denied",
    "unusual traffic",
    "verify you are a human",
    "robot check",
    "pardon our interruption",
]


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def looks_blocked(text):
    lower = text.lower()
    return any(k in lower for k in BLOCK_INDICATORS)


def extract_price(page):
    """Best-effort price extraction: JSON-LD structured data first, then
    meta tags, then a plain-text $xx.xx fallback."""
    try:
        scripts = page.query_selector_all('script[type="application/ld+json"]')
        for s in scripts:
            try:
                blob = json.loads(s.inner_text())
            except Exception:
                continue
            candidates = blob if isinstance(blob, list) else [blob]
            for c in candidates:
                if not isinstance(c, dict):
                    continue
                offers = c.get("offers")
                if not offers:
                    continue
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                price = offers.get("price") or offers.get("lowPrice")
                if price:
                    return float(str(price).replace(",", ""))
    except Exception:
        pass

    try:
        for prop in ("product:price:amount", "og:price:amount"):
            el = page.query_selector(f'meta[property="{prop}"]')
            if el:
                content = el.get_attribute("content")
                if content:
                    return float(content.replace(",", ""))
    except Exception:
        pass

    try:
        text = page.inner_text("body")
        matches = re.findall(r"\$\s?(\d{1,4}(?:\.\d{2})?)", text)
        if matches:
            prices = sorted(float(m) for m in matches)
            return prices[0]
    except Exception:
        pass
    return None


def extract_available_sizes(page):
    """Returns {size_label: is_available} for whatever size controls we can
    find. Selectors are best-effort and may need tuning per site."""
    sizes = {}
    selectors = [
        '[data-testid*="size" i] button',
        'button[aria-label*="size" i]',
        '.product-variations button',
        'fieldset button',
    ]
    for sel in selectors:
        try:
            buttons = page.query_selector_all(sel)
        except Exception:
            continue
        for b in buttons:
            label = (b.get_attribute("aria-label") or b.inner_text() or "").strip()
            if not label or len(label) > 20:
                continue
            disabled = (
                b.get_attribute("aria-disabled") == "true"
                or b.get_attribute("disabled") is not None
                or "unavailable" in (b.get_attribute("class") or "").lower()
                or "sold out" in label.lower()
            )
            sizes[label] = not disabled
        if sizes:
            break
    return sizes


def check_item_with_retries(playwright, item, max_attempts=MAX_ATTEMPTS):
    """Try hard before giving up: multiple attempts, rotating user agents,
    longer waits, and explicit detection of bot-block pages so we can
    back off and retry rather than immediately reporting failure."""
    last_reason = None
    for attempt in range(1, max_attempts + 1):
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context(
                user_agent=USER_AGENTS[attempt % len(USER_AGENTS)],
                viewport={"width": 1280, "height": 900},
                locale="en-US",
            )
            page = context.new_page()
            page.goto(item["url"], timeout=45000, wait_until="domcontentloaded")
            # Wait a bit longer on each successive attempt, in case slow
            # client-side rendering (not blocking) is the real issue.
            page.wait_for_timeout(3000 + attempt * 2000)

            body_text = page.inner_text("body")
            if looks_blocked(body_text):
                last_reason = "the site returned a bot-check/CAPTCHA page"
                time.sleep(4 * attempt)
                continue

            price = extract_price(page)
            sizes = extract_available_sizes(page)
            if price is not None:
                return price, sizes, None  # success

            last_reason = "page loaded but no price could be found (layout may have changed)"
            time.sleep(2 * attempt)
        except Exception as e:
            last_reason = f"error loading page: {e}"
            time.sleep(2 * attempt)
        finally:
            browser.close()

    return None, {}, last_reason


def send_email(subject, body):
    user = os.environ["GMAIL_USER"]
    app_password = os.environ["GMAIL_APP_PASSWORD"]
    to_addr = os.environ.get("NOTIFY_EMAIL", user)

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
        server.login(user, app_password)
        server.sendmail(user, [to_addr], msg.as_string())


def main():
    items = load_json(ITEMS_FILE, [])
    data = load_json(DATA_FILE, {})
    failures = load_json(FAILURES_FILE, [])
    price_drops = []
    size_alerts = []
    errors = []
    now = datetime.now(timezone.utc).isoformat()

    with sync_playwright() as p:
        for item in items:
            prev = data.get(item["id"], {})
            prev_price = prev.get("price")
            prev_sizes = prev.get("sizes", {}) or {}

            price, sizes, fail_reason = check_item_with_retries(p, item)
            status = "ok" if price is not None else "could_not_read_price"

            if fail_reason:
                failures.append({
                    "when": now,
                    "name": item["name"],
                    "url": item["url"],
                    "reason": fail_reason,
                })
                errors.append(f"{item['name']}: {fail_reason}")

            if item.get("track_price") and price is not None and prev_price is not None:
                if price < prev_price:
                    price_drops.append(
                        f"PRICE DROP - {item['name']}: ${prev_price} -> ${price}\n{item['url']}"
                    )

            for sz in item.get("track_sizes", []):
                now_avail = sizes.get(sz, False)
                was_avail = prev_sizes.get(sz, False)
                if now_avail and not was_avail:
                    size_alerts.append(
                        f"SIZE AVAILABLE - {item['name']}: size {sz} is back in stock\n{item['url']}"
                    )

            data[item["id"]] = {
                "name": item["name"],
                "url": item["url"],
                "price": price,
                "sizes": sizes,
                "last_checked": now,
                "status": status,
            }

    save_json(DATA_FILE, data)
    save_json(FAILURES_FILE, failures)

    if price_drops:
        send_email("[Claude: price drop update]", "\n\n".join(price_drops))

    if size_alerts:
        send_email("[Claude: item availability update]", "\n\n".join(size_alerts))

    if errors:
        print("Failed after retries (logged for weekly digest, not emailed now):\n" + "\n".join(errors), file=sys.stderr)


if __name__ == "__main__":
    main()
