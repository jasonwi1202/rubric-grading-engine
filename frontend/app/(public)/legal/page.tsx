import { redirect } from "next/navigation";

/**
 * /legal — redirects to /legal/terms (the canonical first legal document).
 * All individual legal pages are linked from the public site footer.
 */
export default function LegalIndexPage() {
  redirect("/legal/terms");
}
