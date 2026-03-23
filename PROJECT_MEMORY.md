# Project Memory — Workday Application Copilot

Use this file to onboard a new Claude instance for debugging or feature work.
Paste this file at the start of your chat, then describe the issue or task.

---

## What this project does

End-to-end automation for Workday job applications on Windows:
1. **Scrape** — `c_scraper.py` pulls job title, description, saves a PDF snapshot
2. **Generate** — `d_generator.py` picks the right resume/cover letter template by job category, uses Claude Haiku to fill cover letter blanks, converts `.docx` → `.pdf`
3. **Fill** — `e_filler.py` uses Playwright (headed MS Edge browser) to log in to Workday and fill the entire application form page by page
4. **Entry point** — `f_main.py` chains all three steps; after a successful cover letter save it auto-starts form filling without prompting. `e_filler.py` can also run standalone.

---

## File structure

```
workday-application-copilot/
├── f_main.py           # Entry point — scrape → generate → fill (auto, no prompt)
├── c_scraper.py        # Playwright scraper for Workday job pages
├── d_generator.py      # Cover letter generation + PDF conversion
├── e_filler.py         # Workday form automation (~3200 lines, 55+ functions)
├── b_config.py         # USER-SPECIFIC settings (email, paths, languages, etc.)
├── a_applicant.json    # USER-SPECIFIC candidate profile (CV data)
├── requirements.txt
└── .env              # ANTHROPIC_API_KEY
```

**Rule:** `e_filler.py` and `d_generator.py` are generic automation — no personal data.
All personal values live in `b_config.py` and `a_applicant.json`.

---

## b_config.py — what it contains

```python
WORKDAY_EMAIL             # email used to log in / register on Workday
SALUTATION                # e.g. "Mr." — fills the salutation/title dropdown
REFERRAL_SOURCE           # e.g. "Job Board" — answers "How did you hear about us?"
YEARS_EXPERIENCE          # e.g. "4" — answers years-of-experience questions
SALARY_EXPECTATION        # e.g. "100,000 – 110,000" — salary range answer
SALARY_EXPECTATION_SINGLE # e.g. "100,000" — single-figure salary answer
LEAVING_REASON            # sentence used for "reason for leaving" questions
INDIGENOUS_STATUS         # e.g. "Neither" — indigenous identity dropdown answer
DEFAULT_LOCATION          # default location string for form Location fields
VISA_INFO                 # visa/work-rights sentence injected into Claude prompts
WORK_RIGHTS_ANSWER        # exact option text for "right to work" dropdowns
LANG_PROFICIENCY          # dict of languages → {level, fallback, fluent}
OUTPUT_BASE               # path where generated resume/cover letter folders are saved
TEMPLATE_BASE             # path to resume/cover letter template subfolders
SUPPLEMENTARY_FILES       # list of extra PDFs uploaded alongside the resume
```

---

## a_applicant.json — schema

```json
{
  "first_name", "last_name", "email", "phone", "phone_country_code",
  "address": { "street", "suburb", "city", "state", "state_abbr", "postcode", "country" },
  "linkedin", "website",
  "visa": { "type", "expiry", "authorized_to_work", "requires_future_sponsorship", "note" },
  "referral_source",
  "work_experience": [{ "title", "company", "start" (MM/YYYY), "end" (MM/YYYY or "Present"), "description" }],
  "education": [{ "institution", "degree", "field", "start", "end", "gpa" }],
  "certifications": [],
  "skills": []
}
```

---

## d_generator.py — key logic

**`classify_job(title, description)`**
Scores available template subfolders against keyword lists. Title matches get a ×3 multiplier over description matches. Tie-break order: investment > finance > accounting. M&A/transaction terms ("mergers", "acquisition", "deals", "transaction", "m&a") map to "investment".

**`fill_cover_letter(path, company, title, intro, responsibilities, qualifications)`**
Finds `_`-blank paragraphs in the `.docx` template, sends them to Claude Haiku for rewriting, saves the result. Preserves bold formatting on the job title.

**`generate_application(data)`**
Orchestrates classify → copy templates → fill cover letter → convert to PDF → open output folder. Returns `output_folder` on success; `f_main.py` uses this to auto-start form filling.

---

## e_filler.py — section map (current line numbers)

| # | Section | Key functions | ~Line |
|---|---------|---------------|-------|
| 1 | Imports & Constants | — | 1 |
| 2 | Data Loading | `load_applicant` | 36 |
| 3 | Low-level UI Primitives | `_safe_fill`, `_safe_select`, `_is_required`, `_fill_by_label`, `_fill_last_blank`, `_wait_for_prompt_options`, `_pick_prompt_option`, `_workday_dropdown`, `_find_add_another_btn`, `_js_fill_input`, `_type_date`, `_fill_exp_dates`, `_fill_edu_dates`, `_save_section_form`, `_click_radio_or_checkbox`, `_click_section_add`, `_click_text_btn`, `_wait_for_page_ready`, `_handle_apply_popup` | 47 |
| 4 | Format & Classification | `_format_description`, `_degree_level`, `_education_field`, `_screening_value` | 700 |
| 5 | AI Helpers | `_claude_answer`, `_clean_claude_text`, `_claude_skills`, `_claude_review_check` | 816 |
| 6 | Login & Navigation | `_is_on_signin_page`, `_is_on_application_form`, `_click_signin_button`, `_auto_fill_signin`, `_wait_for_form_or_auto_signin`, `_handle_gmail_login`, `_auto_apply_and_login` | 934 |
| 7 | File Upload | `_upload_files` | 1277 |
| 8 | Personal Info | `_fill_state`, `_fill_personal_info` | 1360 |
| 9 | Work Experience | `_count_existing_work_entries`, `_fill_work_experience` | 1712 |
| 10 | Education | `_fill_field_of_study`, `_count_existing_edu_entries`, `_fill_education` | 1836 |
| 11 | Languages | `_fill_proficiency_dropdowns`, `_fill_languages` | 2203 |
| 12 | Skills | `_get_skill_input`, `_fill_skills` | 2385 |
| 13 | Websites / Social | `_fill_websites` | 2543 |
| 14 | Screening Questions | `_quick_answer`, `_fill_screening_questions` | 2601 |
| 15 | Custom Questions | `_fill_custom_questions` | 2993 |
| 16 | Work Authorization | `_fill_work_authorization` | 3110 |
| 17 | Voluntary Disclosure | `_fill_disclosure_checkboxes` | 3149 |
| 18 | Main Entry Point | `fill_application` | 3202 |

---

## Login flow (current — email/password only, no Google OAuth)

```
fill_application()
  └── _auto_apply_and_login()
        ├── navigate to /apply/applyManually
        ├── _handle_gmail_login()
        │     ├── poll up to 10s for email input to become visible (no fixed wait)
        │     ├── auto-fill email from WORKDAY_EMAIL
        │     ├── 2 password fields → new account registration
        │     │     ├── prompt user for password once
        │     │     ├── fill both password fields
        │     │     ├── click Create Account (automation-id or text scan fallback)
        │     │     └── _wait_for_form_or_auto_signin(password=captured)
        │     ├── 1 password field → existing account sign-in
        │     │     ├── prompt user for password once
        │     │     └── _auto_fill_signin() → _wait_for_form_or_auto_signin()
        │     └── 0 password fields → manual fallback prompt
        └── if not already on form: _wait_for_form_or_auto_signin()

_wait_for_form_or_auto_signin(email, password, timeout=45s)
  └── polls every 1s:
        ├── _is_on_signin_page()? → wait for pw field to render → _auto_fill_signin()
        └── _is_on_application_form()? → return (no user prompt)
        timeout → manual input fallback
```

**`_is_on_signin_page()`** — returns True if URL contains "login"/"signin" OR visible email + single password field present
**`_is_on_application_form()`** — returns True if NOT on sign-in page AND 2+ application keywords found in page text
Application keywords: `["first name", "last name", "work experience", "employment history", "education", "upload", "resume", "screening", "my experience", "contact information", "legal name", "phone number"]`

---

## Main loop logic (fill_application)

```
while True (page by page):
  detect which sections are on current page (personal / work_exp / education / language / skills / etc.)
  call the relevant _fill_*() function for each detected section (guarded by filled_sections set)
  _fill_screening_questions() — runs on every page
  _fill_custom_questions()    — runs on every page
  try to click Next / Save & Continue
  if Errors Found banner → re-run screening + custom questions, retry Next
  if stuck on same URL 3 times → prompt user to advance manually
  if still on login page → _wait_for_form_or_auto_signin()
  if review/submit page → _claude_review_check() → wait for user Enter to submit
```

Sections are guarded by a `filled_sections` set so each section is only filled once regardless of how many pages the loop traverses.

---

## Key design patterns

**`_fill_last_blank(page, label_text, value)`**
Finds ALL visible inputs/textareas near a matching label, targets the LAST one (newest form entry). Used for work experience, education entries added dynamically.

**`_workday_dropdown(page, btn_el, search_text, fallbacks)`**
JS-clicks a Workday dropdown button, waits for options, picks best match by: search_text → fallbacks → search-box filter → Claude pick → first non-blank option (last resort).

**`_type_date(page, el, value)`**
Strips value to digits only (e.g. "06/2022" → "062022"), does Ctrl+A + Delete to clear, then types digits. Workday masked inputs handle the "/" automatically.

**`_fill_exp_dates(page, start, end, is_current)`**
Collects ALL visible MM/YYYY inputs, takes the LAST pair (newest form). If `is_current=True`, ticks "I currently work here" first to hide the To field.

**`_fill_edu_dates(page, start, end)`**
Same pattern but for YYYY-only education date inputs.

**`_click_section_add(page, section_keyword)`**
Finds the "Add" or "Add Another" button scoped to a section heading (e.g. "work experience") so it never accidentally clicks another section's button.

**`_quick_answer(label, applicant, job_title, job_desc, company)`**
Rule-based fast-path for common screening questions — returns `(answer, type)` without calling Claude. Handles: right to work, internal referral, years of experience, salary, reason for leaving, indigenous status, prior employment at company.

**`_clean_claude_text(text)`**
Post-processes all Claude responses before they reach form fields. Strips lines starting with `#` or `ANSWER TO:` / `Answer:` (prompt-header leakage). Replaces em dashes (—) and en dashes (–) with `, ` so text reads naturally in form fields.

**`_fill_screening_questions(page, applicant, job_title, job_desc, company)`**
Iterates all "Select One" dropdowns on the page. Uses `_quick_answer` first, falls back to `_screening_value` (Yes/No default). Uses `SCREENING_SKIP_LABELS` blocklist to skip non-screening fields. On a failed dropdown match, does `continue` (not `break`) so remaining questions are still processed.

**`_degree_level(degree_str)`**
Maps degree name to `(primary_search, fallbacks)` for the Workday degree-type dropdown. Notable: CA/CPA/CFA → `("Professional", ["Graduate Diploma", "Graduate Certificate", "MS", "MA", "Postgraduate"])`.

**`_fill_proficiency_dropdowns(page, level, fallback)`**
Fills comprehension/overall/reading/speaking/writing Select One dropdowns. Walks up 4 DOM levels from each button to find a proficiency label. Includes a sanity check: if opened options don't contain proficiency-like words (advanced, fluent, beginner, etc.), closes the dropdown and skips — prevents accidentally filling education degree dropdowns on mixed-section pages.

**`_save_section_form(page)`**
Clicks Save/Done if visible. **Not called** after work experience or education entries (those Workday forms have no inline save button). Still called after language entries.

---

## Bug fix history

### Session 2026-03-22 (earlier)

| Issue | Fix applied |
|-------|-------------|
| Create Account button is a `div[role='button']` with no inner text | Added `aria-label` check to text-scan fallback; added `[aria-label='Create Account'][role='button']` to automation-id selector list |
| Sign-in redirect after registration not detected | `_wait_for_form_or_auto_signin` polls for sign-in page and auto-fills credentials |
| Sign-in page falsely detected as application form | `_is_on_application_form` now calls `_is_on_signin_page` first and returns False if on login page; removed `"address"` from signals (matched "Email Address") |
| Sign-in loop spam (repeated "no password field" messages) | Poll loop now checks `pw_visible` list before printing/attempting — silently waits if field not yet rendered |
| Work experience "From" date not filled | Added `page.wait_for_selector` with 5s timeout for MM/YYYY input before calling `_fill_exp_dates` |
| Education dates showing wrong values (e.g. "6202") | `_type_date` now uses Ctrl+A + Delete instead of `el.select()` to clear React masked inputs before typing |
| Text-scan fallback for Create Account didn't trigger auto sign-in | Replaced `if/else` with `if register_clicked:` block so both automation-id AND text-scan paths call `_wait_for_form_or_auto_signin` |

### Session 2026-03-22 (later) — personal info & screening

| # | Issue | Fix |
|---|-------|-----|
| 1 | Template classifier picked wrong category (accounting over finance) for M&A roles | Added title-based scoring with ×3 multiplier and expanded M&A/transaction keyword list in `classify_job` |
| 2 | Salutation dropdown not filled | Corrected inverted automation-id selector (`[data-automation-id='x'] button` → `button[data-automation-id='x']`) and tightened DOM walk to 3 levels |
| 3 | "I have a preferred name" checkbox was being clicked, expanding the section and causing downstream salutation errors | Skip that checkbox entirely |
| 4 | Personal-info fields (Salutation, Given Name, Phone, Address, etc.) passed to Claude as screening questions | Added `SCREENING_SKIP_LABELS` blocklist in `_fill_screening_questions` |
| 5 | "How Did You Hear About Us?" answered as Yes/No instead of using the referral source dropdown | Detect referral-source label patterns, route to `_workday_dropdown` with `config.REFERRAL_SOURCE` |
| 6 | Referral sub-field "What's their name?" filled with applicant's own name | Only fill when `REFERRAL_SOURCE` implies an actual employee referral |
| 7 | "Have you previously worked at [Company]?" answered wrong | Check applicant `work_experience` list for company name match in `_quick_answer` |
| 8 | Page advance logic ignored validation errors | Added error-banner detection + retry logic after Save and Continue |
| 9 | Degree dropdown only matched abbreviations (BS, MA, MS) | Added `DEGREE_MAP` in `_degree_level` mapping full degree names to primary + fallback option text |
| 10 | Common screening questions called Claude unnecessarily | `_quick_answer` rule-based fast-path for years of experience, salary, reason for leaving, indigenous status, right to work, referral |
| 11 | Work experience entries duplicated on each page loop | `filled_sections` set guard in `fill_application` prevents re-filling |
| 12 | "I currently work here" ticked for all entries | Read `is_current` from `end == "Present"`, check/uncheck based on actual checkbox state |
| 13 | Indigenous identity answer "No" didn't match any dropdown option | Updated `INDIGENOUS_STATUS` default to `"Neither"` with flexible fallbacks for Workday variants |
| 14 | Unnecessary login wait before email fill | Removed fixed wait; replaced with short polling and immediate fill attempt |

### Session 2026-03-24 — login wait, Claude text leak, consent questions, field-of-study, skills

| # | Issue | Fix |
|---|-------|-----|
| 23 | Login showed "Timed out waiting for sign-in form" and wasted up to 15s on every run — waited for container selectors that Transurban/other Workday instances never render | Replaced 12s `wait_for_function` + 3s sleep with a direct 10s poll on the email input itself; exits as soon as the field is visible |
| 24 | Claude response leaked into form fields verbatim: `# ANSWER TO: "What is your current notice period?"` prepended to answers | Added `_clean_claude_text()` helper called at `_claude_answer` return; strips `#` lines and `ANSWER TO:` prefixes before text reaches any form field |
| 25 | Em dashes (—) and en dashes (–) in Claude answers appeared in form fields, making text look like a formatted document | `_clean_claude_text()` replaces both with `, ` |
| 26 | Disability adjustment, medical assessment acknowledgement, and background check consent questions left blank with "Errors Found" banner | `_screening_value` extended with patterns: `"i understand"`, `"please confirm"`, `"medical assessment"`, `"background check"`, `"pre-employment"`, `"condition of employment"`, `"will be required to"` → returns `"Yes"` |
| 27 | One failed `_workday_dropdown` call aborted the entire screening loop, leaving all subsequent questions unanswered | Changed `break` → `continue` on failed match in `_fill_screening_questions` |
| 28 | Field of Study dropdown failed on Workday forms with two-level menu ("Partial List" / "All →") — code tried to search without first expanding the full list | After dropdown opens in `_fill_field_of_study`, check `promptOption` elements for `"all"` / `"all fields"` / `"show all"` and click it before typing the search term |
| 29 | Skills section filled with 15+ valuation variants ("Art Valuation", "Bond Valuation", etc.) — Claude returned generic term "Valuation", Workday returned all matches, code blindly picked first alphabetical result | `_claude_skills` prompt now requires specific, distinct skill names and explicitly forbids generic single-word terms or repeated concept variants; `_fill_skills` removes blind first-option fallback and skips the skill if no close match found |

### Session 2026-03-23 — proficiency loops, language, education, login

| # | Issue | Fix |
|---|-------|-----|
| 15 | "Comprehension*" / "Writing*" proficiency dropdowns looped 29–50 times in screening loop — `_workday_dropdown` last-resort "succeeded" but Workday reverted the field each time | Added `"comprehension"`, `"overall"`, `"reading"`, `"speaking"`, `"writing"`, `"language"` to `SCREENING_SKIP_LABELS` |
| 16 | Language name dropdown filled with wrong (non-English) language — screening loop's last-resort picked first alphabetical option when language button was still "Select One" | `"language"` in `SCREENING_SKIP_LABELS` prevents screening loop from touching language name dropdowns |
| 17 | `_fill_proficiency_dropdowns` opened an education degree dropdown on pages where both sections are visible — DOM walk at level 4 reached a proficiency label from a sibling section | Added sanity check: if opened dropdown options don't contain proficiency-like words (advanced, fluent, beginner, etc.), close and skip |
| 18 | `'ElementHandle' object has no attribute 'triple_click'` in `_fill_field_of_study` | Replaced `target_el.triple_click()` with `target_el.click(click_count=3)` |
| 19 | CA (Chartered Accountant) classified as "Master" / "Postgraduate" by degree dropdown | `DEGREE_MAP` updated: `"chartered"`, `"cpa"`, `"cfa"` → `("Professional", ["Graduate Diploma", "Graduate Certificate", "MS", "MA", "Postgraduate"])` |
| 20 | `[save] No Save/Done button found` printed for every work experience and education entry, adding unnecessary DOM scan overhead | Removed `_save_section_form()` calls from `_fill_work_experience` and `_fill_education` (no inline save button on these Workday forms) |
| 21 | Yes/no prompt shown before Workday form filling, requiring manual input | Removed prompt in `f_main.py`; form filling auto-starts when `generate_application` returns a non-empty `output_folder` |
| 22 | Google OAuth login attempted on every run, causing redirects and failures | Removed all Google sign-in logic from `_handle_gmail_login`; now uses email + user-prompted password only |

---

## Tech stack

| Library | Purpose |
|---------|---------|
| `playwright` (sync) | Browser automation (headed MS Edge) |
| `anthropic` | Claude Haiku for screening answers, skill selection, review check |
| `python-docx` | Fill cover letter `.docx` templates |
| `docx2pdf` | Convert `.docx` → `.pdf` via Microsoft Word (Windows only) |
| `python-dotenv` | Load `ANTHROPIC_API_KEY` from `.env` |

---

## How to debug a specific function

1. Paste this file into your Claude chat
2. Paste the relevant function(s) from `e_filler.py` (use line numbers from the section map above)
3. Paste the error message or describe the observed behaviour
4. Ask Claude to fix it

To get a function: open `e_filler.py`, find it by line number, copy the full `def` block.

---

## GitHub

```
https://github.com/rifattahmid/workday-job-application-copilot
```
