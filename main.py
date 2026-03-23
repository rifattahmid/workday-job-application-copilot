import glob
from pathlib import Path
from scraper import scrape_workday
from generator import generate_application
from filler import fill_application

url = input("Paste Workday URL: ").strip()

data = scrape_workday(url)
data["company"] = input("Enter Company Name: ").strip()

output_folder = generate_application(data)

if output_folder:
    # Cover letter saved — auto-start Workday form filling
    # Find copied resume PDF in output folder
    resume_pdf = ""
    if output_folder:
        pdfs = glob.glob(f"{output_folder}/*.pdf")
        resume_pdfs = [p for p in pdfs if "resume" in Path(p).name.lower()]
        resume_pdf = resume_pdfs[0] if resume_pdfs else (pdfs[0] if pdfs else "")

    fill_application(
        url=url,
        job_title=data.get("title", ""),
        job_desc=data.get("description", ""),
        resume_pdf=resume_pdf,
        output_folder=output_folder or "",
        company=data.get("company", ""),
    )
