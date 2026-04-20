"use client";

/**
 * /dashboard/rubrics/new — Create a new rubric.
 *
 * Security: no student PII is handled here.
 */

import { useRouter } from "next/navigation";
import { RubricBuilderForm } from "@/components/rubric/RubricBuilderForm";
import type { RubricFormValues } from "@/components/rubric/RubricBuilderForm";
import { createRubric } from "@/lib/api/rubrics";
import { ApiError } from "@/lib/api/errors";

export default function NewRubricPage() {
  const router = useRouter();

  const handleSave = async (values: RubricFormValues) => {
    try {
      await createRubric({
        name: values.name,
        criteria: values.criteria,
      });
      router.push("/dashboard");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.replace("/login?next=/dashboard/rubrics/new");
        return;
      }
      // Re-throw so RubricBuilderForm can show a generic error message.
      throw err;
    }
  };

  return (
    <main className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">New rubric</h1>
        <p className="mt-1 text-sm text-gray-500">
          Define the criteria that the AI will use to evaluate student writing.
        </p>
      </div>

      <div className="rounded-lg bg-white p-6 shadow-sm border border-gray-200">
        <RubricBuilderForm
          onSave={handleSave}
          onCancel={() => router.push("/dashboard")}
          saveLabel="Create rubric"
        />
      </div>
    </main>
  );
}
