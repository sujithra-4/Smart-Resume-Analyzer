"""Resume Quality Analysis (rule-based).

This is NOT an ATS prediction. It is a transparent checklist: each issue carries a fixed,
documented penalty subtracted from 100.
"""
import re
from collections import Counter
from typing import Optional

from spacy.lang.en.stop_words import STOP_WORDS

from app.services.skill_extractor import get_skill_extractor
from app.utils.text import is_bullet, strip_bullet

_NUMBER_RE = re.compile(r"\d")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z+#.-]{2,}")


def _issue(type_: str, severity: str, penalty: int, message: str) -> dict:
    return {"type": type_, "severity": severity, "penalty": penalty, "message": message}


def _bullets(profile: dict) -> list[str]:
    lines: list[str] = []
    for e in profile.get("experience", []):
        lines += [l for l in (e.get("description") or "").split("\n") if l.strip()]
    for p in profile.get("projects", []):
        lines += [l for l in (p.get("description") or "").split("\n") if l.strip()]
    return lines


def structure_checks(profile: dict, text: str) -> dict[str, bool]:
    """Eight yes/no checks used for the 'Resume Structure' score component."""
    pi = profile.get("personal_information", {})
    sections = profile.get("sections", {})
    words = len(text.split())
    return {
        "has_name": bool(pi.get("name")),
        "has_email": bool(pi.get("email")),
        "has_summary_or_objective": bool(profile.get("summary")),
        "has_skills_section": "skills" in sections,
        "has_education_section": bool(profile.get("education")) or "education" in sections,
        "has_experience_or_projects": "experience" in sections or "projects" in sections,
        "has_clear_headings": len(sections) >= 3,
        "reasonable_length": 150 <= words <= 900,
    }


def structure_score(profile: dict, text: str) -> float:
    checks = structure_checks(profile, text)
    return round(100 * sum(checks.values()) / len(checks), 1)


def analyze_quality(profile: dict, text: str, page_count: int = 1,
                    missing_required_skills: Optional[list[str]] = None) -> dict:
    issues: list[dict] = []
    pi = profile.get("personal_information", {})
    sections = profile.get("sections", {})
    words = len(text.split())

    # --- contact information -------------------------------------------------
    if not pi.get("email"):
        issues.append(_issue("missing_contact_email", "high", 10, "No e-mail address was detected."))
    if not pi.get("phone"):
        issues.append(_issue("missing_contact_phone", "medium", 5, "No phone number was detected."))
    if not pi.get("name"):
        issues.append(_issue("missing_name", "medium", 5, "Your name could not be detected at the top of the resume."))

    # --- missing sections ----------------------------------------------------
    if not profile.get("summary"):
        issues.append(_issue("missing_summary", "low", 5, "No summary or objective section was found."))
    if "skills" not in sections:
        issues.append(_issue("missing_skills_section", "high", 10, "No dedicated Skills section was found."))
    elif not profile.get("skills"):
        issues.append(_issue("no_skills_detected", "high", 10, "No known skills were detected in the resume."))
    if "education" not in sections and not profile.get("education"):
        issues.append(_issue("missing_education", "high", 10, "No Education section was found."))
    if "experience" not in sections and "projects" not in sections:
        issues.append(_issue("missing_experience_projects", "high", 15,
                             "Neither an Experience nor a Projects section was found."))
    elif "projects" not in sections:
        issues.append(_issue("missing_projects", "low", 6, "No Projects section was found."))

    # --- length ---------------------------------------------------------------
    if words > 900 or page_count > 2:
        issues.append(_issue("excessive_length", "medium", 8,
                             f"The resume is long ({words} words, {page_count} page(s)). One to two pages is usual."))
    elif words < 150:
        issues.append(_issue("too_short", "medium", 10, f"The resume is very short ({words} words)."))

    # --- organisation ---------------------------------------------------------
    if len(sections) < 3:
        issues.append(_issue("poor_organization", "medium", 10,
                             "Fewer than three standard section headings were detected, so content may be hard to scan."))

    # --- weak projects --------------------------------------------------------
    weak = [p["title"] for p in profile.get("projects", [])
            if len((p.get("description") or "").split()) < 12 or not p.get("technologies")]
    if weak:
        issues.append(_issue("weak_project_description", "medium", min(10, 4 * len(weak)),
                             "These projects have a short description or no detected technologies: "
                             + "; ".join(weak[:4]) + "."))

    # --- measurable achievements ---------------------------------------------
    bullets = _bullets(profile)
    if bullets:
        with_numbers = sum(1 for b in bullets if _NUMBER_RE.search(b))
        if with_numbers / len(bullets) < 0.2:
            issues.append(_issue("missing_metric", "medium", 8,
                                 "Project and experience descriptions do not contain measurable results "
                                 f"(only {with_numbers} of {len(bullets)} lines include a number)."))

    # --- repeated words -------------------------------------------------------
    extractor = get_skill_extractor()
    tokens = [w.lower().strip(".-") for w in _WORD_RE.findall(text)]
    counts = Counter(w for w in tokens if w not in STOP_WORDS and not extractor.normalize(w) and len(w) > 3)
    if counts:
        word, n = counts.most_common(1)[0]
        if n >= max(8, int(0.015 * len(tokens))):
            issues.append(_issue("repeated_words", "low", 4, f"The word '{word}' is repeated {n} times."))
    openers = Counter(strip_bullet(b).split()[0].lower() for b in bullets if strip_bullet(b).split())
    if openers:
        opener, n = openers.most_common(1)[0]
        if n >= 3 and len(opener) > 3:
            issues.append(_issue("repeated_bullet_opener", "low", 3,
                                 f"{n} bullet points start with the same word ('{opener}'). Vary your action verbs."))

    # --- job-specific ---------------------------------------------------------
    if missing_required_skills:
        issues.append(_issue("missing_relevant_skills", "high", min(10, 2 * len(missing_required_skills)),
                             "Skills required by the job but not found in the resume: "
                             + ", ".join(missing_required_skills[:8]) + "."))

    score = max(0, 100 - sum(i["penalty"] for i in issues))
    return {"quality_score": score, "issues": issues}
