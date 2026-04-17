import type { Metadata } from "next";
import { PRODUCT_NAME, SUPPORT_EMAIL } from "@/lib/constants";
import { AttorneyDraftBanner } from "@/components/legal/AttorneyDraftBanner";
import { LegalPageShell } from "@/components/legal/LegalPageShell";

export const metadata: Metadata = {
  title: `AI Use Policy — ${PRODUCT_NAME}`,
  description: `AI Use Policy for ${PRODUCT_NAME} — how artificial intelligence is used in our grading service.`,
};

export default function AiPolicyPage() {
  return (
    <LegalPageShell
      title="AI Use Policy"
      lastUpdated="2026-01-01"
      version="1.0-draft"
    >
      <AttorneyDraftBanner />

      <div className="prose prose-gray max-w-none print:prose-sm">
        <h2>1. What AI Is Used For</h2>
        <p>
          {PRODUCT_NAME} uses artificial intelligence to:
        </p>
        <ul>
          <li>Generate per-criterion grade suggestions and score ranges for student essays</li>
          <li>Draft written feedback suggestions for teacher review</li>
          <li>Surface instructional recommendations based on student skill patterns</li>
        </ul>

        <h2>2. What AI Is Not Used For</h2>
        <ul>
          <li>
            <strong>No AI makes final grading decisions.</strong> Every
            AI-generated grade is a suggestion that must be reviewed and
            approved by the teacher before it is recorded.
          </li>
          <li>
            <strong>No AI takes action without teacher approval.</strong> The
            system enforces human review at every consequential step.
          </li>
          <li>
            <strong>AI does not communicate with students.</strong> AI-generated
            feedback is delivered to the teacher, not directly to students.
          </li>
        </ul>

        <h2>3. Model Providers</h2>
        <p>
          {PRODUCT_NAME} uses the OpenAI API for essay grading and feedback
          generation. The specific model version used is configurable. We do
          not use fine-tuned models trained on student data.
        </p>

        <h2>4. Student Data and AI Training</h2>
        <p>
          <strong>[VERIFY CURRENT OPENAI API TERMS]</strong> — Student essay
          content is sent to the OpenAI API for grading. OpenAI&apos;s API
          terms of service prohibit using API inputs for model training by
          default. We do not opt in to any training data sharing with OpenAI or
          any other provider. For current OpenAI data usage terms, see{" "}
          <a
            href="https://openai.com/policies/api-data-usage-policies"
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 underline hover:text-blue-800"
          >
            OpenAI API Data Usage Policies
          </a>
          .
        </p>

        <h2>5. Human Oversight Requirement</h2>
        <p>
          Every AI-generated grade must be reviewed by the teacher before it
          is considered final. {PRODUCT_NAME} enforces this at the system
          level: grades cannot be shared with students or recorded as official
          until the teacher explicitly locks them after review.
        </p>

        <h2>6. Accuracy and Errors</h2>
        <p>
          AI grading is assistive, not authoritative. The teacher is
          responsible for all final grades. If the AI produces an incorrect or
          inappropriate grade or feedback suggestion, the teacher&apos;s
          override is the correction mechanism. We do not guarantee the
          accuracy of AI-generated content.
        </p>

        <h2>7. Bias and Fairness</h2>
        <p>
          AI rubric-based grading is subject to the same biases embedded in
          the rubric itself. Teachers are responsible for the rubrics they
          define. We do not provide automated bias detection. Teachers should
          review grade distributions for unusual patterns and adjust rubrics
          accordingly.
        </p>

        <h2>8. Updates to AI Use</h2>
        <p>
          Material changes to our AI providers or use cases will be disclosed
          to account holders with at least 30 days&apos; notice before taking
          effect.
        </p>

        <h2>Contact</h2>
        <p>
          Questions about our AI use? Contact us at{" "}
          <a
            href={`mailto:${SUPPORT_EMAIL}`}
            className="text-blue-600 underline hover:text-blue-800"
          >
            {SUPPORT_EMAIL}
          </a>
          .
        </p>
      </div>
    </LegalPageShell>
  );
}
