import os
import re
import shutil
from datetime import datetime
from docx import Document
from docx2pdf import convert

OUTPUT_BASE = r"X:\Career & Networking\Resumes\2026\AU"
TEMPLATE_BASE = r"X:\Career & Networking\Resumes\2026\AU\0"

# Matches dates like "19 March 2025"
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
    """
    Replace placeholders in a paragraph.
    Tries per-run first (preserves all run formatting).
    Falls back to collapsing runs if placeholder spans multiple runs.
    """
    if not any(old in para.text for old in replacements):
        return

    # Per-run pass
    for run in para.runs:
        for old, new in replacements.items():
            if old in run.text:
                run.text = run.text.replace(old, new)

    # Cross-run fallback for anything still unresolved
    unresolved = {old: new for old, new in replacements.items() if old in para.text}
    if unresolved and para.runs:
        merged = para.text
        for old, new in unresolved.items():
            merged = merged.replace(old, new)
        para.runs[0].text = merged
        for run in para.runs[1:]:
            run.text = ""


def _apply_date(para, today):
    """Replace a date-like string, with cross-run fallback."""
    if not DATE_PATTERN.search(para.text):
        return
    for run in para.runs:
        if DATE_PATTERN.search(run.text):
            run.text = DATE_PATTERN.sub(today, run.text)
            return
    # Cross-run fallback
    if para.runs:
        para.runs[0].text = DATE_PATTERN.sub(today, para.text)
        for run in para.runs[1:]:
            run.text = ""


def _debug_placeholders(doc):
    """Print all lines containing '_' so we can verify placeholder text."""
    print("\n=== TEMPLATE LINES CONTAINING '_' ===")
    found = False
    for para in doc.paragraphs:
        if "_" in para.text:
            print(f"  {repr(para.text)}")
            found = True
    if not found:
        print("  (none found — check your template uses _ as placeholder)")
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


def parse_claude_output(text):
    strategy = region = ""
    for line in text.splitlines():
        upper = line.upper().strip()
        if upper.startswith("STRATEGY:"):
            strategy = line.split(":", 1)[1].strip()
        elif upper.startswith("REGION:"):
            region = line.split(":", 1)[1].strip()
    return strategy, region


def collect_multiline_input(prompt):
    """Read pasted input; stops on two consecutive blank lines."""
    print(prompt)
    lines = []
    blank_count = 0
    while True:
        line = input()
        if line == "":
            blank_count += 1
            if blank_count >= 2:
                break
            lines.append(line)
        else:
            blank_count = 0
            lines.append(line)
    return "\n".join(lines).strip()


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
    if data.get("html") and data.get("url"):
        from scraper import save_page_as_pdf
        webpage_pdf = os.path.join(output_folder, "Webpage.pdf")
        try:
            save_page_as_pdf(data["html"], data["url"], webpage_pdf)
        except Exception as e:
            print(f"  WARNING: Could not save job page PDF ({e})")

    with open(resume_txt, "r", encoding="utf-8") as f:
        resume_text = f.read()

    print("\n=== PASTE INTO CLAUDE ===\n")
    print(f"ROLE: {title}")
    print(f"COMPANY: {company}")
    print("\nINTRO:\n", data.get("intro", "")[:500])
    print("\nRESPONSIBILITIES:\n", data.get("responsibilities", "")[:800])
    print("\nQUALIFICATIONS:\n", data.get("qualifications", "")[:800])
    print("\nRESUME:\n", resume_text[:1000])
    print("\n=== EXPECTED OUTPUT FORMAT ===")
    print("STRATEGY: [e.g. real assets / credit / equities]")
    print("REGION: [e.g. Asia-Pacific / Global]")

    claude_text = collect_multiline_input(
        "\nPaste Claude's output below (press Enter TWICE when done):"
    )

    strategy, region = parse_claude_output(claude_text)

    if not strategy:
        strategy = input("Could not parse STRATEGY. Enter manually: ").strip()
    if not region:
        region = input("Could not parse REGION. Enter manually: ").strip()

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
