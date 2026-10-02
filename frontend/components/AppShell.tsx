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
    <>
      <div className="atmosphere" />
      <div className="ledger" />

      <div className="flex min-h-screen flex-col">
        <header className="sticky top-0 z-30 border-b border-line/60 bg-ink/75 backdrop-blur-xl">
          <div className="mx-auto flex h-[70px] w-full max-w-6xl items-center gap-7 px-6">
            <Link href="/" className="shrink-0" aria-label="Bald Ridge Lodge home">
              <Logo collapse />
            </Link>

            <nav className="flex items-center gap-1">
              {visible.map(({ href, label, icon: Icon }) => {
                const active = pathname === href || pathname.startsWith(`${href}/`);
                return (
                  <Link
                    key={href}
                    href={href}
                    aria-current={active ? "page" : undefined}
                    className={`relative flex items-center gap-2 rounded-lg px-3 py-2 text-sm transition ${
                      active
                        ? "bg-cyan/10 text-cyan"
                        : "text-muted hover:bg-raised hover:text-text"
                    }`}
                  >
                    <Icon className="h-4 w-4" />
                    <span className="hidden sm:inline">{label}</span>
                    {active && (
                      <span className="absolute inset-x-3 -bottom-[1px] h-px bg-cyan/70" />
                    )}
                  </Link>
                );
              })}
            </nav>

            <div className="ml-auto flex items-center gap-3">
              {user && (
                <div className="hidden text-right leading-tight sm:block">
                  <div className="text-[13px] text-text">{user.full_name || user.email}</div>
                  <div className="font-mono text-[10px] tracking-[0.14em] text-faint uppercase">
                    {ROLE_LABEL[user.role] ?? user.role}
                  </div>
                </div>
              )}
              <ThemeToggle />
              <button
                onClick={() => void signOut()}
                title="Sign out"
                aria-label="Sign out"
                className="grid h-9 w-9 place-items-center rounded-lg border border-line text-muted transition hover:border-rose/45 hover:text-rose"
              >
                <SignOutIcon className="h-4 w-4" />
              </button>
            </div>
          </div>
        </header>

        <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-9">{children}</main>

        <footer className="border-t border-line/60 px-6 py-5">
          <p className="mx-auto max-w-6xl text-[11px] leading-relaxed text-faint">
            Internal use only. This assistant answers from Bald Ridge Lodge&apos;s uploaded
            documents and will refer you to a person when it can&apos;t. Do not enter resident
            names or personal details.
          </p>
        </footer>
      </div>
    </>
  );
}
