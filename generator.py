import os
import re
import shutil
from datetime import datetime
from docx import Document
from docx2pdf import convert
import anthropic

OUTPUT_BASE = r"X:\Career & Networking\Resumes\2026\AU"
TEMPLATE_BASE = r"X:\Career & Networking\Resumes\2026\AU\0"

DATE_PATTERN = re.compile(r"\d{1,2}\s+\w+\s+20\d{2}")


def classify_job(title, description):
    text = (title + " " + description).lower()
    if "account" in text:
        return "accounting"
    return "finance"


def get_paths(category):
    base = os.path.join(TEMPLATE_BASE, category)
    if not os.path.isdir(base):
        raise FileNotFoundError(f"Template folder not found: {base}")

    resume_pdf = cover_docx = resume_txt = None

    for f in os.listdir(base):
        f_lower = f.lower()
        if f_lower.endswith(".pdf") and "resume" in f_lower:
            resume_pdf = os.path.join(base, f)
        elif f_lower.endswith(".docx") and "cover" in f_lower:
            cover_docx = os.path.join(base, f)
        elif f_lower.endswith(".txt") and "resume" in f_lower:
            resume_txt = os.path.join(base, f)

    missing = [
        name for name, val in [
            ("Resume.pdf", resume_pdf),
            ("Cover Letter.docx", cover_docx),
            ("Resume.txt", resume_txt),
        ]
        if val is None
    ]
    if missing:
        raise FileNotFoundError(f"Missing in {base}: {', '.join(missing)}")

    return resume_pdf, cover_docx, resume_txt


def _apply_replacements(para, replacements):
    if not any(old in para.text for old in replacements):
        return

    # Per-run pass
    for run in para.runs:
        for old, new in replacements.items():
            if old in run.text:
                run.text = run.text.replace(old, new)

    # Cross-run fallback
    unresolved = {old: new for old, new in replacements.items() if old in para.text}
    if unresolved and para.runs:
        merged = para.text
        for old, new in unresolved.items():
            merged = merged.replace(old, new)
        para.runs[0].text = merged
        for run in para.runs[1:]:
            run.text = ""


def _apply_date(para, today):
    if not DATE_PATTERN.search(para.text):
        return
    for run in para.runs:
        if DATE_PATTERN.search(run.text):
            run.text = DATE_PATTERN.sub(today, run.text)
            return
    if para.runs:
        para.runs[0].text = DATE_PATTERN.sub(today, para.text)
        for run in para.runs[1:]:
            run.text = ""


def _debug_placeholders(doc):
    print("\n=== TEMPLATE LINES CONTAINING '_' ===")
    found = False
    for para in doc.paragraphs:
        if "_" in para.text:
            print(f"  {repr(para.text)}")
            found = True
    if not found:
        print("  (none found — placeholders may not use _ character)")
    print("======================================\n")


def update_cover_letter(path, company, strategy, region):
    doc = Document(path)
    today = datetime.now().strftime("%d %B %Y")

    _debug_placeholders(doc)

    replacements = {
        " at _": f" at {company}",
        "approach to _ investing": f"approach to {strategy} investing",
        "in the _ region": f"in the {region} region",
    }

    all_paragraphs = list(doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                all_paragraphs.extend(cell.paragraphs)

    for para in all_paragraphs:
        _apply_date(para, today)
        _apply_replacements(para, replacements)

    doc.save(path)
    print(f"  Cover letter saved: {path}")


def infer_strategy_region(title, company, intro, responsibilities, qualifications, resume_text):
    """Use Claude API to infer investment strategy and region from job description."""
    print("\nAsking Claude to infer strategy and region...")

    client = anthropic.Anthropic()

    prompt = f"""You are helping tailor a finance cover letter. Based on the job description below, identify:
1. STRATEGY: The investment strategy (e.g. real assets, credit, equities, infrastructure, private equity, multi-asset)
2. REGION: The geographic focus (e.g. Asia-Pacific, Australia, Global, Americas, EMEA)

ROLE: {title}
COMPANY: {company}

INTRO:
{intro}

RESPONSIBILITIES:
{responsibilities}

QUALIFICATIONS:
{qualifications}

Return ONLY these two lines:
STRATEGY: [value]
REGION: [value]"""

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=100,
        messages=[{"role": "user", "content": prompt}]
    )

    response = message.content[0].text.strip()
    print(f"  Claude response: {response}")

    strategy = region = ""
    for line in response.splitlines():
        upper = line.upper().strip()
        if upper.startswith("STRATEGY:"):
            strategy = line.split(":", 1)[1].strip()
        elif upper.startswith("REGION:"):
            region = line.split(":", 1)[1].strip()

    return strategy, region


def generate_application(data):
    title = data["title"]
    company = data["company"]

    category = classify_job(title, data["description"])
    resume_pdf, cover_docx, resume_txt = get_paths(category)

    folder_name = f"{company} - {title}".replace("/", "-")
    output_folder = os.path.join(OUTPUT_BASE, folder_name)
    os.makedirs(output_folder, exist_ok=True)

    shutil.copy(resume_pdf, os.path.join(output_folder, os.path.basename(resume_pdf)))
    cover_dest = os.path.join(output_folder, os.path.basename(cover_docx))
    shutil.copy(cover_docx, cover_dest)

    # Save job description page as PDF
    if data.get("url"):
        from scraper import save_page_as_pdf
        webpage_pdf = os.path.join(output_folder, "Webpage.pdf")
        try:
            save_page_as_pdf(data["url"], webpage_pdf)
        except Exception as e:
            print(f"  WARNING: Could not save job page PDF ({e})")

    with open(resume_txt, "r", encoding="utf-8") as f:
        resume_text = f.read()

    # Auto-infer strategy and region via Claude API
    strategy, region = infer_strategy_region(
        title, company,
        data.get("intro", ""),
        data.get("responsibilities", ""),
        data.get("qualifications", ""),
        resume_text,
    )

    if not strategy:
        strategy = input("Could not parse STRATEGY. Enter manually: ").strip()
    if not region:
        region = input("Could not parse REGION. Enter manually: ").strip()

    print(f"\n  Strategy: {strategy}")
    print(f"  Region:   {region}")

    update_cover_letter(cover_dest, company, strategy, region)

    pdf_dest = cover_dest.replace(".docx", ".pdf")
    try:
        convert(cover_dest, pdf_dest)
        print(f"  Cover letter PDF saved: {pdf_dest}")
    except Exception as e:
        print(f"  WARNING: PDF conversion failed ({e})")
        print("  Make sure Microsoft Word is installed and the .docx is not open.")

    print(f"\nDone! Saved to: {output_folder}")
    os.startfile(output_folder)

    return output_folder
