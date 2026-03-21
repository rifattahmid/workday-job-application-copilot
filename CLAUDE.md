# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

A CLI tool that automates Workday job applications. Given a Workday job URL it:
1. Scrapes the job posting (title, description, PDF snapshot) via Playwright
2. Classifies the role (investment / accounting / finance) to select the right resume/cover letter template
3. Uses Claude (Haiku) to fill blanks in the cover letter `.docx` and converts it to PDF
4. Optionally launches a Playwright-driven browser to fill out the Workday application form using `applicant.json`

## Running the tool

```bash
# Activate venv first
venv\Scripts\activate

# Run the full pipeline
python main.py

# Run only the form-filler standalone
python filler.py
```

`ANTHROPIC_API_KEY` must be set in `.env` (loaded via `python-dotenv`).

## Key files

| File | Role |
|------|------|
| `main.py` | Entry point — orchestrates scrape → generate → fill |
| `scraper.py` | Playwright scraper; returns job dict with `pdf_bytes` |
| `generator.py` | Template selection, cover letter filling via Claude, PDF conversion |
| `filler.py` | Playwright form automation; reads `applicant.json` for candidate data |
| `applicant.json` | Candidate profile (personal info, work history, education, skills, visa) |
| `.env` | `ANTHROPIC_API_KEY=...` |

## Template directory structure

Hard-coded paths in `generator.py`:
- `OUTPUT_BASE = X:\Career & Networking\Resumes\2026\AU` — where output folders are created
- `TEMPLATE_BASE = X:\Career & Networking\Resumes\2026\AU\0` — source templates

Each template subfolder (e.g. `0\investment\`, `0\accounting\`, `0\finance\`) must contain:
- `Resume.pdf` — uploaded to Workday
- `Cover Letter.docx` — filled with blanks (`_`) replaced by Claude
- `Resume.txt` — plain-text resume loaded for context

Folder classification is keyword-based (`generator.py:classify_job`). Add new folders and extend the `keywords` dict to support new job categories.

## Cover letter blank-filling convention

Blanks in the `.docx` template are represented as underscore runs (`_`). Claude rewrites each blank sentence using job context. Bold formatting is preserved for the job title. The `_rebold_title` helper re-applies bold after text replacement.

## Claude model usage

Both `generator.py` and `filler.py` call `claude-haiku-4-5-20251001` for cost efficiency. The `anthropic.Anthropic()` client is instantiated per-call (no shared client instance).

## Dependencies

Install with:
```bash
pip install -r requirements.txt
playwright install chromium
```

Key packages: `anthropic`, `playwright`, `python-docx`, `docx2pdf`, `beautifulsoup4`, `python-dotenv`. `docx2pdf` requires Microsoft Word to be installed on Windows.
