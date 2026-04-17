import type { Metadata } from "next";
import Link from "next/link";
import { ShieldCheck, UserCheck, Lock, BookOpen } from "lucide-react";
import { PRODUCT_NAME, SUPPORT_EMAIL } from "@/lib/constants";

export const metadata: Metadata = {
  title: `About — ${PRODUCT_NAME}`,
  description: `The mission, principles, and team behind ${PRODUCT_NAME}.`,
};

const PRINCIPLES = [
  {
    icon: UserCheck,
    heading: "Human-in-the-loop, always",
    body: "AI prepares a draft; the teacher decides. No grade is recorded, no feedback shared, and no action taken without explicit teacher approval. That commitment is enforced in the product — not just claimed in marketing.",
  },
  {
    icon: BookOpen,
    heading: "Teacher agency first",
    body: "Teachers set the rubric, define the criteria, override any score, and edit any feedback. The system surfaces information and recommendations — the teacher retains full authority over every instructional decision.",
  },
  {
    icon: Lock,
    heading: "Student data is never sold",
    body: "Student essays, scores, and skill data exist for one purpose: helping teachers improve instruction. The data is never sold, licensed, or used for advertising. Ever.",
  },
  {
    icon: ShieldCheck,
    heading: "FERPA is a hard requirement",
    body: "Student education records are protected by law and by design. We maintain a signed Data Processing Agreement with every institution, and no student data is sent to third-party services without explicit authorization.",
  },
] as const;

const TEAM_MEMBERS = [
  {
    name: "{TODO: insert name}",
    role: "{TODO: insert role}",
    bio: "{TODO: insert bio}",
  },
  {
    name: "{TODO: insert name}",
    role: "{TODO: insert role}",
    bio: "{TODO: insert bio}",
  },
] as const;

/**
 * About page — mission statement, core principles, team placeholder, and
 * contact callout.
 *
 * Fully static — no API calls.
 */
export default function AboutPage() {
  return (
    <>
      {/* Page hero / mission statement */}
      <section className="bg-white px-4 py-16 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-3xl text-center">
          <h1 className="text-4xl font-extrabold tracking-tight text-gray-900 sm:text-5xl">
            Our mission
          </h1>
          <p className="mt-6 text-xl text-gray-500">
            {PRODUCT_NAME} exists because teachers spend too much time grading
            and too little time teaching.
          </p>
          <p className="mt-4 text-lg text-gray-500">
            We built a grading assistant that works the way teachers think —
            rubric-first, criterion-by-criterion, with every AI decision
            explainable and overridable. The teacher is always in the loop,
            always in control, and always the final authority on every grade.
          </p>
        </div>
      </section>

      {/* Core principles */}
      <section className="bg-gray-50 px-4 py-16 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-7xl">
          <h2 className="text-center text-3xl font-bold text-gray-900">
            What we stand for
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-center text-lg text-gray-500">
            These principles are not aspirational. They are design constraints
            that govern every product decision we make.
          </p>
          <div className="mt-12 grid grid-cols-1 gap-8 sm:grid-cols-2">
            {PRINCIPLES.map(({ icon: Icon, heading, body }) => (
              <div
                key={heading}
                className="flex flex-col items-start rounded-xl border border-gray-200 bg-white p-8 shadow-sm"
              >
                <Icon className="h-8 w-8 text-blue-600" aria-hidden="true" />
                <h3 className="mt-4 text-lg font-semibold text-gray-900">
                  {heading}
                </h3>
                <p className="mt-2 text-sm text-gray-500">{body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Team placeholder */}
      <section className="bg-white px-4 py-16 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-7xl">
          <h2 className="text-center text-3xl font-bold text-gray-900">
            Who built it
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-center text-lg text-gray-500">
            {/* {TODO: insert team overview copy} */}
            We are educators and engineers who have lived the grading problem
            firsthand. Our team combines deep K-12 classroom experience with
            expertise in machine learning, product design, and data privacy.
          </p>
          <div className="mt-12 grid grid-cols-1 gap-8 sm:grid-cols-2 lg:grid-cols-3">
            {TEAM_MEMBERS.map(({ name, role, bio }, index) => (
              <div
                key={index}
                className="rounded-xl border border-gray-200 bg-gray-50 p-8"
              >
                {/* {TODO: insert team member headshot} */}
                <div
                  className="h-16 w-16 rounded-full bg-gray-200"
                  aria-hidden="true"
                />
                <p className="mt-4 text-base font-semibold text-gray-900">
                  {name}
                </p>
                <p className="text-sm font-medium text-blue-600">{role}</p>
                <p className="mt-2 text-sm text-gray-500">{bio}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Contact callout */}
      <section className="bg-blue-50 px-4 py-16 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-bold text-gray-900">Get in touch</h2>
          <p className="mt-4 text-lg text-gray-500">
            Questions, partnership inquiries, press requests, or FERPA
            compliance questions — we read every email.
          </p>
          <div className="mt-8 flex flex-col items-center gap-4 sm:flex-row sm:justify-center">
            <a
              href={`mailto:${SUPPORT_EMAIL}`}
              className="rounded-md bg-blue-600 px-8 py-3 text-base font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
            >
              Email us
            </a>
            <Link
              href="/legal/ferpa"
              className="rounded-md border border-gray-300 bg-white px-8 py-3 text-base font-semibold text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
            >
              Read our FERPA notice
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
