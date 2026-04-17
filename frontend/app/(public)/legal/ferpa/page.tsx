import type { Metadata } from "next";
import Link from "next/link";
import { PRODUCT_NAME, SUPPORT_EMAIL } from "@/lib/constants";
import { AttorneyDraftBanner } from "@/components/legal/AttorneyDraftBanner";
import { LegalPageShell } from "@/components/legal/LegalPageShell";

export const metadata: Metadata = {
  title: `FERPA & COPPA Notice — ${PRODUCT_NAME}`,
  description: `FERPA and COPPA compliance notice for ${PRODUCT_NAME} — how we protect student education records.`,
};

export default function FerpaPage() {
  return (
    <LegalPageShell
      title="FERPA & COPPA Notice"
      lastUpdated="2026-01-01"
      version="1.0-draft"
    >
      <AttorneyDraftBanner />

      <div className="prose prose-gray max-w-none print:prose-sm">
        <h2>What Is FERPA?</h2>
        <p>
          The Family Educational Rights and Privacy Act (FERPA) is a US
          federal law that protects the privacy of student education records.
          FERPA gives parents and eligible students rights over their education
          records and restricts how schools may disclose those records to
          third parties.
        </p>

        <h2>Our Role Under FERPA</h2>
        <p>
          <strong>[ATTORNEY DRAFT REQUIRED]</strong> — {PRODUCT_NAME} acts as
          a &quot;school official&quot; with a &quot;legitimate educational
          interest&quot; under 34 CFR §99.31(a)(1). We are not an
          &quot;authorized representative&quot; for audit or evaluation
          purposes under FERPA. We do not have independent rights to student
          education records — we act solely on the school&apos;s instruction
          and under the school&apos;s direction.
        </p>

        <h2>What Student Data We Access</h2>
        <ul>
          <li>Essay text submitted by teachers for grading</li>
          <li>Grades and feedback created by or confirmed by teachers</li>
        </ul>
        <p>
          We do not receive student names, email addresses, or other
          identifying information unless a teacher includes them in an essay
          file. We recommend that teachers remove student names from essay
          files before uploading.
        </p>

        <h2>What We Do Not Do With Student Data</h2>
        <ul>
          <li>We do not sell or rent student data</li>
          <li>We do not use student data for advertising</li>
          <li>We do not use student data to train AI models</li>
          <li>
            We do not share student data with third parties except service
            providers listed in our{" "}
            <Link href="/legal/privacy" className="text-blue-600 underline hover:text-blue-800">
              Privacy Policy
            </Link>{" "}
            and Data Processing Agreement
          </li>
        </ul>

        <h2>Data Processing Agreement</h2>
        <p>
          Schools and districts can request a signed Data Processing Agreement
          (DPA) for FERPA compliance. Our DPA:
        </p>
        <ul>
          <li>Names us as a school official acting on the school&apos;s behalf</li>
          <li>Defines permitted uses of student data</li>
          <li>Defines deletion obligations</li>
          <li>Defines breach notification procedures</li>
        </ul>
        <p>
          To request a DPA, visit our{" "}
          <Link href="/legal/dpa" className="text-blue-600 underline hover:text-blue-800">
            Data Processing Agreement page
          </Link>
          .
        </p>

        <h2>COPPA</h2>
        <p>
          {PRODUCT_NAME} is a teacher tool. We do not collect personal
          information directly from children under 13. Students do not have
          accounts or direct access to {PRODUCT_NAME}. If a teacher
          inadvertently creates a student account, contact us immediately at{" "}
          <a href={`mailto:${SUPPORT_EMAIL}`} className="text-blue-600 underline hover:text-blue-800">
            {SUPPORT_EMAIL}
          </a>{" "}
          to have it removed.
        </p>

        <h2>State Privacy Laws</h2>
        <p>
          In addition to FERPA, we comply with applicable state student data
          privacy laws, including:
        </p>
        <ul>
          <li>
            <strong>California:</strong> SOPIPA, AB 1584
          </li>
          <li>
            <strong>New York:</strong> Education Law §2-d
          </li>
          <li>
            <strong>Other states:</strong> Reviewed on a case-by-case basis.
            Contact us with questions about your state&apos;s requirements.
          </li>
        </ul>

        <h2>Contact for Compliance Questions</h2>
        <p>
          School administrators with FERPA or privacy questions can contact us
          at{" "}
          <a href={`mailto:${SUPPORT_EMAIL}`} className="text-blue-600 underline hover:text-blue-800">
            {SUPPORT_EMAIL}
          </a>
          .
        </p>
      </div>
    </LegalPageShell>
  );
}
