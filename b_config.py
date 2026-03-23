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

# Salutation / title prefix used in the legal name section of Workday forms
# Common options: "Mr.", "Ms.", "Mrs.", "Dr.", "Prof."
SALUTATION = "Mr."   # ← UPDATE THIS

# How you heard about the role — used to answer "How did you hear about us?" questions
# Common options: "LinkedIn", "Job Board", "Indeed", "Seek", "Employee Referral", "Other"
REFERRAL_SOURCE = "Job Board"   # ← UPDATE THIS

# Years of experience in similar roles — used to answer "how many years experience" questions
YEARS_EXPERIENCE = "4"   # ← UPDATE THIS

# Expected salary range (without super) — used when a range is accepted
SALARY_EXPECTATION = "100,000 – 110,000"   # ← UPDATE THIS

# Expected salary as a single value — used when the form only accepts one number
SALARY_EXPECTATION_SINGLE = "100,000"   # ← UPDATE THIS

# Reason for leaving current role — used for open-ended departure questions
LEAVING_REASON = (
    "I am seeking a new opportunity to further develop my skills in a "
    "growth-oriented environment aligned with my long-term career goals."
)   # ← UPDATE THIS

# Aboriginal / Torres Strait Islander status — used to answer indigenous-status questions.
# Workday forms vary: "Neither", "No", "None", "I do not identify", "Prefer not to say".
# "Neither" is the most common non-identifying option across Australian Workday forms.
INDIGENOUS_STATUS = "Neither"   # ← UPDATE THIS if your form uses a different label

# Your default job search location — used to fill Location fields on forms
DEFAULT_LOCATION = "Melbourne, Victoria, Australia"   # ← UPDATE THIS

# ---------------------------------------------------------------------------
# Visa / work rights — used in Claude prompts for screening questions
# ---------------------------------------------------------------------------

VISA_INFO = (
    "Candidate is on Graduate Visa (Subclass 485) expiring 27 April 2026, "
    "will extend for 4 more years."
)   # ← UPDATE THIS  (or set to "" if you are a citizen / permanent resident)

# The exact option text to select for "right to work" / work rights dropdowns.
# Common options (pick the one that matches your situation):
#   "Yes - I am an Australian or New Zealand Citizen"
#   "Yes - I am a Permanent Resident"
#   "Yes - I am a Temporary Resident with Full Working Rights"
#   "Yes - I am a Temporary Resident with Partial Working Rights"
#   "No"
WORK_RIGHTS_ANSWER = "Yes - I am a Temporary Resident with Full Working Rights"   # ← UPDATE THIS

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
