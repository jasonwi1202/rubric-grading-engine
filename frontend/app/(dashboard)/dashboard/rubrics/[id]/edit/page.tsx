"use client";

/**
 * /dashboard/rubrics/[id]/edit — Edit an existing rubric.
 *
 * Fetches the rubric by ID on mount, then renders the RubricBuilderForm
 * pre-populated with the existing values.
 *
 * Security: no student PII is handled here.
 */

import { useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import {
  RubricBuilderForm,
  apiCriteriaToFormCriteria,
} from "@/components/rubric/RubricBuilderForm";
import type { RubricFormValues } from "@/components/rubric/RubricBuilderForm";
import { getRubric, updateRubric } from "@/lib/api/rubrics";
import type { RubricDetailResponse } from "@/lib/api/rubrics";
import { ApiError } from "@/lib/api/errors";

export default function EditRubricPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const rubricId = params.id;

  const [rubric, setRubric] = useState<RubricDetailResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!rubricId) return;

    getRubric(rubricId)
      .then((data) => setRubric(data))
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          router.replace(`/login?next=/dashboard/rubrics/${rubricId}/edit`);
        } else if (err instanceof ApiError && err.status === 403) {
          router.replace("/dashboard/rubrics");
        } else {
          setLoadError("Could not load rubric. Please try again.");
        }
      })
      .finally(() => setLoading(false));
  }, [rubricId, router]);

  const handleSave = async (values: RubricFormValues) => {
    try {
      await updateRubric(rubricId, {
        name: values.name,
        criteria: values.criteria,
      });
      router.push("/dashboard/rubrics");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.replace(`/login?next=/dashboard/rubrics/${rubricId}/edit`);
        return;
      }
      // Re-throw so RubricBuilderForm can show a generic error message.
      throw err;
    }
  };

  // ---------------------------------------------------------------------------
  // Loading / error states
  // ---------------------------------------------------------------------------

  if (loading) {
    return (
      <main className="mx-auto max-w-2xl px-4 py-10">
        <div className="h-8 w-48 animate-pulse rounded bg-gray-200" />
        <div className="mt-6 space-y-3">
          {[1, 2, 3].map((n) => (
            <div key={n} className="h-12 animate-pulse rounded bg-gray-100" />
          ))}
        </div>
      </main>
    );
  }

  if (loadError || !rubric) {
    return (
      <main className="mx-auto max-w-2xl px-4 py-10">
        <p className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
          {loadError ?? "Rubric not found."}
        </p>
        <button
          type="button"
          onClick={() => router.push("/dashboard/rubrics")}
          className="mt-4 text-sm text-blue-600 underline hover:text-blue-800 focus:outline-none focus:ring-2 focus:ring-blue-500 rounded"
        >
          Back to rubrics
        </button>
      </main>
    );
  }

  // Sorted by display_order
  const sortedCriteria = [...rubric.criteria].sort(
    (a, b) => a.display_order - b.display_order,
  );

  const defaultValues: RubricFormValues = {
    name: rubric.name,
    criteria: apiCriteriaToFormCriteria(sortedCriteria),
  };

  return (
    <main className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Edit rubric</h1>
        <p className="mt-1 text-sm text-gray-500">
          Changes apply to future assignments only — existing grades are
          unaffected.
        </p>
      </div>

      <div className="rounded-lg bg-white p-6 shadow-sm border border-gray-200">
        <RubricBuilderForm
          defaultValues={defaultValues}
          onSave={handleSave}
          onCancel={() => router.push("/dashboard/rubrics")}
          saveLabel="Save changes"
        />
      </div>
    </main>
  );
}
