"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import Logo from "@/components/Logo";
import ThemeToggle from "@/components/ThemeToggle";
import { AdminIcon, AskIcon, DocumentsIcon, SignOutIcon } from "@/components/Icons";
import { useAuth } from "@/lib/auth";

const NAV = [
  { href: "/ask", label: "Ask", icon: AskIcon, adminOnly: false },
  { href: "/documents", label: "Documents", icon: DocumentsIcon, adminOnly: false },
  { href: "/admin", label: "Admin", icon: AdminIcon, adminOnly: true },
];

const ROLE_LABEL: Record<string, string> = {
  staff: "Staff",
  leadership: "Leadership",
  admin: "Administrator",
  team: "Team login",
};

export default function AppShell({ children }: { children: React.ReactNode }) {
  const { user, signOut } = useAuth();
  const pathname = usePathname();

  const visible = NAV.filter((item) => !item.adminOnly || user?.role === "admin");

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 border-b border-line bg-ink/90 backdrop-blur">
        <div className="mx-auto flex h-16 w-full max-w-6xl items-center gap-6 px-4 sm:px-6">
          <Link href="/" className="shrink-0" aria-label="Bald Ridge Lodge home">
            <Logo collapse />
          </Link>

          <nav className="flex h-full items-stretch gap-1" aria-label="Main">
            {visible.map(({ href, label, icon: Icon }) => {
              const active = pathname === href || pathname.startsWith(`${href}/`);
              return (
                <Link
                  key={href}
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={`relative flex items-center gap-2 px-3 text-[14px] font-medium transition-colors ${
                    active ? "text-text" : "text-muted hover:text-text"
                  }`}
                >
                  <Icon className="h-4 w-4" />
                  <span className="hidden sm:inline">{label}</span>
                  {active && (
                    <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-cyan" />
                  )}
                </Link>
              );
            })}
          </nav>

          <div className="ml-auto flex items-center gap-2">
            {user && (
              <div className="mr-2 hidden text-right leading-tight md:block">
                <div className="text-[14px] font-medium text-text">
                  {user.full_name || user.email}
                </div>
                <div className="text-[12px] text-faint">{ROLE_LABEL[user.role] ?? user.role}</div>
              </div>
            )}
            <ThemeToggle />
            <button
              onClick={() => void signOut()}
              aria-label="Sign out"
              title="Sign out"
              className="grid h-9 w-9 place-items-center rounded-lg border border-line text-muted transition hover:bg-raised hover:text-text"
            >
              <SignOutIcon className="h-4 w-4" />
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6">{children}</main>

      <footer className="border-t border-line py-5">
        <p className="mx-auto max-w-6xl px-4 text-[13px] leading-relaxed text-faint sm:px-6">
          For Bald Ridge Lodge staff. Answers come only from the Lodge&apos;s own documents, and
          you&apos;ll be pointed to a person when they don&apos;t cover your question. Please
          don&apos;t enter residents&apos; names or personal details.
        </p>
      </footer>
    </div>
  );
}
