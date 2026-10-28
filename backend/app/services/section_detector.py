"""Resume section detection based on heading lines."""
import re
import unicodedata
from dataclasses import dataclass, field

SECTION_ALIASES: dict[str, list[str]] = {
    "summary": ["summary", "professional summary", "profile", "professional profile", "about me",
                "career summary", "executive summary"],
    "objective": ["objective", "career objective", "professional objective"],
    "education": ["education", "education profile", "academic background", "academic details", "academics", "educational qualifications",
                  "academic qualifications", "education and training", "qualifications"],
    "skills": ["skills", "technical skills", "key skills", "core competencies", "skills and tools",
               "technical proficiency", "technologies", "tools and technologies", "skills summary",
               "areas of expertise", "technical expertise"],
    "experience": ["experience", "work experience", "professional experience", "employment history",
                   "internships", "internship experience", "work history", "industry experience",
                   "relevant experience", "internship"],
    "projects": ["projects", "academic projects", "personal projects", "key projects", "project work",
                 "selected projects", "technical projects", "project experience"],
    "certifications": ["certifications", "certificates", "licenses and certifications",
                       "courses and certifications", "certifications and courses",
                       "training and certifications", "courses", "certification"],
    "achievements": ["achievements", "awards", "honors and awards", "accomplishments",
                     "awards and achievements", "extracurricular activities", "extra curricular activities", "honors"],
    "publications": ["publications", "research papers", "research publications"],
}

_ALIAS_TO_SECTION = {alias: sec for sec, aliases in SECTION_ALIASES.items() for alias in aliases}
_COMBINED_ALIASES = {
    "certifications and achievements": ("certifications", "achievements"),
    "certifications achievements": ("certifications", "achievements"),
    "certificates and achievements": ("certifications", "achievements"),
    "courses certifications and achievements": ("certifications", "achievements"),
}


def normalize_heading(line: str) -> str:
    """Return a conservative comparison key while retaining source text elsewhere."""
    s = unicodedata.normalize("NFKD", line or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.casefold().replace("&", " and ")
    # A heading may be styled with bullets, em dashes, underlines, or a trailing colon.
    s = re.sub(r"[\W_]+", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def heading_to_section(line: str) -> str | None:
    """Return the canonical section name if `line` is a section heading."""
    if not line or len(line) > 50 or len(line.split()) > 6:
        return None
    if line.strip().endswith((".", ",")):
        return None
    sections = heading_to_sections(line)
    return sections[0] if sections else None


def heading_to_sections(line: str) -> tuple[str, ...]:
    """Return all categories represented by a heading (combined headings are intentional)."""
    if not line or len(line) > 70 or len(line.split()) > 8:
        return ()
    if line.strip().endswith((".", ",")):
        return ()
    normalized = normalize_heading(line)
    if normalized in _COMBINED_ALIASES:
        return _COMBINED_ALIASES[normalized]
    section = _ALIAS_TO_SECTION.get(normalized)
    return (section,) if section else ()


@dataclass
class SectionResult:
    header: str = ""  # text before the first heading (name, contact details)
    sections: dict[str, str] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)


def detect_sections(text: str) -> SectionResult:
    result = SectionResult()
    current: tuple[str, ...] = ()
    buffers: dict[str, list[str]] = {}
    header_lines: list[str] = []
    for line in text.split("\n"):
        sections = heading_to_sections(line)
        if sections:
            current = sections
            for section in sections:
                buffers.setdefault(section, [])
                if section not in result.order:
                    result.order.append(section)
            continue
        if not current:
            header_lines.append(line)
        else:
            for section in current:
                buffers[section].append(line)
    result.header = "\n".join(header_lines).strip()
    result.sections = {k: "\n".join(v).strip() for k, v in buffers.items() if "\n".join(v).strip()}
    result.order = [s for s in result.order if s in result.sections]
    return result
