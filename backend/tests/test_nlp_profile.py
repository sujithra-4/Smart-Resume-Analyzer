from app.services.nlp_processor import duration_months, merged_months
from app.services.section_detector import detect_sections, heading_to_section
from tests.helpers import read_sample

RESUME = read_sample("resume_priya_raman.txt")


def test_section_detection_finds_all_sections():
    r = detect_sections(RESUME)
    assert r.order == ["summary", "education", "skills", "experience", "projects", "certifications", "achievements"]
    assert "Priya Raman" in r.header and "Python" in r.sections["skills"]


def test_heading_variants():
    assert heading_to_section("TECHNICAL SKILLS") == "skills"
    assert heading_to_section("Work Experience:") == "experience"
    assert heading_to_section("Awards & Achievements") == "achievements"
    assert heading_to_section("  • EDUCATION PROFILE: ") == "education"
    assert heading_to_section("ACADEMIC DETAILS") == "education"
    assert heading_to_section("CERTIFICATIONS & ACHIEVEMENTS") == "certifications"
    assert heading_to_section("EXTRA-CURRICULAR ACTIVITIES") == "achievements"
    assert heading_to_section("I have skills in many things and more") is None


def test_personal_information(processor):
    p = processor.parse(RESUME)["personal_information"]
    assert p["name"] == "Priya Raman"
    assert p["email"] == "priya.raman@example.com"
    assert p["phone"].replace(" ", "") == "+919876543210"
    assert p["location"] == "Chennai, Tamil Nadu"
    assert "github.com" in p["github"]


def test_profile_structure_matches_spec(processor):
    profile = processor.parse(RESUME)
    for key in ["personal_information", "summary", "skills", "education", "experience", "projects",
                "certifications", "achievements"]:
        assert key in profile


def test_education_entry(processor):
    edu = processor.parse(RESUME)["education"]
    assert len(edu) == 1
    assert edu[0]["level"] == "bachelor"
    assert edu[0]["field_of_study"] == "Computer Science and Engineering"
    assert edu[0]["institution"] == "Example Institute of Technology"
    assert (edu[0]["start_year"], edu[0]["end_year"]) == (2022, 2026)
    assert edu[0]["grade"] == "8.7/10"


def test_multiline_education_and_combined_certifications_achievements(processor):
    text = """EDUCATION PROFILE
Bachelor of Technology
in Computer Science
Example College, Chennai, Tamil Nadu | 2020 - 2024 | CGPA: 8.4/10
Higher Secondary Certificate | Example School | 2018 - 2020 | 92%
Secondary School Leaving Certificate | Example School | 2018 | Percentage: 95%
CERTIFICATIONS & ACHIEVEMENTS
- Python for Data Science - Coursera - 2024
- Cloud Fundamentals - Microsoft - 2023
- Participated in HackFest 2024
EXTRA-CURRICULAR ACTIVITIES
- Won gold medal in inter-college badminton tournament
"""
    profile = processor.parse(text)
    assert len(profile["education"]) == 3
    assert profile["education"][0]["level"] == "bachelor"
    assert profile["education"][0]["grade"] == "8.4/10"
    assert {c["issuer"] for c in profile["certifications"]} >= {"Coursera", "Microsoft"}
    assert any("HackFest" in item for item in profile["achievements"])
    assert any("badminton" in item for item in profile["achievements"])


def test_experience_entry(processor):
    p = processor.parse(RESUME)
    exp = p["experience"]
    assert len(exp) == 1
    assert exp[0]["title"] == "Software Engineering Intern"
    assert "Acme Technologies" in exp[0]["company"]
    assert exp[0]["duration_months"] == 3
    assert {"FastAPI", "PostgreSQL", "Redis"} <= set(exp[0]["skills"])
    assert p["total_experience_months"] == 3


def test_projects_and_certifications(processor):
    p = processor.parse(RESUME)
    assert [x["title"] for x in p["projects"]] == ["Smart Notes Classifier", "Campus Event Portal"]
    assert {"React", "Node.js", "MongoDB"} <= set(p["projects"][1]["technologies"])
    names = [c["name"] for c in p["certifications"]]
    assert any("Azure AI Fundamentals" in n for n in names)
    assert next(c for c in p["certifications"] if "Coursera" == (c["issuer"] or ""))["year"] == 2024
    assert len(p["achievements"]) == 2


def test_skills_detected_and_no_fabrication(processor):
    names = {s["name"] for s in processor.parse(RESUME)["skills"]}
    assert {"Python", "FastAPI", "PostgreSQL", "JavaScript", "Machine Learning", "Docker"} <= names
    assert not names & {"Kubernetes", "PyTorch", "AWS", "Django"}  # never in the resume


def test_nlp_stats_present(processor):
    stats = processor.parse(RESUME)["nlp_stats"]
    assert stats["tokens"] > 100 and stats["sentences"] >= 1 and stats["word_count"] > 100


def test_unstructured_text_still_parses(processor):
    p = processor.parse("Just some free text about Python and Docker with an email a@b.com and no headings at all.")
    assert {"Python", "Docker"} <= {s["name"] for s in p["skills"]}
    assert p["personal_information"]["email"] == "a@b.com"


def test_duration_and_overlap_maths():
    assert duration_months("Jun 2025", "Aug 2025") == (2025 * 12 + 5, 3)
    assert duration_months("2022", "2024")[1] == 24
    assert merged_months([(0, 12), (6, 12)]) == 18  # overlapping months are counted once
    assert merged_months([(0, 3), (10, 3)]) == 6
