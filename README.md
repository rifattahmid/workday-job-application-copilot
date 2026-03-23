# Workday Application Copilot

An end-to-end automation tool that takes a Workday job URL and handles everything: scraping the job posting, generating a tailored cover letter with Claude AI, and filling out the Workday application form using Playwright.

---

## What it does

1. **Scrapes** the Workday job posting — extracts the job title, description, and saves a PDF snapshot of the page
2. **Classifies** the role (investment / accounting / finance) and selects the matching resume and cover letter template
3. **Generates** a personalised cover letter — uses Claude AI to fill template blanks with job-specific language, then converts it to PDF
4. **Fills** the Workday application form automatically — logs in, then fills personal info, work history, education, skills, file uploads, screening questions, disclosures, and runs a final AI sense-check before submission

---

## Project structure

```
workday-application-copilot/
├── f_main.py            # Entry point — chains scrape → generate → fill in one run
├── c_scraper.py         # Opens the Workday job page in a browser, extracts the job
│                        #   title and description, and saves a PDF snapshot
├── d_generator.py       # Classifies the job, picks the right resume/cover letter
│                        #   template, uses Claude to fill cover letter blanks, and
│                        #   converts the .docx to PDF ready for upload
├── e_filler.py          # Playwright automation that fills the entire Workday form —
│                        #   login, every form section, file uploads, and submission.
│                        #   Generic engine — contains no personal data, do not edit
├── b_config.py          # YOUR personal settings: email, location, file paths,
│                        #   languages, visa info, supplementary uploads  ← edit this
├── a_applicant.json     # YOUR candidate profile: name, address, work experience,
│                        #   education, skills, certifications               ← edit this
├── requirements.txt     # Python package dependencies
├── PROJECT_MEMORY.md    # Claude onboarding doc — paste into chat for debugging sessions
└── .env                 # Your Anthropic API key (create this file, never commit it)
```

---

## Requirements

- **Windows** (required — `docx2pdf` uses Microsoft Word COM for PDF conversion)
- **Python 3.10+**
- **Microsoft Word** (for `.docx` → `.pdf` conversion)
- **Anthropic API key** — get one at [console.anthropic.com](https://console.anthropic.com)

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/rifattahmid/workday-job-application-copilot.git
cd workday-job-application-copilot
```

### 2. Create and activate a virtual environment

```bash
python -m venv venv
venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Install Playwright browsers

```bash
playwright install msedge
```

### 5. Set your Anthropic API key

Create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=your_api_key_here
```

---

## Configuration

There are two files to personalise before running: `b_config.py` and `a_applicant.json`.

---

### Step 1 — `b_config.py` (settings & paths)

Open `b_config.py` and update every value marked with `← UPDATE THIS`:

| Setting | What it is |
|---------|-----------|
| `WORKDAY_EMAIL` | The email you use (or will create) on Workday job portals |
| `SALUTATION` | Your title prefix — e.g. `"Mr."`, `"Ms."`, `"Dr."` |
| `REFERRAL_SOURCE` | How you heard about the role — e.g. `"LinkedIn"`, `"Job Board"` |
| `YEARS_EXPERIENCE` | Years of relevant experience — e.g. `"4"` |
| `SALARY_EXPECTATION` | Expected salary range — e.g. `"100,000 – 110,000"` |
| `SALARY_EXPECTATION_SINGLE` | Expected salary as a single figure — e.g. `"100,000"` |
| `LEAVING_REASON` | Your reason for leaving current role |
| `INDIGENOUS_STATUS` | Indigenous identity answer — typically `"Neither"` for Australian forms |
| `DEFAULT_LOCATION` | Your city/state used to fill Location fields on forms |
| `VISA_INFO` | Your visa or work-rights status — Claude uses this to answer screening questions |
| `WORK_RIGHTS_ANSWER` | Exact option text for "right to work" dropdowns — e.g. `"Yes - I am a Temporary Resident with Full Working Rights"` |
| `LANG_PROFICIENCY` | Languages you speak and your proficiency level in each |
| `OUTPUT_BASE` | Folder where generated resume/cover letter folders are saved |
| `TEMPLATE_BASE` | Folder containing your resume/cover letter Word template subfolders |
| `SUPPLEMENTARY_FILES` | Extra PDFs uploaded alongside your resume (transcripts, references, etc.) |

> **Tip — use your AI assistant:** Paste `b_config.py` into your AI chat and ask:
> *"Fill in this config file based on my details: [paste your info]."*
> The AI will update every field for you in one go.

---

### Step 2 — `a_applicant.json` (candidate profile)

This file holds the personal information used to fill every Workday form field — name, address, work experience, education, skills, and more. Edit it directly, or ask your AI assistant to generate it from your CV:

> *"Create an a_applicant.json for the Workday Application Copilot based on my CV: [paste CV text]."*

```json
{
  "first_name": "Jane",
  "last_name": "Smith",
  "email": "jane@example.com",
  "phone": "0400000000",
  "phone_country_code": "+61",
  "address": {
    "street": "123 Example St",
    "suburb": "Melbourne",
    "city": "Melbourne",
    "state": "Victoria",
    "state_abbr": "VIC",
    "postcode": "3000",
    "country": "Australia"
  },
  "linkedin": "https://www.linkedin.com/in/yourprofile/",
  "website": "https://github.com/yourusername",
  "visa": {
    "type": "Australian Citizen",
    "expiry": null,
    "authorized_to_work": true,
    "requires_future_sponsorship": false,
    "note": ""
  },
  "referral_source": "LinkedIn",
  "work_experience": [
    {
      "title": "Financial Analyst",
      "company": "Example Corp",
      "start": "01/2023",
      "end": "Present",
      "description": "Brief description of your role and achievements."
    }
  ],
  "education": [
    {
      "institution": "University of Melbourne",
      "degree": "Bachelor of Commerce",
      "field": "Accounting & Finance",
      "start": "02/2019",
      "end": "12/2022",
      "gpa": "3.5/4.0"
    }
  ],
  "certifications": ["CFA Level 1"],
  "skills": ["Financial Modelling", "Excel", "Python", "Power BI", "SQL"]
}
```

---

### Resume templates

The tool selects from categorised resume/cover letter templates stored on your machine. Set `OUTPUT_BASE` and `TEMPLATE_BASE` in `b_config.py`, then create a subfolder per job category (e.g. `Templates\finance\`, `Templates\accounting\`).

Each subfolder must contain:

| File | Purpose |
|------|---------|
| `Resume.pdf` | The resume file uploaded to Workday |
| `Cover Letter.docx` | Word template with `_` blanks that Claude fills in |
| `Resume.txt` | Plain-text version of your resume used as AI context |

Cover letter blanks are underscore characters (`_`). Claude replaces each blank with job-specific language based on the job description. Bold formatting on the job title is preserved automatically.

---

## Usage

### Full pipeline (recommended)

Runs scrape → cover letter generation → form filling in one sequence:

```bash
venv\Scripts\activate
python f_main.py
```

You will be prompted for:
1. The Workday job URL
2. The company name

The form-filler starts automatically once the cover letter is generated — no extra prompt.

### Form-filler only

If you already have your documents and just want to fill the form:

```bash
python e_filler.py
```

You will be prompted for:
1. The Workday job URL
2. The job title
3. Path to your resume PDF

---

## How the form-filler works

The filler opens a visible browser window, navigates to the Workday application page, and handles each section automatically:

| Section | What it does |
|---------|-------------|
| **Login** | Detects whether a Workday account exists — registers a new one if not, or signs in automatically using your saved credentials |
| **File uploads** | Uploads your resume, cover letter, and any supplementary PDFs |
| **Personal info** | Fills name, email, phone, and address from `a_applicant.json` |
| **Work experience** | Adds each job entry — title, company, location, dates, and role description |
| **Education** | Fills institution, degree type, field of study, dates, and GPA |
| **Languages** | Adds each language with proficiency levels from `b_config.py` |
| **Skills** | Uses Claude to pick the most relevant skills for the job, then selects them from Workday's skill search |
| **Websites** | Fills LinkedIn and personal website links |
| **Screening questions** | Answers yes/no and dropdown questions using Claude based on your profile |
| **Disclosures / T&Cs** | Automatically ticks all agreement checkboxes |
| **Review & submit** | Runs a Claude sense-check on the full application, prints a summary, then waits for you to press Enter before submitting |

The browser runs in **visible mode** so you can watch and intervene at any point. Press `Ctrl+C` in the terminal to stop at any time.

---

## Job classification

`d_generator.py` automatically classifies each job into one of three categories to select the right resume/cover letter template:

| Category | Matched keywords |
|----------|-----------------|
| `investment` | investment, portfolio, asset management, fund, equity, credit, infrastructure, capital markets |
| `accounting` | account, audit, tax, bookkeeping, controller, CPA, chartered accountant |
| `finance` | finance, financial, FP&A, treasury, budget, forecast, analyst |

To add a new category, create the template subfolder and extend the `keywords` dict in `d_generator.py`.

---

## Troubleshooting

**`docx2pdf` conversion fails**
Make sure Microsoft Word is installed and the cover letter `.docx` is not open in Word when you run the tool.

**Playwright can't find elements**
Workday's UI varies by company. If the filler stalls, the browser window stays open — you can continue filling manually. Press `Ctrl+C` in the terminal to stop the script.

**API key not found**
Ensure `.env` exists in the project root and contains `ANTHROPIC_API_KEY=your_key`. Do not wrap the key in quotes.

**Skills section fails**
Workday's skill search uses a virtual scroll list. If a skill isn't found after scrolling, it is skipped automatically and the next skill is tried.

---

## Notes

- Designed for **Australian Workday job applications** but works on any Workday instance
- The Claude sense-check before submission is advisory — you always have final approval before anything is submitted
- `.env`, `__pycache__/`, and output folders are excluded from git via `.gitignore`
