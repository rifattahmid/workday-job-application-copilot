---
name: Generic Job Ad Saver & Cover Letter Editor
description: Standalone tool that scrapes any job URL, extracts structured job data via Claude, and generates a tailored cover letter PDF using existing templates.
type: project
---

# Generic Job Ad Saver & Cover Letter Editor — Design Spec

**Date:** 2026-03-23
**Folder:** `X:\AI Projects\job-ad-saver-and-cover-letter-editor\`

## Overview

A stripped-down copy of the Workday job application copilot that works with any job posting URL (not just Workday). Removes all Workday-specific scraping selectors and form-filling code. Keeps the cover letter generation pipeline intact.

**Constraint:** Original files in `workday-job-application-copilot/` must not be modified.

---

## Components

### `scraper.py`
- Uses Playwright (headless Chromium) to load any job URL
- Waits for the page body to load, then extracts all visible text
- Saves a PDF snapshot of the page (same as current)
- Sends the raw text to Claude (`claude-haiku-4-5-20251001`) to extract:
  - `title` — job title
  - `company` — company name (best-effort; user confirms/overrides in main.py)
  - `intro` — introductory paragraph(s)
  - `responsibilities` — responsibilities section
  - `qualifications` — qualifications/requirements section
- Returns same dict shape as `scrape_workday()` so generator works unchanged:
  `{title, company, description, intro, responsibilities, qualifications, url, pdf_bytes}`

### `generator.py`
- Direct copy of `workday-job-application-copilot/generator.py`
- No changes needed — has no Workday-specific code
- Imports `OUTPUT_BASE` and `TEMPLATE_BASE` from local `config.py`

### `main.py`
```
url = input("Paste job URL: ").strip()
data = scrape_job(url)
data["company"] = input(f"Company name [{data['company']}]: ").strip() or data["company"]
generate_application(data)
```
No filler, no form-filling prompt.

### `config.py`
- Copied from current `config.py`
- All Workday-specific vars removed:
  `WORKDAY_EMAIL`, `SALUTATION`, `REFERRAL_SOURCE`, `YEARS_EXPERIENCE`,
  `SALARY_EXPECTATION`, `SALARY_EXPECTATION_SINGLE`, `LEAVING_REASON`,
  `INDIGENOUS_STATUS`, `DEFAULT_LOCATION`, `VISA_INFO`, `WORK_RIGHTS_ANSWER`,
  `LANG_PROFICIENCY`
- Kept: `OUTPUT_BASE`, `TEMPLATE_BASE`, `SUPPLEMENTARY_FILES`

### `requirements.txt`
- Same as current minus `playwright` form-fill deps already covered by scraper usage
- Core deps: `playwright`, `anthropic`, `python-docx`, `docx2pdf`, `python-dotenv`

---

## Data Flow

```
User pastes URL
  → Playwright loads page (any site)
  → page.inner_text() → raw visible text
  → Claude extracts structured fields
  → User confirms company name
  → classify_job() → template category
  → copy resume PDF + cover letter .docx to output folder
  → fill_cover_letter() → Claude rewrites blanks
  → docx2pdf converts to PDF
  → output folder opens
```

---

## What Is NOT Included
- No `filler.py` — no Workday form automation
- No Workday-specific selectors or `data-automation-id` references
- No personal info config vars (email, visa, salary, etc.)
