# Data Ingestion

## Overview

Data ingestion covers how external content — uploaded essay files, LMS roster imports, and LLM responses — enters the system, gets validated, and becomes structured data. Getting this layer right prevents bad data from propagating into grades, profiles, and analytics.

---

## 1. Essay File Ingestion

### Supported Input Types
| Type | Method | Notes |
|---|---|---|
| PDF | File upload | Text extraction via `pdfplumber` |
| DOCX | File upload | Text extraction via `python-docx` |
| TXT | File upload | Read directly |
| Plain text | Paste / API field | Used as-is |

### Extraction Pipeline

```
Raw file received
       │
       ▼
Validate file type (MIME + extension check)
Validate file size (max 10MB per file)
       │
       ▼
Store original file → S3 (before any processing)
       │
       ▼
Extract text:
  PDF  → pdfplumber → raw text
  DOCX → python-docx → raw text
  TXT  → read directly
       │
       ▼
Normalize text:
  - Strip excessive whitespace and blank lines
  - Normalize Unicode (NFC normalization)
  - Remove non-printable characters
  - Detect and flag if extracted text is suspiciously short
    (< 50 words → flag as potential extraction failure)
       │
       ▼
Compute metadata:
  - word_count
  - character_count
  - estimated_reading_time
       │
       ▼
Attempt student auto-assignment (see below)
       │
       ▼
Create EssayVersion record with extracted content
```

### Extraction Failure Handling
- If text extraction fails entirely (corrupt file, image-only PDF), the essay is created with `status: failed` and a clear error message
- The original file is preserved in S3 regardless — teacher can download and submit manually
- Scanned PDFs with no selectable text are detected and flagged: "Text extraction may be unreliable — please verify the essay content before grading"

### Student Auto-Assignment
The system attempts to match each uploaded essay to a student in the class roster using these signals in priority order:

1. **Filename match** — filename contains a name that matches a student on the roster (fuzzy match, threshold: 0.85)
2. **Document metadata** — DOCX author field or PDF metadata contains a student name
3. **Essay header** — first 200 characters contain a recognizable student name pattern (e.g., "Jane Smith" or "Smith, Jane")

Rules:
- Auto-assign only when a single student matches with confidence above the threshold
- If two or more students could match, flag for manual review — do not guess
- If no match is found, essay status is `unassigned` and appears in the unassigned queue
- All auto-assignments are surfaced for teacher confirmation before grading proceeds

---

## 2. LMS Roster Import

### Google Classroom (Phase 2)
- Teacher authenticates via OAuth (read-only scope)
- API call: `GET /v1/courses/{courseId}/students`
- Each student record: `userId`, `profile.name.fullName`, `profile.emailAddress`
- System maps `userId` → `external_id` on the Student record for future syncs
- Duplicate detection: if a student with the same `external_id` already exists, update name — do not create duplicate
- New students in the LMS but not in the local roster are presented as a diff for teacher approval — not silently imported

### CSV Import
Expected columns (case-insensitive, whitespace-trimmed):
```
full_name (required)
external_id (optional — LMS ID for sync)
```
- Rows with missing `full_name` are skipped with a warning
- Duplicates (same name, same class) are flagged for teacher review
- Maximum 200 rows per import

---

## 3. LLM Response Ingestion

LLM responses for grading must be parsed into structured data reliably. The LLM is instructed to return JSON, but responses must be validated before writing to the database.

### Grading Response Schema (expected from LLM)
```json
{
  "criterion_scores": [
    {
      "criterion_id": "uuid",
      "score": 4,
      "justification": "The student presents a clear thesis in the opening paragraph...",
      "confidence": "high"
    }
  ],
  "summary_feedback": "This essay demonstrates strong organizational skills..."
}
```

### Validation Rules
- `criterion_scores` must contain one entry per criterion in the rubric snapshot — no missing, no extras
- Each `score` must be within the criterion's `min_score`–`max_score` range
- Each `justification` must be non-empty and at least 20 characters
- `confidence` must be one of: `high`, `medium`, `low`
- `summary_feedback` must be non-empty

### Failure Handling
| Failure | Response |
|---|---|
| JSON parse error | Retry once with a corrective prompt. If it fails again, mark essay as `failed` with `LLM_PARSE_ERROR`. |
| Missing criterion | Retry once. If still missing, mark criterion score as `null` with `confidence: low` and flag for teacher review. |
| Score out of range | Clamp to the valid range, set `confidence: low`, log the anomaly. |
| Empty justification | Retry once. If still empty, use placeholder "No justification provided." and flag. |

### Prompt Versioning
- All prompt templates are stored in `backend/app/llm/prompts/` as versioned Python modules
- Each `Grade` record stores the prompt version used (`prompt_version` field — add to data model)
- Prompt changes that could affect scoring require a version bump, not an in-place edit
- This enables reproducibility: any grade can be re-examined knowing exactly which prompt produced it

---

## 4. Skill Normalization

Student skill profiles aggregate scores across assignments that may use different rubric criteria names. A normalization layer maps raw criterion names to canonical skill dimensions.

### Canonical Skill Dimensions (Phase 1 — English Writing)
| Canonical Dimension | Example criterion names that map to it |
|---|---|
| `thesis` | "Thesis Statement", "Main Argument", "Central Claim", "Focus" |
| `evidence` | "Evidence Use", "Support", "Use of Textual Evidence", "Supporting Details" |
| `organization` | "Organization", "Structure", "Essay Structure", "Flow" |
| `analysis` | "Analysis", "Critical Thinking", "Depth of Analysis", "Commentary" |
| `mechanics` | "Grammar", "Mechanics", "Conventions", "Spelling and Grammar" |
| `voice` | "Voice", "Style", "Tone", "Word Choice" |

### Normalization Process
1. At grade-write time, each `RubricCriterion.name` is passed through the normalizer
2. Normalizer uses fuzzy string matching against the canonical dimension list
3. Match above threshold (0.80) → mapped to that dimension
4. No match → stored under `other` in the skill profile (does not affect canonical dimensions)
5. Unmapped criteria are logged — if a pattern emerges, add it to the mapping table

### Extensibility
The normalization mapping is stored as configuration (not hardcoded) so it can be extended for new subjects (social studies, science writing) in later phases without code changes.
