"use client";

import AppShell from "@/components/AppShell";
import { useRequireAuth } from "@/lib/auth";

/** Where someone lands when an admin has turned off everything their role
 * could use. Better than bouncing between pages they can't open. */
export default function NoAccessPage() {
  const { user, loading } = useRequireAuth();

  if (loading || !user) {
    return <div className="grid flex-1 place-items-center text-sm text-muted">Loading…</div>;
  }

  return (
    <AppShell>
      <div className="mx-auto max-w-lg rounded-2xl border border-line bg-card/70 p-6">
        <h1 className="text-lg font-semibold text-text">Nothing to show yet</h1>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          You&apos;re signed in as {user.email}, but your role doesn&apos;t currently have access to
          the assistant or the document library. Ask an administrator to check the permissions for
          your role.
        </p>
      </div>
    </AppShell>
  );
}
