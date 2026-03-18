import os
import re
import shutil
from datetime import datetime
from docx import Document
from docx2pdf import convert
import anthropic
from dotenv import load_dotenv
load_dotenv()

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


def _set_para_text(para, text):
    """Replace paragraph text, preserving the first run's formatting."""
    if para.runs:
        para.runs[0].text = text
        for run in para.runs[1:]:
            run.text = ""
    else:
        para.add_run(text)


def fill_cover_letter(path, title, company, intro, responsibilities, qualifications):
    doc = Document(path)
    today = datetime.now().strftime("%d %B %Y")

    # Update date lines (actual date in template → today)
    for para in doc.paragraphs:
        if DATE_PATTERN.search(para.text):
            _set_para_text(para, DATE_PATTERN.sub(today, para.text))

    # Find all paragraphs still containing _ blanks
    blank_paras = [(i, para) for i, para in enumerate(doc.paragraphs) if "_" in para.text]

    print("\n=== BLANKS FOUND IN TEMPLATE ===")
    for _, para in blank_paras:
        print(f"  {repr(para.text)}")
    print("=================================\n")

    if not blank_paras:
        doc.save(path)
        print(f"  Cover letter saved: {path}")
        return

    # Ask Claude to fill every blank
    numbered_lines = "\n".join(f"{i+1}. {para.text}" for i, (_, para) in enumerate(blank_paras))

    client = anthropic.Anthropic()
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        messages=[{"role": "user", "content": f"""Fill ALL blanks (marked with _) in these cover letter lines.

Role: {title}
Company: {company}
Today: {today}

Job description:
{intro}

Responsibilities:
{responsibilities}

Lines to fill:
{numbered_lines}

Return ONLY the filled lines, numbered the same way. Replace every _ with the correct value.
Use {company} for company blanks. Infer investment strategy and region from the job description."""}]
    )

    response = message.content[0].text.strip()
    print(f"  Claude filled blanks:\n{response}\n")

    # Parse numbered responses and apply
    for line in response.splitlines():
        match = re.match(r'^(\d+)\.\s*(.+)$', line.strip())
        if match:
            idx = int(match.group(1)) - 1
            if 0 <= idx < len(blank_paras):
                _, para = blank_paras[idx]
                _set_para_text(para, match.group(2).strip())

    doc.save(path)
    print(f"  Cover letter saved: {path}")


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

    # Save job page PDF (captured during scraping)
    if data.get("webpage_pdf_bytes"):
        webpage_pdf = os.path.join(output_folder, "Position Description.pdf")
        with open(webpage_pdf, "wb") as f:
            f.write(data["webpage_pdf_bytes"])
        print(f"  Job page PDF: {webpage_pdf}")

    with open(resume_txt, "r", encoding="utf-8") as f:
        resume_text = f.read()

    fill_cover_letter(
        cover_dest, title, company,
        data.get("intro", ""),
        data.get("responsibilities", ""),
        data.get("qualifications", ""),
    )

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
