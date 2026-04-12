import os
import re
import json
import urllib.request
import logging
from .models import Experience

logger = logging.getLogger(__name__)

# --- Provider configuration (set these in your .env) ---
LLM_API_URL = os.environ.get('LLM_API_URL', 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions')
LLM_API_KEY = os.environ.get('LLM_API_KEY', '')
LLM_MODEL   = os.environ.get('LLM_MODEL',   'gemini-2.0-flash')

EVALUATION_SYSTEM_PROMPT = """\
You are an expert technical recruiter and ATS system.
Holistically evaluate the Candidate's Professional Experience against the Job Description.
Do NOT just keyword-match; assess whether the candidate's actual trajectory, achievements, \
and seniority level align with the role.

Scoring rubric:
90-100: Strong match — would shortlist immediately
70-89:  Good fit with minor gaps
50-69:  Partial match — significant gaps exist
<50:    Poor match

Respond ONLY with a valid JSON object using exactly this structure:
{
    "score": <integer 0-100>,
    "summary": "<2-3 sentences on overall fit and whether the candidate's seniority matches the role>",
    "matched_skills": ["<strength or matched area>", ...],
    "missing_skills": ["<critical gap>", ...],
    "recommendations": ["<actionable resume tip>", ...]
}"""

EVALUATION_USER_TEMPLATE = """\
JOB DESCRIPTION:
{jd_text}

---
{resume_context}"""

def _build_resume_context() -> str:
    experiences = Experience.objects.all().order_by('-start_date')
    lines = ["CANDIDATE'S PROFESSIONAL EXPERIENCE:\n"]
    for exp in experiences:
        start = exp.start_date.strftime('%Y-%m') if exp.start_date else 'Unknown'
        end   = exp.end_date.strftime('%Y-%m')   if exp.end_date   else 'Present'
        lines.append(f"Role: {exp.title} at {exp.company} ({start} to {end})")
        if exp.description:
            lines.append(f"Description: {exp.description}")
        if exp.skills:
            lines.append(f"Skills: {', '.join(exp.skills)}")
        lines.append('-' * 40)
    return '\n'.join(lines)

def generate_jd_match_evaluation(jd_text: str) -> dict:
    if not jd_text:
        return {
            "score": 0,
            "summary": "No job description provided.",
            "matched_skills": [],
            "missing_skills": [],
            "recommendations": []
        }

    if not LLM_API_URL or not LLM_MODEL:
        raise ValueError("LLM_API_URL and LLM_MODEL must be set in your .env file.")

    user_msg = EVALUATION_USER_TEMPLATE.format(
        jd_text=jd_text,
        resume_context=_build_resume_context(),
    )

    headers = {'Content-Type': 'application/json'}
    if LLM_API_KEY:
        headers['Authorization'] = f'Bearer {LLM_API_KEY}'

    payload = json.dumps({
        'model': LLM_MODEL,
        'messages': [
            {'role': 'system', 'content': EVALUATION_SYSTEM_PROMPT},
            {'role': 'user',   'content': user_msg},
        ],
        'temperature': 0.2,
    }).encode('utf-8')

    try:
        req = urllib.request.Request(LLM_API_URL, data=payload, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=30) as response:
            result   = json.loads(response.read().decode('utf-8'))
            content  = result['choices'][0]['message']['content'].strip()
            content  = re.sub(r'^```(?:json)?\s*\n?|\n?```\s*$', '', content).strip()
            evaluation = json.loads(content)
            return {
                'score':            evaluation.get('score', 0),
                'summary':          evaluation.get('summary', ''),
                'matched_skills':   evaluation.get('matched_skills', []),
                'missing_skills':   evaluation.get('missing_skills', []),
                'recommendations':  evaluation.get('recommendations', []),
            }

    except Exception as exc:
        logger.error('LLM evaluation failed: %s', exc)
        raise ValueError(f'LLM request failed: {exc}')


NEGOTIATION_SYSTEM_PROMPT = """\
You are an expert compensation negotiation coach helping a candidate negotiate a job offer.
Analyze the offer against the candidate's background and current compensation (if provided), \
then give concrete, actionable negotiation advice prioritized by impact.

Respond ONLY with a valid JSON object using exactly this structure:
{
    "talking_points": ["<specific script line or argument to use, ordered by when to deploy>", ...],
    "leverage_points": ["<strength the candidate can cite>", ...],
    "caution_points": ["<risk or weakness to be aware of>", ...],
    "suggested_ask": {
        "base_salary": <integer or null>,
        "sign_on": <integer or null>,
        "equity": <integer annualized USD value or null>,
        "pto_days": <integer or null>,
        "notes": "<brief rationale and priority order for the ask>"
    }
}"""

def _format_offer_time_off(offer) -> str:
    holiday_days = getattr(offer, 'holiday_days', 11)
    if getattr(offer, 'is_unlimited_pto', False):
        return f"Unlimited PTO | Holidays: {holiday_days} days"
    return f"PTO: {offer.pto_days} days | Holidays: {holiday_days} days"


NEGOTIATION_USER_TEMPLATE = """\
TARGET OFFER:
Company: {company}
Role: {role_title}
Location: {location} | RTO: {rto_policy}
Base Salary: ${base_salary:,}
Annual Bonus: ${bonus:,}
Equity (annualized value): ${equity:,}
Sign-On Bonus: ${sign_on:,}
Time Off: {time_off_summary}
Benefits Value: ${benefits_value:,}

---
{current_section}

---
{resume_context}"""


def generate_negotiation_advice(offer, current_offer=None) -> dict:
    if not LLM_API_URL or not LLM_MODEL:
        raise ValueError("LLM_API_URL and LLM_MODEL must be set in your .env file.")

    if current_offer:
        current_section = (
            f"CURRENT / BASELINE COMPENSATION:\n"
            f"Base Salary: ${int(current_offer.base_salary):,}\n"
            f"Annual Bonus: ${int(current_offer.bonus):,}\n"
            f"Equity (annualized): ${int(current_offer.equity):,}\n"
            f"Sign-On: ${int(current_offer.sign_on):,}\n"
            f"Time Off: {_format_offer_time_off(current_offer)}"
        )
    else:
        current_section = "CURRENT / BASELINE COMPENSATION: Not provided — advise based on offer alone."

    app = offer.application
    user_msg = NEGOTIATION_USER_TEMPLATE.format(
        company=app.company.name,
        role_title=app.role_title,
        location=app.location or 'Not specified',
        rto_policy=app.rto_policy or 'Unknown',
        base_salary=int(offer.base_salary),
        bonus=int(offer.bonus),
        equity=int(offer.equity),
        sign_on=int(offer.sign_on),
        time_off_summary=_format_offer_time_off(offer),
        benefits_value=int(offer.benefits_value),
        current_section=current_section,
        resume_context=_build_resume_context(),
    )

    headers = {'Content-Type': 'application/json'}
    if LLM_API_KEY:
        headers['Authorization'] = f'Bearer {LLM_API_KEY}'

    payload = json.dumps({
        'model': LLM_MODEL,
        'messages': [
            {'role': 'system', 'content': NEGOTIATION_SYSTEM_PROMPT},
            {'role': 'user',   'content': user_msg},
        ],
        'temperature': 0.3,
    }).encode('utf-8')

    try:
        req = urllib.request.Request(LLM_API_URL, data=payload, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            content = result['choices'][0]['message']['content'].strip()
            content = re.sub(r'^```(?:json)?\s*\n?|\n?```\s*$', '', content).strip()
            advice = json.loads(content)
            return {
                'talking_points':  advice.get('talking_points', []),
                'leverage_points': advice.get('leverage_points', []),
                'caution_points':  advice.get('caution_points', []),
                'suggested_ask':   advice.get('suggested_ask', {}),
            }
    except Exception as exc:
        logger.error('LLM negotiation advice failed: %s', exc)
        raise ValueError(f'LLM request failed: {exc}')


COVER_LETTER_SYSTEM_PROMPT = """\
You are an expert career coach and professional writer.
Write a compelling, personalized cover letter body for the job application described by the user.

Structure (4 paragraphs):
1. Hook — a specific reason this company or role excites you; never open with \
"I am writing to express my interest" or similar clichés
2. Most relevant experience and how it directly maps to the role requirements
3. A concrete achievement or project that demonstrates measurable impact
4. Call to action — express genuine enthusiasm and invite the next step

Additional rules:
- Mirror the language and terminology from the job description where it feels natural
- Professional, confident, and concise — cut filler phrases
- Do NOT include placeholders like [Your Name] or [Date] — body paragraphs only
- Respond ONLY with the cover letter body text. No JSON, no headers, no extra formatting."""

COVER_LETTER_USER_TEMPLATE = """\
COMPANY: {company}
ROLE: {role_title}
LOCATION: {location}
{jd_section}

---
{resume_context}"""


def generate_cover_letter(application, jd_text: str = '') -> str:
    if not LLM_API_URL or not LLM_MODEL:
        raise ValueError("LLM_API_URL and LLM_MODEL must be set in your .env file.")

    jd_section = f"JOB DESCRIPTION:\n{jd_text}" if jd_text.strip() else \
        "No job description provided — tailor the letter based on the role title and company."

    user_msg = COVER_LETTER_USER_TEMPLATE.format(
        company=application.company.name,
        role_title=application.role_title,
        location=application.location or 'Not specified',
        jd_section=jd_section,
        resume_context=_build_resume_context(),
    )

    headers = {'Content-Type': 'application/json'}
    if LLM_API_KEY:
        headers['Authorization'] = f'Bearer {LLM_API_KEY}'

    payload = json.dumps({
        'model': LLM_MODEL,
        'messages': [
            {'role': 'system', 'content': COVER_LETTER_SYSTEM_PROMPT},
            {'role': 'user',   'content': user_msg},
        ],
        'temperature': 0.7,
    }).encode('utf-8')

    try:
        req = urllib.request.Request(LLM_API_URL, data=payload, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result['choices'][0]['message']['content'].strip()
    except Exception as exc:
        logger.error('LLM cover letter generation failed: %s', exc)
        raise ValueError(f'LLM request failed: {exc}')
