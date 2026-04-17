import type { Metadata } from "next";
import { PRODUCT_NAME } from "@/lib/constants";
import { AttorneyDraftBanner } from "@/components/legal/AttorneyDraftBanner";
import { LegalPageShell } from "@/components/legal/LegalPageShell";
import DpaRequestForm from "./_dpa-form";

export const metadata: Metadata = {
  title: `Data Processing Agreement — ${PRODUCT_NAME}`,
  description: `Request a Data Processing Agreement (DPA) from ${PRODUCT_NAME} for FERPA compliance.`,
};

export default function DpaPage() {
  return (
    <LegalPageShell
      title="Data Processing Agreement"
      lastUpdated="2026-01-01"
      version="1.0-draft"
    >
      <AttorneyDraftBanner />

      <div className="prose prose-gray max-w-none print:prose-sm">
        <h2>What Is a DPA?</h2>
        <p>
          A Data Processing Agreement (DPA) is a written contract between{" "}
          {PRODUCT_NAME} and a school or district that defines how we process
          student education records on the school&apos;s behalf. It
          establishes the permitted uses of data, our security obligations,
          deletion timelines, and breach notification procedures.
        </p>

        <h2>When Do You Need One?</h2>
        <p>
          A DPA is required if your district or state requires a formal
          agreement before adopting third-party edtech tools — which most
          US districts and states now do. We recommend all schools using{" "}
          {PRODUCT_NAME} request a signed DPA before uploading student work.
        </p>

        <h2>What Our DPA Covers</h2>
        <ul>
          <li>Scope of data processing and permitted uses</li>
          <li>Prohibition on selling, renting, or disclosing student data</li>
          <li>Data deletion obligations (30 days post-termination)</li>
          <li>Security requirements and incident response</li>
          <li>Breach notification procedures</li>
          <li>Subprocessor list (OpenAI, Railway, Stripe)</li>
          <li>Audit rights</li>
        </ul>

        <h2>Pre-Signed District Templates</h2>
        <p>
          If your district uses a standard DPA template (such as the Student
          Data Privacy Consortium model DPA), we will review and sign it.
          Include a note in the request form below.
        </p>
      </div>

      <DpaRequestForm />
    </LegalPageShell>
  );
}
