"""Persistence glue: parsed resume dict <-> ORM objects."""
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Certification, Education, Experience, Project, Resume, ResumeSkill
from app.services.nlp_processor import ResumeNLPProcessor
from app.services.quality_analyzer import analyze_quality
from app.utils.files import new_stored_name, resolve_upload_path, sanitize_filename

logger = logging.getLogger(__name__)


def create_resume(db: Session, user_id: int, filename: str, file_type: str, data: bytes, doc: dict,
                  processor: ResumeNLPProcessor) -> Resume:
    """Parse text -> structured profile, store the file safely, persist everything."""
    profile = processor.parse(doc["text"], doc["page_count"], doc.get("links"))
    quality = analyze_quality(profile, doc["text"], doc["page_count"])

    settings = get_settings()
    stored = new_stored_name(file_type)
    upload_root = Path(settings.upload_dir)
    upload_root.mkdir(parents=True, exist_ok=True)
    path = resolve_upload_path(settings.upload_dir, stored)
    path.write_bytes(data)

    try:
        resume = Resume(
            user_id=user_id,
            original_filename=sanitize_filename(filename),
            stored_filename=stored,
            file_type=file_type,
            file_size=len(data),
            page_count=doc["page_count"],
            word_count=profile["nlp_stats"]["word_count"],
            raw_text=doc["text"],
            sections=profile["sections"],
            personal_information=profile["personal_information"],
            summary=profile["summary"],
            achievements=profile["achievements"],
            publications=profile["publications"],
            organizations=profile["organizations"],
            nlp_stats=profile["nlp_stats"],
            quality_score=quality["quality_score"],
            quality_issues=quality["issues"],
        )
        resume.skills = [ResumeSkill(**{k: s[k] for k in
                         ("name", "category", "confidence", "confidence_type", "mentions", "in_skills_section")})
                         for s in profile["skills"]]
        resume.education = [Education(**e) for e in profile["education"]]
        resume.experience = [Experience(**e) for e in profile["experience"]]
        resume.projects = [Project(**p) for p in profile["projects"]]
        resume.certifications = [Certification(**c) for c in profile["certifications"]]
        db.add(resume)
        db.commit()
        db.refresh(resume)
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)  # do not leave orphaned files if the DB write fails
        raise
    logger.info("Resume %s processed (%s, %d skills)", resume.id, file_type, len(resume.skills))
    return resume


def delete_resume_file(resume: Resume) -> None:
    try:
        resolve_upload_path(get_settings().upload_dir, resume.stored_filename).unlink(missing_ok=True)
    except (OSError, ValueError):
        logger.warning("Could not delete stored file for resume %s", resume.id)


def resume_to_profile(resume: Resume) -> dict:
    """Rebuild the structured profile dict from ORM rows (used for matching)."""
    return {
        "personal_information": resume.personal_information,
        "summary": resume.summary,
        "skills": [{"name": s.name, "category": s.category, "confidence": s.confidence,
                    "confidence_type": s.confidence_type, "mentions": s.mentions,
                    "in_skills_section": s.in_skills_section} for s in resume.skills],
        "education": [{"degree": e.degree, "level": e.level, "field_of_study": e.field_of_study,
                       "institution": e.institution, "location": e.location, "start_year": e.start_year, "end_year": e.end_year,
                       "grade": e.grade} for e in resume.education],
        "experience": [{"title": e.title, "company": e.company, "location": e.location,
                        "start_date": e.start_date, "end_date": e.end_date, "duration_months": e.duration_months,
                        "description": e.description, "skills": e.skills} for e in resume.experience],
        "projects": [{"title": p.title, "description": p.description, "technologies": p.technologies}
                     for p in resume.projects],
        "certifications": [{"name": c.name, "issuer": c.issuer, "year": c.year} for c in resume.certifications],
        "achievements": resume.achievements,
        "sections": resume.sections,
        "total_experience_months": _total_months(resume),
    }


def _total_months(resume: Resume) -> int:
    from app.services.nlp_processor import duration_months, merged_months

    intervals = [iv for e in resume.experience if e.start_date
                 and (iv := duration_months(e.start_date, e.end_date or ""))]
    return merged_months(intervals)
