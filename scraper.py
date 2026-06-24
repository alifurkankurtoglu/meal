#!/usr/bin/env python3
"""
Vestel Portal - Günlük Öğle Yemeği Menüsü Scraper (Playwright)
GitHub Actions her gün 06:00 UTC (09:00 TR) tetikler.
"""

import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

PORTAL_URL = "https://portal.vestel.com.tr/irj/portal"

PORTAL_USER = os.environ["PORTAL_USER"]
PORTAL_PASS = os.environ["PORTAL_PASS"]
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
RECIPIENTS = [r.strip() for r in os.environ["MAIL_RECIPIENTS"].split(",")]


def get_menu() -> list[str]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print("→ Portal açılıyor…")
        page.goto(PORTAL_URL, wait_until="networkidle", timeout=60_000)

        # Login formu — SAP portal çeşitli input name'leri kullanabilir
        LOGIN_USER_SELECTORS = [
            'input[name="j_user"]',
            'input[id*="logonuid"]',
            'input[id*="username"]',
            'input[type="text"]',
        ]
        LOGIN_PASS_SELECTORS = [
            'input[name="j_password"]',
            'input[id*="logonpass"]',
            'input[type="password"]',
        ]

        user_input = None
        for sel in LOGIN_USER_SELECTORS:
            loc = page.locator(sel).first
            if loc.count() > 0:
                user_input = loc
                print(f"  User input bulundu: {sel}")
                break

        if user_input:
            pass_input = None
            for sel in LOGIN_PASS_SELECTORS:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    pass_input = loc
                    print(f"  Pass input bulundu: {sel}")
                    break

            if pass_input:
                user_input.fill(PORTAL_USER)
                pass_input.fill(PORTAL_PASS)
                page.locator('input[type="submit"], button[type="submit"]').first.click()
                page.wait_for_load_state("networkidle", timeout=60_000)
                print(f"  Login sonrası URL: {page.url}")
            else:
                print("  ⚠ Şifre alanı bulunamadı")
        else:
            print("  ⚠ Login formu bulunamadı — tüm input'lar:")
            for inp in page.locator("input").all():
                print(f"    {inp.get_attribute('name')} / {inp.get_attribute('type')} / {inp.get_attribute('id')}")

        # Sayfanın iView'larının yüklenmesi için kısa bekle
        print("→ Menü aranıyor…")
        page.wait_for_timeout(5000)

        # Menü kalemlerini topla — JSF PrimeFaces dt.ui-datalist-item
        items: list[str] = []

        # Yemek Menüsü bir iView/iframe içinde — tüm frame'leri tara
        meal_frame = None
        for frame in page.frames:
            try:
                if frame.locator('dt.ui-datalist-item').count() > 0:
                    meal_frame = frame
                    print(f"  Meal frame bulundu: {frame.url}")
                    break
            except Exception:
                pass

        if meal_frame is None:
            print("  ⚠ Meal frame bulunamadı. Tüm frame URL'leri:")
            for f in page.frames:
                print(f"    {f.url}")
            browser.close()
            return []

        # Öğle yemeği: mealAccordionPanel:1 (index 1)
        oglen_panel = meal_frame.locator('[id*="mealAccordionPanel:1"] dt.ui-datalist-item')
        if oglen_panel.count() == 0:
            oglen_panel = meal_frame.locator('dt.ui-datalist-item')

        for dt in oglen_panel.all():
            text = dt.inner_text().strip()
            if text and len(text) > 2:
                items.append(text)

        browser.close()
        print(f"  {len(items)} kalem bulundu")
        return items


def build_email(items: list[str], date_str: str):
    subject = f"Bugünkü Öğle Yemeği Menüsü — {date_str}"
    html_items = "".join(f"<li>{item}</li>" for item in items)
    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:520px;margin:auto">
      <h2 style="color:#c0392b;border-bottom:2px solid #c0392b;padding-bottom:8px">
        Öğle Yemeği Menüsü
      </h2>
      <p style="color:#555">{date_str} &middot; 12:00 / 20:00 / 00:00</p>
      <ul style="font-size:15px;line-height:2">{html_items}</ul>
      <p style="color:#aaa;font-size:12px;margin-top:24px">Bu e-posta otomatik olarak gönderilmiştir.</p>
    </body></html>
    """
    plain = f"Öğle Yemeği Menüsü — {date_str}\n\n" + "\n".join(f"• {i}" for i in items)
    return subject, html, plain


def send_email(subject: str, html: str, plain: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = ", ".join(RECIPIENTS)
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, RECIPIENTS, msg.as_string())

    print(f"✓ Mail gönderildi → {', '.join(RECIPIENTS)}")


def main() -> None:
    from datetime import date
    today = date.today().strftime("%d %B %Y")

    items = get_menu()
    if not items:
        print("⚠ Menü bulunamadı, mail gönderilmedi.", file=sys.stderr)
        sys.exit(1)
    print(f"✓ {len(items)} kalem: {items}")

    subject, html, plain = build_email(items, today)
    send_email(subject, html, plain)


if __name__ == "__main__":
    main()
