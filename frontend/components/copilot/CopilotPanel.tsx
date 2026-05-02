"use client";

/**
 * CopilotPanel — Teacher copilot conversational UI (M7-04).
 *
 * Presents a conversational input surface for teacher prompts and displays
 * structured, linkable responses. Responses render in ranked-list, summary,
 * or recommendation formats with traceable evidence context.
 *
 * Key behaviours:
 *   - Text input for teacher natural-language questions.
 *   - Optional class scope selector (all classes or a specific class).
 *   - Structured response rendering: ranked list, summary, next steps.
 *   - Link-through navigation to relevant student profiles.
 *   - Conversation history displayed as an exchange thread.
 *   - Read-only: no grade changes or autonomous actions are ever triggered.
 *
 * Accessibility:
 *   - Full keyboard navigation (Tab, Enter, Escape).
 *   - aria-live region announces responses to screen readers.
 *   - Focus is managed appropriately on form submission.
 *   - All interactive elements have accessible labels.
 *
 * Security:
 *   - No student PII in query keys — entity IDs only.
 *   - Error messages are static strings; raw server text is never rendered.
 *   - No student data written to localStorage or sessionStorage.
 */

import { useState, useRef, useId, useEffect } from "react";
import Link from "next/link";
import { useQuery, useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { listClasses } from "@/lib/api/classes";
import { queryCopilot } from "@/lib/api/copilot";
import type { CopilotQueryResponse, CopilotRankedItem } from "@/lib/api/copilot";
import { ApiError } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const QUERY_MAX_LENGTH = 500;

/** Example prompts displayed when the conversation is empty. */
const EXAMPLE_PROMPTS = [
  "Who is falling behind on thesis development?",
  "What should I teach tomorrow based on this week's essays?",
  "Which students haven't improved since my last feedback?",
  "Which skill gaps are most common across my class?",
  "Which students are showing the most improvement recently?",
];

// ---------------------------------------------------------------------------
// Form schema — max_length matches backend CopilotQueryRequest
// ---------------------------------------------------------------------------

const querySchema = z.object({
  query: z
    .string()
    .min(1, "Please enter a question.")
    .max(QUERY_MAX_LENGTH, `Question must be ${QUERY_MAX_LENGTH} characters or fewer.`)
    .refine((v) => v.trim().length > 0, "Question must not be blank."),
  class_id: z.string().nullable().optional(),
});

type QueryFormValues = z.infer<typeof querySchema>;

// ---------------------------------------------------------------------------
// Conversation history types
// ---------------------------------------------------------------------------

interface ConversationTurn {
  id: string;
  query: string;
  class_id: string | null;
  class_name: string | null;
  response: CopilotQueryResponse;
  timestamp: Date;
}

// ---------------------------------------------------------------------------
// Error helpers
// ---------------------------------------------------------------------------

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 404) return "Class not found. Please select a different class.";
    if (err.status === 403) return "You do not have access to this class.";
    if (err.status === 503)
      return "The AI service is temporarily unavailable. Please try again shortly.";
    if (err.status === 422)
      return "Your question could not be processed. Please check and try again.";
  }
  return "An error occurred. Please try again.";
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Renders a single ranked item with optional student or skill-level link. */
function RankedItemRow({
  item,
  rank,
}: {
  item: CopilotRankedItem;
  rank: number;
}) {
  const percentValue =
    item.value !== null ? Math.round(item.value * 100) : null;

  return (
    <li className="flex gap-3 py-2">
      {/* Rank number */}
      <span
        className="mt-0.5 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-blue-100 text-xs font-semibold text-blue-700"
        aria-hidden="true"
      >
        {rank}
      </span>

      <div className="min-w-0 flex-1">
        {/* Label + optional signal strength */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-gray-900">{item.label}</span>
          {item.skill_dimension && (
            <span className="rounded-full bg-purple-100 px-2 py-0.5 text-xs font-medium text-purple-700">
              {item.skill_dimension}
            </span>
          )}
          {percentValue !== null && (
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
              {percentValue}%
            </span>
          )}
        </div>

        {/* Explanation */}
        <p className="mt-0.5 text-sm text-gray-600">{item.explanation}</p>

        {/* Student profile link — uses student_id UUID; no PII in URL */}
        {item.student_id && (
          <Link
            href={`/dashboard/students/${item.student_id}`}
            className="mt-1 inline-block rounded text-xs font-medium text-blue-600 underline hover:text-blue-800 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1"
            aria-label={`View student profile${
              item.student_display_name ? ` for ${item.student_display_name}` : ""
            }`}
          >
            View student profile →
          </Link>
        )}
      </div>
    </li>
  );
}

/** Renders the structured copilot response for one conversation turn. */
function CopilotResponse({ response }: { response: CopilotQueryResponse }) {
  return (
    <div className="space-y-4">
      {/* Query interpretation */}
      <p className="text-xs italic text-gray-500">{response.query_interpretation}</p>

      {/* Insufficient data warning */}
      {!response.has_sufficient_data && response.uncertainty_note && (
        <div
          role="note"
          className="rounded-md border border-yellow-200 bg-yellow-50 px-3 py-2 text-sm text-yellow-800"
        >
          <span className="font-semibold">Limited data: </span>
          {response.uncertainty_note}
        </div>
      )}

      {/* Summary */}
      {response.summary && (
        <p className="text-sm text-gray-800">{response.summary}</p>
      )}

      {/* Ranked list */}
      {response.response_type === "ranked_list" &&
        response.ranked_items.length > 0 && (
          <div>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
              Top results
            </h4>
            <ol
              className="divide-y divide-gray-100"
              aria-label="Ranked results from copilot"
            >
              {response.ranked_items.map((item, idx) => (
                <RankedItemRow
                  key={`${item.student_id ?? item.skill_dimension ?? idx}-${idx}`}
                  item={item}
                  rank={idx + 1}
                />
              ))}
            </ol>
          </div>
        )}

      {/* Suggested next steps */}
      {response.suggested_next_steps.length > 0 && (
        <div>
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500">
            Suggested next steps
          </h4>
          <ul
            className="list-inside list-disc space-y-1"
            aria-label="Suggested next steps"
          >
            {response.suggested_next_steps.map((step, i) => (
              <li key={i} className="text-sm text-gray-700">
                {step}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Prompt version footer */}
      <p className="text-xs text-gray-400">
        Model: {response.prompt_version} · Read-only — no actions taken
      </p>
    </div>
  );
}

/** A single exchange in the conversation thread. */
function ConversationTurnCard({ turn }: { turn: ConversationTurn }) {
  const timeLabel = turn.timestamp.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div className="space-y-3">
      {/* Teacher query bubble */}
      <div className="flex justify-end">
        <div className="max-w-xs rounded-2xl rounded-tr-sm bg-blue-600 px-4 py-2 text-sm text-white sm:max-w-sm">
          <p>{turn.query}</p>
          {turn.class_name && (
            <p className="mt-1 text-xs text-blue-200">Scoped to: {turn.class_name}</p>
          )}
          <p className="mt-1 text-xs text-blue-300">{timeLabel}</p>
        </div>
      </div>

      {/* Copilot response */}
      <div className="rounded-2xl rounded-tl-sm border border-gray-200 bg-white px-4 py-3 shadow-sm">
        <div className="mb-2 flex items-center gap-2">
          <span
            className="flex h-5 w-5 items-center justify-center rounded-full bg-indigo-100 text-xs"
            aria-hidden="true"
          >
            ✦
          </span>
          <span className="text-xs font-semibold text-gray-500">Copilot</span>
        </div>
        <CopilotResponse response={turn.response} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function CopilotPanel() {
  const formId = useId();
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const [history, setHistory] = useState<ConversationTurn[]>([]);

  // ----- Class list for scope selector -----
  const { data: classes } = useQuery({
    queryKey: ["classes", { is_archived: false }],
    queryFn: () => listClasses({ is_archived: false }),
  });

  // ----- Form -----
  const {
    register,
    handleSubmit,
    reset,
    watch,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<QueryFormValues>({
    resolver: zodResolver(querySchema),
    defaultValues: { query: "", class_id: null },
  });

  const queryValue = watch("query");
  const charsRemaining = QUERY_MAX_LENGTH - (queryValue?.length ?? 0);

  // ----- Register textarea with merged ref -----
  const { ref: formRef, ...queryRegisterRest } = register("query");

  // ----- Mutation -----
  const mutation = useMutation({
    mutationFn: (values: QueryFormValues) =>
      queryCopilot({
        query: values.query,
        class_id: values.class_id ?? null,
      }),
    onSuccess: (data, variables) => {
      const selectedClass = classes?.find((c) => c.id === variables.class_id);
      const turn: ConversationTurn = {
        id: crypto.randomUUID(),
        query: variables.query,
        class_id: variables.class_id ?? null,
        class_name: selectedClass?.name ?? null,
        response: data,
        timestamp: new Date(),
      };
      setHistory((prev) => [...prev, turn]);
      reset({ query: "", class_id: variables.class_id ?? null });
      // Scroll to the new response, respecting prefers-reduced-motion.
      // Guard against jsdom / environments where matchMedia is not implemented.
      const mediaQuery =
        typeof window !== "undefined" &&
        typeof window.matchMedia === "function"
          ? window.matchMedia("(prefers-reduced-motion: reduce)")
          : null;
      const prefersReduced = mediaQuery?.matches ?? false;
      if (!prefersReduced) {
        setTimeout(() => {
          bottomRef.current?.scrollIntoView?.({ behavior: "smooth" });
        }, 50);
      }
    },
  });

  // Scroll to bottom whenever history grows, respecting prefers-reduced-motion.
  // Guard against jsdom / environments where matchMedia is not implemented.
  useEffect(() => {
    if (history.length > 0) {
      const mediaQuery =
        typeof window !== "undefined" &&
        typeof window.matchMedia === "function"
          ? window.matchMedia("(prefers-reduced-motion: reduce)")
          : null;
      const prefersReduced = mediaQuery?.matches ?? false;
      if (!prefersReduced) {
        bottomRef.current?.scrollIntoView?.({ behavior: "smooth" });
      }
    }
  }, [history.length]);

  const onSubmit = handleSubmit((values) => {
    mutation.mutate(values);
  });

  const onExampleClick = (example: string) => {
    setValue("query", example, { shouldValidate: false });
    inputRef.current?.focus();
  };

  return (
    <div className="flex h-full flex-col">
      {/* Read-only notice */}
      <div
        role="note"
        className="mb-4 flex items-start gap-2 rounded-md border border-indigo-100 bg-indigo-50 px-3 py-2 text-xs text-indigo-700"
      >
        <span aria-hidden="true" className="flex-shrink-0">
          🔍
        </span>
        <span>
          The copilot surfaces information only — it never changes grades or
          triggers actions without your explicit confirmation.
        </span>
      </div>

      {/* Conversation thread */}
      <div
        className="min-h-0 flex-1 overflow-y-auto space-y-6 pb-4"
        role="log"
        aria-label="Copilot conversation"
        aria-live="polite"
        aria-atomic="false"
        aria-relevant="additions"
      >
        {history.length === 0 && !mutation.isPending && (
          <div className="space-y-4">
            {/* Welcome message */}
            <div className="rounded-2xl rounded-tl-sm border border-gray-200 bg-white px-4 py-3 shadow-sm">
              <div className="mb-2 flex items-center gap-2">
                <span
                  className="flex h-5 w-5 items-center justify-center rounded-full bg-indigo-100 text-xs"
                  aria-hidden="true"
                >
                  ✦
                </span>
                <span className="text-xs font-semibold text-gray-500">Copilot</span>
              </div>
              <p className="text-sm text-gray-700">
                Hi! Ask me anything about your class data. I can help you
                identify students who need attention, surface skill gaps, and
                suggest instructional focus areas.
              </p>
            </div>

            {/* Example prompts */}
            <div>
              <p className="mb-2 text-xs text-gray-500">Try asking:</p>
              <ul className="space-y-1.5" aria-label="Example questions">
                {EXAMPLE_PROMPTS.map((prompt) => (
                  <li key={prompt}>
                    <button
                      type="button"
                      onClick={() => onExampleClick(prompt)}
                      className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-left text-sm text-gray-700 hover:border-blue-300 hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      {prompt}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}

        {history.map((turn) => (
          <ConversationTurnCard key={turn.id} turn={turn} />
        ))}

        {/* Loading indicator while mutation is pending */}
        {mutation.isPending && (
          <div
            role="status"
            className="flex items-center gap-2 text-sm text-gray-500"
          >
            <span
              className="flex h-5 w-5 items-center justify-center rounded-full bg-indigo-100 text-xs"
              aria-hidden="true"
            >
              ✦
            </span>
            <span>Thinking…</span>
            <span className="inline-flex gap-0.5" aria-hidden="true">
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-gray-400 [animation-delay:-0.3s]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-gray-400 [animation-delay:-0.15s]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-gray-400" />
            </span>
          </div>
        )}

        {/* Scroll anchor */}
        <div ref={bottomRef} />
      </div>

      {/* Input form */}
      <div className="border-t border-gray-200 pt-4 space-y-2">
        {/* Error alert */}
        {mutation.isError && (
          <p role="alert" className="text-xs text-red-600">
            {errorMessage(mutation.error)}
          </p>
        )}

        <form onSubmit={onSubmit} id={formId} noValidate className="space-y-2">
          {/* Class scope selector */}
          {classes && classes.length > 0 && (
            <div>
              <label
                htmlFor={`${formId}-class`}
                className="block text-xs font-medium text-gray-600"
              >
                Scope (optional)
              </label>
              <select
                id={`${formId}-class`}
                {...register("class_id")}
                className="mt-1 block w-full rounded border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">All classes</option>
                {classes.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Query textarea */}
          <div>
            <label
              htmlFor={`${formId}-query`}
              className="block text-xs font-medium text-gray-600"
            >
              Your question
            </label>
            <textarea
              id={`${formId}-query`}
              rows={3}
              placeholder="Ask about your class data…"
              aria-describedby={
                errors.query
                  ? `${formId}-query-error`
                  : `${formId}-chars-remaining`
              }
              aria-invalid={errors.query ? "true" : undefined}
              className="mt-1 block w-full resize-none rounded border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
              disabled={mutation.isPending || isSubmitting}
              {...queryRegisterRest}
              ref={(el) => {
                formRef(el);
                inputRef.current = el;
              }}
              onKeyDown={(e) => {
                // Cmd/Ctrl+Enter submits the form
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  void onSubmit(e);
                }
              }}
            />
            {errors.query ? (
              <p
                id={`${formId}-query-error`}
                role="alert"
                className="mt-1 text-xs text-red-600"
              >
                {errors.query.message}
              </p>
            ) : (
              <p
                id={`${formId}-chars-remaining`}
                className="mt-0.5 text-right text-xs text-gray-400"
                aria-label={`${charsRemaining} characters remaining`}
              >
                {charsRemaining} remaining
              </p>
            )}
          </div>

          {/* Submit */}
          <div className="flex items-center justify-between">
            {/* Clear history — only shown when there is history */}
            {history.length > 0 ? (
              <button
                type="button"
                onClick={() => setHistory([])}
                className="rounded text-xs text-gray-400 underline hover:text-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                Clear conversation
              </button>
            ) : (
              <span />
            )}

            <button
              type="submit"
              disabled={mutation.isPending || isSubmitting}
              className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 disabled:opacity-50"
            >
              {mutation.isPending ? (
                <>
                  <span className="sr-only">Loading</span>
                  <span aria-hidden="true">…</span>
                  Thinking
                </>
              ) : (
                <>
                  Ask
                  <kbd
                    className="text-xs text-blue-200"
                    aria-label="keyboard shortcut: command or control and enter"
                  >
                    ⌘↵
                  </kbd>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
