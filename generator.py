import os
import re
import shutil
import anthropic
from datetime import datetime
from docx import Document
from docx2pdf import convert
from dotenv import load_dotenv

load_dotenv()

OUTPUT_BASE = r"X:\Career & Networking\Resumes\2026\AU"
TEMPLATE_BASE = r"X:\Career & Networking\Resumes\2026\AU\0"

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


def _replace_in_runs(para, old, new):
    """Replace text per-run. Returns True if any replacement was made."""
    changed = False
    for run in para.runs:
        if old in run.text:
            run.text = run.text.replace(old, new)
            changed = True
    return changed


def fill_cover_letter(path, company, title, intro, responsibilities, qualifications):
    doc = Document(path)
    today = datetime.now().strftime("%d %B %Y")
    date_like = re.compile(r"\d{1,2}[\s/]\w+[\s/]\d{4}|\w+\s+\d{1,2},?\s+\d{4}")

    # Only collect paragraphs that actually need updating (date or _ blanks)
    # This avoids touching signature/hyperlink paragraphs
    to_update = [
        (i, para) for i, para in enumerate(doc.paragraphs)
        if "_" in para.text or date_like.search(para.text)
    ]

    if not to_update:
        doc.save(path)
        print(f"  Cover letter saved (nothing to update): {path}")
        return

    numbered = "\n".join(f"{j+1}. {para.text}" for j, (_, para) in enumerate(to_update))
    print(f"\n=== LINES TO UPDATE ===\n{numbered}\n=======================\n")

    client = anthropic.Anthropic()
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        messages=[{"role": "user", "content": f"""Update these cover letter lines only. Return all of them numbered the same way.

Today: {today}
Role: {title}
Company (USE THIS EXACT NAME, never modify or expand it): {company}

Job intro: {intro[:600]}
Responsibilities: {responsibilities[:500]}
Qualifications: {qualifications[:300]}

Lines to update:
{numbered}

Rules:
- If a line has a date, replace it with: {today}
- If a line has _ blanks, fill each one with the best value based on context
- For any company blank, use EXACTLY: {company}
- For any role/position blank, use EXACTLY: {title}
- Infer investment strategy (e.g. real assets, credit, equities, infrastructure) and region (e.g. Asia-Pacific, Global, Australia) from the job description
- Do NOT rephrase or rewrite — only fill in the blanks and update dates
- Return ONLY the numbered lines, nothing else"""}]
    )

    response = message.content[0].text.strip()
    print(f"  Claude output:\n{response}\n")

    for line in response.splitlines():
        m = re.match(r'^(\d+)\.\s*(.+)$', line.strip())
        if not m:
            continue
        idx = int(m.group(1)) - 1
        if not (0 <= idx < len(to_update)):
            continue
        _, para = to_update[idx]
        new_text = m.group(2).strip()

        if para.text == new_text:
            continue

        # Per-run pass: replace known patterns in each run individually
        if not _replace_in_runs(para, para.text, new_text):
            # Cross-run fallback: safe here because filtered paragraphs
            # (date/blank lines) don't contain hyperlinks
            if para.runs:
                para.runs[0].text = new_text
                for run in para.runs[1:]:
                    run.text = ""

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

    # Write position description PDF (captured during scraping while session was live)
    position_pdf = os.path.join(output_folder, "Position Description.pdf")
    if data.get("pdf_bytes"):
        with open(position_pdf, "wb") as f:
            f.write(data["pdf_bytes"])
        print(f"  Position description PDF: {position_pdf}")

    with open(resume_txt, "r", encoding="utf-8") as f:
        resume_text = f.read()  # noqa: F841 (available for future use)

    fill_cover_letter(
        cover_dest, company, title,
        data.get("intro", ""),
        data.get("responsibilities", ""),
        data.get("qualifications", ""),
    )

    pdf_dest = cover_dest.replace(".docx", ".pdf")
    try:
        convert(cover_dest, pdf_dest)
        print(f"  Cover letter PDF: {pdf_dest}")
    except Exception as e:
        print(f"  WARNING: PDF conversion failed ({e})")
        print("  Make sure Microsoft Word is installed and the .docx is not open.")

    print(f"\nDone! Saved to: {output_folder}")
    os.startfile(output_folder)
    return output_folder
