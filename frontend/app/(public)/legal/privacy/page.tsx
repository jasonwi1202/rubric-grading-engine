import type { Metadata } from "next";
import Link from "next/link";
import { PRODUCT_NAME, SUPPORT_EMAIL } from "@/lib/constants";
import { AttorneyDraftBanner } from "@/components/legal/AttorneyDraftBanner";
import { LegalPageShell } from "@/components/legal/LegalPageShell";

export const metadata: Metadata = {
  title: `Privacy Policy — ${PRODUCT_NAME}`,
  description: `Privacy Policy for ${PRODUCT_NAME} — how we collect, use, and protect your data and student education records.`,
};

export default function PrivacyPage() {
  return (
    <LegalPageShell
      title="Privacy Policy"
      lastUpdated="2026-01-01"
      version="1.0-draft"
    >
      <AttorneyDraftBanner />

      <div className="prose prose-gray max-w-none print:prose-sm">
        <h2>1. What We Collect</h2>
        <ul>
          <li>
            <strong>Account information:</strong> Teacher name, email address,
            and school name.
          </li>
          <li>
            <strong>Usage data:</strong> Feature usage and session data. We do
            not include student PII in usage analytics.
          </li>
          <li>
            <strong>Student data:</strong> Essay text, grades, and
            feedback — collected on behalf of the school under FERPA.
          </li>
          <li>
            <strong>Technical data:</strong> IP addresses for security and
            audit logging only, never for profiling.
          </li>
        </ul>

        <h2>2. What We Do NOT Collect</h2>
        <ul>
          <li>Student email addresses, phone numbers, photos, or demographics</li>
          <li>Precise location data</li>
          <li>Any data for advertising purposes</li>
        </ul>

        <h2>3. How We Use Data</h2>
        <ul>
          <li>To provide the grading service</li>
          <li>
            To improve the service — using aggregated, anonymized usage data
            only; never individual student data
          </li>
          <li>For security and fraud prevention</li>
          <li>To communicate with account holders (teachers, not students)</li>
        </ul>

        <h2>4. Student Data — Special Protections</h2>
        <p>
          Student data is processed solely to provide the educational service.
          Student data is:
        </p>
        <ul>
          <li>Never sold, rented, or disclosed to third parties except service providers under DPA</li>
          <li>Never used to train AI models without explicit written school consent</li>
          <li>Never used to build student profiles for advertising or non-educational purposes</li>
        </ul>
        <p>
          References: FERPA, COPPA, applicable state laws (e.g., SOPIPA, NY
          Education Law §2-d).
        </p>

        <h2>5. Who We Share Data With (Subprocessors)</h2>
        <table>
          <thead>
            <tr>
              <th>Provider</th>
              <th>Purpose</th>
              <th>Data Shared</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <a
                  href="https://openai.com/policies/api-data-usage-policies"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 underline hover:text-blue-800"
                >
                  OpenAI
                </a>
              </td>
              <td>Essay processing for AI grading</td>
              <td>Essay text only — no student names or identifiers</td>
            </tr>
            <tr>
              <td>Railway</td>
              <td>Infrastructure hosting (US)</td>
              <td>All application data</td>
            </tr>
            <tr>
              <td>Stripe</td>
              <td>Payment processing</td>
              <td>Teacher billing data only — no student data</td>
            </tr>
          </tbody>
        </table>

        <h2>6. Data Retention</h2>
        <ul>
          <li>Active accounts: data retained for the duration of subscription + 1 year</li>
          <li>Deleted accounts: student data deleted within 30 days; teacher account data within 90 days</li>
          <li>Audit logs: retained for 3 years for compliance purposes</li>
        </ul>

        <h2>7. Your Rights</h2>
        <ul>
          <li>Access your data</li>
          <li>Request deletion of your teacher account or school data</li>
          <li>
            For student data rights: contact your school administrator — we act
            on the school&apos;s instruction
          </li>
        </ul>

        <h2>8. Security</h2>
        <ul>
          <li>Encryption in transit (TLS) and at rest</li>
          <li>Access controls and authentication requirements</li>
          <li>Regular security reviews</li>
          <li>Breach notification within 72 hours</li>
        </ul>

        <h2>9. Children&apos;s Privacy (COPPA)</h2>
        <p>
          {PRODUCT_NAME} is a teacher tool. We do not collect personal
          information directly from students. Students do not have accounts;
          their data is uploaded and managed by teachers on their behalf.
        </p>

        <h2>10. Changes to This Policy</h2>
        <p>
          We will notify account holders by email at least 30 days before any
          material changes to this policy take effect.
        </p>

        <h2>11. Contact</h2>
        <p>
          For privacy questions or to exercise your rights, contact us at{" "}
          <a href={`mailto:${SUPPORT_EMAIL}`} className="text-blue-600 underline hover:text-blue-800">
            {SUPPORT_EMAIL}
          </a>
          . For FERPA-specific questions, see our{" "}
          <Link href="/legal/ferpa" className="text-blue-600 underline hover:text-blue-800">
            FERPA Notice
          </Link>
          .
        </p>
      </div>
    </LegalPageShell>
  );
}
