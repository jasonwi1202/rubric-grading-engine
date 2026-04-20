/**
 * Tests for the class roster management UI components.
 *
 * Covers:
 * - AddStudentDialog: form validation (empty name, name too long)
 * - AddStudentDialog: successful submission calls API
 * - AddStudentDialog: server 409 shows appropriate message
 * - RemoveStudentDialog: renders student name, cancel/confirm buttons
 * - CsvDiffSummary: displays new/updated/skipped/error counts
 * - CsvImportDialog: upload phase renders file input
 * - CsvImportDialog: shows preview after upload
 *
 * No student PII in fixtures — synthetic names only.
 * No real API calls — all API modules are mocked.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockAddStudent = vi.fn();
const mockPreviewCsvImport = vi.fn();
const mockConfirmCsvImport = vi.fn();
const mockListStudents = vi.fn();
const mockRemoveStudent = vi.fn();

vi.mock("@/lib/api/classes", () => ({
  addStudent: (...args: unknown[]) => mockAddStudent(...args),
  removeStudent: (...args: unknown[]) => mockRemoveStudent(...args),
  listStudents: (...args: unknown[]) => mockListStudents(...args),
  previewCsvImport: (...args: unknown[]) => mockPreviewCsvImport(...args),
  confirmCsvImport: (...args: unknown[]) => mockConfirmCsvImport(...args),
}));

import { AddStudentDialog } from "@/components/classes/AddStudentDialog";
import { RemoveStudentDialog } from "@/components/classes/RemoveStudentDialog";
import { CsvDiffSummary, CsvImportDialog } from "@/components/classes/CsvImportDialog";
import { ApiError } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const CLASS_ID = "cls-001";

beforeEach(() => {
  vi.clearAllMocks();
});

// ===========================================================================
// AddStudentDialog — validation
// ===========================================================================

describe("AddStudentDialog — validation", () => {
  it("shows required error when name is empty", async () => {
    const user = userEvent.setup();
    render(
      <AddStudentDialog
        classId={CLASS_ID}
        open={true}
        onClose={vi.fn()}
        onAdded={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: /add student/i }));

    await waitFor(() => {
      expect(
        screen.getByText(/student name is required/i),
      ).toBeInTheDocument();
    });
    expect(mockAddStudent).not.toHaveBeenCalled();
  });

  it("shows length error when name exceeds 255 characters", async () => {
    const user = userEvent.setup();
    render(
      <AddStudentDialog
        classId={CLASS_ID}
        open={true}
        onClose={vi.fn()}
        onAdded={vi.fn()}
      />,
    );

    const longName = "A".repeat(256);
    await user.type(screen.getByLabelText(/full name/i), longName);
    await user.click(screen.getByRole("button", { name: /add student/i }));

    await waitFor(() => {
      expect(screen.getByText(/name is too long/i)).toBeInTheDocument();
    });
    expect(mockAddStudent).not.toHaveBeenCalled();
  });

  it("does not call API when dialog is closed with empty form", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      <AddStudentDialog
        classId={CLASS_ID}
        open={true}
        onClose={onClose}
        onAdded={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(mockAddStudent).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });
});

// ===========================================================================
// AddStudentDialog — successful submission
// ===========================================================================

describe("AddStudentDialog — successful submission", () => {
  it("calls addStudent with correct values and invokes onAdded", async () => {
    const onAdded = vi.fn();
    const enrolled = {
      enrollment_id: "enr-1",
      enrolled_at: "2025-01-01T00:00:00Z",
      student: {
        id: "stu-1",
        teacher_id: "tch-1",
        full_name: "Test Student",
        external_id: null,
        created_at: "2025-01-01T00:00:00Z",
      },
    };
    mockAddStudent.mockResolvedValueOnce(enrolled);

    const user = userEvent.setup();
    render(
      <AddStudentDialog
        classId={CLASS_ID}
        open={true}
        onClose={vi.fn()}
        onAdded={onAdded}
      />,
    );

    await user.type(screen.getByLabelText(/full name/i), "Test Student");
    await user.click(screen.getByRole("button", { name: /add student/i }));

    await waitFor(() => {
      expect(mockAddStudent).toHaveBeenCalledWith(
        CLASS_ID,
        expect.objectContaining({ full_name: "Test Student" }),
      );
    });
    await waitFor(() => {
      expect(onAdded).toHaveBeenCalledWith(enrolled);
    });
  });

  it("shows conflict message on 409 response", async () => {
    mockAddStudent.mockRejectedValueOnce(
      new ApiError(409, {
        code: "CONFLICT",
        message: "Student already enrolled.",
      }),
    );

    const user = userEvent.setup();
    render(
      <AddStudentDialog
        classId={CLASS_ID}
        open={true}
        onClose={vi.fn()}
        onAdded={vi.fn()}
      />,
    );

    await user.type(screen.getByLabelText(/full name/i), "Test Student");
    await user.click(screen.getByRole("button", { name: /add student/i }));

    await waitFor(() => {
      expect(
        screen.getByText(/already enrolled/i),
      ).toBeInTheDocument();
    });
  });
});

// ===========================================================================
// RemoveStudentDialog
// ===========================================================================

describe("RemoveStudentDialog", () => {
  it("renders student name in the confirmation message", () => {
    render(
      <RemoveStudentDialog
        studentName="Student Alpha"
        open={true}
        onClose={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );
    expect(screen.getByText(/Student Alpha/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /remove student/i })).toBeInTheDocument();
  });

  it("calls onConfirm when the remove button is clicked", async () => {
    const onConfirm = vi.fn();
    const user = userEvent.setup();
    render(
      <RemoveStudentDialog
        studentName="Student Alpha"
        open={true}
        onClose={vi.fn()}
        onConfirm={onConfirm}
      />,
    );

    await user.click(screen.getByRole("button", { name: /remove student/i }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("calls onClose when the cancel button is clicked", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      <RemoveStudentDialog
        studentName="Student Alpha"
        open={true}
        onClose={onClose}
        onConfirm={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("disables buttons while removal is pending", () => {
    render(
      <RemoveStudentDialog
        studentName="Student Alpha"
        open={true}
        onClose={vi.fn()}
        onConfirm={vi.fn()}
        isPending={true}
      />,
    );

    expect(screen.getByRole("button", { name: /removing/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /cancel/i })).toBeDisabled();
  });

  it("does not render when open is false", () => {
    render(
      <RemoveStudentDialog
        studentName="Student Alpha"
        open={false}
        onClose={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

// ===========================================================================
// CsvDiffSummary — count display
// ===========================================================================

describe("CsvDiffSummary", () => {
  it("displays all four counts correctly", () => {
    render(
      <CsvDiffSummary
        counts={{ new: 5, updated: 2, skipped: 1, error: 3 }}
      />,
    );

    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("renders zero counts without crashing", () => {
    render(
      <CsvDiffSummary
        counts={{ new: 0, updated: 0, skipped: 0, error: 0 }}
      />,
    );
    // Four zeros
    const zeros = screen.getAllByText("0");
    expect(zeros).toHaveLength(4);
  });
});

// ===========================================================================
// CsvImportDialog — upload phase
// ===========================================================================

describe("CsvImportDialog — upload phase", () => {
  it("renders the file input and preview button", () => {
    render(
      wrapper({
        children: (
          <CsvImportDialog
            classId={CLASS_ID}
            open={true}
            onClose={vi.fn()}
            onImported={vi.fn()}
          />
        ),
      }),
    );

    expect(screen.getByLabelText(/csv file/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /preview import/i }),
    ).toBeInTheDocument();
  });

  it("preview button is disabled when no file is selected", () => {
    render(
      wrapper({
        children: (
          <CsvImportDialog
            classId={CLASS_ID}
            open={true}
            onClose={vi.fn()}
            onImported={vi.fn()}
          />
        ),
      }),
    );

    expect(
      screen.getByRole("button", { name: /preview import/i }),
    ).toBeDisabled();
  });

  it("shows validation error when CSV is malformed (422)", async () => {
    mockPreviewCsvImport.mockRejectedValueOnce(
      new ApiError(422, {
        code: "UNPROCESSABLE_ENTITY",
        message: "Missing full_name column.",
      }),
    );

    const user = userEvent.setup();
    render(
      wrapper({
        children: (
          <CsvImportDialog
            classId={CLASS_ID}
            open={true}
            onClose={vi.fn()}
            onImported={vi.fn()}
          />
        ),
      }),
    );

    const file = new File(["invalid,csv"], "roster.csv", { type: "text/csv" });
    await user.upload(screen.getByLabelText(/csv file/i), file);
    await user.click(screen.getByRole("button", { name: /preview import/i }));

    await waitFor(() => {
      expect(screen.getByText(/invalid csv file/i)).toBeInTheDocument();
    });
  });

  it("transitions to review phase after a successful upload", async () => {
    const preview = {
      rows: [
        {
          row_number: 1,
          full_name: "Learner One",
          external_id: null,
          status: "new" as const,
          message: null,
          existing_student_id: null,
        },
      ],
      new_count: 1,
      updated_count: 0,
      skipped_count: 0,
      error_count: 0,
    };
    mockPreviewCsvImport.mockResolvedValueOnce(preview);

    const user = userEvent.setup();
    render(
      wrapper({
        children: (
          <CsvImportDialog
            classId={CLASS_ID}
            open={true}
            onClose={vi.fn()}
            onImported={vi.fn()}
          />
        ),
      }),
    );

    const file = new File(
      ["full_name\nLearner One"],
      "roster.csv",
      { type: "text/csv" },
    );
    await user.upload(screen.getByLabelText(/csv file/i), file);
    await user.click(screen.getByRole("button", { name: /preview import/i }));

    await waitFor(() => {
      expect(screen.getByText(/review import/i)).toBeInTheDocument();
    });
    // Confirm button shows total count
    expect(
      screen.getByRole("button", { name: /confirm import \(1\)/i }),
    ).toBeInTheDocument();
  });

  it("does not render when open is false", () => {
    render(
      wrapper({
        children: (
          <CsvImportDialog
            classId={CLASS_ID}
            open={false}
            onClose={vi.fn()}
            onImported={vi.fn()}
          />
        ),
      }),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
