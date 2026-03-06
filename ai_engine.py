"""
AI Engine — uses Groq (free) to score jobs and write cover letters.
"""
import os
import json
from groq import Groq
from dotenv import load_dotenv
from config import PROFILE

load_dotenv()

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
MODEL = "llama-3.1-8b-instant"


def _chat(prompt: str, max_tokens: int = 512) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content.strip()


def _profile_summary() -> str:
    """Format the user profile into a readable string for the AI."""
    p = PROFILE
    skills = ", ".join(p.get("skills", []))
    roles = ", ".join(p.get("preferred_roles", []))

    exp_text = ""
    for e in p.get("experience", []):
        bullets = "\n    - ".join(e.get("bullets", []))
        exp_text += f"\n  {e['title']} at {e['company']} ({e['duration']}):\n    - {bullets}"

    projects_text = ""
    for proj in p.get("projects", []):
        projects_text += f"\n  - {proj['name']}: {proj['description']}"

    return f"""
Name: {p['name']}
Summary: {p['summary']}
Skills: {skills}
Target Roles: {roles}
Seniority: {p.get('seniority', 'junior')}
Remote Only: {p.get('remote_only', True)}

Work Experience:{exp_text}

Projects:{projects_text}
""".strip()


def score_job(job: dict) -> tuple[float, str]:
    """
    Ask Claude to score a job 1-10 based on fit with the user's profile.
    Returns (score, reason).
    """
    profile_text = _profile_summary()
    job_text = f"""
Title: {job.get('title', '')}
Company: {job.get('company', '')}
Location: {job.get('location', '')}
Salary: {job.get('salary', 'Not specified')}
Tags/Skills: {', '.join(job.get('tags', []))}
Description: {job.get('description', 'No description available')[:1500]}
""".strip()

    prompt = f"""You are helping a job seeker evaluate job opportunities.

CANDIDATE PROFILE:
{profile_text}

JOB POSTING:
{job_text}

Score this job from 1-10 based on how well it matches the candidate's profile, skills, and preferences.
Consider: skill match, seniority level, remote availability, role type.

Respond with ONLY valid JSON in this exact format:
{{"score": 8.5, "reason": "Great match because..."}}

Score meaning: 1-3 = poor fit, 4-6 = moderate fit, 7-9 = strong fit, 10 = perfect fit."""

    try:
        text = _chat(prompt, max_tokens=256)
        start = text.find("{")
        end = text.rfind("}") + 1
        result = json.loads(text[start:end])
        return float(result.get("score", 0)), result.get("reason", "")
    except Exception as e:
        print(f"[AI] Score error: {e}")
        return 0.0, f"Error: {e}"


def generate_cover_letter(job: dict) -> str:
    """
    Generate a tailored cover letter for a specific job.
    Returns the cover letter as a string.
    """
    profile_text = _profile_summary()
    job_text = f"""
Title: {job.get('title', '')}
Company: {job.get('company', '')}
Description: {job.get('description', 'No description available')[:2000]}
Tags/Skills: {', '.join(job.get('tags', []))}
""".strip()

    tone = PROFILE.get("cover_letter_tone", "professional yet enthusiastic")
    extra = PROFILE.get("cover_letter_extra", "")

    prompt = f"""Write a tailored cover letter for this job application.

CANDIDATE PROFILE:
{profile_text}

JOB POSTING:
{job_text}

Requirements:
- Tone: {tone}
- {extra}
- Do NOT use generic filler phrases like "I am writing to apply for..."
- Reference specific skills from the job that match the candidate
- 3 paragraphs: opening hook, relevant experience, closing with CTA
- Do NOT include date, address headers — just the body text
- End with: "Best regards,\n{PROFILE['name']}"

Write the cover letter now:"""

    try:
        return _chat(prompt, max_tokens=600)
    except Exception as e:
        print(f"[AI] Cover letter error: {e}")
        return f"Error generating cover letter: {e}"


def tailor_resume_summary(job: dict) -> str:
    """
    Generate a tailored resume summary/objective for a specific job.
    Use this to customize the top of your resume before applying.
    """
    profile_text = _profile_summary()
    job_text = f"""
Title: {job.get('title', '')}
Company: {job.get('company', '')}
Key Skills Required: {', '.join(job.get('tags', []))}
Description excerpt: {job.get('description', '')[:800]}
""".strip()

    prompt = f"""Write a tailored 2-3 sentence professional summary for a resume.

CANDIDATE PROFILE:
{profile_text}

TARGET JOB:
{job_text}

Requirements:
- Start with the candidate's role/identity
- Include 2-3 relevant skills that match the job
- End with what value they bring
- Maximum 60 words
- No first-person pronouns ("I", "my")

Write ONLY the summary text, nothing else:"""

    try:
        return _chat(prompt, max_tokens=150)
    except Exception as e:
        return PROFILE.get("summary", "")


def generate_tailored_resume(job: dict) -> dict:
    """
    Generate minimal ATS-targeted additions to the resume for a specific job.
    Keeps all original content unchanged — only adds 1-2 new bullets and reorders skills.
    Returns: {"priority_skills": [...], "extra_bullets": [...]}
    """
    profile_text = _profile_summary()
    all_skills = PROFILE.get("skills", [])
    job_text = f"""
Title: {job.get('title', '')}
Company: {job.get('company', '')}
Key Skills Required: {', '.join(job.get('tags', []))}
Description: {job.get('description', '')[:1200]}
""".strip()

    prompt = f"""You are helping tailor a resume for ATS keyword matching. Keep changes minimal.

CANDIDATE PROFILE:
{profile_text}

TARGET JOB:
{job_text}

ALL CANDIDATE SKILLS (in order): {', '.join(all_skills)}

Return ONLY valid JSON in this exact format:
{{
  "priority_skills": ["skill_a", "skill_b", "skill_c"],
  "extra_bullets": ["Bullet 1 text", "Bullet 2 text"]
}}

Rules:
- priority_skills: Pick 6-8 skills from the candidate's list that best match THIS job. These will be shown FIRST in the skills section. Do NOT add skills they don't have.
- extra_bullets: Write exactly 1-2 NEW bullet points for the most recent job that naturally incorporate keywords from THIS job description. Must match the candidate's existing writing style (action verb + what they did + result/impact). Max 20 words each. Do NOT start with "I". Do NOT sound like AI marketing copy. Write like a real engineer.
- Do NOT rewrite existing bullets. Only add new ones.
- Do NOT invent experience they don't have — base bullets on their real background."""

    try:
        text = _chat(prompt, max_tokens=400)
        start = text.find("{")
        end = text.rfind("}") + 1
        result = json.loads(text[start:end])
        return result
    except Exception as e:
        return {
            "priority_skills": [],
            "extra_bullets": []
        }


def improve_resume(resume_text: str) -> str:
    """
    Takes raw resume text and returns an improved version with better bullet points.
    """
    prompt = f"""You are an expert resume writer specializing in tech/AI/ML roles.

Here is the candidate's current resume:

{resume_text}

Improve this resume by:
1. Making bullet points more impactful (use action verbs + quantified results)
2. Tightening the language (remove filler words)
3. Ensuring skills section is scannable
4. Adding any missing standard sections

Return the improved resume in plain text format, maintaining the same structure.
ONLY return the resume text — no commentary."""

    try:
        return _chat(prompt, max_tokens=2000)
    except Exception as e:
        return f"Error: {e}"
