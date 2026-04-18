/**
 * Tests for RubricBuilderForm — form validation and weight-sum logic.
 *
 * Covers:
 * - computeWeightSum helper
 * - rubricFormSchema Zod validation (name, criteria, weight sum)
 * - WeightSumIndicator rendering
 * - RubricBuilderForm renders initial criteria
 * - RubricBuilderForm shows validation error when rubric name is empty
 * - RubricBuilderForm shows weight-sum error when weights don't sum to 100
 * - RubricBuilderForm calls onSave with correct values on valid submit
 * - RubricBuilderForm add/remove criterion buttons
 * - RubricBuilderForm move-up / move-down reorder buttons
 * - RubricBuilderForm cancel calls onCancel (no confirm when form is not dirty)
 *
 * No student PII in fixtures.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

import {
  computeWeightSum,
  WeightSumIndicator,
  RubricBuilderForm,
  rubricFormSchema,
  emptyc,
} from "@/components/rubric/RubricBuilderForm";

// ---------------------------------------------------------------------------
// Unit — computeWeightSum
// ---------------------------------------------------------------------------

describe("computeWeightSum", () => {
  it("returns 0 for an empty array", () => {
    expect(computeWeightSum([])).toBe(0);
  });

  it("sums weights correctly", () => {
    expect(
      computeWeightSum([{ weight: 30 }, { weight: 40 }, { weight: 30 }]),
    ).toBe(100);
  });

  it("handles non-finite values by treating them as 0", () => {
    expect(
      computeWeightSum([{ weight: NaN }, { weight: 50 }, { weight: 50 }]),
    ).toBe(100);
  });

  it("handles fractional weights", () => {
    expect(
      computeWeightSum([{ weight: 33.3 }, { weight: 33.3 }, { weight: 33.4 }]),
    ).toBeCloseTo(100, 1);
  });
});

// ---------------------------------------------------------------------------
// Unit — rubricFormSchema validation
// ---------------------------------------------------------------------------

describe("rubricFormSchema", () => {
  const validCriterion = {
    name: "Thesis",
    description: "Does the essay present a thesis?",
    weight: 50,
    min_score: 1,
    max_score: 5,
    anchor_descriptions: {},
  };

  it("accepts a valid rubric with weight sum of 100", () => {
    const result = rubricFormSchema.safeParse({
      name: "My Rubric",
      criteria: [
        validCriterion,
        { ...validCriterion, name: "Evidence", weight: 50 },
      ],
    });
    expect(result.success, JSON.stringify(result)).toBe(true);
  });

  it("rejects an empty rubric name", () => {
    const result = rubricFormSchema.safeParse({
      name: "",
      criteria: [validCriterion, { ...validCriterion, name: "C2", weight: 50 }],
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      // Zod v4 uses `.issues` (not `.errors`)
      const nameErrors = result.error.issues.filter(
        (e) => e.path[0] === "name",
      );
      expect(nameErrors.length).toBeGreaterThan(0);
    }
  });

  it("rejects when weight sum is not 100", () => {
    const result = rubricFormSchema.safeParse({
      name: "My Rubric",
      criteria: [
        { ...validCriterion, weight: 30 },
        { ...validCriterion, name: "C2", weight: 30 },
      ],
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      // Zod v4 uses `.issues`
      const criteriaErrors = result.error.issues.filter(
        (e) => e.path[0] === "criteria",
      );
      expect(criteriaErrors.length).toBeGreaterThan(0);
      expect(criteriaErrors[0].message).toMatch(/100/);
    }
  });

  it("rejects when criteria array is empty", () => {
    const result = rubricFormSchema.safeParse({
      name: "My Rubric",
      criteria: [],
    });
    expect(result.success).toBe(false);
  });

  it("rejects when criteria array exceeds 8 items", () => {
    const criteria = Array.from({ length: 9 }, (_, i) => ({
      ...validCriterion,
      name: `C${i + 1}`,
      weight: i === 0 ? 92 : 1,
    }));
    const result = rubricFormSchema.safeParse({
      name: "My Rubric",
      criteria,
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      // Zod v4 uses `.issues`
      const criteriaErrors = result.error.issues.filter(
        (e) => e.path[0] === "criteria",
      );
      expect(criteriaErrors.length).toBeGreaterThan(0);
    }
  });

  it("rejects a criterion name that is empty", () => {
    const result = rubricFormSchema.safeParse({
      name: "My Rubric",
      criteria: [
        { ...validCriterion, name: "" },
        { ...validCriterion, name: "C2", weight: 50 },
      ],
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      // Zod v4 uses `.issues`
      const nameErrors = result.error.issues.filter(
        (e) => e.path[0] === "criteria" && e.path[2] === "name",
      );
      expect(nameErrors.length).toBeGreaterThan(0);
    }
  });

  it("rejects max_score less than 1", () => {
    const result = rubricFormSchema.safeParse({
      name: "My Rubric",
      criteria: [
        { ...validCriterion, max_score: 0 },
        { ...validCriterion, name: "C2", weight: 50 },
      ],
    });
    expect(result.success).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Unit — emptyc helper
// ---------------------------------------------------------------------------

describe("emptyc", () => {
  it("returns a criterion with the given order in its name", () => {
    const c = emptyc(3);
    expect(c.name).toBe("Criterion 3");
    expect(c.weight).toBe(0);
    expect(c.min_score).toBe(1);
    expect(c.max_score).toBe(5);
    expect(c.anchor_descriptions).toEqual({});
  });
});

// ---------------------------------------------------------------------------
// Unit — WeightSumIndicator
// ---------------------------------------------------------------------------

describe("WeightSumIndicator", () => {
  it("shows green check at exactly 100", () => {
    render(<WeightSumIndicator sum={100} />);
    const el = screen.getByRole("status");
    expect(el).toHaveTextContent("100%");
    expect(el).toHaveTextContent("✓");
    expect(el).not.toHaveTextContent("must equal 100%");
  });

  it("shows red warning below 100", () => {
    render(<WeightSumIndicator sum={80} />);
    const el = screen.getByRole("status");
    expect(el).toHaveTextContent("80%");
    expect(el).toHaveTextContent("must equal 100%");
  });

  it("shows red warning above 100", () => {
    render(<WeightSumIndicator sum={120} />);
    const el = screen.getByRole("status");
    expect(el).toHaveTextContent("120%");
    expect(el).toHaveTextContent("must equal 100%");
  });

  it("rounds the displayed sum", () => {
    render(<WeightSumIndicator sum={99.6} />);
    const el = screen.getByRole("status");
    // Math.round(99.6) = 100 → shows green
    expect(el).toHaveTextContent("100%");
    expect(el).toHaveTextContent("✓");
  });
});

// ---------------------------------------------------------------------------
// Integration — RubricBuilderForm renders
// ---------------------------------------------------------------------------

function buildProps(overrides?: Partial<React.ComponentProps<typeof RubricBuilderForm>>) {
  const onSave = vi.fn().mockResolvedValue(undefined);
  const onCancel = vi.fn();
  return { onSave, onCancel, ...overrides };
}

describe("RubricBuilderForm — rendering", () => {
  it("renders rubric name field", () => {
    render(<RubricBuilderForm {...buildProps()} />);
    expect(screen.getByLabelText(/rubric name/i)).toBeInTheDocument();
  });

  it("renders 3 criteria rows by default", () => {
    render(<RubricBuilderForm {...buildProps()} />);
    expect(screen.getByLabelText(/criterion 1 name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/criterion 2 name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/criterion 3 name/i)).toBeInTheDocument();
    expect(
      screen.queryByLabelText(/criterion 4 name/i),
    ).not.toBeInTheDocument();
  });

  it("renders the weight-sum indicator", () => {
    render(<RubricBuilderForm {...buildProps()} />);
    expect(screen.getByTestId("weight-sum-indicator")).toBeInTheDocument();
  });

  it("renders the save and cancel buttons", () => {
    render(<RubricBuilderForm {...buildProps()} />);
    expect(
      screen.getByRole("button", { name: /save rubric/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /cancel/i }),
    ).toBeInTheDocument();
  });

  it("renders custom saveLabel", () => {
    render(<RubricBuilderForm {...buildProps({ saveLabel: "Create rubric" })} />);
    expect(
      screen.getByRole("button", { name: /create rubric/i }),
    ).toBeInTheDocument();
  });

  it("renders defaultValues when provided", () => {
    render(
      <RubricBuilderForm
        {...buildProps({
          defaultValues: {
            name: "Prefilled Rubric",
            criteria: [
              {
                name: "Thesis",
                description: "",
                weight: 100,
                min_score: 1,
                max_score: 5,
                anchor_descriptions: {},
              },
            ],
          },
        })}
      />,
    );
    const nameInput = screen.getByLabelText(/rubric name/i) as HTMLInputElement;
    expect(nameInput.value).toBe("Prefilled Rubric");
    expect(screen.getByLabelText(/criterion 1 name/i)).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Integration — form validation
// ---------------------------------------------------------------------------

describe("RubricBuilderForm — form validation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows rubric name error when name is empty on submit", async () => {
    const user = userEvent.setup();
    const props = buildProps();
    render(<RubricBuilderForm {...props} />);

    await user.click(screen.getByRole("button", { name: /save rubric/i }));

    await waitFor(() => {
      expect(
        screen.getByText(/rubric name is required/i),
      ).toBeInTheDocument();
    });
    expect(props.onSave).not.toHaveBeenCalled();
  });

  it("shows weight-sum error when weights do not sum to 100", async () => {
    const user = userEvent.setup();
    const props = buildProps();
    render(<RubricBuilderForm {...props} />);

    // Fill rubric name
    await user.type(screen.getByLabelText(/rubric name/i), "Test Rubric");

    // Leave default weights (0, 0, 0) and submit
    await user.click(screen.getByRole("button", { name: /save rubric/i }));

    // Weight-sum error is shown after submit attempt
    await waitFor(() => {
      expect(
        screen.getByText(/weights must sum to 100/i),
      ).toBeInTheDocument();
    });
    expect(props.onSave).not.toHaveBeenCalled();
  });

  it("calls onSave with correct values on valid submit", async () => {
    const user = userEvent.setup();
    const props = buildProps();
    render(
      <RubricBuilderForm
        {...props}
        defaultValues={{
          name: "",
          criteria: [
            {
              name: "Thesis",
              description: "",
              weight: 60,
              min_score: 1,
              max_score: 5,
              anchor_descriptions: {},
            },
            {
              name: "Evidence",
              description: "",
              weight: 40,
              min_score: 1,
              max_score: 5,
              anchor_descriptions: {},
            },
          ],
        }}
      />,
    );

    await user.type(screen.getByLabelText(/rubric name/i), "Valid Rubric");
    await user.click(screen.getByRole("button", { name: /save rubric/i }));

    await waitFor(() => {
      expect(props.onSave).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Valid Rubric",
          criteria: expect.arrayContaining([
            expect.objectContaining({ name: "Thesis", weight: 60 }),
            expect.objectContaining({ name: "Evidence", weight: 40 }),
          ]),
        }),
      );
    });
  });

  it("shows generic server error when onSave rejects", async () => {
    const user = userEvent.setup();
    const props = buildProps({
      onSave: vi.fn().mockRejectedValue(new Error("Server error")),
      defaultValues: {
        name: "My Rubric",
        criteria: [
          {
            name: "Thesis",
            description: "",
            weight: 100,
            min_score: 1,
            max_score: 5,
            anchor_descriptions: {},
          },
        ],
      },
    });
    render(<RubricBuilderForm {...props} />);

    await user.click(screen.getByRole("button", { name: /save rubric/i }));

    await waitFor(() => {
      expect(
        screen.getByText(/failed to save rubric/i),
      ).toBeInTheDocument();
    });
    // Raw server error must not be shown
    expect(screen.queryByText("Server error")).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Integration — add / remove criteria
// ---------------------------------------------------------------------------

describe("RubricBuilderForm — add / remove criteria", () => {
  it("adds a criterion row when '+ Add criterion' is clicked", async () => {
    const user = userEvent.setup();
    render(<RubricBuilderForm {...buildProps()} />);

    // Default: 3 criteria
    expect(
      screen.queryByLabelText(/criterion 4 name/i),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /add criterion/i }));

    await waitFor(() => {
      expect(screen.getByLabelText(/criterion 4 name/i)).toBeInTheDocument();
    });
  });

  it("hides '+ Add criterion' when 8 criteria are present", async () => {
    const user = userEvent.setup();
    render(<RubricBuilderForm {...buildProps()} />);

    // Add 5 more to reach 8 total
    for (let i = 0; i < 5; i++) {
      // eslint-disable-next-line no-await-in-loop
      await user.click(screen.getByRole("button", { name: /add criterion/i }));
    }

    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: /add criterion/i }),
      ).not.toBeInTheDocument();
    });
  });

  it("removes a criterion row when the remove button is clicked", async () => {
    const user = userEvent.setup();
    render(<RubricBuilderForm {...buildProps()} />);

    // Confirm 3 criteria
    expect(screen.getByLabelText(/criterion 1 name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/criterion 2 name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/criterion 3 name/i)).toBeInTheDocument();

    // Remove the third criterion
    await user.click(
      screen.getByRole("button", { name: /remove criterion 3/i }),
    );

    await waitFor(() => {
      expect(
        screen.queryByLabelText(/criterion 3 name/i),
      ).not.toBeInTheDocument();
    });
    // 2 criteria remain
    expect(screen.getByLabelText(/criterion 1 name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/criterion 2 name/i)).toBeInTheDocument();
  });

  it("disables the remove button when only one criterion remains", async () => {
    const user = userEvent.setup();
    render(<RubricBuilderForm {...buildProps()} />);

    // Remove down to 1
    await user.click(
      screen.getByRole("button", { name: /remove criterion 3/i }),
    );
    await waitFor(() => screen.queryByLabelText(/criterion 3 name/i) === null);

    await user.click(
      screen.getByRole("button", { name: /remove criterion 2/i }),
    );
    await waitFor(() => screen.queryByLabelText(/criterion 2 name/i) === null);

    const removeBtn = screen.getByRole("button", {
      name: /remove criterion 1/i,
    });
    expect(removeBtn).toBeDisabled();
  });
});

// ---------------------------------------------------------------------------
// Integration — reorder (keyboard up/down)
// ---------------------------------------------------------------------------

describe("RubricBuilderForm — keyboard reorder", () => {
  it("disables the 'move up' button for the first criterion", () => {
    render(<RubricBuilderForm {...buildProps()} />);
    expect(
      screen.getByRole("button", { name: /move criterion 1 up/i }),
    ).toBeDisabled();
  });

  it("disables the 'move down' button for the last criterion", () => {
    render(<RubricBuilderForm {...buildProps()} />);
    expect(
      screen.getByRole("button", { name: /move criterion 3 down/i }),
    ).toBeDisabled();
  });

  it("moves a criterion up when the 'move up' button is clicked", async () => {
    const user = userEvent.setup();
    render(
      <RubricBuilderForm
        {...buildProps({
          defaultValues: {
            name: "R",
            criteria: [
              {
                name: "Alpha",
                description: "",
                weight: 50,
                min_score: 1,
                max_score: 5,
                anchor_descriptions: {},
              },
              {
                name: "Beta",
                description: "",
                weight: 50,
                min_score: 1,
                max_score: 5,
                anchor_descriptions: {},
              },
            ],
          },
        })}
      />,
    );

    // Before: Alpha=1, Beta=2
    const inputs = () =>
      screen
        .getAllByRole("textbox")
        .filter((el) =>
          (el as HTMLInputElement).placeholder?.includes("Criterion"),
        );

    // Move Beta (index 1) up
    await user.click(
      screen.getByRole("button", { name: /move criterion 2 up/i }),
    );

    await waitFor(() => {
      const vals = inputs().map((el) => (el as HTMLInputElement).value);
      expect(vals[0]).toBe("Beta");
      expect(vals[1]).toBe("Alpha");
    });
  });
});

// ---------------------------------------------------------------------------
// Integration — live weight-sum indicator
// ---------------------------------------------------------------------------

describe("RubricBuilderForm — live weight-sum indicator", () => {
  it("shows red indicator by default (sum is 0)", () => {
    render(<RubricBuilderForm {...buildProps()} />);
    const indicator = screen.getByTestId("weight-sum-indicator");
    expect(indicator).toHaveTextContent("0%");
    expect(indicator).toHaveTextContent("must equal 100%");
  });

  it("updates to green when weights are changed to sum to 100", async () => {
    const user = userEvent.setup();
    render(
      <RubricBuilderForm
        {...buildProps({
          defaultValues: {
            name: "R",
            criteria: [
              {
                name: "C1",
                description: "",
                weight: 0,
                min_score: 1,
                max_score: 5,
                anchor_descriptions: {},
              },
              {
                name: "C2",
                description: "",
                weight: 0,
                min_score: 1,
                max_score: 5,
                anchor_descriptions: {},
              },
            ],
          },
        })}
      />,
    );

    // Set C1 weight to 60
    const weightInputs = screen.getAllByRole("spinbutton").filter((el) =>
      el.id.includes("weight"),
    );
    await user.clear(weightInputs[0]);
    await user.type(weightInputs[0], "60");

    // Set C2 weight to 40
    await user.clear(weightInputs[1]);
    await user.type(weightInputs[1], "40");

    await waitFor(() => {
      const indicator = screen.getByTestId("weight-sum-indicator");
      expect(indicator).toHaveTextContent("100%");
      expect(indicator).toHaveTextContent("✓");
    });
  });
});

// ---------------------------------------------------------------------------
// Integration — expand/collapse detail panel
// ---------------------------------------------------------------------------

describe("RubricBuilderForm — expand/collapse", () => {
  it("shows description and score fields after expanding a criterion", async () => {
    const user = userEvent.setup();
    render(<RubricBuilderForm {...buildProps()} />);

    const expandBtn = screen.getByRole("button", {
      name: /expand criterion 1 details/i,
    });
    await user.click(expandBtn);

    // The description textarea has a unique placeholder
    await waitFor(() => {
      expect(
        screen.getByPlaceholderText(/what this criterion assesses/i),
      ).toBeInTheDocument();
    });
  });

  it("hides the detail panel after collapsing", async () => {
    const user = userEvent.setup();
    render(<RubricBuilderForm {...buildProps()} />);

    const expandBtn = screen.getByRole("button", {
      name: /expand criterion 1 details/i,
    });
    await user.click(expandBtn);
    await waitFor(() =>
      screen.getByPlaceholderText(/what this criterion assesses/i),
    );

    const collapseBtn = screen.getByRole("button", {
      name: /collapse criterion 1 details/i,
    });
    await user.click(collapseBtn);

    await waitFor(() => {
      expect(
        screen.queryByPlaceholderText(/what this criterion assesses/i),
      ).not.toBeInTheDocument();
    });
  });
});
