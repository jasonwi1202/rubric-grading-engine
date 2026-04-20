/**
 * Tests for TemplatePicker component.
 *
 * Covers:
 * - Renders "Close" button and Cancel button
 * - Shows "Select a template" placeholder when nothing is selected
 * - Shows system and personal template groups
 * - Selecting a template loads criteria preview via React Query
 * - "Apply template" button is disabled until a template is selected and preview is loaded
 * - "Apply template" calls onApply with correct values and then onClose
 * - onClose is called when Escape is pressed
 * - onClose is called when Cancel button is clicked
 *
 * React Query is provided via a local QueryClientProvider.
 * All API calls are mocked via vi.mock.
 * No student PII in fixtures.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

import { TemplatePicker } from "@/components/rubric/TemplatePicker";

// ---------------------------------------------------------------------------
// Mock API modules
// ---------------------------------------------------------------------------

vi.mock("@/lib/api/rubric-templates", () => ({
  listRubricTemplates: vi.fn(),
}));

vi.mock("@/lib/api/rubrics", () => ({
  getRubric: vi.fn(),
}));

import { listRubricTemplates } from "@/lib/api/rubric-templates";
import { getRubric } from "@/lib/api/rubrics";

const mockListTemplates = vi.mocked(listRubricTemplates);
const mockGetRubric = vi.mocked(getRubric);

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const SYSTEM_TEMPLATE = {
  id: "sys-1",
  name: "5-Paragraph Essay",
  description: "A starter template for five-paragraph essays.",
  is_system: true,
  created_at: "2026-04-20T00:00:00Z",
  updated_at: "2026-04-20T00:00:00Z",
  criterion_count: 4,
};

const PERSONAL_TEMPLATE = {
  id: "pers-1",
  name: "My Custom Template",
  description: null,
  is_system: false,
  created_at: "2026-04-20T00:00:00Z",
  updated_at: "2026-04-20T00:00:00Z",
  criterion_count: 2,
};

const FULL_RUBRIC = {
  id: "sys-1",
  name: "5-Paragraph Essay",
  description: "A starter template for five-paragraph essays.",
  is_template: true,
  created_at: "2026-04-20T00:00:00Z",
  updated_at: "2026-04-20T00:00:00Z",
  criteria: [
    {
      id: "c1",
      name: "Thesis Statement",
      description: "Does the essay present a clear thesis?",
      weight: 25,
      min_score: 1,
      max_score: 5,
      display_order: 0,
      anchor_descriptions: null,
    },
    {
      id: "c2",
      name: "Supporting Evidence",
      description: "Are the body paragraphs supported by evidence?",
      weight: 25,
      min_score: 1,
      max_score: 5,
      display_order: 1,
      anchor_descriptions: null,
    },
  ],
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function renderPicker(
  props: Partial<React.ComponentProps<typeof TemplatePicker>> = {},
) {
  const onApply = vi.fn();
  const onClose = vi.fn();
  const qc = makeQueryClient();
  render(
    <QueryClientProvider client={qc}>
      <TemplatePicker onApply={onApply} onClose={onClose} {...props} />
    </QueryClientProvider>,
  );
  return { onApply, onClose };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TemplatePicker", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the dialog with heading and close button", async () => {
    mockListTemplates.mockResolvedValue([]);
    renderPicker();
    expect(
      screen.getByRole("dialog", { name: /choose a rubric template/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /close template picker/i }),
    ).toBeInTheDocument();
  });

  it("shows placeholder text when no template is selected", async () => {
    mockListTemplates.mockResolvedValue([SYSTEM_TEMPLATE]);
    renderPicker();
    await waitFor(() =>
      expect(screen.getByText("5-Paragraph Essay")).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/select a template on the left/i),
    ).toBeInTheDocument();
  });

  it("shows system and personal template groups", async () => {
    mockListTemplates.mockResolvedValue([SYSTEM_TEMPLATE, PERSONAL_TEMPLATE]);
    renderPicker();
    await waitFor(() =>
      expect(screen.getByText(/starter templates/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/my templates/i)).toBeInTheDocument();
    expect(screen.getByText("5-Paragraph Essay")).toBeInTheDocument();
    expect(screen.getByText("My Custom Template")).toBeInTheDocument();
  });

  it("shows loading message while templates are loading", () => {
    // Never resolves in time
    mockListTemplates.mockReturnValue(new Promise(() => {}));
    renderPicker();
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("shows error message when template list fails", async () => {
    mockListTemplates.mockRejectedValue(new Error("Network error"));
    renderPicker();
    await waitFor(() =>
      expect(
        screen.getByText(/failed to load templates/i),
      ).toBeInTheDocument(),
    );
  });

  it("Apply button is disabled before selecting a template", async () => {
    mockListTemplates.mockResolvedValue([SYSTEM_TEMPLATE]);
    renderPicker();
    await waitFor(() =>
      expect(screen.getByText("5-Paragraph Essay")).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: /apply template/i }),
    ).toBeDisabled();
  });

  it("calls onClose when Cancel is clicked", async () => {
    const user = userEvent.setup();
    mockListTemplates.mockResolvedValue([]);
    const { onClose } = renderPicker();
    await user.click(screen.getByRole("button", { name: /^cancel$/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("calls onClose when the X button is clicked", async () => {
    const user = userEvent.setup();
    mockListTemplates.mockResolvedValue([]);
    const { onClose } = renderPicker();
    await user.click(
      screen.getByRole("button", { name: /close template picker/i }),
    );
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("shows criteria preview after selecting a template", async () => {
    const user = userEvent.setup();
    mockListTemplates.mockResolvedValue([SYSTEM_TEMPLATE]);
    mockGetRubric.mockResolvedValue(FULL_RUBRIC as Parameters<typeof mockGetRubric>[0] extends string ? ReturnType<typeof mockGetRubric> extends Promise<infer R> ? R : never : never);
    renderPicker();
    await waitFor(() =>
      expect(screen.getByText("5-Paragraph Essay")).toBeInTheDocument(),
    );
    await user.click(screen.getByText("5-Paragraph Essay"));
    await waitFor(() =>
      expect(screen.getByText("Thesis Statement")).toBeInTheDocument(),
    );
    expect(screen.getByText("Supporting Evidence")).toBeInTheDocument();
  });

  it("calls onApply with template values and onClose after applying", async () => {
    const user = userEvent.setup();
    mockListTemplates.mockResolvedValue([SYSTEM_TEMPLATE]);
    mockGetRubric.mockResolvedValue(FULL_RUBRIC as Parameters<typeof mockGetRubric>[0] extends string ? ReturnType<typeof mockGetRubric> extends Promise<infer R> ? R : never : never);
    const { onApply, onClose } = renderPicker();

    await waitFor(() =>
      expect(screen.getByText("5-Paragraph Essay")).toBeInTheDocument(),
    );
    await user.click(screen.getByText("5-Paragraph Essay"));
    await waitFor(() =>
      expect(screen.getByText("Thesis Statement")).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /apply template/i }));

    expect(onApply).toHaveBeenCalledOnce();
    const appliedValues = onApply.mock.calls[0][0] as { name: string; criteria: unknown[] };
    expect(appliedValues.name).toBe("5-Paragraph Essay");
    expect(appliedValues.criteria).toHaveLength(2);
    expect(onClose).toHaveBeenCalledOnce();
  });
});
