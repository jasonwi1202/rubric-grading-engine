import type { Metadata } from "next";
import Link from "next/link";
import { PRODUCT_NAME, SUPPORT_EMAIL } from "@/lib/constants";
import { AttorneyDraftBanner } from "@/components/legal/AttorneyDraftBanner";
import { LegalPageShell } from "@/components/legal/LegalPageShell";

export const metadata: Metadata = {
  title: `Terms of Service — ${PRODUCT_NAME}`,
  description: `Terms of Service for ${PRODUCT_NAME} — the AI-assisted grading tool for K-12 writing teachers.`,
};

export default function TermsPage() {
  return (
    <LegalPageShell
      title="Terms of Service"
      lastUpdated="2026-01-01"
      version="1.0-draft"
    >
      <AttorneyDraftBanner />

      <div className="prose prose-gray max-w-none print:prose-sm">
        <h2>1. Acceptance</h2>
        <p>
          By accessing or using {PRODUCT_NAME} (&quot;the Service&quot;), you
          agree to be bound by these Terms of Service. Schools and districts
          agree to these terms on behalf of their teachers and staff who use
          the Service.
        </p>

        <h2>2. Service Description</h2>
        <p>
          {PRODUCT_NAME} is a teacher-facing AI-assisted grading tool for K-12
          writing instruction. The Service helps teachers grade student essays
          against rubrics, provides AI-generated feedback suggestions, and
          builds student skill profiles. {PRODUCT_NAME} is{" "}
          <strong>not a student-facing product</strong> and does not replace
          teacher judgment — teachers review and approve all grades before they
          are considered final.
        </p>

        <h2>3. Accounts and Access</h2>
        <p>
          You are responsible for maintaining the confidentiality of your
          account credentials. Sharing credentials with others is prohibited.
          You must notify us immediately of any unauthorized use of your
          account.
        </p>

        <h2>4. Acceptable Use</h2>
        <p>Permitted uses include grading student writing for legitimate K-12 educational purposes.</p>
        <p>Prohibited uses include:</p>
        <ul>
          <li>Any use that would violate FERPA or applicable student privacy laws</li>
          <li>Commercial resale or redistribution of the Service</li>
          <li>Automated scraping or bulk extraction of data</li>
          <li>Use for any purpose unrelated to legitimate educational instruction</li>
        </ul>

        <h2>5. Student Data</h2>
        <p>
          <strong>[ATTORNEY DRAFT REQUIRED]</strong> — We act as a
          &quot;school official&quot; under FERPA (34 CFR §99.31(a)(1)).
          Student data is used solely to provide the grading service. We do not
          sell student data. We do not use student data to train AI models
          without explicit written consent from your school or district. See
          our{" "}
          <Link href="/legal/privacy" className="text-blue-600 underline hover:text-blue-800">
            Privacy Policy
          </Link>{" "}
          and{" "}
          <Link href="/legal/ferpa" className="text-blue-600 underline hover:text-blue-800">
            FERPA Notice
          </Link>{" "}
          for full details.
        </p>

        <h2>6. AI-Generated Content</h2>
        <p>
          <strong>[ATTORNEY DRAFT REQUIRED]</strong> — Grades and feedback
          produced by {PRODUCT_NAME} are AI-assisted suggestions. The teacher
          reviews and is responsible for all final grades. We do not guarantee
          the accuracy of AI-generated content. See our{" "}
          <Link href="/legal/ai-policy" className="text-blue-600 underline hover:text-blue-800">
            AI Use Policy
          </Link>{" "}
          for details.
        </p>

        <h2>7. Subscription and Payment</h2>
        <p>
          <strong>[ATTORNEY DRAFT REQUIRED]</strong> — Billing terms,
          auto-renewal, cancellation, and refund policy details will be
          specified here. See the{" "}
          <Link href="/pricing" className="text-blue-600 underline hover:text-blue-800">
            Pricing page
          </Link>{" "}
          for current plan pricing.
        </p>

        <h2>8. Data Retention and Deletion</h2>
        <p>
          We retain your data for the duration of your subscription plus one
          year. Upon account cancellation, student data is deleted within 30
          days and teacher account data within 90 days. To request early
          deletion, contact us at{" "}
          <a href={`mailto:${SUPPORT_EMAIL}`} className="text-blue-600 underline hover:text-blue-800">
            {SUPPORT_EMAIL}
          </a>
          .
        </p>

        <h2>9. Intellectual Property</h2>
        <p>
          We own the Service and its underlying technology. You own your
          rubrics and any content you create. Student essays remain the
          intellectual property of the school and/or student.
        </p>

        <h2>10. Disclaimers and Limitation of Liability</h2>
        <p>
          <strong>[ATTORNEY DRAFT REQUIRED]</strong> — The Service is provided
          &quot;as is.&quot; Disclaimer of warranties and limitation of
          liability language will be specified here by counsel.
        </p>

        <h2>11. Governing Law</h2>
        <p>
          <strong>[ATTORNEY DRAFT REQUIRED]</strong> — These terms are
          governed by US law. The specific governing state will be determined
          by counsel.
        </p>

        <h2>12. Changes to Terms</h2>
        <p>
          We will notify you by email with at least 30 days&apos; notice
          before any material changes to these terms take effect.
        </p>

        <h2>13. Contact</h2>
        <p>
          For legal questions, contact us at{" "}
          <a href={`mailto:${SUPPORT_EMAIL}`} className="text-blue-600 underline hover:text-blue-800">
            {SUPPORT_EMAIL}
          </a>
          .
        </p>
      </div>
    </LegalPageShell>
  );
}
