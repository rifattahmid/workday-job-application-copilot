import os
import shutil
from datetime import datetime
from docx import Document
from docx2pdf import convert

OUTPUT_BASE = r"X:\Career & Networking\Resumes\2026\AU"
TEMPLATE_BASE = r"X:\Career & Networking\Resumes\2026\AU\0"


def classify_job(title, description):
    text = (title + " " + description).lower()
    if "account" in text:
        return "accounting"
    return "finance"


def get_paths(category):
    base = os.path.join(TEMPLATE_BASE, category)

    resume_pdf = None
    cover_docx = None
    resume_txt = None

    for f in os.listdir(base):
        f_lower = f.lower()

        if f_lower.endswith(".pdf") and "resume" in f_lower:
            resume_pdf = os.path.join(base, f)

        elif f_lower.endswith(".docx") and "cover" in f_lower:
            cover_docx = os.path.join(base, f)

        elif f_lower.endswith(".txt") and "resume" in f_lower:
            resume_txt = os.path.join(base, f)

    return resume_pdf, cover_docx, resume_txt


# --- UPDATE COVER LETTER ---
def update_cover_letter(path, company, claude_output):
    doc = Document(path)
    today = datetime.now().strftime("%d %B %Y")

    strategy = claude_output.get("strategy", "")
    region = claude_output.get("region", "")
    company_line = claude_output.get("company_line", company)

    for para in doc.paragraphs:
        text = para.text

        # Date
        if "March" in text or "202" in text:
            text = today

        # Company
        text = text.replace(" at _", f" at {company_line}")

        # Strategy + region
        text = text.replace("_ investing", f"{strategy} investing")
        text = text.replace("_ region", f"{region} region")

        para.text = text

    doc.save(path)


def generate_application(data):
    title = data["title"]
    company = data["company"]

    category = classify_job(title, data["description"])

    resume_pdf, cover_docx, resume_txt = get_paths(category)

    folder_name = f"{company} - {title}".replace("/", "-")
    output_folder = os.path.join(OUTPUT_BASE, folder_name)
    os.makedirs(output_folder, exist_ok=True)

    # Copy resume
    shutil.copy(resume_pdf, os.path.join(output_folder, os.path.basename(resume_pdf)))

    # Copy cover letter
    cover_dest = os.path.join(output_folder, os.path.basename(cover_docx))
    shutil.copy(cover_docx, cover_dest)

    # Load resume text
    with open(resume_txt, "r", encoding="utf-8") as f:
        resume_text = f.read()

    print("\n=== PASTE INTO CLAUDE ===\n")
    print(f"ROLE: {title}")
    print(f"COMPANY: {company}")

    print("\nINTRO:\n", data.get("intro", "")[:500])
    print("\nRESPONSIBILITIES:\n", data.get("responsibilities", "")[:800])
    print("\nQUALIFICATIONS:\n", data.get("qualifications", "")[:800])
    print("\nRESUME:\n", resume_text[:1000])

    print("\n=== EXPECT OUTPUT FORMAT ===")
    print("""
Return ONLY:

STRATEGY: ...
COMPANY_LINE: ...
""")

    os.startfile(output_folder)

    return cover_dest