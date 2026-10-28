"""spaCy-based resume understanding.

Pipeline: tokenisation + sentence segmentation + NER (spaCy) -> section detection ->
dictionary/PhraseMatcher skill extraction -> rule-assisted entity extraction for
education, experience, projects and certifications.

Regular expressions are only used for well-structured fields (e-mail, phone, dates,
degrees). Names, locations and organisations come from spaCy NER, with documented
heuristics as a fallback when NER finds nothing.
"""
import logging
import re
from collections import Counter
from datetime import date
from functools import lru_cache
from typing import Optional
from urllib.parse import urlparse

import spacy

from app.core.config import get_settings
from app.services.section_detector import SectionResult, detect_sections, heading_to_section
from app.services.skill_extractor import SkillExtractor, get_skill_extractor
from app.utils.text import is_bullet, strip_bullet, word_count

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------- spaCy
@lru_cache
def get_nlp():
    """Load the spaCy pipeline once and reuse it for every request."""
    name = get_settings().spacy_model_name
    try:
        nlp = spacy.load(name)
        logger.info("spaCy model '%s' loaded", name)
    except OSError:
        logger.warning(
            "spaCy model '%s' not installed (run: python -m spacy download %s). "
            "Falling back to a blank English pipeline: NER-based fields will be less accurate.",
            name, name,
        )
        nlp = spacy.blank("en")
        nlp.add_pipe("sentencizer")
    return nlp


def nlp_model_status() -> dict:
    nlp = get_nlp()
    return {"name": nlp.meta.get("name") or "blank", "has_ner": "ner" in nlp.pipe_names}


# ---------------------------------------------------------------------------- regexes
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<![\w/])(\+?\d[\d\s().-]{8,18}\d)(?![\w/])")
LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w\-%]+/?", re.I)
GITHUB_RE = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[\w\-]+/?", re.I)

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
_DATE = rf"(?:{_MONTH}\s+\d{{4}}|\d{{1,2}}/\d{{4}}|\d{{4}})"
DATE_RANGE_RE = re.compile(rf"({_DATE})\s*(?:-|–|—|to)\s*({_DATE}|present|current|ongoing|now)", re.I)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

ROLE_WORDS = {
    "intern", "internship", "engineer", "developer", "analyst", "trainee", "associate", "manager", "consultant",
    "researcher", "scientist", "architect", "lead", "designer", "administrator", "specialist", "assistant",
    "officer", "programmer", "tester", "apprentice", "volunteer", "coordinator", "fellow", "director",
    "executive", "member", "representative",
}
COMPANY_RE = re.compile(
    r"\b(inc|ltd|llc|pvt|corp|corporation|technologies|technology|solutions|labs|systems|software|services|"
    r"consulting|company|limited|group|ventures|infotech|analytics|studio|studios|networks)\b\.?", re.I)
INSTITUTION_RE = re.compile(
    r"\b(University|College|Institute|Institution|School|Academy|Polytechnic|IIT|NIT|IIIT|Vidyalaya)\b")

# (regex, level, case_sensitive) in priority order. Levels: 0 school, 1 diploma, 2 bachelor, 3 master, 4 phd
_DEGREE_PATTERNS = [
    (re.compile(r"\bPh\.?\s?D\b|\bDoctorate\b", re.I), 4),
    (re.compile(r"\bMCA\b|\bMBA\b|\bM\.E\b\.?|\bM\.S\b\.?"), 3),
    (re.compile(r"\bM\.?\s?Tech\b|\bM\.?\s?Sc\b|\bMasters?(?:'s)?\b", re.I), 3),
    (re.compile(r"\bB\.E\b\.?|\bBE\b(?=\s+(?:in|\(|-|,)|\s*$)|\bBCA\b|\bBBA\b"), 2),
    (re.compile(r"\bB\.?\s?Tech\b|\bB\.?\s?Sc\b|\bBachelors?(?:'s)?\b", re.I), 2),
    (re.compile(r"\bDiploma\b|\bPolytechnic\b", re.I), 1),
    (re.compile(r"\bHSC\b|\bSSLC\b|\bSSC\b|\bHigher Secondary(?: Certificate)?\b|\bSecondary School Leaving Certificate\b|\b12th\b|\b10th\b|\bClass (?:X|XII)\b|\bIntermediate\b", re.I), 0),
]
LEVEL_NAMES = {0: "school", 1: "diploma", 2: "bachelor", 3: "master", 4: "phd"}

ISSUERS = [
    "Microsoft", "AWS", "Amazon", "Google", "Coursera", "Udemy", "edX", "IBM", "Oracle", "Cisco", "NPTEL",
    "Infosys", "Meta", "Deloitte", "Red Hat", "Linux Foundation", "DeepLearning.AI", "HackerRank", "LinkedIn",
    "Kaggle", "Udacity", "freeCodeCamp", "Great Learning", "Simplilearn",
]
_SEP_RE = re.compile(r"\s[-–—]\s|\s*\|\s*|,\s+|\s\(|\)\s*|\s+at\s+|\s@\s")


# ------------------------------------------------------------------------ date helpers
def _parse_date(token: str) -> Optional[tuple[int, Optional[int]]]:
    """-> (year, month|None); None means 'present'."""
    t = token.strip().lower().rstrip(".")
    if t in {"present", "current", "ongoing", "now"}:
        return None
    m = re.match(r"([a-z]+)\.?\s+(\d{4})$", t)
    if m:
        return int(m.group(2)), _MONTHS.get(m.group(1)[:3])
    m = re.match(r"(\d{1,2})/(\d{4})$", t)
    if m:
        return int(m.group(2)), min(max(int(m.group(1)), 1), 12)
    m = re.match(r"(\d{4})$", t)
    return (int(m.group(1)), None) if m else None


def duration_months(start: str, end: str, today: Optional[date] = None) -> Optional[tuple[int, int]]:
    """Return (start_index, months) where start_index = year*12+month-1, or None if unparseable.

    Heuristics: both months known -> inclusive month count; year-only dates -> whole years
    (minimum 3 months). 'Present' resolves to today's month."""
    today = today or date.today()
    s = _parse_date(start)
    if s is None:
        return None
    e = _parse_date(end)
    if e is None:
        e = (today.year, today.month)
    sy, sm = s
    ey, em = e
    if sm and em:
        s_idx, e_idx = sy * 12 + sm - 1, ey * 12 + em - 1
        months = e_idx - s_idx + 1
    else:
        s_idx = sy * 12 + (sm or 6) - 1
        months = max(3, (ey - sy) * 12)
    return (s_idx, months) if months > 0 else None


def merged_months(intervals: list[tuple[int, int]]) -> int:
    """Total months covered by (start_index, months) intervals, counting overlaps once."""
    total, cur_end = 0, None
    for start, months in sorted(intervals):
        end = start + months
        if cur_end is None or start >= cur_end:
            total += months
            cur_end = end
        elif end > cur_end:
            total += end - cur_end
            cur_end = end
    return total


# --------------------------------------------------------------------------- processor
class ResumeNLPProcessor:
    def __init__(self, nlp=None, extractor: Optional[SkillExtractor] = None):
        self.nlp = nlp or get_nlp()
        self.extractor = extractor or get_skill_extractor()

    # ------------------------------------------------------------------ public API
    def parse(self, text: str, page_count: int = 1, links: Optional[list[dict[str, str]]] = None) -> dict:
        sec: SectionResult = detect_sections(text)
        doc = self.nlp(text)

        organizations = self._organizations(doc)
        sections_for_skills = sec.sections or {"unknown": text}
        skills = [h.to_dict() for h in self.extractor.extract(text, sections_for_skills)]

        experience = self._parse_experience(sec.sections.get("experience", ""))
        intervals = [iv for e in experience if (iv := duration_months(e["start_date"] or "", e["end_date"] or ""))
                     ] if experience else []
        profile = {
            "personal_information": self._personal_information(text, sec, links or []),
            "summary": sec.sections.get("summary") or sec.sections.get("objective", ""),
            "skills": skills,
            "education": self._parse_education(sec.sections.get("education", "")),
            "experience": experience,
            "projects": self._parse_projects(sec.sections.get("projects", "")),
            "certifications": self._parse_certifications(sec.sections.get("certifications", "")),
            "achievements": self._parse_achievements(sec.sections.get("achievements", "")),
            "publications": [strip_bullet(l) for l in sec.sections.get("publications", "").split("\n") if l.strip()],
            "organizations": organizations,
            "sections": sec.sections,
            "section_order": sec.order,
            "total_experience_months": merged_months(intervals),
            "nlp_stats": {
                "model": self.nlp.meta.get("name") or "blank",
                "tokens": sum(1 for t in doc if not t.is_space),
                "sentences": sum(1 for _ in doc.sents) if doc.has_annotation("SENT_START") else 0,
                "entities": dict(Counter(e.label_ for e in doc.ents)),
                "word_count": word_count(text),
                "page_count": page_count,
            },
        }
        return profile

    # ------------------------------------------------------------ personal details
    def _personal_information(self, text: str, sec: SectionResult, links: list[dict[str, str]]) -> dict:
        header = sec.header or "\n".join(text.split("\n")[:6])
        header_lines = [l.strip() for l in header.split("\n") if l.strip()][:8]
        header_text = "\n".join(header_lines)

        email = EMAIL_RE.search(text)
        phone = next((m.group(1).strip() for m in PHONE_RE.finditer(header_text or text)
                      if 10 <= len(re.sub(r"\D", "", m.group(1))) <= 13), None)
        linkedin = LINKEDIN_RE.search(text)
        github = GITHUB_RE.search(text)
        link_map = self._profile_links(links)

        # NER runs per line: an entity must never span a line break (name + city on separate lines).
        segments = [
            seg.strip() for line in header_lines for seg in re.split(r"\s*[|•·]\s*", line)
            if seg.strip() and "@" not in seg and sum(c.isdigit() for c in seg) < 4
        ]
        hdocs = list(self.nlp.pipe(segments)) if segments else []
        name = self._find_name(header_lines, hdocs)
        gpes: list[str] = []
        for hdoc in hdocs:
            for ent in hdoc.ents:
                if ent.label_ in {"GPE", "LOC"} and ent.text not in gpes and not self.extractor.normalize(ent.text):
                    gpes.append(ent.text)
        location = ", ".join(gpes[:2]) if gpes else self._location_pattern(segments)
        return {
            "name": name,
            "email": email.group(0) if email else None,
            "phone": phone,
            "location": location,
            "linkedin": link_map.get("linkedin") or (self._normalise_url(linkedin.group(0)) if linkedin else None),
            "github": link_map.get("github") or (self._normalise_url(github.group(0)) if github else None),
            "links": link_map,
        }

    @staticmethod
    def _normalise_url(value: str) -> Optional[str]:
        value = (value or "").strip().rstrip(".,;)")
        candidate = value if re.match(r"https?://", value, re.I) else f"https://{value}"
        parsed = urlparse(candidate)
        return candidate if parsed.scheme in {"http", "https"} and parsed.netloc else None

    def _profile_links(self, links: list[dict[str, str]]) -> dict[str, str]:
        """Map PDF annotation labels/hosts to known profile links; never infer a target."""
        profiles: dict[str, str] = {}
        for link in links:
            url = self._normalise_url(link.get("url", ""))
            if not url:
                continue
            hint = f"{link.get('label', '')} {url}".lower()
            for key, marker in (("linkedin", "linkedin.com/in/"), ("github", "github.com/"),
                                ("hackerrank", "hackerrank"), ("leetcode", "leetcode"), ("portfolio", "portfolio")):
                if marker in hint or key in hint:
                    profiles.setdefault(key, url)
        return profiles

    def _location_pattern(self, segments: list[str]) -> Optional[str]:
        """Fallback when NER finds no GPE: the small spaCy model often mis-tags short place names
        (e.g. 'Chennai' as ORG). A header segment shaped like 'City, Region' is accepted."""
        for seg in segments:
            parts = [p.strip() for p in seg.split(",")]
            if 2 <= len(parts) <= 3 and all(re.fullmatch(r"[A-Z][A-Za-z.]*(?: [A-Za-z.]+){0,2}", p) for p in parts):
                if not any(self.extractor.normalize(p) or heading_to_section(p) for p in parts):
                    return ", ".join(parts)
        return None

    def _name_like(self, line: str) -> bool:
        words = line.split()
        if not 2 <= len(words) <= 4 or any(ch.isdigit() or ch in "@/:" for ch in line):
            return False
        if not all(re.fullmatch(r"[A-Za-z][A-Za-z.'-]*", w) for w in words):
            return False
        lowered = {w.lower().strip(".") for w in words}
        if lowered & ROLE_WORDS or heading_to_section(line) or self.extractor.normalize(line):
            return False
        return True

    def _find_name(self, header_lines: list[str], hdocs: list) -> Optional[str]:
        for hdoc in hdocs[:5]:  # 1) spaCy NER
            for ent in hdoc.ents:
                if ent.label_ == "PERSON" and self._name_like(ent.text.strip()):
                    return self._tidy_name(ent.text.strip())
        for line in header_lines[:5]:  # 2) heuristic fallback: first name-shaped line
            if self._name_like(line):
                return self._tidy_name(line)
        return None

    @staticmethod
    def _tidy_name(name: str) -> str:
        return name.title() if name.isupper() else name

    def _organizations(self, doc) -> list[str]:
        orgs: list[str] = []
        for ent in doc.ents:
            text = ent.text.strip()
            # spaCy frequently tags tools (Docker, TensorFlow) as ORG; drop known skills.
            if (
                ent.label_ == "ORG" and len(text) > 2 and "\n" not in text and not text.isupper()
                and not self.extractor.normalize(text) and not self._find_degree(text)
                and not heading_to_section(text) and text not in orgs
            ):
                orgs.append(text)
        return orgs[:25]

    # ------------------------------------------------------------------- education
    @staticmethod
    def _find_degree(line: str) -> Optional[tuple[str, int, Optional[str]]]:
        for pattern, level in _DEGREE_PATTERNS:
            m = pattern.search(line)
            if m:
                chunk = re.split(r"\s[-–—]\s|,|\||\(", line[m.start():])[0].strip()
                field = None
                fm = re.search(r"\bin\s+([A-Za-z&][A-Za-z &]+)$", chunk)
                if fm:
                    field = fm.group(1).strip()
                return chunk, level, field
        return None

    def _parse_education(self, section: str) -> list[dict]:
        lines = [strip_bullet(l) for l in section.split("\n") if l.strip()]
        starts = [i for i, l in enumerate(lines) if self._find_degree(l)]
        entries: list[dict] = []
        if starts:
            bounds = starts + [len(lines)]
            for idx, start in enumerate(starts):
                block = lines[start:min(bounds[idx + 1], start + 4)]
                # the institution often sits on the line *before* the degree
                if start > 0 and start - 1 not in starts and INSTITUTION_RE.search(lines[start - 1]) and idx == 0:
                    block = [lines[start - 1]] + block
                entries.append(self._education_entry(block))
        else:  # no recognised degree: keep institution lines so information is not lost
            for l in lines:
                if INSTITUTION_RE.search(l):
                    entries.append(self._education_entry([l]))
        return entries

    def _education_entry(self, block: list[str]) -> dict:
        text = " | ".join(block)
        degree = level = field = None
        for line in block:
            found = self._find_degree(line)
            if found:
                degree, lvl, field = found
                level = LEVEL_NAMES[lvl]
                break
        institution = None
        for line in block:
            for part in _SEP_RE.split(line):
                if INSTITUTION_RE.search(part) and not self._find_degree(part):
                    institution = part.strip(" ,.-")
                    break
            if institution:
                break
        if not institution:
            org = next((e.text for e in self.nlp(text).ents if e.label_ == "ORG"), None)
            institution = org
        location = None
        for line in block:
            m = re.search(r"(?:\||,| - )\s*([A-Z][A-Za-z .'-]+,\s*[A-Z][A-Za-z .'-]+)\s*$", line)
            if m:
                location = m.group(1).strip()
                break
        years = [int(m.group(0)) for m in YEAR_RE.finditer(text)]
        grade_m = re.search(r"(?:CGPA|GPA|Percentage|Grade)\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?\s*(?:/\s*\d+(?:\.\d+)?|%)?)", text, re.I)
        if not grade_m:
            grade_m = re.search(r"([0-9]{2}(?:\.[0-9]+)?\s*%)", text)
        return {
            "degree": degree,
            "level": level,
            "field_of_study": field,
            "institution": institution,
            "location": location,
            "start_year": min(years) if len(years) > 1 else None,
            "end_year": max(years) if years else None,
            "grade": re.sub(r"\s+", "", grade_m.group(1)) if grade_m else None,
        }

    # ------------------------------------------------------------------ experience
    def _parse_experience(self, section: str) -> list[dict]:
        entries: list[dict] = []
        cur: Optional[dict] = None
        for raw in section.split("\n"):
            line = raw.strip()
            if not line:
                continue
            bullet = is_bullet(line)
            m = None if bullet else DATE_RANGE_RE.search(line)
            if m:
                header_rest = (line[:m.start()] + " " + line[m.end():]).strip(" -–—|,()")
                if cur and not cur["start_date"] and not cur["bullets"]:
                    cur["start_date"], cur["end_date"] = m.group(1), m.group(2)
                    cur["header"] = (cur["header"] + " | " + header_rest).strip(" |")
                else:
                    cur = {"header": header_rest, "start_date": m.group(1), "end_date": m.group(2), "bullets": []}
                    entries.append(cur)
            elif bullet:
                if cur is None:
                    cur = {"header": "", "start_date": None, "end_date": None, "bullets": []}
                    entries.append(cur)
                cur["bullets"].append(strip_bullet(line))
            elif cur is None or cur["bullets"]:
                cur = {"header": line, "start_date": None, "end_date": None, "bullets": []}
                entries.append(cur)
            else:  # continuation text (description paragraph) under the current header
                cur["bullets"].append(line) if cur["start_date"] else cur.__setitem__(
                    "header", (cur["header"] + " | " + line).strip(" |"))
        return [self._experience_entry(e) for e in entries]

    def _experience_entry(self, e: dict) -> dict:
        title, company, location = self._split_header(e["header"])
        description = "\n".join(e["bullets"])
        dur = duration_months(e["start_date"] or "", e["end_date"] or "") if e["start_date"] else None
        return {
            "title": title,
            "company": company,
            "location": location,
            "start_date": e["start_date"],
            "end_date": e["end_date"],
            "duration_months": dur[1] if dur else None,
            "description": description,
            "skills": sorted({n for n, _, _ in self.extractor.find_in_text(description + " " + e["header"])}),
        }

    def _split_header(self, header: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
        parts = [p.strip(" .") for p in _SEP_RE.split(header) if p and p.strip(" .")]
        if not parts:
            return None, None, None
        hdoc = self.nlp(header)
        orgs = [e.text for e in hdoc.ents if e.label_ == "ORG"]
        gpes = [e.text for e in hdoc.ents if e.label_ in {"GPE", "LOC"}]
        title = next((p for p in parts if {w.lower() for w in p.split()} & ROLE_WORDS), None)
        company = next((p for p in parts if p != title and (COMPANY_RE.search(p) or any(o in p for o in orgs))), None)
        location = next((p for p in parts if p not in (title, company) and any(g in p for g in gpes)), None)
        if company is None:
            company = next((p for p in parts if p not in (title, location)), None)
        if title is None:
            title = next((p for p in parts if p not in (company, location)), None)
        return title, company, location

    # -------------------------------------------------------------------- projects
    def _parse_projects(self, section: str) -> list[dict]:
        entries: list[dict] = []
        cur: Optional[dict] = None
        for raw in section.split("\n"):
            line = raw.strip()
            if not line:
                continue
            if is_bullet(line):
                if cur is None:
                    cur = {"title": "Untitled project", "lines": []}
                    entries.append(cur)
                cur["lines"].append(strip_bullet(line))
                continue
            looks_like_title = len(line.split()) <= 10 and not line.endswith(".")
            if cur is None or (cur["lines"] and looks_like_title):
                cur = {"title": line, "lines": []}
                entries.append(cur)
            else:
                cur["lines"].append(line)
        result = []
        for e in entries:
            title = re.split(r"\s\|\s|\s[-–—]\s|\(", e["title"])[0].strip() or e["title"]
            body = "\n".join(e["lines"])
            techs = sorted({n for n, _, _ in self.extractor.find_in_text(e["title"] + " " + body)
                            if self.extractor.is_technical(n)})
            result.append({"title": title[:255], "description": body, "technologies": techs})
        return result

    # ------------------------------------------------------------ certifications
    def _parse_certifications(self, section: str) -> list[dict]:
        certs = []
        for raw in section.split("\n"):
            line = strip_bullet(raw)
            if len(line) < 4:
                continue
            if self._is_achievement(line):
                continue
            years = [int(m.group(0)) for m in YEAR_RE.finditer(line)]
            issuer = next((i for i in ISSUERS if re.search(rf"\b{re.escape(i)}\b", line, re.I)), None)
            parts = [p.strip() for p in _SEP_RE.split(line) if p.strip()]
            name = line
            if len(parts) > 1:
                non_meta = [p for p in parts if not YEAR_RE.fullmatch(p.strip(" ()")) and not re.fullmatch(rf"{_MONTH}\s+\d{{4}}", p, re.I)]
                name = max(non_meta, key=len) if non_meta else line
            certs.append({"name": name.strip()[:255], "issuer": issuer, "year": max(years) if years else None})
        return certs

    @staticmethod
    def _is_achievement(line: str) -> bool:
        return bool(re.search(r"\b(hackathon|hackfest|winner|finalist|runner[- ]?up|award|medal|placed|ranked|champion|participat(?:ed|ion)|competition|tournament|sports?)\b", line, re.I))

    def _parse_achievements(self, section: str) -> list[str]:
        return [strip_bullet(line) for line in section.split("\n")
                if line.strip() and self._is_achievement(strip_bullet(line))]
