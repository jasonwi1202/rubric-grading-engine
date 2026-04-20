"use client";

/**
 * TemplatePicker — modal dialog for choosing a rubric starter template.
 *
 * Features:
 * - Lists system templates and the teacher's personal saved templates.
 * - Clicking a template row shows a preview panel with the criteria list.
 * - "Apply template" pre-fills the rubric builder form (does NOT auto-save).
 * - Keyboard accessible: template rows are reachable via standard button
 *   focus, and Escape closes the dialog.
 *
 * Security: no student PII is handled here.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listRubricTemplates, getRubricTemplate } from "@/lib/api/rubric-templates";
import type { RubricTemplateListItem } from "@/lib/api/rubric-templates";
import type { RubricFormValues } from "@/components/rubric/RubricBuilderForm";
import { apiCriteriaToFormCriteria } from "@/components/rubric/RubricBuilderForm";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface TemplatePickerProps {
  /** Called with form values to pre-fill the builder. Does not save. */
  onApply: (values: Partial<RubricFormValues>) => void;
  /** Called when the user dismisses the picker without choosing. */
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TemplatePicker({ onApply, onClose }: TemplatePickerProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [isApplying, setIsApplying] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);

  // Fetch the template list.
  const {
    data: templates,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["rubric-templates"],
    queryFn: listRubricTemplates,
    staleTime: 5 * 60 * 1000, // 5 min — template list is stable
  });

  // Fetch the selected template's full criteria for preview.
  const {
    data: previewRubric,
    isLoading: isPreviewLoading,
  } = useQuery({
    queryKey: ["rubric-template", selectedId],
    queryFn: () => getRubricTemplate(selectedId!),
    enabled: selectedId !== null,
    staleTime: 5 * 60 * 1000,
  });

  const selectedTemplate = templates?.find((t) => t.id === selectedId) ?? null;

  const handleApply = async () => {
    if (!selectedId || !previewRubric) return;
    setApplyError(null);
    setIsApplying(true);
    try {
      onApply({
        name: previewRubric.name,
        criteria: apiCriteriaToFormCriteria(previewRubric.criteria),
      });
      onClose();
    } catch {
      setApplyError("Failed to apply template. Please try again.");
    } finally {
      setIsApplying(false);
    }
  };

  // Group templates by system vs personal.
  const systemTemplates = templates?.filter((t) => t.is_system) ?? [];
  const personalTemplates = templates?.filter((t) => !t.is_system) ?? [];

  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Choose a rubric template"
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
    >
      <div className="flex h-full max-h-[600px] w-full max-w-3xl flex-col rounded-xl bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">
            Choose a template
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close template picker"
            className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <svg
              className="h-5 w-5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="flex min-h-0 flex-1">
          {/* Template list */}
          <div className="w-56 shrink-0 overflow-y-auto border-r border-gray-200 py-3">
            {isLoading && (
              <p className="px-4 py-2 text-sm text-gray-400">Loading…</p>
            )}
            {isError && (
              <p className="px-4 py-2 text-sm text-red-600">
                Failed to load templates.
              </p>
            )}
            {!isLoading && !isError && templates?.length === 0 && (
              <p className="px-4 py-2 text-sm text-gray-400">
                No templates available.
              </p>
            )}

            {systemTemplates.length > 0 && (
              <div>
                <p className="mb-1 px-4 text-xs font-semibold uppercase tracking-wider text-gray-400">
                  Starter templates
                </p>
                <TemplateList
                  items={systemTemplates}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                />
              </div>
            )}

            {personalTemplates.length > 0 && (
              <div className={systemTemplates.length > 0 ? "mt-4" : ""}>
                <p className="mb-1 px-4 text-xs font-semibold uppercase tracking-wider text-gray-400">
                  My templates
                </p>
                <TemplateList
                  items={personalTemplates}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                />
              </div>
            )}
          </div>

          {/* Preview panel */}
          <div className="flex flex-1 flex-col overflow-y-auto p-6">
            {!selectedTemplate && (
              <div className="flex flex-1 flex-col items-center justify-center text-center">
                <p className="text-sm text-gray-400">
                  Select a template on the left to preview its criteria.
                </p>
              </div>
            )}

            {selectedTemplate && (
              <div>
                <h3 className="mb-1 text-base font-semibold text-gray-900">
                  {selectedTemplate.name}
                </h3>
                {selectedTemplate.description && (
                  <p className="mb-4 text-sm text-gray-500">
                    {selectedTemplate.description}
                  </p>
                )}

                {isPreviewLoading && (
                  <div className="space-y-2" aria-live="polite" aria-label="Loading criteria">
                    {Array.from({ length: selectedTemplate.criterion_count }).map(
                      (_, i) => (
                        <div
                          key={i}
                          className="h-10 animate-pulse rounded-md bg-gray-100"
                          aria-hidden="true"
                        />
                      ),
                    )}
                  </div>
                )}

                {previewRubric && !isPreviewLoading && (
                  <div>
                    <p className="mb-2 text-xs font-medium uppercase tracking-wider text-gray-400">
                      Criteria ({previewRubric.criteria.length})
                    </p>
                    <ul className="space-y-2" aria-label="Template criteria">
                      {previewRubric.criteria.map((c) => (
                        <li
                          key={c.id}
                          className="flex items-start justify-between rounded-md border border-gray-200 px-3 py-2 text-sm"
                        >
                          <div>
                            <p className="font-medium text-gray-800">{c.name}</p>
                            {c.description && (
                              <p className="mt-0.5 text-xs text-gray-500">
                                {c.description}
                              </p>
                            )}
                          </div>
                          <span className="ml-4 shrink-0 rounded bg-gray-100 px-2 py-0.5 text-xs font-semibold text-gray-600">
                            {c.weight}%
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-gray-200 px-6 py-4">
          {applyError && (
            <p className="text-sm text-red-600" role="alert">
              {applyError}
            </p>
          )}
          {!applyError && <span />}
          <div className="flex gap-3">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleApply}
              disabled={!selectedId || isPreviewLoading || isApplying}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50"
            >
              {isApplying ? "Applying…" : "Apply template"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// TemplateList sub-component
// ---------------------------------------------------------------------------

interface TemplateListProps {
  items: RubricTemplateListItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

function TemplateList({ items, selectedId, onSelect }: TemplateListProps) {
  return (
    <ul role="list" aria-label="Templates">
      {items.map((t) => (
        <li key={t.id}>
          <button
            type="button"
            onClick={() => onSelect(t.id)}
            aria-pressed={t.id === selectedId}
            className={`w-full px-4 py-2 text-left text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-inset focus:ring-blue-500 ${
              t.id === selectedId
                ? "bg-blue-50 font-medium text-blue-700"
                : "text-gray-700 hover:bg-gray-50"
            }`}
          >
            {t.name}
            <span className="ml-1 text-xs text-gray-400">
              ({t.criterion_count})
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
