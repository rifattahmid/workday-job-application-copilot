"""
filler.py - Fills a Workday job application form using applicant.json.

Usage (called from main.py after scraping):
    fill_application(url, job_title, job_description, resume_pdf_path)

Or run standalone:
    python filler.py
"""

# ===========================================================================
# IMPORTS & CONSTANTS
# ===========================================================================

import json
import os
import re
import time
from pathlib import Path

import anthropic
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from d_config import (WORKDAY_EMAIL, DEFAULT_LOCATION, VISA_INFO, LANG_PROFICIENCY,
                    SUPPLEMENTARY_FILES, SALUTATION, REFERRAL_SOURCE,
                    YEARS_EXPERIENCE, SALARY_EXPECTATION, SALARY_EXPECTATION_SINGLE,
                    LEAVING_REASON, INDIGENOUS_STATUS, WORK_RIGHTS_ANSWER)

APPLICANT_FILE = Path(__file__).parent / "e_applicant.json"


# ===========================================================================
# DATA LOADING
# ===========================================================================

def load_applicant() -> dict:
    with open(APPLICANT_FILE) as f:
        return json.load(f)


# ===========================================================================
# LOW-LEVEL UI PRIMITIVES
# ===========================================================================



def _safe_fill(page, selector: str, value: str):
    try:
        el = page.query_selector(selector)
        if el and el.is_visible():
            el.click()
            el.fill(value)
            return True
    except Exception:
        pass
    return False


def _safe_select(page, selector: str, value: str):
    """Try to select a dropdown option containing value."""
    try:
        el = page.query_selector(selector)
        if el and el.is_visible():
            el.click()
            time.sleep(0.3)
            options = page.query_selector_all("[data-automation-id='promptOption']")
            for opt in options:
                if value.lower() in opt.inner_text().lower():
                    opt.click()
                    return True
            page.select_option(selector, label=value)
            return True
    except Exception:
        pass
    return False


def _is_required(el) -> bool:
    try:
        return (
            el.get_attribute("aria-required") == "true"
            or el.get_attribute("required") is not None
        )
    except Exception:
        return False


def _fill_by_label(page, label_text: str, value: str, ask_if_missing: bool = False,
                   exclude: str = "") -> bool:
    """Find an input by its nearby label text and fill it (first match).

    exclude: if set, skip any label whose text contains this string (case-insensitive).
             Used to avoid filling e.g. 'Preferred First Name' when searching 'First Name'.
    """
    if not value:
        return False
    try:
        el = page.query_selector(f"input[aria-label*='{label_text}']")
        if not el:
            el = page.query_selector(f"input[placeholder*='{label_text}']")
        if not el:
            labels = page.query_selector_all("label")
            for lbl in labels:
                lbl_txt = lbl.inner_text().lower()
                if exclude and exclude.lower() in lbl_txt:
                    continue
                if label_text.lower() in lbl_txt:
                    for_id = lbl.get_attribute("for")
                    if for_id:
                        el = page.query_selector(f"#{for_id}")
                        break
        if el and el.is_visible():
            if not value and ask_if_missing and _is_required(el):
                value = input(f"  Required field '{label_text}' is empty. Enter value: ").strip()
            if value:
                el.click()
                el.fill(value)
                return True
    except Exception:
        pass
    return False


def _fill_last_blank(page, label_text: str, value: str) -> bool:
    """
    Find ALL visible inputs/textareas matching label_text and fill the LAST one.
    - "Last" = newest form at the bottom of the list → targets the newly added entry
      without needing to skip already-filled fields from previous entries.
    - Pre-filled values from Workday's resume-parse are overwritten intentionally.
    """
    if not value:
        return False
    candidates = []
    try:
        labels = page.query_selector_all("label")
        for lbl in labels:
            if label_text.lower() not in lbl.inner_text().lower():
                continue
            for_id = lbl.get_attribute("for")
            if not for_id:
                continue
            el = page.query_selector(f"#{for_id}")
            if el and el.is_visible():
                candidates.append(el)
        # Also search by aria-label for inputs and textareas
        for tag in ["input", "textarea"]:
            for el in page.query_selector_all(f"{tag}[aria-label*='{label_text}' i]"):
                try:
                    if el.is_visible():
                        candidates.append(el)
                except Exception:
                    pass
    except Exception:
        pass

    if candidates:
        last = candidates[-1]
        last.scroll_into_view_if_needed()
        last.click()
        last.fill(value)
        return True
    return False


def _wait_for_prompt_options(page, timeout: int = 4000) -> list:
    """Wait for Workday prompt options to appear and return them.
    Tries multiple selectors since different Workday versions use different IDs."""
    OPTION_SELS = [
        "[data-automation-id='promptOption']",
        "[data-automation-id='listItem']",
        "li[role='option']",
        "[role='option']",
        "[role='listbox'] li",
        "[data-automation-id='dropdownOption']",
    ]
    # Wait for the first selector that appears
    for sel in OPTION_SELS:
        try:
            page.wait_for_selector(sel, state="visible", timeout=timeout)
            break
        except PlaywrightTimeout:
            continue
    # Collect from all selectors (de-duplicate by text)
    seen_texts = set()
    results = []
    for sel in OPTION_SELS:
        for el in page.query_selector_all(sel):
            try:
                if not el.is_visible():
                    continue
                txt = el.inner_text().strip()
                if txt and txt not in seen_texts:
                    seen_texts.add(txt)
                    results.append(el)
            except Exception:
                continue
    return results


def _pick_prompt_option(page, opts, search_text: str) -> bool:
    """Scan visible prompt options for a match and click it."""
    for opt in opts:
        try:
            if search_text.lower() in opt.inner_text().lower():
                opt.scroll_into_view_if_needed()
                opt.click()
                time.sleep(0.3)
                return True
        except Exception:
            continue
    return False


def _workday_dropdown(page, btn_el, search_text: str,
                      fallbacks: list | None = None) -> bool:
    """
    Click a Workday dropdown button, wait for options, and pick the best match.
    Tries search_text first, then each fallback in order, then first real option.
    Uses JS click to bypass Playwright's 'element not enabled' wait.
    """
    try:
        btn_el.evaluate("el => { el.scrollIntoView({block:'center'}); el.click(); }")
        time.sleep(0.3)
        opts = _wait_for_prompt_options(page)

        # Build the list of terms to try in order
        attempts = [search_text] + (fallbacks or [])
        for term in attempts:
            if _pick_prompt_option(page, opts, term):
                return True

        # Try typing in search box to narrow list
        search_input = page.query_selector(
            "input[data-automation-id='searchBox'], "
            "input[placeholder*='Search' i]"
        )
        if search_input and search_input.is_visible():
            for term in attempts:
                search_input.fill(term)
                time.sleep(0.3)
                opts = _wait_for_prompt_options(page, timeout=2000)
                if _pick_prompt_option(page, opts, term):
                    return True
            if opts:
                # Skip "Select One" / blank first option if present
                for opt in opts:
                    txt = opt.inner_text().strip().lower()
                    if txt and txt not in ("select one", "- select one -", ""):
                        opt.evaluate("el => { el.scrollIntoView({block:'center'}); el.click(); }")
                        return True

        # Claude fallback — when no string match works, ask Claude to pick the best
        # option from the full visible list. This handles salary ranges ("$100,000 -
        # $110,000" vs our "100,000 – 110,000"), work rights variants, etc.
        clean_opts = [
            o.inner_text().strip() for o in opts
            if o.inner_text().strip()
            and o.inner_text().strip().lower() not in ("select one", "- select one -", "")
        ]
        if clean_opts:
            try:
                client = anthropic.Anthropic()
                msg = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=60,
                    messages=[{"role": "user", "content":
                        f"Pick the single best option from this dropdown list for the target value.\n"
                        f"Target: {search_text}\n"
                        f"Options:\n" + "\n".join(f"- {o}" for o in clean_opts) +
                        "\n\nReply with ONLY the exact option text, nothing else."}]
                )
                best = msg.content[0].text.strip()
                if _pick_prompt_option(page, opts, best):
                    print(f"      Claude picked dropdown option: {best!r}")
                    return True
            except Exception:
                pass

        # Absolute last resort: pick first non-blank option
        for opt in opts:
            txt = opt.inner_text().strip().lower()
            if txt and txt not in ("select one", "- select one -", ""):
                opt.evaluate("el => { el.scrollIntoView({block:'center'}); el.click(); }")
                print(f"      WARNING: no match found — picked first option as fallback")
                return True

    except Exception as e:
        print(f"      Dropdown error: {e}")
    return False


def _find_add_another_btn(page) -> bool:
    """Click 'Add Another' button if present — used after first entry is saved."""
    for btn in page.query_selector_all("button"):
        try:
            txt = btn.inner_text().strip().lower()
            if txt in ("add another", "+ add another", "add more") and btn.is_visible():
                btn.scroll_into_view_if_needed()
                btn.click()
                return True
        except Exception:
            continue
    return False


def _js_fill_input(el, value: str):
    """
    Set a React-controlled input value.
    Uses the native HTMLInputElement value setter so React's synthetic event
    system fires correctly (plain el.value= assignment is ignored by React).
    Falls back to Playwright's fill() after scrolling into view.
    """
    # Step 1: Scroll into view so Playwright actions won't fail with viewport errors
    try:
        el.evaluate("el => el.scrollIntoView({ block: 'center', behavior: 'instant' })")
        time.sleep(0.15)
    except Exception:
        pass

    # Step 2: React-compatible JS setter (preferred)
    try:
        el.evaluate("""(el, v) => {
            el.focus();
            // Use React's own native setter to bypass the value property override
            const nativeSetter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;
            nativeSetter.call(el, '');
            el.dispatchEvent(new Event('input',  { bubbles: true }));
            nativeSetter.call(el, v);
            el.dispatchEvent(new Event('input',  { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new KeyboardEvent('keyup', { key: v.slice(-1), bubbles: true }));
        }""", value)
        return
    except Exception:
        pass

    # Step 3: Playwright fill() as final fallback (triggers typing simulation)
    try:
        el.fill(value)
    except Exception:
        pass


def _type_date(page, el, value: str):
    """
    Type a MM/YYYY date into a Workday masked date input by sending digits only.
    Masked inputs format the separator automatically — typing '062022' gives '06/2022'.
    This avoids issues with the '/' character confusing the input's cursor position.
    """
    digits = "".join(c for c in value if c.isdigit())  # "06/2022" → "062022"
    if not digits:
        return
    try:
        # Scroll & JS-click to focus without triggering Playwright's viewport check
        el.evaluate("el => { el.scrollIntoView({block:'center', behavior:'instant'}); el.click(); }")
        time.sleep(0.2)
        # Ctrl+A then Delete to clear — more reliable than el.select() on React masked inputs
        page.keyboard.press("Control+a")
        time.sleep(0.05)
        page.keyboard.press("Delete")
        time.sleep(0.1)
        # Type just the digits — the masked field handles the "/" separator
        page.keyboard.type(digits, delay=30)
        time.sleep(0.15)
    except Exception:
        # Fallback: use nativeSetter with digit-only string
        _js_fill_input(el, digits)


def _fill_exp_dates(page, start: str, end: str, is_current: bool) -> bool:
    """
    Fill From/To dates in the LAST (newest) experience form by position.
    Collects all visible MM/YYYY inputs and takes the last pair — no label substring
    matching, so skills or other 'From'-labelled fields can't be accidentally targeted.
    Uses JS-based fill to avoid TargetClosedError on elements outside the viewport.
    """
    if not start:
        return False

    # Wait up to 5s for at least one date input to appear (form may still be rendering)
    DATE_PLACEHOLDERS = ["MM/YYYY", "MM / YYYY", "mm/yyyy", "Month/Year", "MM/YY", "m/yyyy"]
    DATE_AIDS = [
        "input[data-automation-id='startDate']",
        "input[data-automation-id='endDate']",
        "input[data-automation-id='from']",
        "input[data-automation-id='to']",
        "input[data-automation-id='dateFrom']",
        "input[data-automation-id='dateTo']",
        "input[data-automation-id*='Date']",
        "input[data-automation-id*='date']",
    ]
    found_any = False
    for ph in DATE_PLACEHOLDERS:
        try:
            page.wait_for_selector(f"input[placeholder='{ph}']", timeout=2000, state="visible")
            found_any = True
            break
        except Exception:
            pass
    if not found_any:
        for sel in DATE_AIDS[:2]:
            try:
                page.wait_for_selector(sel, timeout=2000, state="visible")
                found_any = True
                break
            except Exception:
                pass
    if not found_any:
        time.sleep(2.0)  # last resort: give form extra time to render

    # Gather all visible date inputs — try multiple placeholder variants first
    all_inputs = []
    seen_ids = set()
    for ph in DATE_PLACEHOLDERS:
        for el in page.query_selector_all(f"input[placeholder='{ph}']"):
            try:
                if el.is_visible():
                    eid = el.evaluate("el => el.outerHTML.slice(0,80)")
                    if eid not in seen_ids:
                        all_inputs.append(el)
                        seen_ids.add(eid)
            except Exception:
                pass

    # Fallback: data-automation-id containing "date" / "Date"
    if not all_inputs:
        for sel in DATE_AIDS:
            for el in page.query_selector_all(sel):
                try:
                    if el.is_visible():
                        eid = el.evaluate("el => el.outerHTML.slice(0,80)")
                        if eid not in seen_ids:
                            all_inputs.append(el)
                            seen_ids.add(eid)
                except Exception:
                    pass

    # Last resort: JS dump of ALL visible inputs — print placeholders/ids for debugging
    if not all_inputs:
        try:
            all_visible_inputs = page.evaluate("""() =>
                [...document.querySelectorAll('input')].filter(el => {
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                }).map(el => ({
                    ph: el.placeholder, id: el.id,
                    aid: el.getAttribute('data-automation-id') || '',
                    type: el.type
                }))
            """)
            print(f"      [Date debug] No MM/YYYY inputs found. All visible inputs: {all_visible_inputs}")
        except Exception:
            pass
        return False

    # The last two inputs belong to the newest (last) entry form
    from_inp = all_inputs[-2] if len(all_inputs) >= 2 else all_inputs[-1]
    to_inp   = all_inputs[-1] if len(all_inputs) >= 2 else None

    _type_date(page, from_inp, start)
    time.sleep(0.3)

    # Fill To date only when this is NOT a current role and a real end date exists
    end_val = (end or "").strip().lower()
    if not is_current and to_inp and end_val and end_val not in ("present", "current", "now"):
        _type_date(page, to_inp, end)
        time.sleep(0.3)

    return True


def _fill_edu_dates(page, start: str, end: str) -> bool:
    """
    Fill From/To year inputs in the LAST (newest) education form by position.
    Education uses YYYY-only inputs.
    """
    start_year = start.split("/")[-1] if start else ""
    end_year   = end.split("/")[-1]   if end and end != "Present" else ""

    all_inputs = []
    for el in page.query_selector_all("input[placeholder='YYYY']"):
        try:
            if el.is_visible():
                all_inputs.append(el)
        except Exception:
            pass

    if not all_inputs:
        return False

    from_inp = all_inputs[-2] if len(all_inputs) >= 2 else all_inputs[-1]
    to_inp   = all_inputs[-1] if len(all_inputs) >= 2 else None

    if start_year:
        _type_date(page, from_inp, start_year)
        time.sleep(0.3)

    if end_year and to_inp:
        _type_date(page, to_inp, end_year)
        time.sleep(0.3)

    return True


def _save_section_form(page):
    """Click Save / Done in a modal/inline form."""
    save_btn = page.query_selector(
        "button[data-automation-id='saveButton'], "
        "button[aria-label='Save'], "
        "button[data-automation-id='done']"
    )
    if save_btn and save_btn.is_visible():
        save_btn.evaluate("el => { el.scrollIntoView({block:'center'}); el.click(); }")
        time.sleep(2.0)   # wait for entry to collapse and "Add Another" to appear
        return True
    for btn in page.query_selector_all("button"):
        try:
            if btn.inner_text().strip().lower() in ("save", "done") and btn.is_visible():
                btn.evaluate("el => { el.scrollIntoView({block:'center'}); el.click(); }")
                time.sleep(2.0)
                return True
        except Exception:
            continue
    print("    [save] No Save/Done button found")
    return False


def _click_radio_or_checkbox(page, label_text: str, value: str) -> bool:
    try:
        labels = page.query_selector_all("label")
        for lbl in labels:
            if value.lower() in lbl.inner_text().lower():
                lbl.click()
                return True
    except Exception:
        pass
    return False


def _click_section_add(page, section_keyword: str) -> bool:
    """
    Find the Add / Add Another button that belongs to a named section.
    Uses DOCUMENT ORDER positioning: finds the section heading, then searches
    forward in the DOM until the next known section heading — so it cannot
    accidentally click an Add button from a different section.
    """
    return page.evaluate("""
        (keyword) => {
            const kw = keyword.toLowerCase();
            const ADD_TEXTS = new Set(['add', '+ add', 'add another', '+ add another']);
            // Known section headings used as boundaries
            const SECTION_HEADERS = [
                'work experience', 'employment history',
                'education', 'languages', 'language',
                'skills', 'skill', 'certifications', 'training',
                'volunteer', 'achievements', 'websites', 'website'
            ];

            const allEls = Array.from(document.querySelectorAll('*'));

            // Helper: does element text match the section keyword?
            // Handles "Work Experience", "Work Experience (1)", "Work Experience 1 entry" etc.
            const matchesKw = (txt) =>
                txt === kw || txt === kw + 's' ||
                txt.startsWith(kw + ' ') || txt.startsWith(kw + '(');

            const matchesHeader = (txt, h) =>
                txt === h || txt === h + 's' ||
                txt.startsWith(h + ' ') || txt.startsWith(h + '(');

            // 1. Find the FIRST occurrence of our section heading (leaf-node preferred)
            let headingIdx = -1;
            for (let i = 0; i < allEls.length; i++) {
                const el = allEls[i];
                if (!el.offsetParent) continue;
                const txt = el.textContent.trim().toLowerCase();
                if (matchesKw(txt) && el.children.length === 0) { headingIdx = i; break; }
            }
            // Fallback: any visible element whose text starts with the keyword
            if (headingIdx === -1) {
                for (let i = 0; i < allEls.length; i++) {
                    const el = allEls[i];
                    if (!el.offsetParent) continue;
                    const txt = el.textContent.trim().toLowerCase();
                    if (matchesKw(txt)) { headingIdx = i; break; }
                }
            }
            if (headingIdx === -1) return false;

            // 2. Find where the NEXT different section heading starts
            let endIdx = allEls.length;
            for (let i = headingIdx + 1; i < allEls.length; i++) {
                const el = allEls[i];
                if (!el.offsetParent) continue;
                const txt = el.textContent.trim().toLowerCase();
                if (SECTION_HEADERS.some(h => h !== kw && matchesHeader(txt, h))) { endIdx = i; break; }
            }

            // 3. Find first Add/Add Another button between heading and next section
            for (let i = headingIdx; i < endIdx; i++) {
                const el = allEls[i];
                if (el.tagName !== 'BUTTON' || !el.offsetParent) continue;
                const btnTxt = el.textContent.trim().toLowerCase();
                if (ADD_TEXTS.has(btnTxt)) {
                    el.scrollIntoView({ block: 'center' });
                    el.click();
                    return true;
                }
            }
            return false;
        }
    """, section_keyword)


def _click_text_btn(page, *texts) -> bool:
    """Click the first visible button/link whose text matches any of texts (case-insensitive)."""
    text_set = {t.lower() for t in texts}
    for el in page.query_selector_all("button, a"):
        try:
            if not el.is_visible():
                continue
            if el.inner_text().strip().lower() in text_set:
                el.scroll_into_view_if_needed()
                el.click()
                return True
        except Exception:
            continue
    return False


def _wait_for_page_ready(page, timeout=12000):
    """Wait for network idle, swallowing timeout errors."""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass


def _handle_apply_popup(page):
    """
    Workday sometimes shows a modal after landing on /apply:
      - 'Apply Manually'  ← preferred
      - 'Apply with LinkedIn' / 'Apply with Indeed'  ← skip
      - 'Continue' / 'Proceed'
    Returns the label clicked, or None.
    """
    time.sleep(1.5)
    try:
        result = page.evaluate("""
            () => {
                const PREFER = ['apply manually', 'continue', 'proceed'];
                const AVOID  = ['linkedin', 'indeed', 'google', 'facebook'];
                const scopes = [
                    ...Array.from(document.querySelectorAll(
                        '[role="dialog"], [role="alertdialog"], [aria-modal="true"], .modal'
                    )),
                    document.body
                ];
                for (const scope of scopes) {
                    const els = Array.from(scope.querySelectorAll('button, a, [role="button"]'));
                    for (const pref of PREFER) {
                        for (const el of els) {
                            const txt = (el.innerText || el.textContent || '').trim().toLowerCase();
                            if (!txt.includes(pref)) continue;
                            if (AVOID.some(a => txt.includes(a))) continue;
                            const r = el.getBoundingClientRect();
                            if (r.width > 0 && r.height > 0) {
                                el.click();
                                return pref;
                            }
                        }
                    }
                }
                return null;
            }
        """)
        if result:
            print(f"  Popup: clicked '{result}' — waiting for page to load...")
            # Wait for the navigation that follows the popup click
            try:
                page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            _wait_for_page_ready(page, timeout=8000)
            time.sleep(1.0)
            return result
    except Exception:
        pass
    return None


# ===========================================================================
# FORMAT & CLASSIFICATION HELPERS
# ===========================================================================



def _format_description(text: str) -> str:
    """Convert a paragraph description into bullet points."""
    if not text:
        return text
    # Split on ". " to get individual sentences
    sentences = [s.strip() for s in re.split(r'\.\s+', text) if s.strip()]
    bullets = []
    for s in sentences:
        if not s.endswith("."):
            s += "."
        bullets.append(f"• {s}")
    return "\n".join(bullets)


def _degree_level(degree_str: str) -> tuple:
    """Map a full degree name to (search_text, fallbacks) for Workday dropdown matching.

    Returns a tuple so callers can pass both to _workday_dropdown(), covering
    forms that show full words ("Master of Science") and those with abbreviations
    only ("MS", "MA").
    """
    DEGREE_MAP = {
        "bachelor":     ("Bachelor",    ["BS", "BA", "B.S.", "B.A.", "Bachelors", "Undergraduate"]),
        "bba":          ("Bachelor",    ["BS", "BA", "B.S.", "B.A.", "Bachelors", "Undergraduate"]),
        "bsc":          ("Bachelor",    ["BS", "BA", "B.S.", "B.A.", "Bachelors", "Undergraduate"]),
        "b.sc":         ("Bachelor",    ["BS", "BA", "B.S.", "B.A.", "Bachelors", "Undergraduate"]),
        "b.comm":       ("Bachelor",    ["BS", "BA", "B.S.", "B.A.", "Bachelors", "Undergraduate"]),
        "commerce":     ("Bachelor",    ["BS", "BA", "B.S.", "B.A.", "Bachelors", "Undergraduate"]),
        "mba":          ("MBA",         ["M.B.A.", "Master of Business", "Master", "MS", "MA", "Postgraduate"]),
        "master":       ("Master",      ["MS", "MA", "M.S.", "M.A.", "Masters", "MSc", "Postgraduate"]),
        "msc":          ("Master",      ["MS", "MA", "M.S.", "M.A.", "Masters", "MSc", "Postgraduate"]),
        "mfin":         ("Master",      ["MS", "MA", "M.S.", "M.A.", "Masters", "MSc", "Postgraduate"]),
        "m.fin":        ("Master",      ["MS", "MA", "M.S.", "M.A.", "Masters", "MSc", "Postgraduate"]),
        "postgraduate": ("Master",      ["MS", "MA", "M.S.", "M.A.", "Masters", "Postgraduate"]),
        "phd":          ("PhD",         ["Ph.D.", "Doctorate", "Doctor", "DBA"]),
        "doctor":       ("PhD",         ["Ph.D.", "Doctorate", "Doctor", "DBA"]),
        "dba":          ("PhD",         ["Ph.D.", "Doctorate", "Doctor", "DBA"]),
        "associate":    ("Associate",   ["AS", "A.S.", "AA"]),
        "diploma":      ("Diploma",     ["Certificate", "Cert"]),
        "certificate":  ("Certificate", ["Cert", "Diploma"]),
        "high school":  ("High School", ["Secondary", "GED", "HSC"]),
        "chartered":    ("Professional", ["Graduate Diploma", "Graduate Certificate",
                                          "MS", "MA", "Postgraduate"]),
        "cpa":          ("Professional", ["Graduate Diploma", "Graduate Certificate",
                                          "MS", "MA", "Postgraduate"]),
        "cfa":          ("Professional", ["Graduate Diploma", "Graduate Certificate",
                                          "MS", "MA", "Postgraduate"]),
        "professional": ("Postgraduate", ["Professional", "Master", "MS", "MA"]),
    }
    d = degree_str.lower()
    for key, result in DEGREE_MAP.items():
        if key in d:
            return result
    return ("Other", [])


def _education_field(edu_field: str, job_title: str, job_desc: str, edu_degree: str = "") -> str:
    """
    Determine field of study to search in Workday's Field of Study panel.
    Rules (in priority order):
    - Professional qualifications (CA, CPA, CFA, Chartered): always use applicant.json field
    - Masters degree → always "Finance" for relevant jobs
    - Bachelor degree → always "Accounting" for relevant jobs
    """
    deg_lower = edu_degree.lower()

    # Never override professional qualification fields — CA stays "Accounting", etc.
    if any(x in deg_lower for x in ["chartered", "certified", "cpa", "cfa", " ca"]):
        return edu_field

    job = (job_title + " " + job_desc).lower()
    is_invest   = any(x in job for x in ["investment", "fund", "portfolio", "asset management",
                                          "real estate", "real assets", "infrastructure", "equity", "credit"])
    is_accounting = any(x in job for x in ["account", "audit", "tax"])
    is_finance  = any(x in job for x in ["finance", "financial", "analyst", "fp&a", "treasury"])
    relevant_job = is_invest or is_accounting or is_finance

    if not relevant_job:
        return edu_field

    # Masters → always Finance (degree is Banking & Finance; "Banking and Finance" is not
    # a valid Workday option so always normalise to "Finance")
    if any(x in deg_lower for x in ["master", "mba", "msc", "postgrad"]):
        return "Finance"

    # Bachelor → Finance for investment/finance roles, Accounting for accounting roles
    if any(x in deg_lower for x in ["bachelor", "undergraduate"]):
        if is_invest or is_finance:
            return "Finance"
        return "Accounting"

    return edu_field


def _screening_value(label_text: str) -> str:
    """Determine Yes/No for a screening question. Default is No."""
    lbl = label_text.lower()
    # Age 18+ → Yes
    if "18" in label_text and any(x in lbl for x in ["age", "old", "least", "years"]):
        return "Yes"
    # Agree/acknowledge/certify/confirm statements → always Yes
    if any(x in lbl for x in ["i agree", "i acknowledge", "i certify", "i confirm",
                                "agree to", "acknowledge that", "certify that",
                                "confirm that", "accept the", "read and understand",
                                "terms and condition", "privacy policy", "code of conduct"]):
        return "Yes"
    # Consent/acknowledgement of company process (medical assessment, background check,
    # drug test, reference check, etc.) → Yes.
    # These questions ask the applicant to confirm they understand or accept a process.
    if any(x in lbl for x in ["i understand", "please confirm", "please acknowledge",
                                "medical assessment", "background check", "background screen",
                                "drug test", "drug screen", "criminal check", "police check",
                                "reference check", "pre-employment", "condition of employment",
                                "will be required to"]):
        return "Yes"
    # Everything else defaults to No (sponsorship, visa, affiliations, etc.)
    return "No"


# ===========================================================================
# AI HELPERS
# ===========================================================================



def _claude_answer(question: str, context: str, applicant: dict, job_title: str = "",
                   job_desc: str = "", long_form: bool = False) -> str:
    """Ask Claude to answer a single form question given applicant data and job context.

    long_form=True: used for open-ended textarea questions (skills match, motivation, etc.)
    — generates a full paragraph with higher token limit instead of a brief answer.
    """
    client = anthropic.Anthropic()

    if long_form:
        extra_instructions = (
            "- This is an open-ended textarea question requiring a substantive paragraph (3–5 sentences).\n"
            "- Highlight specific skills, experiences, and achievements from the candidate's work history "
            "that are most relevant to this role and company.\n"
            "- Be specific and concrete — mention real skills, tools, or achievements from the candidate's profile.\n"
            "- Write in first person. Do not start with 'I' — begin with an action word or skill.\n"
            "- Do NOT write a generic answer. Tailor it to the job title and description provided.\n"
            "- Do not include headers, bullet points, or labels — just the paragraph text."
        )
        max_tokens = 600
    else:
        extra_instructions = (
            "- Return ONLY the answer to fill in — no explanation, no punctuation wrapper.\n"
            "- For yes/no questions, return exactly: Yes or No\n"
            "- For dropdowns, return the most likely option text.\n"
            "- Keep answers concise and professional."
        )
        max_tokens = 200

    prompt = f"""You are filling out a job application form on behalf of this candidate.

CANDIDATE INFO:
{json.dumps(applicant, indent=2)}

JOB TITLE: {job_title}
JOB DESCRIPTION (excerpt): {job_desc[:1500]}

FORM QUESTION / FIELD LABEL:
{question}

CONTEXT (nearby text on the page):
{context}

VISA / WORK RIGHTS: {VISA_INFO}

Instructions:
{extra_instructions}
- Always use the candidate's exact details where available.
- For "how did you hear about us" prefer LinkedIn, else Company Website."""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    return _clean_claude_text(message.content[0].text.strip())


def _clean_claude_text(text: str) -> str:
    """Strip prompt-header lines and normalise dashes in a Claude-generated answer.

    Removes any line that looks like a meta-instruction rather than an actual answer:
    - Lines starting with '#' (markdown headings / comment-style headers)
    - Lines starting with 'ANSWER TO:' or 'Answer:'

    Also replaces em dashes (—) and en dashes (–) with a plain comma-space so the
    text reads naturally in a form field rather than looking like a formatted document.
    """
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # Skip header / meta lines
        if stripped.startswith("#"):
            continue
        lc = stripped.lower()
        if lc.startswith("answer to:") or lc.startswith("answer:"):
            continue
        cleaned.append(line)
    result = "\n".join(cleaned).strip()
    # Replace typographic dashes with plain comma-space
    result = result.replace("—", ", ").replace("–", ", ")
    # Collapse any double comma-spaces introduced by consecutive dashes
    result = re.sub(r",\s*,", ",", result)
    return result


def _claude_skills(job_title: str, job_desc: str, applicant: dict) -> str:
    """Return a comma-separated list of the 10 most relevant skills for this job.
    Skills must be specific and distinct — no generic single-word terms that would
    match dozens of Workday database entries (e.g. 'Valuation' → use 'DCF Valuation').
    """
    client = anthropic.Anthropic()
    applicant_skills = ", ".join(applicant.get("skills", []))
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=160,
        messages=[{"role": "user", "content": f"""You are filling the Skills section of a job application.
Select exactly 10 skills that are most relevant to this specific role.

Rules:
- Each skill must be a specific, distinct technical skill (e.g. "Financial Modelling", "DCF Analysis", "Management Reporting")
- Do NOT use generic single-word terms like "Valuation", "Finance", "Analysis" — these match hundreds of database entries
- Do NOT repeat the same concept with different prefixes (e.g. do not list "Bond Valuation", "Debt Valuation", "Fair Valuation" — pick ONE valuation skill)
- Prefer skills the applicant already has based on their background
- Use standard corporate HR skill database names (short, commonly used terms)

APPLICANT SKILLS: {applicant_skills}
JOB TITLE: {job_title}
JOB DESCRIPTION: {job_desc[:800]}

Return ONLY a comma-separated list of exactly 10 skills. No numbering, no explanations, no headers."""}]
    )
    return message.content[0].text.strip()


def _claude_review_check(page_text: str, applicant: dict) -> str:
    """Ask Claude Haiku to sense-check the Review page before submission."""
    client = anthropic.Anthropic()
    name  = f"{applicant.get('first_name','')} {applicant.get('last_name','')}".strip()
    email = applicant.get("email", "")
    prompt = (
        f"You are reviewing a job application before final submission.\n\n"
        f"=== REVIEW PAGE TEXT (first 3000 chars) ===\n{page_text[:3000]}\n\n"
        f"=== APPLICANT PROFILE ===\n"
        f"Name: {name}\nEmail: {email}\n\n"
        f"Sense-check the application in bullet points:\n"
        f"1. Are key fields present (name, contact, experience, education)?\n"
        f"2. Any obvious errors or missing information?\n"
        f"3. Does everything look consistent?\n"
        f"Be brief. Flag only real issues or confirm it looks good."
    )
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


# ===========================================================================
# LOGIN & NAVIGATION
# ===========================================================================



_APPLICATION_FORM_SIGNALS = [
    "first name", "last name", "work experience", "employment history",
    "education", "upload", "resume", "screening", "my experience",
    "contact information", "legal name", "phone number",
]


def _is_on_signin_page(page) -> bool:
    """Return True if the page is a Workday login / sign-in page (not an application form)."""
    try:
        url = page.url.lower()
        if "login" in url or "signin" in url:
            return True
        # Visible email + exactly one visible password field = sign-in form
        pw_inputs    = [e for e in page.query_selector_all("input[type='password']") if e.is_visible()]
        email_inputs = [e for e in page.query_selector_all(
            "input[type='email'], input[name='email'], input[name='username']"
        ) if e.is_visible()]
        return len(pw_inputs) == 1 and len(email_inputs) >= 1
    except Exception:
        return False


def _is_on_application_form(page) -> bool:
    """Return True if the current page looks like a Workday application form."""
    try:
        if _is_on_signin_page(page):
            return False
        text = page.inner_text("body").lower()
        return sum(1 for k in _APPLICATION_FORM_SIGNALS if k in text) >= 2
    except Exception:
        return False


def _click_signin_button(page) -> bool:
    """Click the Sign In / Log In submit button. Returns True if clicked."""
    SIGNIN_KEYWORDS = ["sign in", "log in", "login", "signin"]
    for el in page.query_selector_all("button, input[type='submit'], [role='button'], a"):
        try:
            if not el.is_visible():
                continue
            txt  = (el.inner_text() or el.get_attribute("value") or "").strip().lower()
            aria = (el.get_attribute("aria-label") or "").strip().lower()
            aid  = (el.get_attribute("data-automation-id") or "").lower()
            label = txt or aria or aid
            if any(k in label for k in SIGNIN_KEYWORDS) and "create" not in label:
                el.evaluate("el => { el.scrollIntoView({block:'center'}); el.click(); }")
                print(f"  Clicked sign-in button: '{label}'")
                return True
        except Exception:
            continue
    return False


def _auto_fill_signin(page, email: str, password: str) -> bool:
    """Fill email + password into a sign-in form and click submit. Returns True if submitted."""
    for sel in [
        "input[type='email']", "input[name='email']", "input[name='username']",
        "input[autocomplete='email']", "input[autocomplete='username']",
        "input[id*='email' i]", "input[id*='user' i]",
    ]:
        el = page.query_selector(sel)
        if el and el.is_visible():
            el.click()
            time.sleep(0.2)
            el.fill(email)
            print(f"  Auto sign-in: filled email '{email}'")
            break

    pw_inputs = [el for el in page.query_selector_all("input[type='password']") if el.is_visible()]
    if not pw_inputs:
        print("  Auto sign-in: no password field found.")
        return False
    pw_inputs[0].click()
    time.sleep(0.2)
    pw_inputs[0].fill(password)
    print("  Auto sign-in: filled password.")
    time.sleep(0.3)
    return _click_signin_button(page)


def _wait_for_form_or_auto_signin(page, email: str, password: str | None, timeout: int = 45) -> None:
    """
    Poll the page after login/registration until:
    - Application form detected → return immediately (no user prompt)
    - Sign-in page detected + password available → auto sign in and keep polling
    - Timeout → fall back to manual user prompt
    """
    print("  Watching for application form or sign-in redirect (auto mode)...")
    deadline = time.time() + timeout
    signin_attempted = False

    while time.time() < deadline:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            pass

        # Check sign-in FIRST — prevents false-positive form detection on login pages
        if _is_on_signin_page(page):
            if password and not signin_attempted:
                # Silently wait until the password field actually renders before attempting
                try:
                    pw_visible = [e for e in page.query_selector_all("input[type='password']") if e.is_visible()]
                except Exception:
                    time.sleep(1.0)
                    continue  # page navigating — wait and retry
                if not pw_visible:
                    time.sleep(1.0)
                    continue  # form still loading — don't spam messages
                print("  Sign-in page detected — auto signing in with stored credentials...")
                if _auto_fill_signin(page, email, password):
                    signin_attempted = True
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=12000)
                    except Exception:
                        pass
                    time.sleep(2.0)
                    signin_attempted = False  # allow retry if redirected to sign-in again
            time.sleep(1.0)
            continue

        if _is_on_application_form(page):
            print("  Application form detected — proceeding automatically.")
            return

        time.sleep(1.0)

    # Timeout fallback
    if not _is_on_application_form(page):
        print("  Could not auto-detect form or sign in within timeout.")
        input("  Please complete sign-in and reach the first form page, then press Enter: ")


def _handle_gmail_login(page, gmail: str):
    """
    Detect Workday sign-in page → fill email → prompt user for password → sign in.
    Handles both sign-in (1 password field) and new account registration (2 password fields).
    Returns the password entered during registration (or None).
    """
    print(f"  [Login check] URL: {page.url}")

    # Poll up to 10s for the email input to become visible.
    EMAIL_SELECTORS = [
        "input[type='email']",
        "input[name='email']",
        "input[name='username']",
        "input[autocomplete='email']",
        "input[autocomplete='username']",
        "input[id*='email' i]",
        "input[id*='user' i]",
    ]
    deadline = time.time() + 10
    while time.time() < deadline:
        for sel in EMAIL_SELECTORS:
            el = page.query_selector(sel)
            if el and el.is_visible():
                break
        else:
            time.sleep(0.3)
            continue
        break

    print("  Filling email/password sign-in form...")

    # Fill email field
    email_inp = None
    for sel in [
        "input[type='email']",
        "input[name='email']",
        "input[name='username']",
        "input[autocomplete='email']",
        "input[autocomplete='username']",
        "input[id*='email' i]",
        "input[id*='user' i]",
    ]:
        el = page.query_selector(sel)
        if el and el.is_visible():
            email_inp = el
            break

    if email_inp:
        email_inp.click()
        time.sleep(0.2)
        email_inp.fill(gmail)
        print(f"  Filled email field: {gmail}")
    else:
        print("  Could not find email field.")

    # Check for password fields — if there are two, it's a registration form
    pw_inputs = [
        el for el in page.query_selector_all("input[type='password']")
        if el.is_visible()
    ]

    if len(pw_inputs) >= 2:
        # Registration form: new password + confirm password
        print("  Found two password fields — this looks like a new account registration page.")
        password = input("  Enter the password you want to create for this account: ").strip()

        for pw_inp in pw_inputs[:2]:
            pw_inp.click()
            time.sleep(0.2)
            pw_inp.fill(password)
            time.sleep(0.2)
        print("  Filled new password and confirm password fields.")

        # Click the create account / register button
        # First try Workday automation-id patterns
        register_clicked = False
        WORKDAY_CREATE_SELS = [
            "[data-automation-id='createAccountButton']",
            "[data-automation-id='createAccount']",
            "[data-automation-id='registerButton']",
            "[data-automation-id='register']",
            "[data-automation-id='signUp']",
            "[data-automation-id='submitButton']",
            "[data-automation-id='submit']",
            "[aria-label='Create Account'][role='button']",
            "[data-automation-id='click_filter'][aria-label='Create Account']",
        ]
        for sel in WORKDAY_CREATE_SELS:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.evaluate("el => { el.scrollIntoView({block:'center'}); el.click(); }")
                    register_clicked = True
                    print(f"  Clicked register/create button via automation-id: {sel}")
                    break
            except Exception:
                continue

        # Fallback: scan all clickable elements by text
        if not register_clicked:
            CREATE_KEYWORDS = [
                "create account", "create an account", "register", "sign up",
                "create", "submit", "get started", "continue",
            ]
            candidates = []
            for el in page.query_selector_all("button, input[type='submit'], [role='button'], a"):
                try:
                    if not el.is_visible():
                        continue
                    txt = (el.inner_text() or el.get_attribute("value") or "").strip().lower()
                    aid = (el.get_attribute("data-automation-id") or "").lower()
                    aria = (el.get_attribute("aria-label") or "").strip().lower()
                    label = txt or aria or aid
                    candidates.append(f"'{label}'")
                    if any(k in txt or k in aid or k in aria for k in CREATE_KEYWORDS):
                        el.evaluate("el => { el.scrollIntoView({block:'center'}); el.click(); }")
                        register_clicked = True
                        print(f"  Clicked register/create button: '{label}'")
                        break
                except Exception:
                    continue
            if not register_clicked:
                print(f"  Could not find a create/register button.")
                print(f"  Visible buttons found: {', '.join(candidates[:15]) or 'none'}")
                input("  Please click the create/register button manually, then press Enter: ")

        if register_clicked:
            print("  Account creation submitted — watching for redirect...")
            try:
                page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            time.sleep(2.0)
            _wait_for_form_or_auto_signin(page, gmail, password)
            return password

    elif len(pw_inputs) == 1:
        # Single password field — sign-in to existing account.
        print("  Found sign-in form (single password field).")
        password = input("  Enter your Workday account password to auto sign in: ").strip()
        if password:
            _auto_fill_signin(page, gmail, password)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=12000)
            except Exception:
                pass
            time.sleep(2.0)
            _wait_for_form_or_auto_signin(page, gmail, password)
            return password
        else:
            input("  Press Enter once you are fully signed in: ")

    else:
        print("  No password fields found — please complete sign-in manually.")
        input("  Press Enter once you are fully signed in: ")


def _auto_apply_and_login(page, gmail: str = WORKDAY_EMAIL):
    """
    1. Navigate directly to job_url/apply/applyManually (skips the popup entirely)
    2. Sign in via email + user-prompted password
    3. If /applyManually fails (404 / redirect away), fall back to job_url/apply
       and wait for user to log in and reach first form page manually
    4. Prompt user to press Enter once on first form page
    """
    base_url = page.url.rstrip('/')
    # Strip any existing /apply segment so we always build from the job URL
    for suffix in ['/apply/applyManually', '/applyManually', '/apply']:
        if base_url.lower().endswith(suffix):
            base_url = base_url[: len(base_url) - len(suffix)]
            break

    apply_manually_url = base_url + '/apply/applyManually'
    apply_url          = base_url + '/apply'

    # --- Step 1: Go directly to /apply/applyManually ---
    print(f"\n  Navigating to: {apply_manually_url}")
    try:
        page.goto(apply_manually_url, timeout=30000, wait_until="domcontentloaded")
        _wait_for_page_ready(page)
    except Exception as e:
        print(f"  Could not load applyManually ({e})")

    # Check if we landed somewhere valid (not a 404 / redirect back to job listing)
    landed_url = page.url.lower()
    on_apply_page = "applymanually" in landed_url or "apply" in landed_url

    if not on_apply_page:
        # Fall back to /apply and let user handle login
        print(f"  applyManually URL failed — falling back to: {apply_url}")
        try:
            page.goto(apply_url, timeout=30000, wait_until="domcontentloaded")
            _wait_for_page_ready(page)
        except Exception as e:
            print(f"  Could not load /apply either ({e})")
        print("\n  Please log in and navigate to the first page of the application form.")
        input("  Press Enter once you are on the first page: ")
        return

    print(f"  Landed on: {page.url}")

    # Give the Workday React app a moment to render the sign-in form
    time.sleep(1.0)

    # --- Step 2: Email/password sign-in ---
    captured_password = _handle_gmail_login(page, gmail)

    # --- Step 3: Auto-detect form or handle any remaining sign-in redirect ---
    # If _handle_gmail_login already resolved to the form, this is a no-op.
    if not _is_on_application_form(page):
        _wait_for_form_or_auto_signin(page, gmail, captured_password)


# ===========================================================================
# FILE UPLOAD
# ===========================================================================



def _upload_files(page, resume_pdf: str, output_folder: str = ""):
    """
    Upload files to the Workday file upload area.
    - Single-file input  → resume only.
    - Multi-file input   → resume + cover letter + 3 supplementary PDFs (max 5 total).

    Supplementary PDFs (added when multi-upload is available):
      - Recommendations.pdf
      - Monash University Transcript.pdf
      - CA ANZ Statement of Academic Record.pdf
    """
    SUPPLEMENTARY = SUPPLEMENTARY_FILES

    upload_input = page.query_selector("input[type='file']")
    if not upload_input:
        print("  No file upload input found on this page.")
        return

    if not resume_pdf or not Path(resume_pdf).exists():
        print("  Resume PDF not found, skipping upload.")
        return

    files_to_upload = [resume_pdf]

    # Check if input accepts multiple files
    is_multiple = upload_input.evaluate("el => el.multiple || el.getAttribute('multiple') !== null")

    if is_multiple:
        # Cover letter from output folder
        if output_folder:
            import glob as _glob
            for pdf in _glob.glob(f"{output_folder}/*.pdf"):
                name = Path(pdf).name.lower()
                if "position description" in name or "resume" in name:
                    continue
                if "cover" in name or "letter" in name:
                    files_to_upload.append(pdf)
                    break

        # Supplementary PDFs — add only if total stays under Workday's 5 MB limit
        SIZE_LIMIT = 5 * 1024 * 1024   # 5 MB in bytes
        total_size = sum(Path(f).stat().st_size for f in files_to_upload if Path(f).exists())
        for path in SUPPLEMENTARY:
            p = Path(path)
            if not p.exists():
                print(f"  Supplementary file not found, skipping: {p.name}")
                continue
            file_size = p.stat().st_size
            if total_size + file_size > SIZE_LIMIT:
                print(f"  Skipping {p.name} — would exceed 5 MB limit "
                      f"({(total_size + file_size) / 1024 / 1024:.1f} MB total)")
                break
            files_to_upload.append(path)
            total_size += file_size

        # Cap at 5 (Workday's typical maximum)
        files_to_upload = files_to_upload[:5]

    print(f"  Uploading {len(files_to_upload)} file(s): {[Path(f).name for f in files_to_upload]}")
    try:
        upload_input.set_input_files(files_to_upload)
        time.sleep(2)
        # Check if Workday rejected the batch (shows an inline error about file size/type)
        error_visible = upload_input.evaluate("""el => {
            const form = el.closest('form, section, div[data-automation-id]') || el.parentElement;
            return form ? form.innerText.toLowerCase().includes('5mb') ||
                          form.innerText.toLowerCase().includes('error') : false;
        }""")
        if error_visible and len(files_to_upload) > 1:
            print("    Upload error detected — retrying with resume only.")
            upload_input.set_input_files([resume_pdf])
            time.sleep(2)
        print("    Upload complete.")
    except Exception as e:
        print(f"    Upload failed: {e}")


# ===========================================================================
# PERSONAL INFORMATION
# ===========================================================================



def _fill_state(page, state: str, state_abbr: str):
    """
    Fill State/Territory field.
    Approach mirrors how street address is filled: find the field by label,
    type the value, wait for suggestions, pick the matching one.
    """
    print(f"    Setting state: {state} ({state_abbr})")

    # Close any lingering dropdown before we start
    page.keyboard.press("Escape")
    time.sleep(0.2)

    # ── Strategy 1: INPUT with known data-automation-id (typeahead, like street address) ──
    input_selectors = [
        "input[data-automation-id='addressSection_countryRegion']",
        "input[data-automation-id='addressSection_stateProvince']",
        "input[data-automation-id='addressSection_regionSubdivision1']",
        "input[data-automation-id='countryRegion']",
        "input[data-automation-id='stateProvince']",
        "input[data-automation-id='region']",
    ]
    for sel in input_selectors:
        inp = page.query_selector(sel)
        if inp and inp.is_visible():
            print(f"      Found state input via: {sel}")
            inp.click()
            inp.fill(state)
            opts = _wait_for_prompt_options(page, timeout=3000)
            print(f"      Options after fill: {len(opts)}")
            if _pick_prompt_option(page, opts, state):
                print(f"      State selected: {state}")
                return True
            if _pick_prompt_option(page, opts, state_abbr):
                print(f"      State selected via abbr: {state_abbr}")
                return True
            if opts:
                first = opts[0].inner_text().strip()
                opts[0].scroll_into_view_if_needed()
                opts[0].click()
                print(f"      State fallback first option: {first}")
                return True

    # ── Strategy 2: JS — find label → associated INPUT, fill it like typeahead ──
    el_info = page.evaluate("""
        () => {
            for (const lbl of document.querySelectorAll('label')) {
                const txt = lbl.textContent.trim().toLowerCase();
                if (!txt.includes('state') && !txt.includes('territory') &&
                    !txt.includes('region') && !txt.includes('province')) continue;
                const forId = lbl.getAttribute('for');
                if (!forId) continue;
                const el = document.getElementById(forId);
                if (!el || !el.offsetParent) continue;
                return { id: forId, tag: el.tagName };
            }
            return null;
        }
    """)

    if el_info:
        print(f"      JS found element: id='{el_info['id']}' tag={el_info['tag']}")
        el = page.query_selector(f"#{el_info['id']}")
        if el and el.is_visible():
            if el_info["tag"] == "INPUT":
                el.click()
                el.fill(state)
                opts = _wait_for_prompt_options(page, timeout=3000)
                print(f"      Options after JS input fill: {len(opts)}")
                if _pick_prompt_option(page, opts, state) or _pick_prompt_option(page, opts, state_abbr):
                    return True
            elif el_info["tag"] == "BUTTON":
                el.scroll_into_view_if_needed()
                el.click()
                # Wait for a listbox with multiple state options to appear
                try:
                    page.wait_for_selector("[role='listbox']", state="visible", timeout=3000)
                except Exception:
                    pass
                # Try multiple option selectors — avoid single-item false positives (phone code)
                for opt_sel in [
                    "[data-automation-id='promptOption']",
                    "[role='option']",
                    "li[data-automation-id]",
                ]:
                    opts = page.query_selector_all(opt_sel)
                    if len(opts) > 1:   # >1 means it's a real state list, not phone code
                        print(f"      {len(opts)} options via '{opt_sel}'")
                        if _pick_prompt_option(page, opts, state) or _pick_prompt_option(page, opts, state_abbr):
                            return True
                        break
                page.keyboard.press("Escape")
                time.sleep(0.2)

    # ── Strategy 3: Scan ALL buttons; require >1 option after click (filter false positives) ──
    print("      Strategy 3: scanning buttons for state/territory...")
    for btn in page.query_selector_all("button"):
        try:
            if not btn.is_visible():
                continue
            lbl = (btn.get_attribute("aria-label") or "").lower()
            txt = btn.inner_text().strip().lower()
            if not any(x in lbl or x in txt for x in ["state", "territory", "region", "province"]):
                continue
            print(f"      Candidate btn: aria-label='{lbl}' text='{txt}'")
            btn.scroll_into_view_if_needed()
            btn.click()
            try:
                page.wait_for_selector("[role='listbox']", state="visible", timeout=3000)
            except Exception:
                pass
            for opt_sel in [
                "[data-automation-id='promptOption']",
                "[role='option']",
                "li[data-automation-id]",
            ]:
                opts = page.query_selector_all(opt_sel)
                if len(opts) > 1:
                    print(f"      {len(opts)} options via '{opt_sel}': {[o.inner_text()[:15] for o in opts[:4]]}")
                    if _pick_prompt_option(page, opts, state) or _pick_prompt_option(page, opts, state_abbr):
                        return True
                    break
            page.keyboard.press("Escape")
            time.sleep(0.2)
        except Exception as e:
            print(f"      Btn error: {e}")
            continue

    print("      WARNING: Could not set state/territory.")
    return False


def _fill_personal_info(page, applicant: dict, job_title: str, job_desc: str):
    print("  Filling personal information...")
    a = applicant

    # Name — exclude="preferred" prevents filling "Preferred First/Last Name" fields
    _safe_fill(page, "input[data-automation-id='legalNameSection_firstName']", a["first_name"])
    _safe_fill(page, "input[data-automation-id='legalNameSection_lastName']", a["last_name"])
    _fill_by_label(page, "First Name", a["first_name"], exclude="preferred")
    _fill_by_label(page, "Last Name",  a["last_name"],  exclude="preferred")

    # Ensure "I have a preferred name" checkbox is UNCHECKED — never tick it.
    # If the form pre-ticks it for some reason, uncheck it; otherwise leave it alone.
    _PREF_NAME_FRAGMENTS = [
        "preferred name", "use a different name", "goes by a different name",
        "alternate name", "known as",
    ]
    for cb in page.query_selector_all("input[type='checkbox']"):
        try:
            cb_label = cb.evaluate("""el => {
                if (el.id) {
                    const l = document.querySelector('label[for="' + el.id + '"]');
                    if (l) return l.textContent.trim().toLowerCase();
                }
                const p = el.closest('label');
                if (p) return p.textContent.trim().toLowerCase();
                return '';
            }""")
            if any(f in cb_label for f in _PREF_NAME_FRAGMENTS):
                if cb.is_checked():
                    cb.evaluate("el => { el.scrollIntoView({block:'center'}); el.click(); }")
                    time.sleep(0.3)
                    print("    Unchecked 'preferred name' checkbox")
                # Whether checked or not, stop after finding it
                break
        except Exception:
            continue

    # Salutation / Title dropdown — detect purely by label, no position assumptions.
    salutation = SALUTATION
    salutation_fallbacks = ["Mr.", "Mr", "Mr "]
    salutation_filled = False
    print(f"    Filling Salutation → {salutation}")

    # Strategy 1: button carries the automation-id directly (not a child of it).
    for sel in [
        "button[data-automation-id='legalNameSection_salutation']",
        "button[data-automation-id='salutation']",
        "button[data-automation-id='nameTitle']",
        "button[data-automation-id='title']",
    ]:
        btn = page.query_selector(sel)
        if btn and btn.is_visible():
            _workday_dropdown(page, btn, salutation, fallbacks=salutation_fallbacks)
            salutation_filled = True
            print(f"    Salutation filled via Strategy 1 → {salutation}")
            break

    if not salutation_filled:
        # Strategy 2: walk up at most 3 parent levels from each visible button.
        # Check only DIRECT children of each ancestor for a label/legend/div whose
        # stripped text equals "Salutation" exactly (case-insensitive).
        # Stop early if we reach FORM, BODY, or MAIN to prevent page-wide false matches.
        for btn in page.query_selector_all("button"):
            try:
                if not btn.is_visible():
                    continue
                matched = btn.evaluate("""el => {
                    const STOP_TAGS = new Set(['FORM', 'BODY', 'MAIN', 'HTML']);
                    let node = el.parentElement;
                    for (let i = 0; i < 3; i++) {
                        if (!node || STOP_TAGS.has(node.tagName)) break;
                        for (const child of node.children) {
                            const t = child.textContent.trim().toLowerCase();
                            if (t === 'salutation' || t === 'salutation *' ||
                                    t === 'salutation*') return true;
                        }
                        node = node.parentElement;
                    }
                    return false;
                }""")
                if matched:
                    _workday_dropdown(page, btn, salutation, fallbacks=salutation_fallbacks)
                    salutation_filled = True
                    print(f"    Salutation filled via Strategy 2 → {salutation}")
                    break
            except Exception:
                continue

    if not salutation_filled:
        # Strategy 3: label[for=id] / aria-labelledby fallback — unchanged.
        for lbl in page.query_selector_all("label"):
            lbl_txt = lbl.inner_text().strip().lower()
            if "salutation" not in lbl_txt:
                continue
            # Try label[for] → element id
            for_id = lbl.get_attribute("for")
            if for_id:
                el = page.query_selector(f"#{for_id}")
                if el and el.is_visible():
                    _workday_dropdown(page, el, salutation, fallbacks=salutation_fallbacks)
                    salutation_filled = True
                    print(f"    Salutation filled via Strategy 3 → {salutation}")
                    break
            # Try button[aria-labelledby=label-id]
            lbl_id = lbl.get_attribute("id")
            if lbl_id:
                btn = page.query_selector(f"button[aria-labelledby='{lbl_id}']")
                if btn and btn.is_visible():
                    _workday_dropdown(page, btn, salutation, fallbacks=salutation_fallbacks)
                    salutation_filled = True
                    print(f"    Salutation filled via Strategy 3 → {salutation}")
                    break

    if not salutation_filled:
        print("    WARNING: Salutation not filled — manual intervention may be needed")

    # Email
    _safe_fill(page, "input[data-automation-id='email']", a["email"])
    _fill_by_label(page, "Email", a["email"])

    addr = a["address"]
    phone_val = a["phone"]

    # Phone Device Type — button dropdown, pick "Mobile"
    phone_type_filled = False
    for sel in [
        "[data-automation-id='phone-device-type'] button",
        "[data-automation-id='phoneDeviceType'] button",
        "[data-automation-id='deviceType'] button",
        "[data-automation-id='phone_device_type'] button",
        "[data-automation-id='phoneType'] button",
    ]:
        btn = page.query_selector(sel)
        if btn and btn.is_visible():
            _workday_dropdown(page, btn, "Mobile", fallbacks=["Cell", "Other"])
            phone_type_filled = True
            break
    if not phone_type_filled:
        # Label-based fallback
        for lbl in page.query_selector_all("label"):
            lbl_txt = lbl.inner_text().strip().lower()
            if not any(x in lbl_txt for x in ["device type", "phone type", "phone device"]):
                continue
            for_id = lbl.get_attribute("for")
            if not for_id:
                continue
            el = page.query_selector(f"#{for_id}")
            if el and el.is_visible():
                _workday_dropdown(page, el, "Mobile", fallbacks=["Cell", "Other"])
                break

    # Country Phone Code
    try:
        cc_el = page.get_by_label("Country Phone Code", exact=False).first
        if cc_el.is_visible():
            tag = cc_el.evaluate("el => el.tagName").lower()
            if tag == "input":
                cc_el.click()
                cc_el.fill("Australia")
            else:
                cc_el.click()
            # Wait for options to appear, then pick +61 Australia
            opts = _wait_for_prompt_options(page, timeout=4000)
            for opt in opts:
                txt = opt.inner_text()
                if "australia" in txt.lower() or "+61" in txt:
                    opt.scroll_into_view_if_needed()
                    opt.click()
                    break
    except Exception:
        pass

    # Phone Number — digits only
    phone_input = page.query_selector(
        "input[data-automation-id='phone'], "
        "input[data-automation-id='phoneNumber']"
    )
    if phone_input and phone_input.is_visible():
        phone_input.click()
        phone_input.fill(phone_val)
    else:
        _fill_by_label(page, "Phone Number", phone_val)

    # Address
    addr_search = page.query_selector("input[data-automation-id='addressSection_addressLine1']")
    if addr_search:
        addr_search.fill(f"{addr['street']}, {addr['suburb']}")
        time.sleep(1.5)
        suggestions = page.query_selector_all("[data-automation-id='promptOption']")
        if suggestions:
            suggestions[0].click()
        else:
            addr_search.fill(addr["street"])
    else:
        _fill_by_label(page, "Address Line 1", addr["street"])
        _fill_by_label(page, "Street", addr["street"])

    _fill_by_label(page, "City", addr["city"])
    _fill_by_label(page, "Suburb", addr["suburb"])
    _fill_by_label(page, "Postcode", addr["postcode"])
    _fill_by_label(page, "Postal Code", addr["postcode"])
    _fill_by_label(page, "Zip", addr["postcode"])

    # State / Territory
    _fill_state(page, addr["state"], addr.get("state_abbr", "VIC"))

    # LinkedIn / website
    _fill_by_label(page, "LinkedIn", a["linkedin"])
    _fill_by_label(page, "Website", a.get("website", ""))
    _fill_by_label(page, "GitHub", a.get("website", ""))
    _fill_by_label(page, "Portfolio", a.get("website", ""))

    print("    Personal info filled.")


# ===========================================================================
# WORK EXPERIENCE
# ===========================================================================



def _count_existing_work_entries(page) -> int:
    """Count filled work experience entries by their numbered headings.
    Workday renders each entry with a heading like 'Work Experience 1', 'Work Experience 2', etc.
    This is simpler and more reliable than counting delete buttons by section scope.
    """
    return page.evaluate("""() => {
        let count = 0;
        for (const el of document.querySelectorAll('*')) {
            if (!el.offsetParent) continue;
            if (el.children.length > 0) continue;  // leaf text nodes only
            const txt = el.textContent.trim();
            if (/^Work Experience \\d+$/i.test(txt) ||
                /^Employment \\d+$/i.test(txt) ||
                /^Experience \\d+$/i.test(txt)) {
                count++;
            }
        }
        return count;
    }""")


def _fill_work_experience(page, applicant: dict):
    print("  Filling work experience...")

    # Pre-check: if the form already has entries filled (e.g. from a previous run
    # that Workday auto-saved), skip adding new ones to prevent duplicates.
    expected = len(applicant["work_experience"])
    existing = _count_existing_work_entries(page)
    if existing >= expected:
        print(f"    Skipping — {existing} entries already on form (need {expected})")
        return
    if existing > 0:
        print(f"    Found {existing} existing entries — will add the remaining {expected - existing}")
        # Skip the first `existing` entries from applicant.json
        entries_to_add = applicant["work_experience"][existing:]
    else:
        entries_to_add = applicant["work_experience"]

    for i, exp in enumerate(entries_to_add):
        global_i = existing + i
        print(f"    Adding experience {global_i+1}: {exp['title']} at {exp['company']}")

        # Always use _click_section_add — it now matches 'Add' AND 'Add Another',
        # and is scoped to the work experience section heading to prevent
        # accidentally clicking another section's button.
        clicked = _click_section_add(page, "work experience")
        if not clicked:
            print("    Could not find Work Experience Add/Add Another button — stopping.")
            break
        # Wait for the new form to render (including date inputs which render async)
        time.sleep(2.0)

        # Fill text fields — _fill_last_blank targets the last (newest) form
        _fill_last_blank(page, "Job Title", exp["title"])
        _fill_last_blank(page, "Position Title", exp["title"])
        _fill_last_blank(page, "Company", exp["company"])
        _fill_last_blank(page, "Employer", exp["company"])
        _fill_last_blank(page, "Organization", exp["company"])
        _fill_last_blank(page, "Location", DEFAULT_LOCATION)

        # Determine whether this is an active/current role
        is_current = exp.get("end", "").strip().lower() in ("present", "current", "now", "")

        # Sync "I currently work here" checkbox using Playwright's own .click()
        # so React's synthetic onChange fires correctly (JS cb.click() bypasses it).
        # Collect ALL visible "I currently work here" checkboxes (one per entry on the form),
        # then target the one at index `global_i` — the entry we just added.
        _CURRENT_WORK_PHRASES = ["currently work", "current employer", "i currently work"]
        cb_elements = []
        for lbl in page.query_selector_all("label"):
            try:
                lbl_txt = lbl.inner_text().lower()
                if any(ph in lbl_txt for ph in _CURRENT_WORK_PHRASES):
                    for_id = lbl.get_attribute("for")
                    cb = None
                    if for_id:
                        cb = page.query_selector(f"#{for_id}")
                    if not cb:
                        cb = lbl.query_selector("input[type='checkbox']")
                    if cb:
                        cb_elements.append(cb)
            except Exception:
                continue
        cb_element = cb_elements[global_i] if global_i < len(cb_elements) else None
        if cb_element:
            try:
                currently_checked = cb_element.is_checked()
                if is_current and not currently_checked:
                    cb_element.click()
                    print("      'I currently work here' → checked")
                elif not is_current and currently_checked:
                    cb_element.click()
                    print("      'I currently work here' → unchecked")
            except Exception as e:
                print(f"      WARNING: could not sync 'currently work here' checkbox: {e}")
        time.sleep(0.5)  # let To field appear/disappear before filling dates

        # Dates — wait explicitly for the date input to render after other fields are filled
        date_appeared = False
        for ph in ["MM/YYYY", "MM / YYYY", "mm/yyyy", "Month/Year"]:
            try:
                page.wait_for_selector(f"input[placeholder='{ph}']", state="visible", timeout=800)
                date_appeared = True
                break
            except Exception:
                pass
        if not date_appeared:
            time.sleep(0.8)  # brief extra wait if no date input detected yet
        if not _fill_exp_dates(page, exp["start"], exp["end"], is_current):
            print(f"      Warning: MM/YYYY date inputs not found for '{exp['title']}'")

        # Description — bullet points
        desc = _format_description(exp["description"])
        if not _fill_last_blank(page, "Description", desc):
            if not _fill_last_blank(page, "Role Description", desc):
                _fill_last_blank(page, "Job Description", desc)


# ===========================================================================
# EDUCATION
# ===========================================================================



def _fill_field_of_study(page, field: str) -> bool:
    """
    Fill Workday's Field of Study — a search + radio-button panel.
    1. Find the label → associated element (could be an input or custom button).
    2. Click it to open the search panel.
    3. Type the search term in the Search box.
    4. Click the matching radio button / option.
    """
    # Find the LAST visible element associated with a "Field of Study" label
    target_el = None
    for lbl in page.query_selector_all("label"):
        try:
            lbl_txt = lbl.inner_text().strip().lower()
            if not any(x in lbl_txt for x in ["field of study", "major", "area of study"]):
                continue
            for_id = lbl.get_attribute("for")
            if not for_id:
                continue
            el = page.query_selector(f"#{for_id}")
            if el and el.is_visible():
                target_el = el  # keep overwriting → gets the last (newest) form
        except Exception:
            continue

    if not target_el:
        return False

    try:
        # target_el IS the search input — the label's for= attribute points directly
        # to the selectinput widget's <input>. Clicking with Playwright (CDP) produces
        # isTrusted=true events, ensuring React's event handlers fire correctly.
        target_el.scroll_into_view_if_needed()
        target_el.click()
        time.sleep(0.8)

        # Wait for the dropdown options to appear
        try:
            page.wait_for_selector("[data-automation-id='promptOption']", state="visible", timeout=3000)
        except Exception:
            return False

        # Some Workday instances show a two-level menu: "Partial List" and "All →".
        # We must click "All" first to expand the full searchable list.
        try:
            all_opts = page.query_selector_all("[data-automation-id='promptOption']")
            for opt in all_opts:
                try:
                    opt_txt = opt.inner_text().strip().lower()
                    if opt_txt in ("all", "all fields", "show all") or opt_txt.startswith("all "):
                        opt.scroll_into_view_if_needed()
                        opt.click()
                        time.sleep(0.5)
                        break
                except Exception:
                    continue
        except Exception:
            pass

        # Clear existing value then type the search term
        target_el.click(click_count=3)
        target_el.type(field, delay=60)
        time.sleep(0.8)

        # Log visible options after typing for diagnosis
        visible_opts = page.evaluate("""() =>
            Array.from(document.querySelectorAll('[data-automation-id="promptOption"]'))
                .filter(e => e.offsetParent)
                .map(e => e.textContent.trim())
                .slice(0, 8)
        """)
        print(f"      Options after typing '{field}': {visible_opts}")

        # Strategy 1: Playwright .click() on a matching option (CDP — isTrusted=true).
        # JS dispatchEvent gives isTrusted=false which Workday's React event system ignores.
        clicked = None
        opts = _wait_for_prompt_options(page, timeout=3000)
        for opt in opts:
            try:
                if not opt.is_visible():
                    continue
                if field.lower() in opt.inner_text().strip().lower():
                    opt.scroll_into_view_if_needed()
                    opt.click()
                    time.sleep(0.3)
                    clicked = opt.inner_text().strip()
                    break
            except Exception:
                continue

        # Strategy 2: ArrowDown + Enter — ONLY when the filtered list already contains
        # a relevant option (i.e. at least one option text contains the search term).
        # Without this guard, ArrowDown blindly picks the first alphabetical result
        # (e.g. "Agricultural Business and Management" when searching "Finance").
        if not clicked and opts:
            has_relevant = any(
                field.lower() in (o.inner_text().strip().lower())
                for o in opts
                if o.is_visible()
            )
            if has_relevant:
                try:
                    target_el.press("ArrowDown")
                    time.sleep(0.3)
                    target_el.press("Enter")
                    time.sleep(0.3)
                    clicked = field
                except Exception:
                    pass

        # Strategy 3: radio buttons with matching label text (alternate Workday layout)
        if not clicked:
            for inp in page.query_selector_all("input[type='radio']"):
                try:
                    lbl_el = page.query_selector(f"label[for='{inp.get_attribute('id')}']")
                    if lbl_el and field.lower() in lbl_el.inner_text().lower():
                        inp.scroll_into_view_if_needed()
                        inp.click()
                        time.sleep(0.3)
                        clicked = field
                        break
                except Exception:
                    continue

        time.sleep(0.3)
        print(f"      Field of study clicked: {clicked!r}")

        # Close the panel with a REAL trusted mouse click outside the widget.
        # Synthetic JS events have isTrusted=false which Workday's UXI click-outside
        # handler ignores. page.mouse.click() uses CDP Input.dispatchMouseEvent
        # which produces isTrusted=true and correctly triggers the close handler.
        # Click 80px above target_el — that's the Degree/Institution field, outside panel.
        try:
            box = target_el.bounding_box()
            if box:
                click_y = max(10, box["y"] - 80)
                page.mouse.click(box["x"] + box["width"] / 2, click_y)
            else:
                page.mouse.click(100, 100)
        except Exception:
            page.mouse.click(100, 100)
        time.sleep(0.3)

        # Verify closed
        try:
            page.wait_for_selector("[data-automation-id='promptOption']", state="hidden", timeout=800)
        except Exception:
            pass  # best effort — proceed regardless

        return bool(clicked)

    except Exception as e:
        print(f"      Field of study error: {e}")
        try:
            box = target_el.bounding_box()
            if box:
                page.mouse.click(box["x"] + box["width"] / 2, max(10, box["y"] - 80))
            else:
                page.mouse.click(100, 100)
        except Exception:
            pass
    return False


def _count_existing_edu_entries(page) -> int:
    """Count how many education entries already exist on the form (by delete buttons)."""
    return page.evaluate("""() => {
        const allEls = Array.from(document.querySelectorAll('*'));
        let sectionStart = -1;
        let sectionEnd = allEls.length;
        const STOP_HEADERS = [
            'languages', 'language', 'skills', 'certifications',
            'volunteer', 'achievements', 'websites', 'website',
        ];
        for (let i = 0; i < allEls.length; i++) {
            const el = allEls[i];
            if (!el.offsetParent) continue;
            const txt = el.textContent.trim().toLowerCase();
            if ((txt === 'education' || txt.startsWith('education ') || txt.startsWith('education('))
                && el.children.length === 0) {
                sectionStart = i;
                break;
            }
        }
        if (sectionStart === -1) return 0;
        for (let i = sectionStart + 1; i < allEls.length; i++) {
            const el = allEls[i];
            if (!el.offsetParent) continue;
            const txt = el.textContent.trim().toLowerCase();
            if (STOP_HEADERS.some(h => txt === h || txt.startsWith(h + ' ') || txt.startsWith(h + '('))) {
                sectionEnd = i;
                break;
            }
        }
        let count = 0;
        for (let i = sectionStart; i < sectionEnd; i++) {
            const el = allEls[i];
            if (!el.offsetParent) continue;
            const tag = el.tagName.toLowerCase();
            const role = (el.getAttribute('role') || '').toLowerCase();
            const ariaLabel = (el.getAttribute('aria-label') || '').toLowerCase();
            const txt = el.textContent.trim().toLowerCase();
            if ((tag === 'button' || role === 'button') &&
                (ariaLabel.includes('delete') || ariaLabel.includes('remove') ||
                 txt === 'delete' || txt === 'remove')) {
                count++;
            }
        }
        return count;
    }""")


def _fill_education(page, applicant: dict, job_title: str = "", job_desc: str = ""):
    print("  Filling education...")

    expected = len(applicant["education"])
    existing = _count_existing_edu_entries(page)
    if existing >= expected:
        print(f"    Skipping education — {existing} entries already on form (need {expected})")
        return
    if existing > 0:
        print(f"    Found {existing} existing education entries — adding remaining {expected - existing}")
        entries_to_add = applicant["education"][existing:]
    else:
        entries_to_add = applicant["education"]

    for i, edu in enumerate(entries_to_add):
        global_edu_i = existing + i
        print(f"    Adding education {global_edu_i+1}: {edu['degree']} at {edu['institution']}")

        # Always use section-scoped _click_section_add (matches 'Add' and 'Add Another')
        # so we never accidentally click work experience's 'Add Another' button
        clicked = _click_section_add(page, "education")
        if not clicked:
            print("    Could not find Education Add/Add Another button — stopping.")
            break
        time.sleep(1.2)

        # School — use _fill_last_blank so we target the new blank form
        filled_school = False
        for lbl in ["School or University", "School", "Institution", "University", "College"]:
            if _fill_last_blank(page, lbl, edu["institution"]):
                filled_school = True
                break

        # Degree — find the button near a "Degree" label (not "Field of Study")
        degree_search, degree_fallbacks = _degree_level(edu["degree"])
        print(f"      Degree search: '{degree_search}'  fallbacks: {degree_fallbacks}")
        degree_filled = False

        # Method 0: native <select> near a Degree label (some Workday implementations)
        if not degree_filled:
            for sel_el in page.query_selector_all("select"):
                try:
                    if not sel_el.is_visible():
                        continue
                    near_degree = sel_el.evaluate("""el => {
                        let node = el.parentElement;
                        for (let i = 0; i < 6; i++) {
                            if (!node) break;
                            for (const l of node.querySelectorAll('label')) {
                                const t = l.textContent.toLowerCase();
                                if (t.includes('degree') && !t.includes('field') && !t.includes('study')) return true;
                            }
                            node = node.parentElement;
                        }
                        return false;
                    }""")
                    if not near_degree:
                        continue
                    options = sel_el.evaluate("el => Array.from(el.options).map(o => ({v: o.value, t: o.text}))")
                    for attempt in [degree_search] + degree_fallbacks:
                        for opt in options:
                            if attempt.lower() in opt["t"].lower():
                                sel_el.select_option(value=opt["v"])
                                degree_filled = True
                                print(f"      Degree set via native select: {opt['t']}")
                                break
                        if degree_filled:
                            break
                    if degree_filled:
                        break
                except Exception:
                    continue

        # Method 1: data-automation-id selectors
        if not degree_filled:
            for deg_sel in [
                "button[data-automation-id='degree']",
                "button[data-automation-id='degreeType']",
                "button[data-automation-id='educationDegree']",
                "[data-automation-id='degree'] button",
                "[data-automation-id='degreeType'] button",
                "[data-automation-id='educationDegree'] button",
            ]:
                deg_btn = page.query_selector(deg_sel)
                if deg_btn and deg_btn.is_visible():
                    _workday_dropdown(page, deg_btn, degree_search, fallbacks=degree_fallbacks)
                    degree_filled = True
                    break

        # Method 2: find label "Degree" → associated button/select (last one = new form)
        if not degree_filled:
            candidates = []
            for lbl in page.query_selector_all("label"):
                lbl_txt = lbl.inner_text().strip().lower()
                # Match "Degree" but NOT "Field of Study" labels
                if "degree" in lbl_txt and "field" not in lbl_txt and "study" not in lbl_txt:
                    for_id = lbl.get_attribute("for")
                    if not for_id:
                        continue
                    el = page.query_selector(f"#{for_id}")
                    if el and el.is_visible():
                        candidates.append(el)
            if candidates:
                el = candidates[-1]  # last = newest form
                tag = el.evaluate("e => e.tagName")
                if tag == "BUTTON":
                    _workday_dropdown(page, el, degree_search, fallbacks=degree_fallbacks)
                    degree_filled = True
                elif tag == "SELECT":
                    options = el.evaluate("e => Array.from(e.options).map(o => o.text)")
                    for attempt in [degree_search] + degree_fallbacks:
                        for opt_txt in options:
                            if attempt.lower() in opt_txt.lower():
                                el.select_option(label=opt_txt)
                                degree_filled = True
                                break
                        if degree_filled:
                            break

        # Method 3: scan all "Select One" buttons near a Degree label
        if not degree_filled:
            for btn in page.query_selector_all("button"):
                try:
                    if not btn.is_visible() or btn.inner_text().strip() != "Select One":
                        continue
                    near_degree = btn.evaluate("""el => {
                        let node = el.parentElement;
                        for (let i = 0; i < 8; i++) {
                            if (!node) break;
                            for (const l of node.querySelectorAll('label')) {
                                const t = l.textContent.toLowerCase();
                                if (t.includes('degree') && !t.includes('field') && !t.includes('study')) return true;
                            }
                            node = node.parentElement;
                        }
                        return false;
                    }""")
                    if near_degree:
                        _workday_dropdown(page, btn, degree_search, fallbacks=degree_fallbacks)
                        degree_filled = True
                        break
                except Exception:
                    continue

        # Field of study — adjusted for job context
        field = _education_field(edu["field"], job_title, job_desc, edu["degree"])
        print(f"      Field of study: '{field}'")
        field_filled = _fill_field_of_study(page, field)

        # GPA
        if edu.get("gpa"):
            gpa_full = edu["gpa"]           # "3.6/4.0"
            gpa_val = gpa_full.split("/")[0]  # "3.6"
            _fill_last_blank(page, "GPA", gpa_val)
            _fill_last_blank(page, "Overall Result (GPA)", gpa_full)
            _fill_last_blank(page, "Grade", gpa_full)

        # Dates — positional: picks last pair of YYYY inputs (education uses year-only)
        end_val = edu["end"] if edu["end"] != "Present" else ""
        if not _fill_edu_dates(page, edu["start"], end_val):
            # Fallback: education fields that use a 4-digit year box → pass year-only
            start_yr = edu["start"].split("/")[-1] if edu["start"] else ""
            end_yr   = end_val.split("/")[-1]       if end_val        else ""
            _fill_exp_dates(page, start_yr, end_yr, edu["end"] == "Present")


# ===========================================================================
# LANGUAGES
# ===========================================================================




def _fill_proficiency_dropdowns(page, level: str, fallback: str):
    """
    Fill all visible proficiency/comprehension/overall/reading/speaking Select One dropdowns
    with the given proficiency level. Tries level first, then fallback, then first option.
    """
    proficiency_labels = ["comprehension", "overall", "reading", "speaking", "writing", "proficiency"]
    for btn in page.query_selector_all("button"):
        try:
            if not btn.is_visible():
                continue
            btn_txt = btn.inner_text().strip()
            if btn_txt not in ("Select One", "- Select One -"):
                continue
            # Check if this button is near a proficiency label.
            # Only look at DIRECT CHILD labels of each ancestor (not querySelectorAll
            # which would reach across to other form groups and misidentify the language
            # name dropdown as a proficiency dropdown).
            label_near = btn.evaluate("""el => {
                let node = el.parentElement;
                for (let i = 0; i < 4; i++) {
                    if (!node) break;
                    for (const child of node.children) {
                        if (child.tagName !== 'LABEL') continue;
                        const t = child.textContent.trim().toLowerCase();
                        if (t.includes('comprehension') || t.includes('overall') ||
                            t.includes('reading') || t.includes('speaking') ||
                            t.includes('writing') || t.includes('proficiency')) return t;
                    }
                    node = node.parentElement;
                }
                return '';
            }""")
            if not label_near:
                continue
            btn.evaluate("el => { el.scrollIntoView({block:'center'}); el.click(); }")
            opts = _wait_for_prompt_options(page, timeout=2000)
            print(f"      Proficiency ({label_near[:30]}): {[o.inner_text().strip() for o in opts[:5]]}")
            # Sanity-check: verify the dropdown looks like a proficiency list, not an
            # education degree list. On pages with both education and language sections,
            # the DOM walk can find a proficiency label via a distant ancestor and then
            # accidentally open an education "Select One" button instead.
            PROFICIENCY_OPTION_WORDS = {
                "advanced", "intermediate", "beginner", "fluent", "native",
                "proficient", "basic", "conversational", "limited", "bilingual",
                "elementary", "classroom", "study", "none",
            }
            opt_texts = [o.inner_text().strip().lower() for o in opts[:6] if o.inner_text().strip()]
            looks_like_proficiency = any(
                any(w in t for w in PROFICIENCY_OPTION_WORDS) for t in opt_texts
            )
            if not looks_like_proficiency:
                page.keyboard.press("Escape")
                time.sleep(0.2)
                continue
            # Try exact level, then fallback, then pick last (highest) available
            matched = False
            for search in [level, fallback]:
                for opt in opts:
                    if search.lower() in opt.inner_text().lower():
                        opt.evaluate("el => { el.scrollIntoView({block:'center'}); el.click(); }")
                        time.sleep(0.3)
                        matched = True
                        break
                if matched:
                    break
            if not matched and opts:
                opts[-1].evaluate("el => { el.scrollIntoView({block:'center'}); el.click(); }")
                time.sleep(0.3)
        except Exception:
            continue


def _fill_languages(page):
    """Add languages to the Languages section with proficiency levels."""
    print("  Filling languages...")
    # Only English for now; expand list when language selection is stable
    languages = ["English"]

    for lang in languages:
        print(f"    Adding language: {lang}")
        prof = LANG_PROFICIENCY.get(lang, {"level": "Beginner", "fallback": "Elementary", "fluent": False})

        clicked = _click_section_add(page, "language")
        if not clicked:
            print(f"    Could not find Language Add/Add Another button — stopping at {lang}.")
            break
        time.sleep(1.0)  # let the new language form render

        # ── Find the Language NAME dropdown ──────────────────────────────────────
        # Must be a "Select One" button whose NEAREST label says "language"
        # (not comprehension/reading/etc.).  Use JS to find + click it in one shot.
        lang_btn_clicked = page.evaluate("""(langName) => {
            const SELECT_TEXTS = new Set(['select one', '- select one -']);
            const PROFICIENCY_WORDS = ['comprehension','overall','reading','speaking','writing','proficiency'];
            const buttons = Array.from(document.querySelectorAll('button'));
            // Collect all "Select One" buttons whose nearest label is a language label
            const candidates = [];
            for (const btn of buttons) {
                const txt = btn.textContent.trim().toLowerCase();
                if (!SELECT_TEXTS.has(txt) || !btn.offsetParent) continue;
                // Walk up to find the nearest label (direct child of a parent)
                let node = btn.parentElement;
                let labelText = '';
                for (let i = 0; i < 4; i++) {
                    if (!node) break;
                    for (const child of node.children) {
                        if (child.tagName !== 'LABEL') continue;
                        const t = child.textContent.trim().toLowerCase();
                        if (t.length > 0) { labelText = t; break; }
                    }
                    if (labelText) break;
                    node = node.parentElement;
                }
                const isProficiency = PROFICIENCY_WORDS.some(w => labelText.includes(w));
                const isLanguage = labelText.includes('language') && !isProficiency;
                if (isLanguage) candidates.push(btn);
            }
            // Click the last candidate (newest form at bottom)
            if (candidates.length > 0) {
                const btn = candidates[candidates.length - 1];
                btn.scrollIntoView({ block: 'center' });
                btn.click();
                return true;
            }
            return false;
        }""", lang)

        lang_filled = False
        if lang_btn_clicked:
            time.sleep(0.5)
            # Type to filter the language list
            try:
                search = page.query_selector(
                    "input[data-automation-id='searchBox'], "
                    "input[placeholder*='Search' i], "
                    "input[placeholder*='Type' i]"
                )
                if search and search.is_visible():
                    search.fill(lang)
                    time.sleep(0.4)
            except Exception:
                pass
            opts = _wait_for_prompt_options(page, timeout=3000)
            print(f"      Lang opts: {[o.inner_text().strip() for o in opts[:6]]}")
            for opt in opts:
                if lang.lower() in opt.inner_text().strip().lower():
                    opt.evaluate("el => { el.scrollIntoView({block:'center'}); el.click(); }")
                    lang_filled = True
                    print(f"      Selected language: {lang}")
                    time.sleep(0.3)
                    break
            if not lang_filled:
                page.keyboard.press("Escape")
                print(f"      No match for '{lang}' in options")
        else:
            print(f"      Could not find language dropdown for '{lang}'")

        # "I am fluent in this language" checkbox
        if prof["fluent"]:
            page.evaluate("""() => {
                for (const lbl of document.querySelectorAll('label')) {
                    if (lbl.textContent.toLowerCase().includes('fluent')) {
                        const id = lbl.getAttribute('for');
                        const cb = id ? document.getElementById(id) : lbl.querySelector('input[type=checkbox]');
                        if (cb && !cb.checked) { cb.click(); return; }
                        lbl.click(); return;
                    }
                }
            }""")

        # Fill all proficiency dropdowns (Comprehension, Overall, Reading, Speaking, Writing)
        _fill_proficiency_dropdowns(page, prof["level"], prof["fallback"])

        _save_section_form(page)


# ===========================================================================
# SKILLS
# ===========================================================================



def _get_skill_input(page):
    """Find the skills typeahead input on the page."""
    for sel in [
        "input[id*='skills' i]",                              # most specific: id="skills--skills"
        "input[data-uxi-widget-type='selectinput'][id*='skills' i]",  # UXI selectinput scoped to skills
        "input[placeholder*='Add Skills' i]",
        "input[placeholder*='Type to Add' i]",
        "input[placeholder*='skill' i]",
        "input[aria-label*='skill' i]",
        "[data-automation-id*='skill'] input",
        "[data-automation-id*='Skill'] input",
        "input[data-automation-id='searchBox'][id*='skills' i]",  # scoped — avoids field of study
    ]:
        el = page.query_selector(sel)
        if el and el.is_visible():
            return el
    # JS fallback: find input near a label containing "skill"
    try:
        result = page.evaluate("""() => {
            for (const lbl of document.querySelectorAll('label, [class*="label" i], p, span, div')) {
                const t = lbl.textContent.trim().toLowerCase();
                if (!t.includes('skill')) continue;
                // Look for a nearby input (sibling, parent's child, etc.)
                const parent = lbl.parentElement;
                if (!parent) continue;
                const inp = parent.querySelector('input');
                if (inp && inp.offsetParent) return true;
            }
            return false;
        }""")
        if result:
            # Find any visible input near a skills heading
            for inp in page.query_selector_all("input"):
                try:
                    if inp.is_visible():
                        ph = (inp.get_attribute("placeholder") or "").lower()
                        if "search" in ph or "type" in ph or ph == "":
                            # Check if a "skills" label is nearby
                            nearby = inp.evaluate("""el => {
                                const p = el.closest('section, div[class*="section"], div[class*="card"]');
                                return p ? p.textContent.toLowerCase().includes('skill') : false;
                            }""")
                            if nearby:
                                return inp
                except Exception:
                    pass
    except Exception:
        pass
    return None


def _fill_skills(page, applicant: dict, job_title: str, job_desc: str):
    """Add skills using the Workday typeahead checkbox selector."""
    print("  Filling skills...")
    skills = applicant.get("skills", [])
    if job_title or job_desc:
        try:
            skills_str = _claude_skills(job_title, job_desc, applicant)
            # Strip any markdown headers/bullets Claude may have included
            import re as _re
            skills_str = _re.sub(r"#[^\n]*\n?", "", skills_str)   # remove ## headings
            skills_str = _re.sub(r"^\s*[-*]\s*", "", skills_str, flags=_re.MULTILINE)
            skills = [s.strip() for s in skills_str.split(",") if s.strip() and not s.strip().startswith("#")]
            print(f"    Claude selected skills: {skills}")
        except Exception as e:
            print(f"    Claude skills failed ({e}), using all")

    added = 0
    for skill in skills[:10]:
        skill_input = _get_skill_input(page)
        if not skill_input:
            print(f"    No skill input found, stopping.")
            break

        # Close any stale dropdown from a previous iteration, then click via JS
        # to bypass any remaining overlay (pageFooter or open selectinputlistitem).
        page.keyboard.press("Escape")
        time.sleep(0.2)
        skill_input.evaluate("el => { el.scrollIntoView({block:'center', behavior:'instant'}); }")
        time.sleep(0.2)
        skill_input.evaluate("el => el.click()")
        time.sleep(0.3)   # wait for JS focus to transfer before sending keyboard events
        page.keyboard.press("Control+a")
        page.keyboard.press("Delete")
        page.keyboard.type(skill, delay=30)   # fires keydown/keypress/keyup per character

        # The UXI selectinput requires Enter to submit the search query.
        page.keyboard.press("Enter")
        time.sleep(0.5)

        opts = _wait_for_prompt_options(page, timeout=4000)
        if not opts:
            skill_input.press("Escape")
            time.sleep(0.2)
            continue

        # Pick best match — require a close substring match.
        # No fallback to "first option": a generic search term (e.g. "Valuation") can
        # return dozens of unrelated variants and we must not blindly accept the first.
        best_opt = None
        skill_lc = skill.lower()
        for opt in opts:
            try:
                opt_txt = opt.inner_text().strip().lower()
            except Exception:
                continue
            # Skip "Search Results (N)" header lines
            if "search result" in opt_txt or opt_txt.isdigit():
                continue
            if skill_lc in opt_txt or opt_txt in skill_lc:
                best_opt = opt
                break
        if best_opt is None:
            print(f"    No close match for '{skill}' in Workday options — skipping")
            skill_input.press("Escape")
            time.sleep(0.2)
            continue

        if best_opt:
            # Click the checkbox inside the option (if present), else click the option itself
            try:
                cb = best_opt.query_selector("input[type='checkbox']")
                if cb:
                    cb.evaluate("el => { el.scrollIntoView({block:'center'}); el.click(); }")
                else:
                    best_opt.evaluate("el => { el.scrollIntoView({block:'center'}); el.click(); }")
            except Exception:
                best_opt.evaluate("el => { el.scrollIntoView({block:'center'}); el.click(); }")
            time.sleep(0.3)
            added += 1
            # Close the multiselect dropdown with a trusted mouse click ABOVE the
            # skill input — identical pattern to field-of-study close.
            # Escape via JS focus does NOT work for UXI multiselect dropdowns
            # (they require isTrusted=true click-outside events to close).
            try:
                box = skill_input.bounding_box()
                if box:
                    page.mouse.click(box["x"] + box["width"] / 2, max(10, box["y"] - 80))
                else:
                    page.mouse.click(100, 100)
                time.sleep(0.3)
            except Exception:
                pass

    # Close the skills dropdown if still open
    try:
        skill_input = _get_skill_input(page)
        if skill_input:
            skill_input.press("Escape")
    except Exception:
        pass

    print(f"    Added {added} skill(s).")


# ===========================================================================
# WEBSITES & SOCIAL MEDIA
# ===========================================================================



def _fill_websites(page, applicant: dict):
    """
    Fill website sections:
    - Social Network URLs → LinkedIn field (already rendered, just fill it)
    - Websites section   → click Add, fill GitHub URL in the new row
    """
    linkedin = applicant.get("linkedin", "")
    github   = applicant.get("website", "")

    # ── LinkedIn in the Social Network URLs panel (pre-rendered field) ──
    if linkedin:
        for lbl_text in ["LinkedIn", "LinkedIn URL", "LinkedIn Profile"]:
            if _fill_by_label(page, lbl_text, linkedin):
                print(f"    LinkedIn filled.")
                break

    # ── GitHub via the Websites section "Add" button ──
    if github:
        # Use _click_section_add to find the Add button in the Websites section
        clicked = _click_section_add(page, "websites")
        if not clicked:
            clicked = _click_section_add(page, "website")
        if clicked:
            time.sleep(0.8)
            # Fill the URL input that appears in the new row
            url_filled = False
            for lbl_text in ["URL", "Website", "Website URL", "Address", "Link"]:
                if _fill_last_blank(page, lbl_text, github):
                    url_filled = True
                    break
            if not url_filled:
                # Try any visible empty text input in the websites area
                for inp in page.query_selector_all("input[type='text'], input[type='url']"):
                    try:
                        if inp.is_visible() and not inp.input_value().strip():
                            inp.evaluate("el => el.scrollIntoView({block:'center'})")
                            inp.fill(github)
                            url_filled = True
                            break
                    except Exception:
                        continue
            if url_filled:
                print(f"    GitHub URL added: {github}")
            else:
                print(f"    GitHub URL: could not find URL input after clicking Add")
        else:
            # No dedicated Websites Add button — try filling a generic Website label
            for lbl_text in ["Website", "URL", "Other Website", "Personal Website", "Portfolio"]:
                if _fill_by_label(page, lbl_text, github):
                    print(f"    GitHub filled via label '{lbl_text}'.")
                    break


# ===========================================================================
# QUESTION ROUTING HELPER
# ===========================================================================


def _quick_answer(label: str, applicant: dict, job_title: str, job_desc: str,
                  company: str = "") -> tuple:
    """Return (answer, input_type) for a question label without calling Claude if possible.

    input_type is one of: "yes_no", "text", "textarea", or "claude" (must call Claude).
    "yes_no" answer is "yes" or "no".
    "text"/"textarea" answer is the string to type.
    "claude" means no rule matched — caller should pass to _claude_answer().
    """
    q = label.lower()

    # ── Work rights / right to work ──
    # Returns the exact dropdown option text (from config) so _workday_dropdown can
    # partial-match it, e.g. "Yes - I am a Temporary Resident with Full Working Rights".
    if any(s in q for s in ["right to work", "work rights", "work in australia",
                             "legally entitled to work", "authorized to work",
                             "authorised to work", "eligible to work",
                             "work legally", "permitted to work"]):
        if applicant.get("visa", {}).get("authorized_to_work", True):
            return WORK_RIGHTS_ANSWER, "dropdown"
        return "No", "dropdown"

    # ── Internal referral / "do you know someone here" ──
    # Distinct from "How Did You Hear About Us?" — this is a Yes/No question.
    if any(s in q for s in ["referred by", "been referred", "know anyone",
                             "someone at", "internal referral", "employee referral"]):
        work_exp = applicant.get("work_experience", [])
        cos = [e.get("company", "").lower() for e in work_exp if e.get("company")]
        answer = "yes" if (company and any(company.lower() in co or co in company.lower()
                                           for co in cos)) else "no"
        return answer, "yes_no"

    # ── Years of experience ──
    if any(s in q for s in ["years of experience", "years experience", "how many years",
                             "years in a similar", "years relevant"]):
        return YEARS_EXPERIENCE, "text"

    # ── Salary expectation ──
    if any(s in q for s in ["salary expectation", "salary range", "expected salary",
                             "remuneration", "compensation", "package", "salary inclusive",
                             "base salary", "total salary", "annual salary", "ctc",
                             "salary expectations"]):
        # Use single value if question implies one number; range otherwise
        if any(s in q for s in ["single", "one figure", "number only", "per annum"]):
            return SALARY_EXPECTATION_SINGLE, "text"
        return SALARY_EXPECTATION, "text"

    # ── Reason for leaving ──
    if any(s in q for s in ["reason for leaving", "why are you leaving",
                             "leaving your current", "why do you want to leave",
                             "why leave", "reasons for leaving"]):
        return LEAVING_REASON, "textarea"

    # ── Aboriginal / Torres Strait Islander / Indigenous ──
    # Type "dropdown" because Workday often renders this as a multi-option list
    # (e.g. "No", "Yes", "Prefer not to answer") rather than a plain yes/no radio.
    if any(s in q for s in ["aboriginal", "torres strait", "indigenous", "first nations"]):
        return INDIGENOUS_STATUS, "dropdown"

    # ── Skills/experience match → must use Claude ──
    if any(s in q for s in ["skills and experience match", "why are you suitable",
                             "why do you want this role", "what makes you a good fit",
                             "describe your experience", "why are you applying",
                             "what interests you", "tell us about yourself"]):
        return "", "claude"

    # ── Prior employment at this specific company ──
    if any(s in q for s in ["previously worked", "former employee", "worked for",
                             "employed by", "worked at", "prior employment",
                             "previously employed"]):
        work_exp = applicant.get("work_experience", [])
        cos = [e.get("company", "").lower() for e in work_exp if e.get("company")]
        answer = "yes" if any(co and co in q for co in cos) else "no"
        return answer, "yes_no"

    return "", "claude"


# ===========================================================================
# SCREENING QUESTIONS
# ===========================================================================



def _fill_screening_questions(page, applicant: dict, job_title: str, job_desc: str,
                               company: str = ""):
    """Fill screening/disclosure select dropdowns. Default: No. Age 18+: Yes."""
    print("  Filling screening/disclosure questions...")
    answered = 0

    # Personal-info fields that Workday sometimes renders with "Select One" buttons
    # but are NOT screening questions — skip them silently.
    SCREENING_SKIP_LABELS = [
        "salutation", "title", "given name", "first name", "family name",
        "last name", "preferred name", "phone", "email", "address",
        "suburb", "postcode", "state", "region", "country",
        # Language-section proficiency sub-fields — handled by _fill_proficiency_dropdowns,
        # not screening questions. Without this, the loop fills them with "No" and then
        # Workday reverts the field, causing an infinite 50-iteration loop.
        "comprehension", "overall", "reading", "speaking", "writing", "language",
    ]

    # ── Workday custom dropdown buttons showing "Select One" ──
    # Re-query on every iteration to avoid stale ElementHandle after DOM changes.
    SELECT_TEXTS = {"Select One", "- Select One -", "Please Select", "-- Select --"}
    max_iter = 50
    for _ in range(max_iter):
        # Find the first unanswered "Select One" button
        target_btn = None
        for btn in page.query_selector_all("button"):
            try:
                if btn.is_visible() and btn.inner_text().strip() in SELECT_TEXTS:
                    target_btn = btn
                    break
            except Exception:
                continue
        if not target_btn:
            break

        try:
            # Walk up DOM to find the nearest label text
            label_text = target_btn.evaluate("""el => {
                let node = el.parentElement;
                for (let i = 0; i < 10; i++) {
                    if (!node) break;
                    const lbls = node.querySelectorAll('label, [data-automation-id*="Label"], p, span');
                    for (const l of lbls) {
                        const t = l.textContent.trim();
                        if (t.length > 5 && t.length < 300 && !t.includes('Select One')) return t;
                    }
                    node = node.parentElement;
                }
                return '';
            }""")

            # Strip Workday validation error prefixes so _screening_value gets clean text
            # e.g. "Error: The field Are you at least 18... is required and must have a value."
            clean_label = label_text
            for pfx in ["error:", "error :"]:
                if clean_label.lower().startswith(pfx):
                    clean_label = clean_label[len(pfx):].strip()
            # Also strip trailing " is required and must have a value." boilerplate
            for sfx in [" is required and must have a value.", " is required."]:
                if clean_label.lower().endswith(sfx):
                    clean_label = clean_label[: -len(sfx)].strip()
            # Strip "The field " prefix
            if clean_label.lower().startswith("the field "):
                clean_label = clean_label[len("the field "):].strip()

            # Skip personal-info fields that are not screening questions
            if any(skip in clean_label.lower() for skip in SCREENING_SKIP_LABELS):
                page.keyboard.press("Escape")
                time.sleep(0.2)
                break

            # ── Referral / "How Did You Hear About Us?" detection ──
            # Check the label BEFORE clicking so we can route to _workday_dropdown
            # directly — avoids opening the dropdown twice and logging a misleading "→ No".
            REFERRAL_LABEL_SIGNALS = [
                "hear about us", "how did you find", "referral source",
                "how did you hear", "learn about this", "how were you referred",
                "source of hire",
            ]
            if any(sig in clean_label.lower() for sig in REFERRAL_LABEL_SIGNALS):
                print(f"    Referral: '{clean_label[:70]}' → {REFERRAL_SOURCE}")
                _workday_dropdown(
                    page, target_btn, REFERRAL_SOURCE,
                    fallbacks=["Corporate Website", "Job Board", "LinkedIn",
                               "Indeed", "Seek", "Online", "Other"],
                )
                answered += 1
                continue  # next Select One button

            # ── Disability — skip unless the field is explicitly required ──
            # Disability is a sensitive optional field. Never touch it unless Workday
            # marks it as required (asterisk in label or aria-required attribute).
            _IS_DISABILITY_Q = any(s in clean_label.lower() for s in
                                   ["disability", "disabled", "impairment"])
            if _IS_DISABILITY_Q:
                lbl_has_asterisk = "*" in clean_label
                btn_required = target_btn.evaluate(
                    "el => el.getAttribute('aria-required') === 'true' || "
                    "el.closest('[aria-required=\"true\"]') !== null"
                )
                if not lbl_has_asterisk and not btn_required:
                    page.keyboard.press("Escape")
                    time.sleep(0.2)
                    continue  # skip this question, keep processing others

            # ── Resolve the answer to select ──
            # _quick_answer handles all known question types with exact/partial option text.
            # Fall back to _screening_value (Yes/No default) for everything else.
            qa_answer, qa_type = _quick_answer(clean_label, applicant, job_title, job_desc,
                                               company=company)
            if qa_answer and qa_type not in ("claude", "textarea", "text"):
                value = qa_answer
                # For plain yes/no answers, provide synonyms as fallbacks so Workday
                # variants like "True / False" or "I agree" are also matched.
                if value.lower() == "yes":
                    fallbacks = ["Yes", "True", "I agree", "Agree"]
                elif value.lower() == "no":
                    fallbacks = ["No", "False", "I disagree", "Disagree"]
                elif any(s in clean_label.lower() for s in
                         ["aboriginal", "torres strait", "indigenous", "first nations"]):
                    # Indigenous identity — Workday forms use many different non-identifying
                    # option names. Provide all common variants as fallbacks so whichever
                    # label this particular form uses gets matched.
                    fallbacks = [
                        "Neither", "No", "None",
                        "I do not identify", "Does not identify",
                        "Prefer not to say", "Prefer not to answer",
                        "Decline to Answer", "Decline to answer",
                        "Not Applicable", "N/A",
                    ]
                else:
                    fallbacks = ["Yes", "No"]
            else:
                value = _screening_value(clean_label)
                fallbacks = ["Yes", "No"] if value == "Yes" else ["No", "Yes"]

            print(f"    Screening: '{clean_label[:70]}' → {value}")

            # _workday_dropdown handles click, option wait, partial matching, and fallbacks
            matched = _workday_dropdown(page, target_btn, value, fallbacks=fallbacks)
            if matched:
                answered += 1
            else:
                print(f"      Could not select '{value}' — pressing Escape and skipping")
                page.keyboard.press("Escape")
                time.sleep(0.3)
                continue
        except Exception as e:
            print(f"      Screening error: {e}")
            page.keyboard.press("Escape")
            time.sleep(0.3)
            continue

    # ── Native <select> elements ──
    select_els = page.query_selector_all("select")
    for sel_el in select_els:
        try:
            current = sel_el.evaluate("el => el.options[el.selectedIndex]?.text || ''")
            if current.strip() and "select" not in current.lower():
                continue  # already answered

            sel_id = sel_el.get_attribute("id") or ""
            label_text = ""
            if sel_id:
                lbl = page.query_selector(f"label[for='{sel_id}']")
                if lbl:
                    label_text = lbl.inner_text().strip()

            value = _screening_value(label_text)
            print(f"    Screening (select): '{label_text[:60]}' → {value}")

            options = sel_el.evaluate(
                "el => Array.from(el.options).map(o => ({value: o.value, text: o.text}))"
            )
            for opt in options:
                if value.lower() in opt["text"].lower():
                    if sel_id:
                        page.select_option(f"#{sel_id}", value=opt["value"])
                    else:
                        sel_el.evaluate(
                            f"el => {{ el.value = '{opt['value']}'; "
                            f"el.dispatchEvent(new Event('change', {{bubbles:true}})); }}"
                        )
                    answered += 1
                    break
        except Exception:
            continue

    # ── Yes/No radio button questions ──
    # Some Workday forms render boolean questions as radio button pairs rather
    # than Select One dropdowns. Group radios by name, skip already-answered groups.
    radio_groups: dict = {}
    for rb in page.query_selector_all("input[type='radio']"):
        try:
            name = rb.get_attribute("name") or ""
            if not name:
                continue
            if name not in radio_groups:
                radio_groups[name] = []
            radio_groups[name].append(rb)
        except Exception:
            continue

    for name, radios in radio_groups.items():
        try:
            # Skip if any radio in the group is already selected
            if any(rb.is_checked() for rb in radios):
                continue

            # Resolve question label from the group (walk up from first radio)
            question_text = radios[0].evaluate("""el => {
                let node = el.parentElement;
                for (let i = 0; i < 8; i++) {
                    if (!node) break;
                    const lbls = node.querySelectorAll(
                        'label, [data-automation-id*="Label"], legend, p, span');
                    for (const l of lbls) {
                        const t = l.textContent.trim();
                        if (t.length > 5 && t.length < 400) return t;
                    }
                    node = node.parentElement;
                }
                return '';
            }""")

            # Collect the Yes/No option labels
            options = {}
            for rb in radios:
                lbl = rb.evaluate("""el => {
                    if (el.id) {
                        const l = document.querySelector('label[for="' + el.id + '"]');
                        if (l) return l.textContent.trim();
                    }
                    const p = el.closest('label');
                    if (p) return p.textContent.trim();
                    return el.value || '';
                }""")
                options[lbl.strip().lower()] = rb

            if not any(k in options for k in ["yes", "no", "true", "false"]):
                continue  # not a Yes/No group

            # Determine answer — try pattern rules first, fall back to Claude
            quick, _ = _quick_answer(question_text, applicant, job_title, job_desc,
                                     company=company)
            if quick in ("yes", "no"):
                answer = quick
            else:
                answer = _claude_answer(
                    question_text, VISA_INFO, applicant,
                    job_title=job_title, job_desc=job_desc
                ).lower().strip()
                if answer not in ("yes", "no"):
                    answer = "no"

            # Click the matching radio
            target = options.get(answer) or options.get("true" if answer == "yes" else "false")
            if target:
                print(f"    Radio '{question_text[:60]}' → {answer}")
                target.evaluate("el => { el.scrollIntoView({block:'center'}); el.click(); }")
                time.sleep(0.3)
                answered += 1
        except Exception:
            continue

    # ── Checkbox-style "I agree" disclosures ──
    # Some Workday forms present agreement statements as unchecked checkboxes rather
    # than Select One dropdowns. Check any unchecked checkbox whose nearby label
    # contains agree/acknowledge/certify language.
    AGREE_KEYWORDS = ["agree", "acknowledge", "certify", "confirm", "accept",
                      "terms", "privacy", "code of conduct", "read and understand"]
    for cb in page.query_selector_all("input[type='checkbox']"):
        try:
            if not cb.is_visible():
                continue
            if cb.is_checked():
                continue
            label_txt = cb.evaluate("""el => {
                // Try label[for=id] — most reliable
                if (el.id) {
                    const lbl = document.querySelector('label[for="' + el.id + '"]');
                    if (lbl) return lbl.textContent.trim();
                }
                // Try wrapping label
                const parent = el.closest('label');
                if (parent) return parent.textContent.trim();
                // Do NOT fall back to parentElement.textContent — it captures
                // unrelated surrounding text (footer links, privacy notices, etc.)
                // which causes false keyword matches on unrelated checkboxes.
                return '';
            }""")
            if any(kw in label_txt.lower() for kw in AGREE_KEYWORDS):
                print(f"    Agree checkbox: '{label_txt[:80]}' → checking")
                cb.evaluate("el => { el.scrollIntoView({block:'center'}); el.click(); }")
                time.sleep(0.3)
                answered += 1
        except Exception:
            continue

    print(f"    Answered {answered} screening question(s).")


# ===========================================================================
# CUSTOM QUESTIONS
# ===========================================================================



def _fill_custom_questions(page, applicant: dict, job_title: str, job_desc: str,
                           company: str = ""):
    """Find all unanswered visible text/textarea inputs and answer them.

    Pattern-matched questions (years experience, salary, leaving reason, etc.) are
    answered from config without calling Claude. Remaining questions go to Claude.
    """
    print("  Filling custom questions...")
    questions_answered = 0

    SKIP_LABELS = ["extension", "phone ext", "fax", "search", "filter",
                   "skill", "language", "first name", "last name", "email",
                   "phone", "address", "postcode", "suburb", "city", "linkedin",
                   "website", "github", "portfolio", "gpa", "grade"]

    for inp in page.query_selector_all("input[type='text'], textarea"):
        try:
            if not inp.is_visible():
                continue
            if inp.input_value().strip():
                continue

            # Resolve label text — try multiple strategies in order
            label = ""
            inp_id = inp.get_attribute("id") or ""
            if inp_id:
                lbl_el = page.query_selector(f"label[for='{inp_id}']")
                if lbl_el:
                    label = lbl_el.inner_text().strip()
            if not label:
                # aria-labelledby points to one or more element IDs that form the label
                aria_lblby = inp.get_attribute("aria-labelledby") or ""
                if aria_lblby:
                    parts = []
                    for lid in aria_lblby.split():
                        el = page.query_selector(f"#{lid}")
                        if el:
                            t = el.inner_text().strip()
                            if t:
                                parts.append(t)
                    label = " ".join(parts)
            if not label:
                label = (inp.get_attribute("aria-label") or
                         inp.get_attribute("placeholder") or "")
            if not label:
                # Walk up DOM for a nearby label
                label = inp.evaluate("""el => {
                    let node = el.parentElement;
                    for (let i = 0; i < 6; i++) {
                        if (!node) break;
                        for (const l of node.querySelectorAll('label, p, legend')) {
                            const t = l.textContent.trim();
                            if (t.length > 4 && t.length < 200) return t;
                        }
                        node = node.parentElement;
                    }
                    return '';
                }""")

            if not label or len(label) < 4:
                continue
            if any(kw in label.lower() for kw in SKIP_LABELS):
                continue

            # Disability — skip unless explicitly required (asterisk or aria-required)
            if any(s in label.lower() for s in ["disability", "disabled", "impairment"]):
                is_required = (
                    "*" in label
                    or inp.get_attribute("aria-required") == "true"
                    or inp.get_attribute("required") is not None
                )
                if not is_required:
                    continue

            # Try pattern rules first
            answer, input_type = _quick_answer(label, applicant, job_title, job_desc,
                                               company=company)
            if input_type == "claude" or not answer:
                # Detect open-ended textarea questions and use long_form Claude response
                is_textarea = inp.evaluate("el => el.tagName.toLowerCase()") == "textarea"
                _LONG_FORM_SIGNALS = [
                    "explain", "describe", "tell us", "why are you", "what makes",
                    "skills and experience", "skills match", "suitable", "motivation",
                    "why do you want", "what interests", "how have you", "provide",
                    "elaborate", "outline", "summarise", "summarize",
                ]
                use_long = is_textarea or any(sig in label.lower() for sig in _LONG_FORM_SIGNALS)
                answer = _claude_answer(label, VISA_INFO, applicant, job_title, job_desc,
                                        long_form=use_long)

            if not answer:
                continue

            print(f"    Custom question: '{label[:60]}' → '{answer[:60]}'")
            inp.scroll_into_view_if_needed()
            inp.click()
            inp.fill(answer)
            # Dispatch React synthetic events so Workday's controlled-component
            # state updates. Without this, .fill() changes the DOM value but
            # React's state remains empty, causing "field is required" on submit.
            inp.evaluate("""el => {
                el.dispatchEvent(new Event('input',  {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
            }""")
            questions_answered += 1
        except Exception:
            continue

    print(f"    Answered {questions_answered} custom question(s).")


# ===========================================================================
# WORK AUTHORIZATION
# ===========================================================================



def _fill_work_authorization(page, applicant: dict, job_title: str, job_desc: str):
    """Handle work authorization / visa questions."""
    print("  Handling work authorization...")

    auth_patterns = [
        "authorized to work", "work authorization", "right to work",
        "work rights", "visa", "sponsorship", "citizen", "permanent resident"
    ]

    labels = page.query_selector_all("label, [data-automation-id*='question']")
    for lbl in labels:
        try:
            text = lbl.inner_text().lower()
            if not any(p in text for p in auth_patterns):
                continue

            answer = _claude_answer(lbl.inner_text(), "", applicant, job_title, job_desc)
            for_id = lbl.get_attribute("for")
            if for_id:
                target = page.query_selector(f"#{for_id}")
                if target:
                    tag = target.evaluate("el => el.tagName").lower()
                    if tag == "input":
                        input_type = target.get_attribute("type")
                        if input_type in ("radio", "checkbox"):
                            if answer.lower() in ("yes", "true"):
                                target.click()
                        elif input_type == "text":
                            target.fill(answer)
        except Exception:
            continue


# ===========================================================================
# VOLUNTARY DISCLOSURE
# ===========================================================================



def _fill_disclosure_checkboxes(page) -> int:
    """
    Tick unchecked checkboxes on Voluntary Disclosures / T&C pages whose label
    contains consent/agreement keywords. Skips unrelated checkboxes (e.g. "preferred name").
    Workday checkbox inputs have opacity:0 so Playwright's is_visible() skips them;
    JS click() bypasses that and directly toggles the checked state.
    Returns the number of boxes ticked.
    """
    # Tick all unchecked checkboxes on disclosure/T&C pages, but skip any
    # checkbox whose label mentions a preferred/alternate name option.
    SKIP_LABEL_FRAGMENTS = [
        "preferred name", "use a different name", "goes by a different name",
        "alternate name", "known as",
        # Work-experience checkboxes — must NOT be ticked by the disclosure sweep
        "currently work", "i currently work", "current employer",
    ]
    ticked = page.evaluate("""(skipFragments) => {
        let n = 0;
        for (const cb of document.querySelectorAll('input[type="checkbox"]')) {
            if (cb.checked) continue;
            // Only skip if inside a display:none ancestor (truly hidden)
            let node = cb.parentElement;
            while (node && node !== document.body) {
                if (getComputedStyle(node).display === 'none') { node = null; break; }
                node = node.parentElement;
            }
            if (!node) continue;
            // Resolve the label text for this checkbox
            let labelText = '';
            if (cb.id) {
                const lbl = document.querySelector('label[for="' + cb.id + '"]');
                if (lbl) labelText = lbl.textContent.trim().toLowerCase();
            }
            if (!labelText) {
                const wrapping = cb.closest('label');
                if (wrapping) labelText = wrapping.textContent.trim().toLowerCase();
            }
            // Skip preferred-name and similar opt-in checkboxes
            if (skipFragments.some(f => labelText.includes(f))) continue;
            cb.click();
            n++;
        }
        return n;
    }""", SKIP_LABEL_FRAGMENTS)
    return ticked or 0


# ===========================================================================
# MAIN ENTRY POINT
# ===========================================================================



def fill_application(url: str, job_title: str = "", job_desc: str = "",
                     resume_pdf: str = "", output_folder: str = "",
                     company: str = ""):
    applicant = load_applicant()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            slow_mo=50,
            channel="msedge",
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        page = browser.new_page()
        page.goto(url, timeout=60000)

        _auto_apply_and_login(page)

        page_num = 1
        last_url = ""
        stuck_count = 0
        # Sections that must run exactly once, tracked as a set of string keys.
        # Sections NOT in this set run every page (screening, custom_questions,
        # disclosure, work_authorization).
        filled_sections: set = set()

        while True:
            print(f"\n--- Filling page {page_num} ---")
            # Wait for React to render ACTUAL Workday form content — not just the nav bar.
            # The nav bar alone already gives >300 chars, so we check for known section keywords.
            _CONTENT_JS = """() => {
                const txt = document.body.innerText.toLowerCase();
                return txt.includes('work experience') || txt.includes('employment history') ||
                       txt.includes('my experience') || txt.includes('education') ||
                       txt.includes('language') || txt.includes('skill') ||
                       txt.includes('first name') || txt.includes('last name') ||
                       txt.includes('screening') || txt.includes('disclosure') ||
                       txt.includes('resume') || txt.includes('upload') ||
                       txt.includes('review') || txt.includes('submit') ||
                       txt.includes('visa') || txt.includes('sponsorship') ||
                       txt.includes('select one') || txt.includes('authorization');
            }"""
            try:
                page.wait_for_function(_CONTENT_JS, timeout=12000)
            except Exception:
                time.sleep(3.0)   # hard fallback if no keywords found
            current_url = page.url

            if current_url == last_url:
                stuck_count += 1
                if stuck_count >= 3:
                    print(f"\n  Stuck on same page after {stuck_count} attempts.")
                    print("  Please fill/fix this page manually in the browser, then press Enter to continue.")
                    input("  Press Enter when ready: ")
                    stuck_count = 0
                    last_url = ""
                    page_num += 1
                    continue
            else:
                stuck_count = 0
                last_url = current_url

            page_text = page.inner_text("body").lower()

            # Guard: if we're still on the login/apply page (not yet on the form),
            # pause and wait for the user to finish logging in manually.
            current_url_lower = page.url.lower()
            on_login_page = (
                "applymanually" in current_url_lower and
                not any(x in page_text for x in [
                    "first name", "work experience", "employment history",
                    "education", "upload", "resume", "screening"
                ])
            )
            if on_login_page:
                print("\n  Still on the login/sign-in page — attempting auto sign-in...")
                _wait_for_form_or_auto_signin(page, WORKDAY_EMAIL, None)
                _wait_for_page_ready(page, timeout=10000)
                page_text = page.inner_text("body").lower()

            # Debug: show which section keywords are present on this page
            detected = []
            if any(x in page_text for x in ["first name", "last name", "email", "phone", "address"]): detected.append("personal")
            if "work experience" in page_text or "employment history" in page_text: detected.append("work_exp")
            if "education" in page_text: detected.append("education")
            if "language" in page_text: detected.append("language")
            if "skill" in page_text: detected.append("skill")
            if any(x in page_text for x in ["upload", "resume", "cv"]): detected.append("upload")
            # Disclosure: require the prominent heading, not just any mention of "terms"
            if "voluntary disclosure" in page_text or (
                    "terms and condition" in page_text and "affirm and agree" in page_text):
                detected.append("disclosure")
            # Review: must be an h1/h2/h3 with exactly "Review" as its text
            if page.evaluate("""() => Array.from(document.querySelectorAll('h1,h2,h3'))
                    .some(h => h.textContent.trim().toLowerCase() === 'review')"""):
                detected.append("review")
            print(f"  [Page sections detected]: {detected}")

            if "personal" not in filled_sections and any(x in page_text for x in ["first name", "last name", "email", "phone", "address"]):
                _fill_personal_info(page, applicant, job_title, job_desc)
                filled_sections.add("personal")

            if "work_exp" not in filled_sections and ("work experience" in page_text or "employment history" in page_text):
                _fill_work_experience(page, applicant)
                filled_sections.add("work_exp")

            if "education" not in filled_sections and "education" in page_text:
                _fill_education(page, applicant, job_title, job_desc)
                filled_sections.add("education")

            if "languages" not in filled_sections and "language" in page_text and any(x in page_text for x in ["add", "select one"]):
                _fill_languages(page)
                filled_sections.add("languages")

            if "skills" not in filled_sections and "skill" in page_text and any(x in page_text for x in ["add", "type to add"]):
                _fill_skills(page, applicant, job_title, job_desc)
                filled_sections.add("skills")

            # File upload — only once, never re-upload
            if "files" not in filled_sections and any(x in page_text for x in ["upload", "attach", "resume", "cv"]):
                if page.query_selector("input[type='file']"):
                    _upload_files(page, resume_pdf, output_folder)
                    filled_sections.add("files")

            # Websites — only once
            if "websites" not in filled_sections and ("website" in page_text or "linkedin" in page_text):
                _fill_websites(page, applicant)
                filled_sections.add("websites")

            # Work authorization — only once
            if "work_auth" not in filled_sections and any(x in page_text for x in ["visa", "authorized", "sponsorship", "right to work", "work rights"]):
                _fill_work_authorization(page, applicant, job_title, job_desc)
                filled_sections.add("work_auth")

            # Screening questions — run on every page
            _fill_screening_questions(page, applicant, job_title, job_desc, company=company)

            # Disclosure / Terms-and-Conditions pages: tick ALL unchecked checkboxes
            if "disclosure" in detected:
                n = _fill_disclosure_checkboxes(page)
                print(f"  Disclosure page: ticked {n} checkbox(es).")

            # Fill any remaining unanswered text fields
            _fill_custom_questions(page, applicant, job_title, job_desc, company=company)

            # (Review sense-check runs later, just before Submit is clicked)

            # Navigate
            def _find_btn(*labels):
                selectors = []
                for lbl in labels:
                    selectors += [
                        f"button[data-automation-id='{lbl}']",
                        f"button[aria-label='{lbl}']",
                    ]
                for sel in selectors:
                    el = page.query_selector(sel)
                    if el and el.is_visible():
                        return el
                for btn in page.query_selector_all("button"):
                    try:
                        txt = btn.inner_text().strip().lower()
                        if any(lbl.lower() in txt for lbl in labels) and btn.is_visible():
                            return btn
                    except Exception:
                        continue
                return None

            next_btn   = _find_btn("bottom-navigation-next-btn", "Next", "Save and Continue", "saveAndContinueButton")
            review_btn = _find_btn("bottom-navigation-review-btn", "Review")
            submit_btn = _find_btn("bottom-navigation-submit-btn", "Submit")

            if next_btn:
                print("  Moving to next page...")
                next_btn.scroll_into_view_if_needed()
                next_btn.click()
                time.sleep(1.5)

                # ── Error-retry: if Workday shows "Errors Found", re-fill and retry ──
                for _retry in range(2):
                    err_banner = page.query_selector(
                        "[data-automation-id='errors-found'], "
                        "[class*='error-container'], "
                        "[data-automation-id='validationError']"
                    )
                    if not err_banner:
                        # Also check by text in case automation-id varies
                        try:
                            err_banner = page.get_by_text("Errors Found", exact=False).first
                            if not err_banner.is_visible():
                                err_banner = None
                        except Exception:
                            err_banner = None
                    if not err_banner:
                        break

                    print(f"  Errors Found banner detected — re-filling and retrying "
                          f"(attempt {_retry + 1}/2)...")
                    _fill_screening_questions(page, applicant, job_title, job_desc,
                                              company=company)
                    _fill_custom_questions(page, applicant, job_title, job_desc,
                                           company=company)
                    time.sleep(0.5)
                    retry_btn = _find_btn("bottom-navigation-next-btn", "Next",
                                          "Save and Continue", "saveAndContinueButton")
                    if retry_btn:
                        retry_btn.scroll_into_view_if_needed()
                        retry_btn.click()
                        time.sleep(1.5)

                # Wait for the new page's React content to fully render
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=20000)
                except Exception:
                    pass
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                # Wait for actual Workday form content (not just nav bar)
                try:
                    page.wait_for_function(_CONTENT_JS, timeout=12000)
                except Exception:
                    time.sleep(3.0)
                time.sleep(1.0)
                page_num += 1
            elif review_btn:
                print("\n  Reached review page.")
                print("  Please review all details in the browser before submitting.")
                input("  Press Enter to submit, or Ctrl+C to stop and review manually: ")
                review_btn.click()
                time.sleep(2)
            elif submit_btn and submit_btn.is_visible():
                print("\n  ── Review page reached ──")
                print("  Running Claude sense-check on the application...")
                try:
                    review_text = page.inner_text("body")
                    feedback = _claude_review_check(review_text, applicant)
                    print(f"\n  Claude sense-check:\n{feedback}\n")
                except Exception as e:
                    print(f"  (Sense-check failed: {e})")
                input("  Press Enter to submit, or Ctrl+C to abort: ")
                print("  Submitting application...")
                submit_btn.click()
                print("  Application submitted!")
                time.sleep(3)
                break
            else:
                print("  No navigation button found. Please click Save/Next manually in the browser.")
                input("  Press Enter after you have moved to the next page: ")
                page_num += 1
                last_url = ""

        browser.close()


if __name__ == "__main__":
    url = input("Paste Workday job URL: ").strip()
    job_title = input("Job title (or press Enter to skip): ").strip()
    resume_pdf = input("Path to resume PDF (or press Enter to skip): ").strip()
    company = input("Company name (or press Enter to skip): ").strip()
    fill_application(url, job_title=job_title, resume_pdf=resume_pdf, company=company)
