# =============================================================================
# USER CONFIGURATION — personalise this file for your own details
# =============================================================================
# Run your AI assistant on this file and ask it to fill in every value marked
# with  ← UPDATE THIS  based on your personal information and preferences.
# =============================================================================

# ---------------------------------------------------------------------------
# Contact & account
# ---------------------------------------------------------------------------

# The email address you use (or will create) on Workday job portals
WORKDAY_EMAIL = "rtahmid9999@gmail.com"   # ← UPDATE THIS

# Your default job search location — used to fill Location fields on forms
DEFAULT_LOCATION = "Melbourne, Victoria, Australia"   # ← UPDATE THIS

# ---------------------------------------------------------------------------
# Visa / work rights — used in Claude prompts for screening questions
# ---------------------------------------------------------------------------

VISA_INFO = (
    "Candidate is on Graduate Visa (Subclass 485) expiring 27 April 2026, "
    "will extend for 4 more years."
)   # ← UPDATE THIS  (or set to "" if you are a citizen / permanent resident)

# ---------------------------------------------------------------------------
# Language proficiency
# ---------------------------------------------------------------------------
# Keys   : language names exactly as they appear in Workday dropdowns
# level  : preferred proficiency option text to match in the dropdown
# fallback: second-choice option text if 'level' is not found
# fluent : True = mark as fluent/native if the form has that toggle

LANG_PROFICIENCY = {
    "English":  {"level": "Advanced",      "fallback": "Bilingual",       "fluent": True},
    "Bengali":  {"level": "Intermediate",  "fallback": "Conversational",  "fluent": True},
    "Spanish":  {"level": "Beginner",      "fallback": "Elementary",      "fluent": False},
    "Hindi":    {"level": "Beginner",      "fallback": "Elementary",      "fluent": False},
    "Malay":    {"level": "Beginner",      "fallback": "Elementary",      "fluent": False},
}   # ← UPDATE THIS

# ---------------------------------------------------------------------------
# Output & template paths  (used by generator.py)
# ---------------------------------------------------------------------------

# Folder where generated resumes / cover letters are saved
OUTPUT_BASE = r"X:\Career & Networking\Resumes\2026\AU"   # ← UPDATE THIS

# Folder containing your resume/cover-letter Word templates (sub-folders per
# job category, e.g.  TEMPLATE_BASE\Finance\  TEMPLATE_BASE\Accounting\ )
TEMPLATE_BASE = r"X:\Career & Networking\Resumes\2026\AU\0"   # ← UPDATE THIS

# ---------------------------------------------------------------------------
# Supplementary file uploads (optional — uploaded alongside your resume)
# ---------------------------------------------------------------------------
# Add paths to any extra PDFs you want uploaded (e.g. transcripts, references).
# Leave the list empty [] if you have none. Maximum 3 files, total ≤ 5 MB.

SUPPLEMENTARY_FILES = [
    r"X:\Career & Networking\Resumes\Recommendations\Recommendations.pdf",
    r"X:\Career & Networking\Resumes\Grades\Monash University Transcript.pdf",
    r"X:\Career & Networking\Resumes\Grades\CA ANZ Statement of Academic Record.pdf",
]   # ← UPDATE THIS
