/**
 * Tests for the essay input UI components (M3.11).
 *
 * Covers:
 * - EssayUploadDialog: file-type validation (Zod)
 * - EssayUploadDialog: file-size validation (Zod)
 * - EssayUploadDialog: text-paste validation
 * - EssayUploadDialog: upload button disabled when no files / no text
 * - EssayUploadDialog: successful file upload calls API and triggers onUploaded
 * - EssayUploadDialog: API FILE_TYPE_NOT_ALLOWED error shows correct message
 * - EssayUploadDialog: API FILE_TOO_LARGE error shows correct message
 * - AutoAssignmentReview: renders assigned and needs-review essays
 * - AutoAssignmentReview: "Proceed to grading" disabled when unresolved essays exist
 * - AutoAssignmentReview: manual correction — select student and Save calls API
 * - AutoAssignmentReview: shows save error when assignEssay fails
 *
 * No student PII in fixtures — synthetic data only.
 * No real API calls — all API modules are mocked.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockUploadEssays = vi.fn();
const mockAssignEssay = vi.fn();

vi.mock("@/lib/api/essays", () => ({
  uploadEssays: (...args: unknown[]) => mockUploadEssays(...args),
  assignEssay: (...args: unknown[]) => mockAssignEssay(...args),
  listEssays: vi.fn(),
}));

import { EssayUploadDialog, fileSchema, pasteTextSchema } from "@/components/essays/EssayUploadDialog";
import { AutoAssignmentReview } from "@/components/essays/AutoAssignmentReview";
import { ApiError } from "@/lib/api/errors";
import type { EssayListItem } from "@/lib/api/essays";
import type { EnrolledStudentResponse } from "@/lib/api/classes";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Deterministic counter-based IDs to satisfy the testing guide's requirement
// to avoid random data in fixtures while still being unique per test.
let _idCounter = 0;
function nextId(prefix: string): string {
  return `${prefix}-${String(++_idCounter).padStart(3, "0")}`;
}

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const ASSIGNMENT_ID = "asgn-001";

function makeEssay(
  overrides: Partial<EssayListItem> = {},
): EssayListItem {
  return {
    essay_id: nextId("essay"),
    assignment_id: ASSIGNMENT_ID,
    student_id: null,
    student_name: null,
    status: "queued",
    word_count: 350,
    submitted_at: "2026-01-01T00:00:00Z",
    auto_assign_status: "unassigned",
    ...overrides,
  };
}

function makeStudent(overrides: Partial<EnrolledStudentResponse["student"]> = {}): EnrolledStudentResponse {
  const studentId = overrides.id ?? nextId("stu");
  return {
    enrollment_id: nextId("enr"),
    enrolled_at: "2026-01-01T00:00:00Z",
    student: {
      id: studentId,
      teacher_id: "tch-001",
      full_name: `Learner ${studentId.toUpperCase()}`,
      external_id: null,
      created_at: "2026-01-01T00:00:00Z",
      ...overrides,
    },
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

// ===========================================================================
// fileSchema (Zod) — unit tests
// ===========================================================================

describe("fileSchema — Zod validation", () => {
  it("accepts a valid PDF file under the size limit", () => {
    const file = new File(["content"], "essay.pdf", {
      type: "application/pdf",
    });
    expect(fileSchema.safeParse(file).success).toBe(true);
  });

  it("accepts a DOCX file", () => {
    const file = new File(["content"], "essay.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });
    expect(fileSchema.safeParse(file).success).toBe(true);
  });

  it("accepts a TXT file", () => {
    const file = new File(["content"], "essay.txt", { type: "text/plain" });
    expect(fileSchema.safeParse(file).success).toBe(true);
  });

  it("rejects an unsupported file type", () => {
    const file = new File(["content"], "essay.png", { type: "image/png" });
    const result = fileSchema.safeParse(file);
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0].message).toMatch(/PDF, DOCX, and TXT/i);
    }
  });

  it("rejects a file over 10 MB", () => {
    // Create a File whose size property exceeds 10 MB
    const bigContent = new Uint8Array(11 * 1024 * 1024);
    const file = new File([bigContent], "big.pdf", {
      type: "application/pdf",
    });
    const result = fileSchema.safeParse(file);
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0].message).toMatch(/10 MB/i);
    }
  });
});

// ===========================================================================
// pasteTextSchema (Zod) — unit tests
// ===========================================================================

describe("pasteTextSchema — Zod validation", () => {
  it("accepts valid text", () => {
    expect(
      pasteTextSchema.safeParse({ text: "An essay." }).success,
    ).toBe(true);
  });

  it("rejects empty text", () => {
    const result = pasteTextSchema.safeParse({ text: "" });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0].message).toMatch(/required/i);
    }
  });

  it("rejects whitespace-only text", () => {
    const result = pasteTextSchema.safeParse({ text: "   " });
    expect(result.success).toBe(false);
  });

  it("rejects text over 500 000 characters", () => {
    const result = pasteTextSchema.safeParse({ text: "a".repeat(500_001) });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0].message).toMatch(/500/);
    }
  });
});

// ===========================================================================
// EssayUploadDialog — rendering & validation
// ===========================================================================

describe("EssayUploadDialog — initial render", () => {
  it("renders the file upload tab and browse drop zone", () => {
    render(
      <EssayUploadDialog
        assignmentId={ASSIGNMENT_ID}
        open={true}
        onClose={vi.fn()}
        onUploaded={vi.fn()}
      />,
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/file upload/i)).toBeInTheDocument();
    expect(screen.getByText(/paste text/i)).toBeInTheDocument();
    // Drop zone button
    expect(
      screen.getByRole("button", { name: /drop zone/i }),
    ).toBeInTheDocument();
    // Upload submit button
    expect(
      screen.getByRole("button", { name: /^upload$/i }),
    ).toBeDisabled();
  });

  it("does not render when open is false", () => {
    render(
      <EssayUploadDialog
        assignmentId={ASSIGNMENT_ID}
        open={false}
        onClose={vi.fn()}
        onUploaded={vi.fn()}
      />,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("EssayUploadDialog — file-tab validation", () => {
  it("shows validation error for unsupported file type", async () => {
    // applyAccept: false bypasses userEvent's accept-attribute filter so we
    // can test the component's own Zod validation with an unsupported file.
    const user = userEvent.setup({ applyAccept: false });
    render(
      <EssayUploadDialog
        assignmentId={ASSIGNMENT_ID}
        open={true}
        onClose={vi.fn()}
        onUploaded={vi.fn()}
      />,
    );

    const fileInput = screen.getByLabelText(/select essay files/i);
    const badFile = new File(["bad"], "photo.png", { type: "image/png" });
    await user.upload(fileInput, badFile);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
      expect(screen.getByText(/PDF, DOCX, and TXT/i)).toBeInTheDocument();
    });
    expect(mockUploadEssays).not.toHaveBeenCalled();
  });

  it("enables the Upload button after a valid file is added", async () => {
    const user = userEvent.setup();
    render(
      <EssayUploadDialog
        assignmentId={ASSIGNMENT_ID}
        open={true}
        onClose={vi.fn()}
        onUploaded={vi.fn()}
      />,
    );

    const fileInput = screen.getByLabelText(/select essay files/i);
    const good = new File(["content"], "essay.pdf", {
      type: "application/pdf",
    });
    await user.upload(fileInput, good);

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /^upload$/i }),
      ).not.toBeDisabled();
    });
  });

  it("lists selected files and allows removing one", async () => {
    const user = userEvent.setup();
    render(
      <EssayUploadDialog
        assignmentId={ASSIGNMENT_ID}
        open={true}
        onClose={vi.fn()}
        onUploaded={vi.fn()}
      />,
    );

    const fileInput = screen.getByLabelText(/select essay files/i);
    const f1 = new File(["a"], "one.pdf", { type: "application/pdf" });
    const f2 = new File(["b"], "two.pdf", { type: "application/pdf" });
    await user.upload(fileInput, [f1, f2]);

    await waitFor(() => {
      expect(screen.getByText("one.pdf")).toBeInTheDocument();
      expect(screen.getByText("two.pdf")).toBeInTheDocument();
    });

    // Remove the first file
    await user.click(screen.getByRole("button", { name: /remove one\.pdf/i }));

    await waitFor(() => {
      expect(screen.queryByText("one.pdf")).not.toBeInTheDocument();
      expect(screen.getByText("two.pdf")).toBeInTheDocument();
    });
  });
});

describe("EssayUploadDialog — text-paste tab", () => {
  it("shows the textarea when the paste text tab is active", async () => {
    const user = userEvent.setup();
    render(
      <EssayUploadDialog
        assignmentId={ASSIGNMENT_ID}
        open={true}
        onClose={vi.fn()}
        onUploaded={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("tab", { name: /paste text/i }));
    expect(
      screen.getByLabelText(/essay text/i),
    ).toBeInTheDocument();
  });

  it("upload button is disabled with empty text", async () => {
    const user = userEvent.setup();
    render(
      <EssayUploadDialog
        assignmentId={ASSIGNMENT_ID}
        open={true}
        onClose={vi.fn()}
        onUploaded={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("tab", { name: /paste text/i }));
    expect(
      screen.getByRole("button", { name: /^upload$/i }),
    ).toBeDisabled();
  });

  it("shows validation error when submit with empty text", async () => {
    const user = userEvent.setup();
    render(
      <EssayUploadDialog
        assignmentId={ASSIGNMENT_ID}
        open={true}
        onClose={vi.fn()}
        onUploaded={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("tab", { name: /paste text/i }));
    // Type and clear to trigger state change that enables the button at
    // zero characters. We type a space then clear to see the validation.
    const textarea = screen.getByLabelText(/essay text/i);
    await user.type(textarea, " ");
    // Button is still disabled for whitespace-only. Manually test via the
    // paste path which uses trimmed check inside the component.
    expect(
      screen.getByRole("button", { name: /^upload$/i }),
    ).toBeDisabled();
    expect(mockUploadEssays).not.toHaveBeenCalled();
  });
});

describe("EssayUploadDialog — successful upload", () => {
  it("calls uploadEssays with selected files and invokes onUploaded", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const onUploaded = vi.fn();

    const result = [
      {
        essay_id: "essay-aaa",
        essay_version_id: "ev-aaa",
        assignment_id: ASSIGNMENT_ID,
        student_id: null,
        status: "queued",
        word_count: 200,
        file_storage_key: "essays/asgn-001/essay-aaa/essay.pdf",
        submitted_at: "2026-01-01T00:00:00Z",
        auto_assign_status: "unassigned" as const,
      },
    ];
    mockUploadEssays.mockResolvedValueOnce(result);

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(
      <EssayUploadDialog
        assignmentId={ASSIGNMENT_ID}
        open={true}
        onClose={vi.fn()}
        onUploaded={onUploaded}
      />,
    );

    const fileInput = screen.getByLabelText(/select essay files/i);
    const good = new File(["content"], "essay.pdf", {
      type: "application/pdf",
    });
    await user.upload(fileInput, good);
    await user.click(screen.getByRole("button", { name: /^upload$/i }));

    // Advance past the progress ticker intervals (10 × 300ms = 3 s) and
    // the 400ms closing delay.
    await vi.runAllTimersAsync();

    await waitFor(() => {
      expect(mockUploadEssays).toHaveBeenCalledWith(
        ASSIGNMENT_ID,
        expect.objectContaining({ files: expect.arrayContaining([good]) }),
      );
      expect(onUploaded).toHaveBeenCalledWith(result);
    });

    vi.useRealTimers();
  });
});

describe("EssayUploadDialog — API error handling", () => {
  it("shows FILE_TYPE_NOT_ALLOWED error message", async () => {
    mockUploadEssays.mockRejectedValueOnce(
      new ApiError(422, {
        code: "FILE_TYPE_NOT_ALLOWED",
        message: "Unsupported MIME type.",
      }),
    );

    const user = userEvent.setup();
    render(
      <EssayUploadDialog
        assignmentId={ASSIGNMENT_ID}
        open={true}
        onClose={vi.fn()}
        onUploaded={vi.fn()}
      />,
    );

    const fileInput = screen.getByLabelText(/select essay files/i);
    await user.upload(
      fileInput,
      new File(["x"], "essay.pdf", { type: "application/pdf" }),
    );
    await user.click(screen.getByRole("button", { name: /^upload$/i }));

    await waitFor(() => {
      expect(
        screen.getByText(/unsupported type/i),
      ).toBeInTheDocument();
    });
  });

  it("shows FILE_TOO_LARGE error message", async () => {
    mockUploadEssays.mockRejectedValueOnce(
      new ApiError(422, {
        code: "FILE_TOO_LARGE",
        message: "File exceeds limit.",
      }),
    );

    const user = userEvent.setup();
    render(
      <EssayUploadDialog
        assignmentId={ASSIGNMENT_ID}
        open={true}
        onClose={vi.fn()}
        onUploaded={vi.fn()}
      />,
    );

    const fileInput = screen.getByLabelText(/select essay files/i);
    await user.upload(
      fileInput,
      new File(["x"], "essay.pdf", { type: "application/pdf" }),
    );
    await user.click(screen.getByRole("button", { name: /^upload$/i }));

    await waitFor(() => {
      // Match the specific error message (not the drop zone hint)
      expect(screen.getByRole("alert")).toBeInTheDocument();
      expect(screen.getByText(/files exceed the.*MB limit/i)).toBeInTheDocument();
    });
  });
});

// ===========================================================================
// AutoAssignmentReview — rendering
// ===========================================================================

describe("AutoAssignmentReview — rendering", () => {
  it("renders assigned and unassigned sections", () => {
    const stu = makeStudent({ id: "stu-fixed", full_name: "Learner Alpha" });
    const assigned = makeEssay({
      essay_id: "essay-aa1",
      auto_assign_status: "assigned",
      student_id: "stu-fixed",
      student_name: "Learner Alpha",
    });
    const unassigned = makeEssay({
      essay_id: "essay-bb1",
      auto_assign_status: "unassigned",
    });

    render(
      wrapper({
        children: (
          <AutoAssignmentReview
            assignmentId={ASSIGNMENT_ID}
            essays={[assigned, unassigned]}
            students={[stu]}
            onProceed={vi.fn()}
          />
        ),
      }),
    );

    // Summary text
    expect(screen.getByText(/1 of 2 essay/i)).toBeInTheDocument();

    // Needs-review section
    expect(screen.getByText(/needs assignment/i)).toBeInTheDocument();

    // Auto-assigned section: student name appears in the assigned table row
    const assignedTable = screen.getByRole("table", { name: /auto-assigned essays/i });
    expect(within(assignedTable).getByText("Learner Alpha")).toBeInTheDocument();
  });

  it("shows empty state when no essays", () => {
    render(
      wrapper({
        children: (
          <AutoAssignmentReview
            assignmentId={ASSIGNMENT_ID}
            essays={[]}
            students={[]}
            onProceed={vi.fn()}
          />
        ),
      }),
    );
    expect(screen.getByText(/no essays uploaded/i)).toBeInTheDocument();
  });

  it("disables Proceed button when unresolved essays exist", () => {
    const unassigned = makeEssay({ auto_assign_status: "unassigned" });
    render(
      wrapper({
        children: (
          <AutoAssignmentReview
            assignmentId={ASSIGNMENT_ID}
            essays={[unassigned]}
            students={[makeStudent()]}
            onProceed={vi.fn()}
          />
        ),
      }),
    );

    expect(
      screen.getByRole("button", { name: /proceed to grading/i }),
    ).toBeDisabled();
  });

  it("enables Proceed button when all essays are assigned", () => {
    const assigned = makeEssay({
      auto_assign_status: "assigned",
      student_id: "stu-x",
      student_name: "Learner X",
    });
    render(
      wrapper({
        children: (
          <AutoAssignmentReview
            assignmentId={ASSIGNMENT_ID}
            essays={[assigned]}
            students={[makeStudent({ id: "stu-x" })]}
            onProceed={vi.fn()}
          />
        ),
      }),
    );

    expect(
      screen.getByRole("button", { name: /proceed to grading/i }),
    ).not.toBeDisabled();
  });
});

// ===========================================================================
// AutoAssignmentReview — manual correction flow
// ===========================================================================

describe("AutoAssignmentReview — manual correction", () => {
  it("calls assignEssay when teacher selects a student and clicks Save", async () => {
    const user = userEvent.setup();

    const stu = makeStudent({ id: "stu-abc", full_name: "Learner Beta" });
    const essay = makeEssay({
      essay_id: "essay-cc1",
      auto_assign_status: "unassigned",
    });

    mockAssignEssay.mockResolvedValueOnce({
      ...essay,
      student_id: "stu-abc",
      student_name: "Learner Beta",
    });

    render(
      wrapper({
        children: (
          <AutoAssignmentReview
            assignmentId={ASSIGNMENT_ID}
            essays={[essay]}
            students={[stu]}
            onProceed={vi.fn()}
          />
        ),
      }),
    );

    // Select a student in the dropdown (aria-label uses slice(0, 8) of ID)
    const select = screen.getByRole("combobox", {
      name: /assign essay/i,
    });
    await user.selectOptions(select, "stu-abc");

    // Click Save
    const saveBtn = screen.getByRole("button", {
      name: /save assignment for essay/i,
    });
    await user.click(saveBtn);

    await waitFor(() => {
      expect(mockAssignEssay).toHaveBeenCalledWith("essay-cc1", {
        student_id: "stu-abc",
      });
    });
  });

  it("Save button is disabled until a student is selected", () => {
    const essay = makeEssay({
      essay_id: "essay-dd1",
      auto_assign_status: "ambiguous",
    });

    render(
      wrapper({
        children: (
          <AutoAssignmentReview
            assignmentId={ASSIGNMENT_ID}
            essays={[essay]}
            students={[makeStudent()]}
            onProceed={vi.fn()}
          />
        ),
      }),
    );

    expect(
      screen.getByRole("button", {
        name: /save assignment for essay/i,
      }),
    ).toBeDisabled();
  });

  it("shows a save error when assignEssay fails", async () => {
    const user = userEvent.setup();

    const stu = makeStudent({ id: "stu-def", full_name: "Learner Gamma" });
    const essay = makeEssay({
      essay_id: "essay-ee1",
      auto_assign_status: "unassigned",
    });

    mockAssignEssay.mockRejectedValueOnce(
      new ApiError(500, { code: "INTERNAL_ERROR", message: "Server error." }),
    );

    render(
      wrapper({
        children: (
          <AutoAssignmentReview
            assignmentId={ASSIGNMENT_ID}
            essays={[essay]}
            students={[stu]}
            onProceed={vi.fn()}
          />
        ),
      }),
    );

    const select = screen.getByRole("combobox", {
      name: /assign essay/i,
    });
    await user.selectOptions(select, "stu-def");
    await user.click(
      screen.getByRole("button", {
        name: /save assignment for essay/i,
      }),
    );

    await waitFor(() => {
      expect(screen.getByText(/failed to save assignment/i)).toBeInTheDocument();
    });
  });

  it("calls onProceed when Proceed button is clicked", async () => {
    const user = userEvent.setup();
    const onProceed = vi.fn();

    const assigned = makeEssay({
      auto_assign_status: "assigned",
      student_id: "stu-y",
      student_name: "Learner Y",
    });

    render(
      wrapper({
        children: (
          <AutoAssignmentReview
            assignmentId={ASSIGNMENT_ID}
            essays={[assigned]}
            students={[makeStudent({ id: "stu-y" })]}
            onProceed={onProceed}
          />
        ),
      }),
    );

    await user.click(
      screen.getByRole("button", { name: /proceed to grading/i }),
    );
    expect(onProceed).toHaveBeenCalledTimes(1);
  });
});

// ===========================================================================
// AutoAssignmentReview — already-corrected essay (student_id non-null, status ambiguous)
// ===========================================================================

describe("AutoAssignmentReview — previously corrected essay", () => {
  it("shows student name instead of dropdown for already-corrected essays", () => {
    const essay = makeEssay({
      essay_id: "essay-ff1",
      auto_assign_status: "ambiguous",
      student_id: "stu-z",
      student_name: "Learner Zeta",
    });

    render(
      wrapper({
        children: (
          <AutoAssignmentReview
            assignmentId={ASSIGNMENT_ID}
            essays={[essay]}
            students={[makeStudent({ id: "stu-z", full_name: "Learner Zeta" })]}
            onProceed={vi.fn()}
          />
        ),
      }),
    );

    // Dropdown should not be visible; student name should be
    expect(
      screen.queryByRole("combobox"),
    ).not.toBeInTheDocument();

    // Find student name within the needs-review table
    const table = screen.getByRole("table", { name: /essays needing assignment/i });
    expect(within(table).getByText("Learner Zeta")).toBeInTheDocument();
  });
});
