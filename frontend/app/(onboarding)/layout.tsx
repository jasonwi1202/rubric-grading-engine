/**
 * Onboarding layout — full-screen wizard experience.
 *
 * Intentionally minimal: no sidebar, no top navigation. The wizard occupies
 * the full viewport so teachers can focus on the setup steps without
 * distraction from the main app chrome.
 */
export default function OnboardingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {children}
    </div>
  );
}
