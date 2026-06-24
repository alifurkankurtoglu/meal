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

from groq import Groq
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

PORTAL_URL = "https://portal.vestel.com.tr/irj/portal"

PORTAL_USER = os.environ["PORTAL_USER"]
PORTAL_PASS = os.environ["PORTAL_PASS"]
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
_raw_recipients = os.environ["MAIL_RECIPIENTS"].replace(";", ",")
RECIPIENTS = [r.strip() for r in _raw_recipients.split(",") if r.strip()]


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

        # Direkt VestelPortal sayfasına git (bilinen meal URL)
        print("→ Menü sayfasına gidiliyor…")
        MEAL_URL = "https://portal.vestel.com.tr/VestelPortal/index.xhtml"
        page.goto(MEAL_URL, wait_until="networkidle", timeout=60_000)
        print(f"  Meal URL status: {page.url}")

        items: list[str] = []

        # Accordion başlıklarını listele (debug)
        headers = page.locator('[id*="mealAccordionPanel"][id$="_header"]').all()
        print(f"  Accordion header sayısı: {len(headers)}")
        for i, h in enumerate(headers):
            print(f"    [{i}] id={h.get_attribute('id')} text={h.inner_text()[:50]}")

        # Öğle Yemeği accordion'ını bul ve aç
        oglen_header = page.locator('[id*="mealAccordionPanel:1_header"]')
        if oglen_header.count() > 0:
            oglen_header.first.click()
            page.wait_for_timeout(2000)
            print("  Öğle accordion'ı tıklandı")
        else:
            # Text ile bul
            oglen_header = page.locator('text=/[ÖO]ğle Yeme/i').first
            if oglen_header.count() > 0:
                oglen_header.click()
                page.wait_for_timeout(2000)
                print("  Öğle accordion text ile tıklandı")

        # Öğle yemeği kalemlerini al
        oglen_items = page.locator('[id*="mealAccordionPanel:1"] dt.ui-datalist-item')
        if oglen_items.count() == 0:
            oglen_items = page.locator('[aria-hidden="false"] dt.ui-datalist-item, [style*="display: block"] dt.ui-datalist-item')
        print(f"  Öğle dt count: {oglen_items.count()}")

        for dt in oglen_items.all():
            text = dt.inner_text().strip()
            if text and len(text) > 2:
                items.append(text)

        browser.close()
        print(f"  {len(items)} kalem bulundu")
        return items


def generate_comment(items: list[str]) -> str:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return ""
    try:
        menu_text = ", ".join(items)
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": (
                    f"Bugünkü öğle yemeği menüsü: {menu_text}\n\n"
                    "Bu menü için kısa, esprili ve Türkçe bir yorum yaz. "
                    "Maksimum 2 cümle olsun, samimi ve neşeli bir ton kullan. "
                    "Sadece yorumu yaz, başka bir şey ekleme."
                ),
            }],
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"  ⚠ AI yorum üretilemedi: {e}")
        return ""


def build_email(items: list[str], date_str: str, comment: str = ""):
    subject = f"Bugünkü Öğle Yemeği Menüsü — {date_str}"
    html_items = "".join(f"<li>{item}</li>" for item in items)
    comment_html = (
        f'<p style="font-size:15px;color:#2c3e50;background:#fef9e7;'
        f'border-left:4px solid #f39c12;padding:10px 14px;border-radius:4px;'
        f'margin:16px 0">💬 {comment}</p>'
        if comment else ""
    )
    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:520px;margin:auto">
      <h2 style="color:#c0392b;border-bottom:2px solid #c0392b;padding-bottom:8px">
        Öğle Yemeği Menüsü
      </h2>
      <p style="color:#555">{date_str} &middot; 12:00 / 20:00 / 00:00</p>
      {comment_html}
      <ul style="font-size:15px;line-height:2">{html_items}</ul>
      <p style="color:#aaa;font-size:12px;margin-top:24px">Bu e-posta otomatik olarak gönderilmiştir.</p>
    </body></html>
    """
    plain = f"Öğle Yemeği Menüsü — {date_str}\n\n"
    if comment:
        plain += f"💬 {comment}\n\n"
    plain += "\n".join(f"• {i}" for i in items)
    return subject, html, plain


def send_email(subject: str, html: str, plain: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = GMAIL_USER
    msg["Bcc"] = ", ".join(RECIPIENTS)
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

    comment = generate_comment(items)
    subject, html, plain = build_email(items, today, comment)
    send_email(subject, html, plain)


if __name__ == "__main__":
    main()
