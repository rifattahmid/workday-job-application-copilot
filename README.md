# Workday Application Copilot

An end-to-end automation tool that takes a Workday job URL and handles everything: scraping the job posting, generating a tailored cover letter with Claude AI, and filling out the Workday application form using Playwright.

---

## What it does

1. **Scrapes** the Workday job posting — extracts the job title, description, and saves a PDF snapshot of the page
2. **Classifies** the role (investment / accounting / finance) and selects the matching resume and cover letter template
3. **Generates** a personalised cover letter — uses Claude Haiku to fill template blanks with job-specific language, then converts it to PDF
4. **Fills** the Workday application form automatically — personal info, work history, education, skills, file uploads, disclosures, and a final AI sense-check before submission

---

## Requirements

- **Windows** (required — `docx2pdf` depends on Microsoft Word for PDF conversion)
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
playwright install chromium
```

### 5. Set your Anthropic API key

Create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=your_api_key_here
```

---

## Configuration

There are two files to personalise before running: `config.py` and `applicant.json`.

---

### Step 1 — `config.py` (settings & paths)

Open `config.py` and update every value marked with `← UPDATE THIS`:

| Setting | What it is |
|---------|-----------|
| `WORKDAY_EMAIL` | The email you use (or will create) on Workday job portals |
| `DEFAULT_LOCATION` | Your city/state used to fill Location fields |
| `VISA_INFO` | Your visa or work-rights status, used by Claude to answer screening questions |
| `LANG_PROFICIENCY` | Languages you speak and your proficiency level in each |
| `OUTPUT_BASE` | Folder where generated resumes/cover letters are saved |
| `TEMPLATE_BASE` | Folder containing your resume/cover letter Word templates |
| `SUPPLEMENTARY_FILES` | Extra PDFs uploaded alongside your resume (transcripts, references, etc.) |

> **Tip — use your AI assistant:** Open `config.py`, paste it into your AI chat, and ask:
> *"Fill in this config file based on my details: [paste your info]."*
> The AI will update every field for you in one go.

---

### Step 2 — `applicant.json` (candidate profile)

This file holds the personal information used to fill every Workday form field. Edit it with your own details, or ask your AI assistant to generate it:

> *"Create an applicant.json for the Workday Application Copilot based on my CV: [paste CV text]."*

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

The tool selects from categorised resume/cover letter templates stored on your machine. Set `OUTPUT_BASE` and `TEMPLATE_BASE` in `config.py`, then create a subfolder per job category (e.g. `Templates\finance\`, `Templates\accounting\`).

Each subfolder must contain:

| File | Purpose |
|------|---------|
| `Resume.pdf` | Uploaded to Workday |
| `Cover Letter.docx` | Template with `_` blanks for Claude to fill |
| `Resume.txt` | Plain-text resume for AI context |

Cover letter blanks are underscore characters (`_`). Claude replaces each blank with job-specific language. Bold formatting on the job title is preserved automatically.

---

## Usage

### Full pipeline (recommended)

Runs scrape → cover letter generation → form filling in sequence:

```bash
venv\Scripts\activate
python main.py
```

You will be prompted for:
1. The Workday job URL
2. The company name
3. Whether to launch the form-filler after documents are generated

### Form-filler only

If you already have your documents and just want to fill the form:

```bash
python filler.py
```

You will be prompted for:
1. The Workday job URL
2. The job title
3. Path to your resume PDF

---

## How the form-filler works

The filler navigates Workday page by page and handles each section automatically:

| Section | What it does |
|---------|-------------|
| **Personal info** | Fills name, email, phone, address from `applicant.json` |
| **Work experience** | Fills each job entry — title, company, dates, description |
| **Education** | Fills institution, degree, field of study, dates, GPA |
| **Skills** | Uses Claude to pick the 10 most relevant skills for the job, then selects them from Workday's skill search |
| **File uploads** | Uploads resume + cover letter + supplementary PDFs (auto-detects single vs multi-file upload) |
| **Disclosures / T&Cs** | Automatically ticks all agreement checkboxes and saves |
| **Review & submit** | Runs a Claude sense-check on the full application, prints feedback, then waits for you to press Enter before submitting |

The browser runs in **visible (headed) mode** so you can watch and intervene at any point with `Ctrl+C`.

---

## Job classification

The tool automatically classifies each job into one of three categories to select the right template:

| Category | Matched keywords |
|----------|-----------------|
| `investment` | investment, portfolio, asset management, fund, equity, credit, infrastructure, capital markets |
| `accounting` | account, audit, tax, bookkeeping, controller, CPA, chartered accountant |
| `finance` | finance, financial, FP&A, treasury, budget, forecast, analyst |

To add a new category, create the template subfolder and extend the `keywords` dict in `generator.py`.

---

## Project structure

```
workday-application-copilot/
├── main.py           # Entry point — runs the full pipeline
├── scraper.py        # Playwright scraper — extracts job data and PDF
├── generator.py      # Template selection, cover letter filling, PDF conversion
├── filler.py         # Playwright form automation (generic — do not edit)
├── config.py         # YOUR settings: email, location, paths, languages  ← edit this
├── applicant.json    # YOUR candidate profile: CV, experience, education  ← edit this
├── requirements.txt  # Python dependencies
└── .env              # ANTHROPIC_API_KEY (create this, do not commit)
```

---

## Troubleshooting

**`docx2pdf` conversion fails**
Make sure Microsoft Word is installed and the cover letter `.docx` is not open in Word when you run the tool.

**Playwright can't find elements**
Workday's UI varies by company. If the filler stalls, the browser window stays open — you can continue manually. Press `Ctrl+C` in the terminal to stop.

**API key not found**
Ensure `.env` exists in the project root and contains `ANTHROPIC_API_KEY=your_key`. Do not wrap the key in quotes.

**Skills section fails**
Workday's skill search uses a virtual scroll list. If a skill isn't found after scrolling, it is skipped automatically and the next skill is tried.

---

## Notes

- This tool is designed for **Australian Workday job applications** but works on any Workday instance
- The Claude sense-check before submission is advisory — you always have final approval via the Enter prompt
- `.env`, `__pycache__/`, and output folders are excluded from git via `.gitignore`
