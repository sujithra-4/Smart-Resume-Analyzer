import logging
from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from tests.helpers import make_blank_pdf_bytes, make_docx_bytes, make_pdf_bytes, read_sample

RESUME, JOB = read_sample("resume_priya_raman.txt"), read_sample("job_ml_engineer.txt")
PDF = ("resume.pdf", None, "application/pdf")
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def upload(client, data, name="resume.pdf", mime="application/pdf"):
    return client.post("/api/resumes/upload", files={"file": (name, data, mime)})


@pytest.fixture()
def resume_id(auth_client):
    r = upload(auth_client, make_pdf_bytes(RESUME))
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture()
def job_id(auth_client):
    r = auth_client.post("/api/jobs/analyze", json={"title": "ML Engineer", "description": JOB})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ------------------------------------------------------------------ upload
def test_health_endpoint(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["database"] == "ok"


def test_upload_pdf_returns_structured_profile(auth_client):
    r = upload(auth_client, make_pdf_bytes(RESUME))
    assert r.status_code == 201
    body = r.json()
    assert body["personal_information"]["name"] == "Priya Raman"
    assert {"Python", "FastAPI"} <= {s["name"] for s in body["skills"]}
    assert all(s["confidence_type"] == "heuristic" for s in body["skills"])
    assert body["education"] and body["experience"] and len(body["projects"]) == 2 and body["certifications"]
    assert "skills" in body["sections_detected"] and 0 <= body["quality_score"] <= 100
    assert "ATS" in body["quality_note"]
    assert "stored_filename" not in body and "raw_text" not in body  # no server paths / internals exposed


def test_upload_docx(auth_client):
    r = upload(auth_client, make_docx_bytes(RESUME), "cv.docx", DOCX_MIME)
    assert r.status_code == 201 and r.json()["file_type"] == "docx"


def test_stored_file_uses_server_generated_name(auth_client):
    import os
    r = upload(auth_client, make_pdf_bytes(RESUME), "../../evil name.pdf")
    assert r.status_code == 201 and r.json()["original_filename"] == "evil name.pdf"
    files = os.listdir(os.environ["UPLOAD_DIR"])
    assert files and all("evil" not in f for f in files)


@pytest.mark.parametrize("name,mime,data,status", [
    ("notes.txt", "text/plain", b"plain text resume", 415),
    ("resume.exe", "application/octet-stream", b"MZ....", 415),
    ("resume.pdf", "image/png", b"%PDF-1.4", 415),
    ("resume.pdf", "application/pdf", b"", 422),
    ("resume.pdf", "application/pdf", b"this is not a pdf", 422),
    ("resume.docx", DOCX_MIME, b"this is not a docx", 422),
    ("resume.pdf", "application/pdf", b"%PDF-1.4 truncated", 422),
    ("big.pdf", "application/pdf", b"%PDF-" + b"0" * (1_100_000), 413),
])
def test_invalid_uploads_return_clean_errors(auth_client, name, mime, data, status):
    r = upload(auth_client, data, name, mime)
    assert r.status_code == status
    assert isinstance(r.json()["detail"], str) and "Traceback" not in r.text


def test_pdf_with_no_text_returns_422(auth_client):
    r = upload(auth_client, make_blank_pdf_bytes())
    assert r.status_code == 422 and "OCR" in r.json()["detail"]


def test_empty_docx_returns_422(auth_client):
    r = upload(auth_client, make_docx_bytes(""), "empty.docx", DOCX_MIME)
    assert r.status_code == 422


def test_unsupported_message_matches_spec(auth_client):
    assert upload(auth_client, b"x", "a.txt", "text/plain").json()["detail"] == \
        "Unsupported file format. Please upload PDF or DOCX."


def test_failed_upload_leaves_no_files_or_rows(auth_client):
    import os
    d = os.environ["UPLOAD_DIR"]
    before = set(os.listdir(d)) if os.path.isdir(d) else set()
    assert upload(auth_client, b"not a pdf", "resume.pdf").status_code == 422
    after = set(os.listdir(d)) if os.path.isdir(d) else set()
    assert before == after  # rejected files are never written to disk
    assert auth_client.get("/api/resumes").json() == []


@pytest.mark.parametrize(("error_type", "status", "detail"), [
    (OperationalError, 503, "Database is unavailable. Please try again later."),
    (ProgrammingError, 500, "A database error occurred."),
])
def test_database_failure_rolls_back_and_removes_uploaded_file(
    auth_client, monkeypatch, caplog, error_type, status, detail
):
    import os

    upload_dir = os.environ["UPLOAD_DIR"]
    before = set(os.listdir(upload_dir)) if os.path.isdir(upload_dir) else set()

    def fail_commit(_session):
        raise error_type(
            "INSERT INTO resumes",
            {"raw_text": "private resume contents"},
            RuntimeError("private database details"),
        )

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", fail_commit)
        with caplog.at_level(logging.ERROR, logger="app.core.exceptions"):
            response = upload(auth_client, make_pdf_bytes(RESUME))

    assert response.status_code == status
    assert response.json() == {"detail": detail}
    assert f"{error_type.__name__} traceback:" in caplog.text
    assert "private resume contents" not in caplog.text
    assert "private database details" not in caplog.text
    after = set(os.listdir(upload_dir)) if os.path.isdir(upload_dir) else set()
    assert before == after
    assert auth_client.get("/api/resumes").json() == []


# ---------------------------------------------------------------- resumes CRUD
def test_list_get_delete_resume(auth_client, resume_id):
    lst = auth_client.get("/api/resumes").json()
    assert len(lst) == 1 and lst[0]["skill_count"] > 5 and lst[0]["candidate_name"] == "Priya Raman"
    assert auth_client.get(f"/api/resumes/{resume_id}").status_code == 200
    assert auth_client.delete(f"/api/resumes/{resume_id}").status_code == 204
    assert auth_client.get(f"/api/resumes/{resume_id}").status_code == 404
    assert auth_client.get("/api/resumes").json() == []


def test_users_cannot_see_each_others_data(client, auth_client, resume_id, job_id):
    other = client.post("/api/auth/register", json={"email": "other@example.com", "full_name": "Other Person",
                                                    "password": "Passw0rd999"})
    assert other.status_code == 201
    tok = client.post("/api/auth/login", json={"email": "other@example.com", "password": "Passw0rd999"}).json()
    h = {"Authorization": f"Bearer {tok['access_token']}"}
    assert client.get(f"/api/resumes/{resume_id}", headers=h).status_code == 404
    assert client.delete(f"/api/resumes/{resume_id}", headers=h).status_code == 404
    assert client.get(f"/api/jobs/{job_id}", headers=h).status_code == 404
    assert client.post("/api/matching/analyze", json={"resume_id": resume_id, "job_id": job_id},
                       headers=h).status_code == 404
    assert client.get("/api/resumes", headers=h).json() == []


# ------------------------------------------------------------------------ jobs
def test_job_analysis_response(auth_client, job_id):
    r = auth_client.get(f"/api/jobs/{job_id}")
    assert r.status_code == 200
    a = r.json()["analysis"]
    assert "Python" in a["required_skills"] and "Docker" in a["preferred_skills"]
    assert not any(k.startswith("_") for k in a)


@pytest.mark.parametrize("payload", [
    {"description": "too short"},
    {"description": "x" * 60},  # long enough in characters, but not 10 words
    {},
    {"description": "word " * 5000},
])
def test_invalid_job_description(auth_client, payload):
    assert auth_client.post("/api/jobs/analyze", json=payload).status_code == 422


def test_unknown_job_404(auth_client):
    assert auth_client.get("/api/jobs/9999").status_code == 404


# -------------------------------------------------------------------- matching
def test_matching_full_flow(auth_client, resume_id, job_id):
    r = auth_client.post("/api/matching/analyze", json={"resume_id": resume_id, "job_id": job_id})
    assert r.status_code == 201, r.text
    a = r.json()
    cs = a["component_scores"]
    assert set(cs) == {"skills", "semantic", "experience", "education", "structure"}
    expected = (0.40 * cs["skills"] + 0.30 * cs["semantic"] + 0.15 * cs["experience"]
                + 0.10 * cs["education"] + 0.05 * cs["structure"])
    assert a["overall_score"] == pytest.approx(expected, abs=0.1)  # score is computed, not hard-coded
    assert 0 <= a["semantic_similarity"] <= 1
    sk = a["details"]["skills"]
    assert "Python" in sk["matched_skills"] and "Kubernetes" in sk["missing_skills"]
    assert "Terraform" in sk["skill_gaps"]["optional"]
    assert a["recommendations"] and all(x["reason"] for x in a["recommendations"])
    assert "not a prediction of hiring" in a["disclaimer"]
    assert a["resume_name"] == "resume.pdf" and a["job_title"] == "ML Engineer"

    got = auth_client.get(f"/api/matching/{a['id']}")
    assert got.status_code == 200 and got.json()["overall_score"] == a["overall_score"]


def test_matching_is_deterministic_and_reuses_cached_embeddings(auth_client, resume_id, job_id):
    p = {"resume_id": resume_id, "job_id": job_id}
    a1 = auth_client.post("/api/matching/analyze", json=p).json()
    a2 = auth_client.post("/api/matching/analyze", json=p).json()
    assert a1["id"] != a2["id"] and a1["overall_score"] == a2["overall_score"]
    assert a1["semantic_similarity"] == a2["semantic_similarity"]


def test_better_resume_scores_higher_than_unrelated_one(auth_client, job_id):
    good = upload(auth_client, make_pdf_bytes(RESUME)).json()["id"]
    other_text = ("Rahul Menon\nKochi, Kerala | rahul.m@example.com | +91 90000 11111\n\nSKILLS\nPhotoshop, "
                  "Illustrator, Figma, Communication\n\nEXPERIENCE\nGraphic Designer - Pixel Studio\nJan 2023 - Dec 2023\n"
                  "- Designed posters, brochures and social media graphics for retail clients\n\nEDUCATION\n"
                  "Bachelor of Arts in Design\nSample Arts College\n2019 - 2022")
    bad = upload(auth_client, make_pdf_bytes(other_text)).json()["id"]
    s_good = auth_client.post("/api/matching/analyze", json={"resume_id": good, "job_id": job_id}).json()
    s_bad = auth_client.post("/api/matching/analyze", json={"resume_id": bad, "job_id": job_id}).json()
    assert s_good["overall_score"] > s_bad["overall_score"] + 20
    assert s_good["semantic_similarity"] > s_bad["semantic_similarity"]


def test_matching_unknown_ids_404_and_validation(auth_client, resume_id, job_id):
    assert auth_client.post("/api/matching/analyze", json={"resume_id": 999, "job_id": job_id}).status_code == 404
    assert auth_client.post("/api/matching/analyze", json={"resume_id": resume_id, "job_id": 999}).status_code == 404
    assert auth_client.post("/api/matching/analyze", json={"resume_id": resume_id}).status_code == 422
    assert auth_client.get("/api/matching/12345").status_code == 404


def test_deleting_resume_removes_its_analyses(auth_client, resume_id, job_id):
    auth_client.post("/api/matching/analyze", json={"resume_id": resume_id, "job_id": job_id})
    auth_client.delete(f"/api/resumes/{resume_id}")
    assert auth_client.get("/api/matching").json() == []


def test_model_failure_returns_503_not_stack_trace(auth_client, resume_id, job_id):
    from app.api.deps import get_embedder
    from app.core.exceptions import ModelUnavailableError
    from app.main import app

    def broken():
        raise ModelUnavailableError()

    app.dependency_overrides[get_embedder] = broken
    r = auth_client.post("/api/matching/analyze", json={"resume_id": resume_id, "job_id": job_id})
    assert r.status_code == 503 and "model" in r.json()["detail"].lower()


# ------------------------------------------------------------------- dashboard
def test_dashboard_empty_and_populated(auth_client, resume_id, job_id):
    d = auth_client.get("/api/dashboard").json()
    assert d["counts"] == {"resumes": 1, "jobs": 1, "analyses": 0} and d["latest_analysis"] is None
    auth_client.post("/api/matching/analyze", json={"resume_id": resume_id, "job_id": job_id})
    d = auth_client.get("/api/dashboard").json()
    assert d["counts"]["analyses"] == 1
    la = d["latest_analysis"]
    assert la["matched_skills"] and la["missing_skills"] and la["component_scores"]
    assert d["history"] and d["skills_by_category"] and d["top_missing_skills"]
    assert "not hiring probabilities" in d["disclaimer"]


def test_history_list(auth_client, resume_id, job_id):
    auth_client.post("/api/matching/analyze", json={"resume_id": resume_id, "job_id": job_id})
    h = auth_client.get("/api/matching").json()
    assert len(h) == 1 and h[0]["job_title"] == "ML Engineer" and "overall_score" in h[0]


def test_validation_error_format_is_clean(client):
    r = client.post("/api/auth/login", json={})
    assert r.status_code == 422 and isinstance(r.json()["detail"], str) and r.json()["errors"]


def test_swagger_and_redoc_available(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert client.get("/openapi.json").status_code == 200
