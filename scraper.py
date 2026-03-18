from playwright.sync_api import sync_playwright
import re


def extract_sections(description):
    responsibilities = []
    qualifications = []
    intro = []

    text = description.replace("\u2022", "\n- ")

    sections = re.split(
        r"(Primary Responsibilities|Key Responsibilities|Responsibilities|Qualifications)",
        text,
        flags=re.IGNORECASE
    )

    current_section = "intro"

    for part in sections:
        part = part.strip()

        if re.search(r"Responsibilities", part, re.IGNORECASE):
            current_section = "resp"
            continue
        elif re.search(r"Qualifications", part, re.IGNORECASE):
            current_section = "qual"
            continue

        if current_section == "intro":
            intro.append(part)
        elif current_section == "resp":
            responsibilities.append(part)
        elif current_section == "qual":
            qualifications.append(part)

    return (
        "\n".join(intro).strip(),
        "\n".join(responsibilities).strip(),
        "\n".join(qualifications).strip()
    )


def scrape_workday(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        page.goto(url, timeout=60000)
        page.wait_for_selector("div[data-automation-id='jobPostingDescription']", timeout=15000)

        title = page.locator("h2[data-automation-id='jobPostingHeader']").inner_text()
        description = page.locator("div[data-automation-id='jobPostingDescription']").inner_text()

        browser.close()

    intro, responsibilities, qualifications = extract_sections(description)

    return {
        "title": title,
        "company": "UNKNOWN",
        "description": description,
        "intro": intro,
        "responsibilities": responsibilities,
        "qualifications": qualifications,
        "url": url,
    }


def save_page_as_pdf(url, output_path):
    """Navigate to URL in headless browser and save as PDF."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=60000, wait_until="networkidle")
        page.pdf(path=output_path, format="A4", print_background=True)
        browser.close()
    print(f"  Job page PDF: {output_path}")
