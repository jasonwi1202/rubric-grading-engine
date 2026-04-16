/**
 * Layout for the (auth) route group — login and any future auth pages.
 * Unauthenticated users should see a clean, centred layout without the
 * dashboard chrome.
 */
export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50">
      {children}
    </div>
  );
}
