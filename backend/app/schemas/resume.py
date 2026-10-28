from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class SkillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str
    category: str
    confidence: float
    confidence_type: str = "heuristic"  # heuristic score, NOT a model probability
    mentions: int = 1
    in_skills_section: bool = False


class EducationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    degree: Optional[str] = None
    level: Optional[str] = None
    field_of_study: Optional[str] = None
    institution: Optional[str] = None
    location: Optional[str] = None
    start_year: Optional[int] = None
    end_year: Optional[int] = None
    grade: Optional[str] = None


class ExperienceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    duration_months: Optional[int] = None
    description: str = ""
    skills: list[str] = []


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    title: str
    description: str = ""
    technologies: list[str] = []


class CertificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str
    issuer: Optional[str] = None
    year: Optional[int] = None


class ResumeSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    original_filename: str
    file_type: str
    page_count: int
    word_count: int
    quality_score: float
    created_at: datetime
    skill_count: int = 0
    candidate_name: Optional[str] = None


class ResumeDetail(BaseModel):
    """Structured resume profile returned by upload and GET /resumes/{id}."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    original_filename: str
    file_type: str
    file_size: int
    page_count: int
    word_count: int
    created_at: datetime
    personal_information: dict[str, Any]
    summary: str
    skills: list[SkillOut]
    education: list[EducationOut]
    experience: list[ExperienceOut]
    projects: list[ProjectOut]
    certifications: list[CertificationOut]
    achievements: list[str]
    publications: list[str]
    organizations: list[str]
    sections_detected: list[str] = []
    nlp_stats: dict[str, Any]
    quality_score: float
    quality_issues: list[dict[str, Any]]
    quality_note: str = "Resume Quality Analysis is a rule-based checklist. It is not an ATS prediction."
