# Workday Application Copilot — Handoff Summary

## Project Info

- **Repo:** https://github.com/dmtalien/workday-application-copilot.git — `main` branch
- **Local path:** `X:\AI Projects\workday-application-copilot\`
- **Key file:** `filler.py` (~1700+ lines, Playwright automation for Workday job applications)

---

## What the Tool Does

Full pipeline: `scraper.py` → `generator.py` → `filler.py` via `main.py`

- `filler.py` automates Workday applications using **Playwright with Edge** (`channel="msedge"`, `--disable-blink-features=AutomationControlled`)
- Reads applicant data from `applicant.json` (Rifat Tahmid, Melbourne)
- Auto-navigates to `/apply/applyManually`, does Gmail login (`rtahmid9999@gmail.com`), waits for user password, then fills the form

---

## Current State — What's Working

| Section | Status |
|---|---|
| Gmail login | ✅ Navigates to `applyManually`, waits for sign-in form via `wait_for_function`, clicks `[data-automation-id='GoogleSignInButton']` |
| Personal info | ✅ Name, address, phone, state dropdown |
| Work experience | ✅ All 5 entries added, dates filled via React native setter, "currently work here" checkbox clicked BEFORE date fill to prevent React re-render resetting the From field |
| Education | ✅ Triggered correctly (removed requirement for "degree/institution/school" in page text), degree dropdown works (Masters/Bachelor/Postgraduate), CA stays "Accounting" |
| Languages | ✅ English only, JS label-proximity detection for language dropdown, proficiency uses direct-child label check |
| Screening questions | ✅ Re-queries "Select One" buttons each iteration (fixed stale ElementHandle), strips "Error: The field..." prefix from labels |
| File upload | ✅ Resume only for single-file inputs, resume + cover letter for multi-file |
| Websites | ✅ LinkedIn filled in Social Network URLs, GitHub added via Websites "Add" button |
| Page detection | ✅ Waits for actual Workday content keywords (`work experience`, `education`, `select one`, etc.) not just 300 chars |

---

## Skills Section — Fixed (2026-03-20)

**Function:** `_fill_skills(page, applicant, job_title, job_desc)` — around line ~1405

### Root Causes Fixed

The actual HTML observed: `<input placeholder="Search" data-uxi-widget-type="selectinput" id="skills--skills" data-automation-id="searchBox">`

**Bug 1** — `_get_skill_input` couldn't find the element: none of the old selectors matched. Fixed by adding `"input[data-uxi-widget-type='selectinput']"` and `"input[id*='skills' i]"` at the top of the selector list, and correcting `'SearchInput'` → `'searchBox'`.

**Bug 2** — `fill()` doesn't fire keyboard events: the UXI selectinput widget requires `keydown/keyup` to trigger its search handler. Fixed by replacing `fill(skill)` with `page.keyboard.type(skill, delay=30)` after `Ctrl+A` + `Delete` to clear.

**Bug 3** — Enter was only pressed as a fallback: the widget requires Enter to *submit* the search query before any dropdown appears. Fixed so Enter is always pressed immediately after typing.

### Current Code Flow (post-fix)

1. Claude selects top 10 skills via `_claude_skills()` — unchanged
2. `_get_skill_input(page)` — now finds input via `data-uxi-widget-type='selectinput'`
3. `click()` → `Ctrl+A` → `Delete` → `keyboard.type(skill, delay=30)` → `Enter`
4. Wait 0.5s → `_wait_for_prompt_options(page, timeout=4000)`
5. Best-match option clicked (checkbox inside if present, else the option element)
6. `Escape` to close dropdown → next skill

---

## Key Architecture Notes

### `_click_section_add(page, section_keyword)`
JS document-order scan: finds section heading (handles "Work Experience (1)" via `startsWith`), finds next section heading as boundary, clicks first Add/Add Another button between them.

### `_fill_last_blank(page, label_text, value)`
Finds ALL label→input pairs matching `label_text`, fills the **last** visible one (= newest form at bottom). Intentionally overwrites pre-filled values.

### `_js_fill_input(el, value)`
React-compatible: uses `Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set` + dispatches `input`/`change` events. Falls back to Playwright `fill()`.

### `_wait_for_prompt_options(page, timeout)`
Tries multiple selectors:
```python
"[data-automation-id='promptOption']"
"[data-automation-id='listItem']"
"li[role='option']"
"[role='option']"
"[role='listbox'] li"
"[data-automation-id='dropdownOption']"
```

### Page Loop
Uses `_CONTENT_JS` — waits for actual Workday keywords in body text before reading `page_text`. One-time flags (`work_exp_filled`, `education_filled`, etc.) prevent double-filling.

---

## `applicant.json` Key Data

| Field | Value |
|---|---|
| Name | Rifat Tahmid |
| Email | rtahmid9999@gmail.com |
| Phone | 0415869643 (+61) |
| Address | Rosslyn St, West Melbourne, VIC 3003, Australia |
| Work experience | 5 entries (current job has `"end": "Present"`) |
| Education | CA (Accounting), Master of Banking & Finance, Bachelor of Business |
| Skills | Full list in JSON — Claude picks top 10 per job |
| LinkedIn | https://www.linkedin.com/in/rifat-tahmid/ |
| GitHub | Stored in `website` field of applicant.json |

---

## Other Notes

- **Languages:** Only English is filled currently (list hardcoded to `["English"]` in `_fill_languages`). Other languages (Bengali, Spanish, Hindi, Malay) are defined in `LANG_PROFICIENCY` map but commented out pending stable language dropdown detection.
- **Degree mapping:** `_degree_level()` maps full degree names to keywords: Master → "Master", Bachelor → "Bachelor", CA/Chartered → "Professional" (falls back to "Postgraduate" if "Professional" not in dropdown).
- **Field of Study:** `_fill_field_of_study()` handles Workday's radio-button search panel. `_education_field()` determines the value — professional qualifications (CA, CPA, CFA) always use their own field; investment roles get "Finance"; accounting roles get "Accounting" for Bachelor, "Finance" for Masters.
- **Edge browser required:** Google OAuth blocks Chrome's automation flags. Edge with `ignore_default_args=["--enable-automation"]` avoids the detection.
