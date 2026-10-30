# Smart Resume Analyzer & Job Matching System

An AI/NLP web application that reads a resume (PDF or DOCX), extracts structured information with spaCy, compares it
with a job description using Sentence-Transformer embeddings, and explains the result: matched and missing skills,
a transparent match score, resume quality issues and recommendations that say *why* they were made.

> **Important:** the match score is a *Resume-Job Match Score* built from semantic similarity and skill overlap.
> It is **not** a hiring probability and **not** a real ATS prediction.

## Project overview
Stack: React + Vite + Tailwind + Recharts (frontend), FastAPI + SQLAlchemy + Alembic + PostgreSQL (backend),
spaCy + `sentence-transformers/all-MiniLM-L6-v2` + scikit-learn/NumPy (AI), PyMuPDF + python-docx (documents),
JWT auth, Docker Compose. The core system runs locally with **no paid APIs**.

## Problem statement
Students rewrite resumes without knowing how they read against a specific job. Keyword counters miss paraphrases
("built web services" vs "REST APIs") and do not explain themselves. This project combines dictionary-based skill
matching (precise, explainable) with embeddings (handles wording differences) and shows both.

## Objectives
Register/login; upload and parse resumes; extract profile, skills and sections; analyse job descriptions; compute
semantic similarity; find matched, missing and additional skills; classify skill gaps; analyse resume quality;
generate explainable recommendations; store history; expose REST APIs; run in Docker; ship tests and an evaluation script.

## Features
- PDF/DOCX upload with extension, MIME, size, signature, empty and corrupted-file validation
- spaCy tokenisation, sentence segmentation and NER (name, location, organisations) plus dictionary skill matching
- Section detection (summary, objective, education, skills, experience, projects, certifications, achievements, publications)
- Education, experience (with date-based duration), projects and certifications extraction
- Job description analysis: required / preferred skills, years of experience, education, responsibilities, keywords
- Embeddings for the full documents, resume sections and individual job requirement lines
- Skill gap analysis (critical / important / optional) taken from the wording of the job description
- Rule-based Resume Quality Analysis
- Explainable recommendations and a transparent weighted score
- React dashboard with charts, history, protected routes, loading/error/success states

## System architecture
```
React (Vite) ──REST/JSON──▶ FastAPI ──▶ services ──▶ PostgreSQL
                              │
   routes (thin) ─────────────┤  document_processor ─ pdf_parser / docx_parser
                              │  nlp_processor ─ section_detector ─ skill_extractor
                              │  job_analyzer
                              │  embedding_service (model loaded once)
                              │  matching_service ─ quality_analyzer ─ recommendation_engine
                              └─ analysis_service (orchestration + persistence)
```

## AI pipeline
```
Upload → validate → extract text → clean → spaCy (tokens, sentences, NER) → sections
       → skills (PhraseMatcher + normalisation) → education / experience / projects / certifications
Job text → job analysis (context-aware skills, years, education, requirements)
Embeddings (MiniLM, chunked + mean-pooled) → cosine similarity (document, sections, requirement lines)
Skill matching → skill gaps → quality analysis → recommendations → weighted score → stored analysis
```

## Technology stack
See the overview. Python 3.11+, Node 18+ (20 in Docker), PostgreSQL 16.

## Folder structure
```
smart-resume-analyzer/
├── backend/
│   ├── app/{main.py, api/, core/, database/, models/, schemas/, services/, utils/}
│   ├── alembic/            migrations (0001_initial_schema)
│   ├── evaluation/         evaluate_models.py, sample_dataset.json, README.md
│   ├── sample_data/        fictional resume + job description, PDF/DOCX generator, custom skills example
│   ├── tests/              pytest suite
│   ├── requirements.txt, requirements-dev.txt, Dockerfile
├── frontend/               src/{components,pages,services,hooks,utils}, Dockerfile, nginx.conf
├── docker-compose.yml, .env.example, .gitignore, LICENSE, README.md
```

## Installation
**Manual installation prerequisites (without Docker):** Python 3.11+, Node 18+, and PostgreSQL 14+.

## Environment variables
Copy `.env.example` to `.env` (project root; the backend also reads `backend/.env`).

| Variable | Purpose |
|----------|---------|
| `POSTGRES_USER/PASSWORD/DB/HOST/PORT` | database connection (or set `DATABASE_URL` directly) |
| `JWT_SECRET_KEY` | **required**, 16+ chars. Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | token lifetime (default 60) |
| `CORS_ORIGINS` | allowed browser origins, comma separated |
| `MAX_UPLOAD_MB` | upload limit (default 5) |
| `PRELOAD_MODELS` | load spaCy + transformer at startup |
| `CUSTOM_SKILLS_PATH` | JSON file extending the skill dictionary |
| `VITE_API_URL` | backend URL as seen from the browser (frontend build/dev) |

The app refuses to start without `JWT_SECRET_KEY`. Nothing secret is hard-coded.

## PostgreSQL setup
```sql
CREATE USER resume_user WITH PASSWORD 'your-password';
CREATE DATABASE resume_analyzer OWNER resume_user;
```
Put the same values in `.env`. Docker Compose creates the database for you from the same variables.

## Running without Docker
```bash
cp .env.example .env            # then edit passwords and JWT_SECRET_KEY

# Backend
cd backend
python -m venv venv
venv\Scripts\activate           # Windows   (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
python -m spacy download en_core_web_sm
alembic upgrade head            # create tables
uvicorn app.main:app --reload

# Frontend (new terminal)
cd frontend
cp .env.example .env
npm install
npm run dev
```
The transformer model downloads automatically on first use (about 90 MB) and is then loaded once and reused.
If the spaCy model is missing, the app falls back to a blank English pipeline (NER fields become less accurate)
and logs a warning.

## Running with Docker
Install Docker Desktop and make sure its Linux engine is running. You do not need to install Python, Node.js,
PostgreSQL, or the project's Python and Node.js dependencies separately; the Docker images provide the runtimes
and install the project dependencies.

```bash
cp .env.example .env            # set POSTGRES_PASSWORD and JWT_SECRET_KEY
docker compose up --build
```
The backend image downloads the spaCy and transformer models at build time (CPU-only PyTorch), runs
`alembic upgrade head`, then starts Uvicorn. All three services have health checks.

| URL | What |
|-----|------|
| http://localhost:5173 | Frontend |
| http://localhost:8000 | Backend |
| http://localhost:8000/docs | Swagger UI (use *Authorize* with your email + password) |
| http://localhost:8000/redoc | ReDoc |
| http://localhost:8000/api/health | Health (DB, spaCy, model status) |

## API documentation
Interactive docs are generated by FastAPI at `/docs` and `/redoc`.

| Method | Path | Notes |
|--------|------|-------|
| POST | `/api/auth/register`, `/api/auth/login` | JWT bearer token; `/api/auth/token` is the OAuth2 form variant for Swagger |
| GET | `/api/auth/me` | current user |
| POST | `/api/resumes/upload` | multipart `file`; returns the structured profile |
| GET / GET / DELETE | `/api/resumes`, `/api/resumes/{id}` | list, detail, delete |
| POST / GET | `/api/jobs/analyze`, `/api/jobs/{id}` (+ `GET /api/jobs`) | job description analysis |
| POST / GET | `/api/matching/analyze`, `/api/matching/{id}` (+ `GET /api/matching`) | run and read analyses |
| GET | `/api/dashboard`, `/api/health` | aggregates; health |

Errors are JSON, e.g. `{"detail": "Unsupported file format. Please upload PDF or DOCX."}`. Status codes used:
201, 204, 401, 404, 409, 413, 415, 422, 503. Stack traces are never returned.

## AI methodology
- **NLP / NER (spaCy `en_core_web_sm`)**: tokenises and segments sentences; NER finds PERSON, GPE and ORG entities.
  Tool names that spaCy mislabels as ORG (Docker, TensorFlow) are filtered out. Small-model NER misses some place names,
  so a documented "City, Region" fallback is used. Regex is used only for e-mail, phone, dates and degree names.
- **Skill extraction**: a category → canonical → aliases dictionary (`skills_data.py`) compiled into spaCy
  `PhraseMatcher`s. Matching is token-aligned (Java never matches inside JavaScript), longest match wins, and short or
  ambiguous aliases (C, R, Go, REST, Excel) are case-sensitive. Aliases normalise (`JS → JavaScript`, `Postgres → PostgreSQL`).
  **Confidence is a heuristic**, not a probability: base 0.60, +0.20 listed in a Skills section, +0.10 evidenced in
  experience/projects, +0.05 repeated, +0.05 usage cue, capped at 0.95. Every skill carries `confidence_type: "heuristic"`.
- **Sentence Transformers / embeddings**: `all-MiniLM-L6-v2` maps text to 384-dimensional unit vectors. It truncates at
  about 256 word-pieces, so documents are split into overlapping 180-word chunks, embedded, and mean-pooled.
  The model is a lazy, thread-safe singleton; document and section vectors are cached in the database.
- **Cosine similarity**: dot product of unit vectors. Computed for full resume vs job, each resume section vs job, and each
  job requirement line vs its best-matching resume line (requirement coverage; threshold 0.45 is a tunable heuristic).
- **Skill matching**: normalised resume skills vs normalised job skills → matched / missing / additional.
- **Skill gap analysis**: priority comes only from the job text. *Critical* = in a requirements section or a "must/required"
  clause. *Important* = preferred / nice-to-have, or only in responsibilities. *Optional* = mentioned elsewhere (for example
  the company blurb). A clause like "Strong Python and Docker is a plus" is split so Python is critical and Docker important.
- **Resume Quality Analysis**: rule checklist with fixed documented penalties (missing contact/sections, length,
  weak projects, missing metrics, repeated words, poor organisation, job-specific missing skills). Not an ATS prediction.
- **Recommendation engine**: every recommendation is built from a concrete finding, is worded conditionally
  ("If you have Docker experience…") and includes a `reason`. It never adds skills, projects or experience.
- **Transparent score**:
  `overall = 0.40·skills + 0.30·semantic + 0.15·experience + 0.10·education + 0.05·structure`.
  Skills: weighted coverage (required 1.0, preferred/responsibility 0.5, other 0.25). Semantic: 100 × cosine similarity
  (not rescaled). Experience: 50% years fit + 50% evidence that matched skills appear in experience/projects. Education:
  degree-level fit (a degree in progress counts). Structure: share of eight structural checks. Component scores are shown separately.

## Evaluation
`backend/evaluation/evaluate_models.py` computes precision, recall and F1 for skill extraction and skill matching, and
ranking metrics for semantic matching, from `sample_dataset.json` (small, fictional, hand-labelled).
Run it yourself: `cd backend && python evaluation/evaluate_models.py`.

**Results:** none are recorded in this README on purpose. Run the script on your machine and paste your own output here.
Because the dataset and the skill dictionary were written by the same person, expect optimistic skill-extraction scores;
extend the dataset with real examples before drawing conclusions. See `backend/evaluation/README.md`.

## Testing
```bash
cd backend
pip install -r requirements-dev.txt
pytest                    # unit + API tests (SQLite in a temp dir, no network)
RUN_MODEL_TESTS=1 pytest  # also runs the test that needs the real transformer (downloads the model)
```
Tests cover PDF/DOCX extraction, skill extraction and normalisation, job analysis, semantic matching maths, score
calculation, authentication, upload validation (invalid, empty, unsupported, oversized, corrupted), user data isolation
and all endpoints. API tests inject a small deterministic bag-of-words encoder so the suite runs offline; the transformer
itself is exercised only by the opt-in test above.

| Page | Screenshot |
|------|-----------|
| Dashboard | `docs/dashboard.png` *(placeholder)* |
| Resume details | `docs/resume.png` *(placeholder)* |
| Match report | `docs/match.png` *(placeholder)* |

## Future enhancements
- Azure AI services (see next section), OCR for scanned PDFs, RAG over job postings, a GenAI career assistant
  (grounded in the extracted profile, never inventing experience), Azure deployment, larger evaluation sets with
  inter-annotator agreement, a skill ontology (ESCO / O*NET) instead of a hand-written dictionary.

## Responsible AI
- The match score is a similarity measure, **not** hiring probability.
- Recommendations are suggestions; review them yourself and add only skills and experience you really have.
- The system never fabricates candidate information; recommendations are conditional and cite their reason.
- It does not use protected characteristics (the model sees text only; name, gender, age, photo and similar are not scored).
  Embedding models can still carry biases from their training data, so this tool must not be used to screen candidates automatically.
- Extraction can be wrong (layouts, scanned files, unusual headings). Always verify extracted details.
- Resumes contain personal data: files and text are stored per user, never logged, and can be deleted.

## Security notes
bcrypt (SHA-256 pre-hashed) passwords; JWT with expiry; no secrets in code; strict upload validation (extension, MIME,
magic bytes, size, server-generated storage names, no paths in responses); CORS allow-list; ORM-only queries; per-user
data isolation; generic auth errors with equalised timing; clean error responses. The token is kept in `localStorage`
(trade-off explained in `frontend/src/hooks/useAuth.jsx`); httpOnly cookies are a stronger production option.

