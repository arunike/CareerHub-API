import os
import json
import urllib.request
import logging
from .models import Experience

logger = logging.getLogger(__name__)

# --- Provider configuration (set these in your .env) ---
LLM_API_URL = os.environ.get('LLM_API_URL', 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions')
LLM_API_KEY = os.environ.get('LLM_API_KEY', '')
LLM_MODEL   = os.environ.get('LLM_MODEL',   'gemini-2.0-flash')

EVALUATION_PROMPT_TEMPLATE = """
You are an expert technical recruiter and ATS system.
Holistically evaluate the Candidate's Professional Experience against the Job Description.
Do NOT just keyword-match; assess whether the candidate's actual trajectory and achievements align with the role.

Respond ONLY with a valid JSON object using exactly this structure:
{{
    "score": <integer 0-100>,
    "summary": "<2-3 sentences explaining overall fit>",
    "matched_skills": ["<strength or matched area>", ...],
    "missing_skills": ["<critical gap>", ...],
    "recommendations": ["<actionable resume tip>", ...]
}}

---
JOB DESCRIPTION:
{jd_text}

---
{resume_context}
"""

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

    prompt = EVALUATION_PROMPT_TEMPLATE.format(
        jd_text=jd_text,
        resume_context=_build_resume_context(),
    )

    headers = {'Content-Type': 'application/json'}
    if LLM_API_KEY:
        headers['Authorization'] = f'Bearer {LLM_API_KEY}'

    payload = json.dumps({
        'model': LLM_MODEL,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.2,
    }).encode('utf-8')

    try:
        req = urllib.request.Request(LLM_API_URL, data=payload, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=30) as response:
            result   = json.loads(response.read().decode('utf-8'))
            content  = result['choices'][0]['message']['content'].strip()

            # Strip markdown code fences if the model ignores instructions
            if content.startswith('```'):
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:]
                content = content.strip()

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


NEGOTIATION_PROMPT_TEMPLATE = """
You are an expert compensation negotiation coach helping a candidate negotiate a job offer.
Analyze the offer against the candidate's background and current compensation (if available), then provide concrete, actionable negotiation advice.

Respond ONLY with a valid JSON object using exactly this structure:
{{
    "talking_points": ["<specific script line or argument to use>", ...],
    "leverage_points": ["<strength the candidate can cite>", ...],
    "caution_points": ["<risk or weakness to be aware of>", ...],
    "suggested_ask": {{
        "base_salary": <integer or null>,
        "sign_on": <integer or null>,
        "equity": <integer or null>,
        "pto_days": <integer or null>,
        "notes": "<brief rationale for the suggested ask>"
    }}
}}

---
TARGET OFFER:
Company: {company}
Role: {role_title}
Location: {location} | RTO: {rto_policy}
Base Salary: ${base_salary:,}
Annual Bonus: ${bonus:,}
Equity (annualized): ${equity:,}
Sign-On Bonus: ${sign_on:,}
PTO: {pto_days} days | Holidays: {holiday_days} days
Benefits Value: ${benefits_value:,}

---
{current_section}

---
{resume_context}
"""


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
            f"PTO: {current_offer.pto_days} days"
        )
    else:
        current_section = "CURRENT / BASELINE COMPENSATION: Not provided — advise based on offer alone."

    app = offer.application
    prompt = NEGOTIATION_PROMPT_TEMPLATE.format(
        company=app.company.name,
        role_title=app.role_title,
        location=app.location or 'Not specified',
        rto_policy=app.rto_policy or 'Unknown',
        base_salary=int(offer.base_salary),
        bonus=int(offer.bonus),
        equity=int(offer.equity),
        sign_on=int(offer.sign_on),
        pto_days=offer.pto_days,
        holiday_days=offer.holiday_days,
        benefits_value=int(offer.benefits_value),
        current_section=current_section,
        resume_context=_build_resume_context(),
    )

    headers = {'Content-Type': 'application/json'}
    if LLM_API_KEY:
        headers['Authorization'] = f'Bearer {LLM_API_KEY}'

    payload = json.dumps({
        'model': LLM_MODEL,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.3,
    }).encode('utf-8')

    try:
        req = urllib.request.Request(LLM_API_URL, data=payload, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            content = result['choices'][0]['message']['content'].strip()
            if content.startswith('```'):
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:]
                content = content.strip()
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


COVER_LETTER_PROMPT_TEMPLATE = """
You are an expert career coach and professional writer.
Write a compelling, personalized cover letter for the following job application.
The cover letter should be professional, concise (3-4 paragraphs), and highlight the candidate's most relevant experience and skills for this specific role.
Do NOT include placeholder text like [Your Name] or [Date] — write the body paragraphs only.

Respond ONLY with the cover letter body text. No JSON, no headers, no extra formatting.

---
COMPANY: {company}
ROLE: {role_title}
LOCATION: {location}
{jd_section}

---
{resume_context}
"""


def generate_cover_letter(application, jd_text: str = '') -> str:
    if not LLM_API_URL or not LLM_MODEL:
        raise ValueError("LLM_API_URL and LLM_MODEL must be set in your .env file.")

    jd_section = f"JOB DESCRIPTION:\n{jd_text}" if jd_text.strip() else \
        "No job description provided — tailor the letter based on the role title and company."

    prompt = COVER_LETTER_PROMPT_TEMPLATE.format(
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
        'messages': [{'role': 'user', 'content': prompt}],
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
