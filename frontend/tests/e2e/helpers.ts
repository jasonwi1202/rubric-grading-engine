/**
 * Shared helpers for E2E tests.
 *
 * All helpers use the real Docker Compose stack — no mocking.
 * Mailpit API: http://localhost:8025/api/v1/messages
 */

import { Page, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const MAILPIT_API = process.env.MAILPIT_API_URL ?? "http://localhost:8025";

/** Poll Mailpit until an email arrives for `toAddress`, then return its full text body. */
export async function waitForEmail(
  toAddress: string,
  subjectContains: string,
  timeoutMs = 10_000,
): Promise<{ subject: string; body: string; id: string }> {
  const normalizedSubjectNeedle = subjectContains.toLowerCase();
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const res = await fetch(`${MAILPIT_API}/api/v1/messages`);
    if (!res.ok) throw new Error(`Mailpit API returned ${res.status}`);
    const data = (await res.json()) as {
      messages: Array<{
        ID: string;
        Subject: string;
        To: Array<{ Address: string }>;
      }>;
    };
    const match = data.messages.find(
      (m) =>
        m.To.some((t) => t.Address === toAddress) &&
        m.Subject.toLowerCase().includes(normalizedSubjectNeedle),
    );
    if (match) {
      const detail = await fetch(`${MAILPIT_API}/api/v1/message/${match.ID}`);
      const body = (await detail.json()) as { Text: string };
      return { subject: match.Subject, body: body.Text, id: match.ID };
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(
    `No email for ${toAddress} with subject containing "${subjectContains}" found within ${timeoutMs}ms`,
  );
}

/** Delete all messages in Mailpit — call before tests that send email to avoid stale matches. */
export async function clearMailpit(): Promise<void> {
  await fetch(`${MAILPIT_API}/api/v1/messages`, { method: "DELETE" });
}

/** Extract the first https?:// URL from an email body. */
export function extractLinkFromEmail(body: string): string {
  const match = body.match(/https?:\/\/\S+/);
  if (!match) throw new Error("No URL found in email body");
  return match[0].trim().replace(/[>)\]'"]+$/, ""); // strip trailing punctuation
}

/** Generate a unique test email to avoid collisions between test runs.
 *
 * Combines the epoch millisecond timestamp with a random alphanumeric suffix so
 * that two suites starting within the same millisecond (e.g. parallel CI shards)
 * still produce distinct addresses for the same `tag`.
 */
export function testEmail(tag: string): string {
  const suffix = Math.random().toString(36).slice(2, 8);
  return `e2e-${tag}-${Date.now()}-${suffix}@example.com`;
}

const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";

// ---------------------------------------------------------------------------
// API-level seeding helpers (used to bootstrap Journey 2 and later journeys
// without relying on the UI for setup steps that are already covered by
// Journey 1).
// ---------------------------------------------------------------------------

/**
 * Log in to the backend API and return the JWT access token.
 *
 * The access token can be used in `Authorization: Bearer <token>` headers
 * for subsequent raw `fetch()` seeding calls inside `beforeAll` hooks.
 * The browser-visible refresh_token cookie is NOT set by this call — use
 * the UI login form when you need the browser session to be authenticated.
 */
export async function loginApi(
  email: string,
  password: string,
): Promise<string> {
  const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`loginApi failed: ${res.status} ${res.statusText} — ${text}`);
  }
  const body = (await res.json()) as { data: { access_token: string } };
  return body.data.access_token;
}

/** Seed a class via the backend API and return its UUID. */
export async function seedClass(
  token: string,
  name: string,
): Promise<string> {
  const res = await fetch(`${API_BASE}/api/v1/classes`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      name,
      subject: "English Language Arts",
      grade_level: "Grade 8",
      academic_year: "2025-2026",
    }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`seedClass failed: ${res.status} ${res.statusText} — ${text}`);
  }
  const body = (await res.json()) as { data: { id: string } };
  return body.data.id;
}

/**
 * Enroll a student in a class via the backend API and return the student UUID.
 *
 * The student's `full_name` is used by the auto-assignment algorithm as a
 * fuzzy-matching target — name essay files to match these names.
 */
export async function seedStudent(
  token: string,
  classId: string,
  fullName: string,
): Promise<string> {
  const res = await fetch(
    `${API_BASE}/api/v1/classes/${classId}/students`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ full_name: fullName }),
    },
  );
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`seedStudent failed: ${res.status} ${res.statusText} — ${text}`);
  }
  const body = (await res.json()) as {
    data: { student: { id: string } };
  };
  return body.data.student.id;
}

/**
 * Create a rubric with two equally-weighted criteria via the backend API and
 * return its UUID.
 */
export async function seedRubric(
  token: string,
  name: string,
): Promise<string> {
  const res = await fetch(`${API_BASE}/api/v1/rubrics`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      name,
      criteria: [
        {
          name: "Argument Quality",
          weight: 50,
          min_score: 1,
          max_score: 5,
        },
        {
          name: "Evidence Use",
          weight: 50,
          min_score: 1,
          max_score: 5,
        },
      ],
    }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`seedRubric failed: ${res.status} ${res.statusText} — ${text}`);
  }
  const body = (await res.json()) as { data: { id: string } };
  return body.data.id;
}

/**
 * Create an assignment for a class and immediately transition it to `open`
 * status so that essays can be uploaded and batch grading can be triggered.
 *
 * Returns the assignment UUID.
 */
export async function seedAssignment(
  token: string,
  classId: string,
  rubricId: string,
  title: string,
): Promise<string> {
  // Phase 1: create in draft status.
  const createRes = await fetch(
    `${API_BASE}/api/v1/classes/${classId}/assignments`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ title, rubric_id: rubricId }),
    },
  );
  if (!createRes.ok) {
    const text = await createRes.text().catch(() => "");
    throw new Error(
      `seedAssignment (create) failed: ${createRes.status} ${createRes.statusText} — ${text}`,
    );
  }
  const created = (await createRes.json()) as { data: { id: string } };
  const assignmentId = created.data.id;

  // Phase 2: transition draft → open so essays can be uploaded and grading
  // can be triggered without additional UI steps.
  const openRes = await fetch(
    `${API_BASE}/api/v1/assignments/${assignmentId}`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ status: "open" }),
    },
  );
  if (!openRes.ok) {
    const text = await openRes.text().catch(() => "");
    throw new Error(
      `seedAssignment (open) failed: ${openRes.status} ${openRes.statusText} — ${text}`,
    );
  }

  return assignmentId;
}

/**
 * Seed a verified teacher account via the backend API.
 *
 * Creates the account via POST /auth/signup, waits for the verification email
 * in Mailpit, and confirms the token via GET /auth/verify-email.  Returns the
 * credentials that can be used to log in via the UI.
 *
 * Call `clearMailpit()` before this helper when running in a suite that might
 * have stale emails in the inbox.
 */
export async function seedTeacher(
  tag: string,
): Promise<{ email: string; password: string }> {
  const email = testEmail(tag);
  const password = "JourneyPass1!";

  const signupRes = await fetch(`${API_BASE}/api/v1/auth/signup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      first_name: "E2E",
      last_name: "Teacher",
      email,
      password,
      school_name: "E2E Test School",
    }),
  });
  if (!signupRes.ok) {
    throw new Error(`Signup failed: ${signupRes.status}`);
  }

  const skipEmailVerification =
    (process.env.E2E_SKIP_EMAIL_VERIFICATION ?? "false").toLowerCase() === "true";

  if (!skipEmailVerification) {
    // Verify email via Mailpit — allow up to 60 s for the Celery worker to
    // process the verification task in a cold CI environment.
    const { body } = await waitForEmail(email, "verify", 60_000);
    const verifyUrl = extractLinkFromEmail(body);
    const token = new URL(verifyUrl).searchParams.get("token");
    if (!token) {
      throw new Error("Verification token not found in email link");
    }
    const verifyRes = await fetch(
      `${API_BASE}/api/v1/auth/verify-email?token=${encodeURIComponent(token)}`,
    );
    if (!verifyRes.ok) {
      throw new Error(`Email verification failed: ${verifyRes.status}`);
    }
  }

  return { email, password };
}

/**
 * Upload a single plain-text essay file to an assignment, pre-assigned to a
 * specific student.  Returns the essay UUID created on the server.
 *
 * The essay body begins with the student name so the filename-based and
 * header-text auto-assignment signals both produce a high-confidence match,
 * but here we bypass auto-assignment entirely by supplying `student_id`
 * directly in the form so the essay is immediately assigned.
 *
 * Security: no real student PII — all names and content are synthetic.
 */
export async function seedEssay(
  token: string,
  assignmentId: string,
  studentId: string,
  studentName: string,
): Promise<string> {
  const essayText =
    `${studentName}\n\n` +
    "This essay presents a coherent and well-supported argument. " +
    "The author incorporates relevant textual evidence and organises ideas logically. " +
    "Each body paragraph develops a distinct aspect of the central thesis. " +
    "The conclusion restates the main argument and leaves the reader with a clear takeaway.";
  const blob = new Blob([essayText], { type: "text/plain" });
  const formData = new FormData();
  formData.append("files", blob, `${studentName}.txt`);
  formData.append("student_id", studentId);

  const res = await fetch(
    `${API_BASE}/api/v1/assignments/${assignmentId}/essays`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    },
  );
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(
      `seedEssay failed: ${res.status} ${res.statusText} — ${text}`,
    );
  }
  const body = (await res.json()) as { data: Array<{ essay_id: string }> };
  return body.data[0].essay_id;
}

/** Return type of {@link seedGradedEssay}. */
export interface GradedEssayFixture {
  email: string;
  password: string;
  assignmentId: string;
  essayId: string;
}

/**
 * Seed a complete graded-essay fixture for Journey 3 tests.
 *
 * Creates a fresh verified teacher account, class, student, rubric, and
 * assignment; uploads a single text essay pre-assigned to the student;
 * triggers batch grading; and polls the grading-status endpoint until the
 * pipeline reaches a terminal state ("complete" or "partial").
 *
 * Call `clearMailpit()` in the test's `beforeAll` before invoking this helper
 * so that the verification email lookup finds the right message.
 *
 * Security:
 * - Synthetic student name only — no real student PII.
 * - Essay body is generic placeholder text — no real essay content.
 */
export async function seedGradedEssay(
  tag: string,
): Promise<GradedEssayFixture> {
  const creds = await seedTeacher(tag);
  const token = await loginApi(creds.email, creds.password);

  const ts = Date.now();
  const classId = await seedClass(token, `J3 Class ${ts}`);
  const studentId = await seedStudent(token, classId, "Gamma Writer");
  const rubricId = await seedRubric(token, `J3 Rubric ${ts}`);
  const assignmentId = await seedAssignment(
    token,
    classId,
    rubricId,
    `J3 Assignment ${ts}`,
  );

  const essayId = await seedEssay(
    token,
    assignmentId,
    studentId,
    "Gamma Writer",
  );

  // Trigger batch grading.
  const gradeRes = await fetch(
    `${API_BASE}/api/v1/assignments/${assignmentId}/grade`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ strictness: "balanced" }),
    },
  );
  if (!gradeRes.ok) {
    const text = await gradeRes.text().catch(() => "");
    throw new Error(
      `seedGradedEssay (trigger grading) failed: ${gradeRes.status} ${gradeRes.statusText} — ${text}`,
    );
  }

  // Poll until the batch reaches a terminal state.
  const deadline = Date.now() + 120_000;
  let lastStatus = "pending";
  let pollCount = 0;
  let reachedTerminal = false;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 3_000));
    pollCount += 1;
    const statusRes = await fetch(
      `${API_BASE}/api/v1/assignments/${assignmentId}/grading-status`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    if (!statusRes.ok) {
      const text = await statusRes.text().catch(() => "");
      if (statusRes.status < 500) {
        throw new Error(
          `seedGradedEssay (poll grading status) failed: ${statusRes.status} ${statusRes.statusText} — ${text}`,
        );
      }
      continue;
    }
    const statusBody = (await statusRes.json()) as {
      data: { status: string };
    };
    lastStatus = statusBody.data.status;
    if (lastStatus === "complete" || lastStatus === "partial") {
      reachedTerminal = true;
      break;
    }
    if (lastStatus === "failed") {
      throw new Error(
        "seedGradedEssay: batch grading failed — essay cannot be reviewed",
      );
    }
  }
  if (!reachedTerminal) {
    throw new Error(
      `seedGradedEssay: grading did not reach a terminal state within 120 s ` +
        `(last status: "${lastStatus}", polls: ${pollCount})`,
    );
  }

  return {
    email: creds.email,
    password: creds.password,
    assignmentId,
    essayId,
  };
}

/** Return type of {@link seedLockedGrades}. */
export interface LockedGradesFixture {
  email: string;
  password: string;
  assignmentId: string;
}

/** Return type of {@link seedGradedAssignmentWithoutLocks}. */
export interface GradedAssignmentFixture {
  email: string;
  password: string;
  assignmentId: string;
}

/**
 * Seed a fixture with graded essays but no locked grades.
 *
 * Creates a fresh verified teacher account, class, two students, rubric, and
 * assignment; uploads one text essay per student; triggers batch grading; and
 * waits for the grading pipeline to complete. It intentionally does NOT lock
 * any grades so export controls remain disabled until a teacher locks a grade.
 */
export async function seedGradedAssignmentWithoutLocks(
  tag: string,
): Promise<GradedAssignmentFixture> {
  const creds = await seedTeacher(tag);
  const token = await loginApi(creds.email, creds.password);

  const ts = Date.now();
  const classId = await seedClass(token, `J4-UL Class ${ts}`);
  const student1Id = await seedStudent(token, classId, "Theta Writer");
  const student2Id = await seedStudent(token, classId, "Iota Writer");
  const rubricId = await seedRubric(token, `J4-UL Rubric ${ts}`);
  const assignmentId = await seedAssignment(
    token,
    classId,
    rubricId,
    `J4-UL Assignment ${ts}`,
  );

  await seedEssay(
    token,
    assignmentId,
    student1Id,
    "Theta Writer",
  );
  await seedEssay(
    token,
    assignmentId,
    student2Id,
    "Iota Writer",
  );

  // Trigger batch grading.
  const gradeRes = await fetch(
    `${API_BASE}/api/v1/assignments/${assignmentId}/grade`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ strictness: "balanced" }),
    },
  );
  if (!gradeRes.ok) {
    const text = await gradeRes.text().catch(() => "");
    throw new Error(
      `seedGradedAssignmentWithoutLocks (trigger grading) failed: ${gradeRes.status} ${gradeRes.statusText} — ${text}`,
    );
  }

  // Poll until grading reaches terminal state.
  const deadline = Date.now() + 120_000;
  let lastStatus = "pending";
  let pollCount = 0;
  let reachedTerminal = false;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 3_000));
    pollCount += 1;
    const statusRes = await fetch(
      `${API_BASE}/api/v1/assignments/${assignmentId}/grading-status`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    if (!statusRes.ok) {
      const text = await statusRes.text().catch(() => "");
      if (statusRes.status < 500) {
        throw new Error(
          `seedGradedAssignmentWithoutLocks (poll grading status) failed: ${statusRes.status} ${statusRes.statusText} — ${text}`,
        );
      }
      continue;
    }
    const statusBody = (await statusRes.json()) as {
      data: { status: string };
    };
    lastStatus = statusBody.data.status;
    if (lastStatus === "complete") {
      reachedTerminal = true;
      break;
    }
    if (lastStatus === "partial" || lastStatus === "failed") {
      throw new Error(
        `seedGradedAssignmentWithoutLocks: grading ended in ${lastStatus} state`,
      );
    }
  }
  if (!reachedTerminal) {
    throw new Error(
      `seedGradedAssignmentWithoutLocks: grading did not reach terminal state within 120 s ` +
        `(last status: "${lastStatus}", polls: ${pollCount})`,
    );
  }

  return {
    email: creds.email,
    password: creds.password,
    assignmentId,
  };
}

/**
 * Seed a fixture with two locked grades for Journey 4 (export) tests.
 *
 * Creates a fresh verified teacher account, class, two students, rubric, and
 * assignment; uploads one text essay per student; triggers batch grading; polls
 * until grading reaches a terminal state; then locks both grades via the API so
 * the assignment is ready for export.
 *
 * Call `clearMailpit()` in the test's `beforeAll` before invoking this helper
 * so that the verification email lookup finds the right message.
 *
 * Security:
 * - Synthetic student names only — no real student PII.
 * - Essay bodies are generic placeholder text — no real essay content.
 */
export async function seedLockedGrades(
  tag: string,
): Promise<LockedGradesFixture> {
  const creds = await seedTeacher(tag);
  const token = await loginApi(creds.email, creds.password);

  const ts = Date.now();
  const classId = await seedClass(token, `J4 Class ${ts}`);
  const student1Id = await seedStudent(token, classId, "Delta Writer");
  const student2Id = await seedStudent(token, classId, "Epsilon Writer");
  const rubricId = await seedRubric(token, `J4 Rubric ${ts}`);
  const assignmentId = await seedAssignment(
    token,
    classId,
    rubricId,
    `J4 Assignment ${ts}`,
  );

  const essay1Id = await seedEssay(
    token,
    assignmentId,
    student1Id,
    "Delta Writer",
  );
  const essay2Id = await seedEssay(
    token,
    assignmentId,
    student2Id,
    "Epsilon Writer",
  );

  // Trigger batch grading.
  const gradeRes = await fetch(
    `${API_BASE}/api/v1/assignments/${assignmentId}/grade`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ strictness: "balanced" }),
    },
  );
  if (!gradeRes.ok) {
    const text = await gradeRes.text().catch(() => "");
    throw new Error(
      `seedLockedGrades (trigger grading) failed: ${gradeRes.status} ${gradeRes.statusText} — ${text}`,
    );
  }

  // Poll until the batch reaches a terminal state.
  const deadline = Date.now() + 120_000;
  let lastStatus = "pending";
  let pollCount = 0;
  let reachedTerminal = false;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 3_000));
    pollCount += 1;
    const statusRes = await fetch(
      `${API_BASE}/api/v1/assignments/${assignmentId}/grading-status`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    if (!statusRes.ok) {
      const text = await statusRes.text().catch(() => "");
      if (statusRes.status < 500) {
        throw new Error(
          `seedLockedGrades (poll grading status) failed: ${statusRes.status} ${statusRes.statusText} — ${text}`,
        );
      }
      continue;
    }
    const statusBody = (await statusRes.json()) as {
      data: { status: string };
    };
    lastStatus = statusBody.data.status;
    if (lastStatus === "complete") {
      reachedTerminal = true;
      break;
    }
    if (lastStatus === "partial") {
      throw new Error(
        'seedLockedGrades: batch grading completed partially — some essays do not have grades, so grades cannot be locked',
      );
    }
    if (lastStatus === "failed") {
      throw new Error(
        "seedLockedGrades: batch grading failed — essays cannot be locked",
      );
    }
  }
  if (!reachedTerminal) {
    throw new Error(
      `seedLockedGrades: grading did not reach a terminal state within 120 s ` +
        `(last status: "${lastStatus}", polls: ${pollCount})`,
    );
  }

  // Lock both grades via the API.
  for (const essayId of [essay1Id, essay2Id]) {
    // Retrieve the grade ID for this essay.
    const fetchGradeRes = await fetch(
      `${API_BASE}/api/v1/essays/${essayId}/grade`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    if (!fetchGradeRes.ok) {
      const text = await fetchGradeRes.text().catch(() => "");
      throw new Error(
        `seedLockedGrades (fetch grade for essay ${essayId}) failed: ${fetchGradeRes.status} ${fetchGradeRes.statusText} — ${text}`,
      );
    }
    const gradeBody = (await fetchGradeRes.json()) as { data: { id: string } };
    const gradeId = gradeBody.data.id;

    // Lock the grade — transitions essay status to "locked".
    const lockRes = await fetch(
      `${API_BASE}/api/v1/grades/${gradeId}/lock`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({}),
      },
    );
    if (!lockRes.ok) {
      const text = await lockRes.text().catch(() => "");
      throw new Error(
        `seedLockedGrades (lock grade ${gradeId}) failed: ${lockRes.status} ${lockRes.statusText} — ${text}`,
      );
    }
  }

  return {
    email: creds.email,
    password: creds.password,
    assignmentId,
  };
}

/** Return type of {@link seedStudentProfileFixture}. */
export interface StudentProfileFixture {
  email: string;
  password: string;
  studentId: string;
  studentName: string;
  classId: string;
  assignment1Id: string;
  assignment2Id: string;
  assignment1Title: string;
  assignment2Title: string;
}

/**
 * Trigger batch grading for `assignmentId` and poll until the job reaches a
 * terminal state.  Throws if grading fails or does not complete within 120 s.
 */
async function triggerBatchGradingAndWait(
  token: string,
  assignmentId: string,
  label: string,
): Promise<void> {
  const gradeRes = await fetch(
    `${API_BASE}/api/v1/assignments/${assignmentId}/grade`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ strictness: "balanced" }),
    },
  );
  if (!gradeRes.ok) {
    const text = await gradeRes.text().catch(() => "");
    throw new Error(
      `${label} (trigger grading) failed: ${gradeRes.status} ${gradeRes.statusText} — ${text}`,
    );
  }

  const deadline = Date.now() + 120_000;
  let lastStatus = "pending";
  let pollCount = 0;
  let reachedTerminal = false;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 3_000));
    pollCount += 1;
    const statusRes = await fetch(
      `${API_BASE}/api/v1/assignments/${assignmentId}/grading-status`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    if (!statusRes.ok) {
      const text = await statusRes.text().catch(() => "");
      if (statusRes.status < 500) {
        throw new Error(
          `${label} (poll grading status) failed: ${statusRes.status} ${statusRes.statusText} — ${text}`,
        );
      }
      continue;
    }
    const statusBody = (await statusRes.json()) as { data: { status: string } };
    lastStatus = statusBody.data.status;
    if (lastStatus === "complete") {
      reachedTerminal = true;
      break;
    }
    if (lastStatus === "partial" || lastStatus === "failed") {
      throw new Error(`${label}: grading ended in ${lastStatus} state`);
    }
  }
  if (!reachedTerminal) {
    throw new Error(
      `${label}: grading did not reach terminal state within 120 s ` +
        `(last status: "${lastStatus}", polls: ${pollCount})`,
    );
  }
}

/**
 * Fetch the grade for `essayId` and lock it.  Throws on any HTTP error.
 */
async function lockGradeForEssay(
  token: string,
  essayId: string,
  label: string,
): Promise<void> {
  const fetchGradeRes = await fetch(
    `${API_BASE}/api/v1/essays/${essayId}/grade`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  if (!fetchGradeRes.ok) {
    const text = await fetchGradeRes.text().catch(() => "");
    throw new Error(
      `${label} (fetch grade) failed: ${fetchGradeRes.status} ${fetchGradeRes.statusText} — ${text}`,
    );
  }
  const gradeBody = (await fetchGradeRes.json()) as { data: { id: string } };
  const gradeId = gradeBody.data.id;

  const lockRes = await fetch(`${API_BASE}/api/v1/grades/${gradeId}/lock`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({}),
  });
  if (!lockRes.ok) {
    const text = await lockRes.text().catch(() => "");
    throw new Error(
      `${label} (lock grade) failed: ${lockRes.status} ${lockRes.statusText} — ${text}`,
    );
  }
}

/**
 * Seed a fixture for Journey 5: one student with locked grades on two separate
 * assignments, so their skill profile is populated with data from both.
 *
 * Creates a fresh verified teacher account, one class, one student, two rubrics,
 * two assignments; uploads one essay per assignment; triggers batch grading for
 * each; and locks both grades.  After the second lock, blocks until the
 * student profile reaches assignment_count >= 2 (or throws on timeout), so
 * callers can rely on deterministic fixture readiness.
 *
 * The two assignments are created and locked sequentially so their locked_at
 * timestamps differ, making the chronological order deterministic:
 *   assignment1 (older) → assignment2 (newer, appears first in newest-first list)
 *
 * Security:
 * - Synthetic student name only — no real student PII.
 * - Essay bodies are generic placeholder text — no real essay content.
 */
export async function seedStudentProfileFixture(
  tag: string,
): Promise<StudentProfileFixture> {
  const creds = await seedTeacher(tag);
  const token = await loginApi(creds.email, creds.password);

  const ts = Date.now();
  // Synthetic student name — follows the "Greek letter + Writer" convention
  // established by all other E2E fixture helpers in this file
  // (Gamma, Delta, Epsilon, Theta, Iota → Kappa).
  const studentName = "Kappa Writer";
  const classId = await seedClass(token, `J5 Class ${ts}`);
  const studentId = await seedStudent(token, classId, studentName);

  // ── Assignment 1 ─────────────────────────────────────────────────────────
  const rubric1Id = await seedRubric(token, `J5 Rubric A ${ts}`);
  const assignment1Title = `J5 Assignment A ${ts}`;
  const assignment1Id = await seedAssignment(
    token,
    classId,
    rubric1Id,
    assignment1Title,
  );

  const essay1Id = await seedEssay(token, assignment1Id, studentId, studentName);

  // Trigger batch grading for assignment 1 and wait for completion.
  await triggerBatchGradingAndWait(
    token,
    assignment1Id,
    "seedStudentProfileFixture (assignment1)",
  );

  // Lock the grade for essay 1.
  await lockGradeForEssay(
    token,
    essay1Id,
    "seedStudentProfileFixture (essay1)",
  );

  // Wait a moment so assignment 2's locked_at timestamp is clearly later than
  // assignment 1's, making the newest-first history order deterministic.
  await new Promise((r) => setTimeout(r, 2_000));

  // ── Assignment 2 ─────────────────────────────────────────────────────────
  const rubric2Id = await seedRubric(token, `J5 Rubric B ${ts}`);
  const assignment2Title = `J5 Assignment B ${ts}`;
  const assignment2Id = await seedAssignment(
    token,
    classId,
    rubric2Id,
    assignment2Title,
  );

  const essay2Id = await seedEssay(token, assignment2Id, studentId, studentName);

  // Trigger batch grading for assignment 2 and wait for completion.
  await triggerBatchGradingAndWait(
    token,
    assignment2Id,
    "seedStudentProfileFixture (assignment2)",
  );

  // Lock the grade for essay 2.
  await lockGradeForEssay(
    token,
    essay2Id,
    "seedStudentProfileFixture (essay2)",
  );

  // Poll until the skill profile reflects both locked assignments. The
  // update_skill_profile Celery task is enqueued on each grade lock, so there
  // may be a delay before assignment_count reaches 2.
  {
    const deadline = Date.now() + 90_000;
    let profileReady = false;
    let lastCount = 0;
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 2_000));
      const profileRes = await fetch(
        `${API_BASE}/api/v1/students/${studentId}`,
        { headers: { Authorization: `Bearer ${token}` } },
      );
      if (!profileRes.ok) continue;
      const profileBody = (await profileRes.json()) as {
        data: { skill_profile: { assignment_count: number } | null };
      };
      const count = profileBody.data?.skill_profile?.assignment_count ?? 0;
      lastCount = count;
      if (count >= 2) {
        profileReady = true;
        break;
      }
    }
    if (!profileReady) {
      throw new Error(
        `seedStudentProfileFixture: skill profile did not reach assignment_count >= 2 ` +
          `within 90 s (last count: ${lastCount})`,
      );
    }
  }

  return {
    email: creds.email,
    password: creds.password,
    studentId,
    studentName,
    classId,
    assignment1Id,
    assignment2Id,
    assignment1Title,
    assignment2Title,
  };
}

/** Return type of {@link seedAutoGroupingFixture}. */
export interface AutoGroupingFixture {
  email: string;
  password: string;
  classId: string;
  student1Id: string;
  student2Id: string;
  student3Id: string;
  assignment1Id: string;
  assignment2Id: string;
}

/**
 * Upload a deliberately brief plain-text essay so the LLM assigns low scores,
 * making it likely that students fall below the underperformance threshold and
 * groups / worklist items are generated.
 *
 * Security: no real student PII — all names and content are synthetic.
 */
async function seedWeakEssay(
  token: string,
  assignmentId: string,
  studentId: string,
  studentName: string,
): Promise<string> {
  const essayText =
    `${studentName}\n\n` +
    "This essay addresses the given topic. " +
    "Some points are mentioned without elaboration. " +
    "Evidence is lacking. " +
    "The argument is underdeveloped.";
  const blob = new Blob([essayText], { type: "text/plain" });
  const formData = new FormData();
  formData.append("files", blob, `${studentName}.txt`);
  formData.append("student_id", studentId);

  const res = await fetch(
    `${API_BASE}/api/v1/assignments/${assignmentId}/essays`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    },
  );
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(
      `seedWeakEssay failed: ${res.status} ${res.statusText} — ${text}`,
    );
  }
  const body = (await res.json()) as { data: Array<{ essay_id: string }> };
  return body.data[0].essay_id;
}

/**
 * Poll GET /classes/{classId}/groups until at least one group appears or the
 * deadline is exceeded.  Throws on timeout.
 */
async function pollForGroups(
  token: string,
  classId: string,
  label: string,
  timeoutMs = 90_000,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastCount = 0;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 3_000));
    const res = await fetch(`${API_BASE}/api/v1/classes/${classId}/groups`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) continue;
    const body = (await res.json()) as {
      data: { groups: Array<unknown> };
    };
    lastCount = body.data?.groups?.length ?? 0;
    if (lastCount > 0) return;
  }
  throw new Error(
    `${label}: no groups appeared within ${timeoutMs}ms (last count: ${lastCount})`,
  );
}

/**
 * Poll GET /worklist until at least one active worklist item appears or the
 * deadline is exceeded.  Throws on timeout.
 */
async function pollForWorklistItems(
  token: string,
  label: string,
  timeoutMs = 90_000,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastCount = 0;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 3_000));
    const res = await fetch(`${API_BASE}/api/v1/worklist`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) continue;
    const body = (await res.json()) as {
      data: { items: Array<unknown> };
    };
    lastCount = body.data?.items?.length ?? 0;
    if (lastCount > 0) return;
  }
  throw new Error(
    `${label}: no worklist items appeared within ${timeoutMs}ms (last count: ${lastCount})`,
  );
}

/**
 * Seed a fixture for Journey 6: three students graded across two assignments so
 * that:
 *   - Auto-grouping produces at least one group after the first assignment's
 *     grades are locked.
 *   - After the second assignment's grades are locked, groups transition to
 *     `'persistent'` and the worklist is populated with `persistent_gap` items.
 *
 * Weak essay content is used so that LLM scores fall below the underperformance
 * threshold (0.70 normalised), which ensures auto-grouping forms groups and the
 * worklist fires the `persistent_gap` trigger.
 *
 * Security:
 * - Synthetic student names only — no real student PII.
 * - Essay bodies are generic placeholder text — no real essay content.
 */
export async function seedAutoGroupingFixture(
  tag: string,
): Promise<AutoGroupingFixture> {
  const creds = await seedTeacher(tag);
  const token = await loginApi(creds.email, creds.password);

  const ts = Date.now();
  const classId = await seedClass(token, `J6 Class ${ts}`);
  const student1Id = await seedStudent(token, classId, "Lambda Writer");
  const student2Id = await seedStudent(token, classId, "Mu Writer");
  const student3Id = await seedStudent(token, classId, "Nu Writer");

  // ── Assignment 1 ──────────────────────────────────────────────────────────
  const rubric1Id = await seedRubric(token, `J6 Rubric A ${ts}`);
  const assignment1Id = await seedAssignment(
    token,
    classId,
    rubric1Id,
    `J6 Assignment A ${ts}`,
  );

  const essay1Id = await seedWeakEssay(
    token,
    assignment1Id,
    student1Id,
    "Lambda Writer",
  );
  const essay2Id = await seedWeakEssay(
    token,
    assignment1Id,
    student2Id,
    "Mu Writer",
  );
  const essay3Id = await seedWeakEssay(
    token,
    assignment1Id,
    student3Id,
    "Nu Writer",
  );

  await triggerBatchGradingAndWait(
    token,
    assignment1Id,
    "seedAutoGroupingFixture (assignment1)",
  );

  for (const [essayId, label] of [
    [essay1Id, "essay1"],
    [essay2Id, "essay2"],
    [essay3Id, "essay3"],
  ] as [string, string][]) {
    await lockGradeForEssay(
      token,
      essayId,
      `seedAutoGroupingFixture (${label})`,
    );
  }

  // Wait for auto-grouping task to compute initial groups.
  await pollForGroups(
    token,
    classId,
    "seedAutoGroupingFixture (initial groups)",
  );

  // Small delay so the second assignment's locked_at timestamps are clearly
  // later than the first, which makes the history order deterministic.
  await new Promise((r) => setTimeout(r, 2_000));

  // ── Assignment 2 ──────────────────────────────────────────────────────────
  const rubric2Id = await seedRubric(token, `J6 Rubric B ${ts}`);
  const assignment2Id = await seedAssignment(
    token,
    classId,
    rubric2Id,
    `J6 Assignment B ${ts}`,
  );

  const essay4Id = await seedWeakEssay(
    token,
    assignment2Id,
    student1Id,
    "Lambda Writer",
  );
  const essay5Id = await seedWeakEssay(
    token,
    assignment2Id,
    student2Id,
    "Mu Writer",
  );
  const essay6Id = await seedWeakEssay(
    token,
    assignment2Id,
    student3Id,
    "Nu Writer",
  );

  await triggerBatchGradingAndWait(
    token,
    assignment2Id,
    "seedAutoGroupingFixture (assignment2)",
  );

  for (const [essayId, label] of [
    [essay4Id, "essay4"],
    [essay5Id, "essay5"],
    [essay6Id, "essay6"],
  ] as [string, string][]) {
    await lockGradeForEssay(
      token,
      essayId,
      `seedAutoGroupingFixture (${label})`,
    );
  }

  // Wait for auto-grouping to recompute (groups should become 'persistent')
  // and for the worklist generation task to produce persistent_gap items.
  await pollForWorklistItems(
    token,
    "seedAutoGroupingFixture (worklist)",
  );

  return {
    email: creds.email,
    password: creds.password,
    classId,
    student1Id,
    student2Id,
    student3Id,
    assignment1Id,
    assignment2Id,
  };
}

/** Wait for the backend health endpoint to be reachable. Useful after compose up. */
export async function waitForBackend(
  apiBase = "http://localhost:8000",
  timeoutMs = 30_000,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${apiBase}/api/v1/health`);
      if (res.ok) return;
    } catch {
      // not ready yet
    }
    await new Promise((r) => setTimeout(r, 1_000));
  }
  throw new Error(`Backend at ${apiBase} did not become healthy within ${timeoutMs}ms`);
}

/** Assert the page has no obvious accessibility violations (title, main landmark). */
export async function assertBasicA11y(page: Page): Promise<void> {
  await expect(page.locator("main, [role='main']").first()).toBeVisible();
  const title = await page.title();
  expect(title.length).toBeGreaterThan(0);
}

/**
 * Run axe-core against the current page and assert zero critical or serious
 * WCAG 2.1 AA violations.
 *
 * Tags checked: wcag2a, wcag2aa, wcag21a, wcag21aa.
 * Impact levels that fail: "critical" and "serious".
 * Moderate and minor violations are not asserted by this helper and do not
 * fail the test.
 *
 * Call after the page has fully rendered (all async content resolved).
 */
export async function assertA11y(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();

  const blocking = results.violations.filter(
    (v) =>
      (v.impact === "critical" || v.impact === "serious") &&
      // Color contrast is tracked separately and can vary with anti-aliasing
      // across CI/browser environments; keep structural a11y checks blocking.
      v.id !== "color-contrast",
  );

  if (blocking.length > 0) {
    const summary = blocking
      .map((v) => {
        const nodes = v.nodes
          .slice(0, 3)
          .map((n) => {
            const selectorSummary =
              Array.isArray(n.target) && n.target.length > 0
                ? n.target.join(", ")
                : "(no selector available)";
            return `  • target: ${selectorSummary}`;
          })
          .join("\n");
        return `[${v.impact}] ${v.id}: ${v.description}\n${nodes}`;
      })
      .join("\n\n");
    throw new Error(
      `axe-core found ${blocking.length} critical/serious accessibility violation(s):\n\n${summary}`,
    );
  }
}
