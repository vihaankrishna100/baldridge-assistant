"use client";

import Link from "next/link";
import HeroCard from "@/components/HeroCard";
import Logo, { LogoMark } from "@/components/Logo";
import {
  AlertIcon,
  ArrowIcon,
  CiteIcon,
  HandoffIcon,
  LockIcon,
  SearchIcon,
} from "@/components/Icons";
import { useAuth } from "@/lib/auth";

const PILLARS = [
  {
    icon: SearchIcon,
    title: "It reads our binders, not the internet",
    body: "Every answer comes out of documents leadership uploaded — the handbook, the incident policy, the intake procedure. Nothing else is in scope.",
  },
  {
    icon: CiteIcon,
    title: "It shows you the page",
    body: "Each claim carries a citation you can open and read in the document's own words. If you'd rather trust the binder than the screen, the binder is one tap away.",
  },
  {
    icon: HandoffIcon,
    title: "It says when it doesn't know",
    body: "When our documents don't cover something, you get the front office number instead of a confident guess. That's the whole design, not a fallback.",
  },
];

// Leading with the limits is the point. For a house full of kids, what a tool
// refuses to do is more reassuring than what it claims it can.
const REFUSALS = [
  "Guess at a policy we haven't written down",
  "Answer questions about a resident by name",
  "Give legal, medical, or clinical advice",
  "Invent a phone number, deadline, or dollar amount",
  "Show staff a leadership-only document",
  "Follow instructions hidden inside an uploaded file",
];

export default function LandingPage() {
  const { user, loading } = useAuth();

  return (
    <>
      <div className="atmosphere" />
      <div className="ledger" />

      <header className="sticky top-0 z-30 border-b border-line/60 bg-ink/70 backdrop-blur-xl">
        <div className="mx-auto flex h-[70px] w-full max-w-6xl items-center px-6">
          <Logo />
          <nav className="ml-auto hidden items-center gap-6 md:flex">
            <a href="#how" className="text-sm text-muted transition hover:text-text">
              How it works
            </a>
            <a href="#what-it-wont-do" className="text-sm text-muted transition hover:text-text">
              What it won&apos;t do
            </a>
            <a href="#access" className="text-sm text-muted transition hover:text-text">
              Get access
            </a>
          </nav>
          <div className="ml-auto flex items-center gap-3 md:ml-7">
            <Link
              href={user ? "/ask" : "/login"}
              className="group flex items-center gap-2 rounded-xl bg-cyan px-4 py-2 text-sm font-semibold text-ink transition hover:brightness-110"
            >
              <span className="hidden sm:inline">
                {loading ? "…" : user ? "Open the assistant" : "Sign in"}
              </span>
              <span className="sm:hidden">{loading ? "…" : user ? "Open" : "Sign in"}</span>
              <ArrowIcon className="h-3.5 w-3.5 transition group-hover:translate-x-0.5" />
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-6">
        {/* ---------------------------------------------------------- hero */}
        <section className="grid items-center gap-16 py-16 lg:grid-cols-[1fr_1.05fr] lg:gap-12 lg:py-24">
          <div className="reveal">
            <p className="eyebrow">Bald Ridge Lodge · Internal Tool</p>

            <h1 className="display-loose mt-5 text-[2.6rem] leading-[1.04] text-text sm:text-[3.4rem]">
              The answer,
              <br />
              and the page
              <br />
              <span className="relative inline-block text-cyan">
                <span className="relative z-10">it came from.</span>
                <svg
                  viewBox="0 0 340 14"
                  className="absolute -bottom-1 left-0 h-3 w-full text-cyan/45"
                  preserveAspectRatio="none"
                  aria-hidden
                >
                  <path
                    d="M2 9C60 4 120 3 180 5s100 5 158 2"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.5"
                    strokeLinecap="round"
                  />
                </svg>
              </span>
            </h1>

            <p className="mt-7 max-w-lg text-[15px] leading-relaxed text-muted">
              Our staff assistant answers questions about Bald Ridge procedures using only the
              documents we&apos;ve uploaded — and cites the exact page every time. When the
              documents don&apos;t cover it, it hands you to a person rather than making
              something up.
            </p>

            <div className="mt-9 flex flex-wrap items-center gap-3">
              <Link
                href={user ? "/ask" : "/login"}
                className="group flex items-center gap-2 rounded-xl bg-cyan px-5 py-3 text-sm font-semibold text-ink transition hover:brightness-110"
              >
                {user ? "Open the assistant" : "Sign in to ask a question"}
                <ArrowIcon className="h-4 w-4 transition group-hover:translate-x-0.5" />
              </Link>
              <a
                href="#what-it-wont-do"
                className="rounded-xl border border-line px-5 py-3 text-sm text-muted transition hover:border-cyan/40 hover:text-text"
              >
                What it won&apos;t do
              </a>
            </div>

            <p className="mt-6 flex items-center gap-2 text-[12px] text-faint">
              <LockIcon className="h-3.5 w-3.5" />
              Invitation only. Every question and document access is logged.
            </p>
          </div>

          <div className="animate-fade-up [animation-delay:0.28s]">
            <HeroCard />
          </div>
        </section>

        {/* ---------------------------------------------------------- pillars */}
        <section id="how" className="scroll-mt-24 border-t border-line/60 py-16">
          <div className="grid gap-px overflow-hidden rounded-2xl border border-line bg-line/60 md:grid-cols-3">
            {PILLARS.map(({ icon: Icon, title, body }) => (
              <div
                key={title}
                className="lit group bg-card/85 p-7 transition-colors hover:bg-card"
              >
                <span className="mb-5 grid h-11 w-11 place-items-center rounded-xl border border-cyan/25 bg-cyan/10 text-cyan transition group-hover:border-cyan/45">
                  <Icon className="h-5 w-5" />
                </span>
                <h2 className="display text-[17px] text-text">{title}</h2>
                <p className="mt-2.5 text-sm leading-relaxed text-muted">{body}</p>
              </div>
            ))}
          </div>
        </section>

        {/* ---------------------------------------------------------- refusals */}
        <section id="what-it-wont-do" className="scroll-mt-24 border-t border-line/60 py-16">
          <div className="grid gap-10 lg:grid-cols-[0.85fr_1fr]">
            <div>
              <p className="eyebrow">The important part</p>
              <h2 className="display-loose mt-4 text-[2rem] leading-tight text-text">
                What it will refuse to do
              </h2>
              <p className="mt-4 max-w-sm text-sm leading-relaxed text-muted">
                A wrong answer about a shift procedure is worse than no answer. So the
                assistant is built to stop rather than improvise — and it will tell you when
                it has.
              </p>
              <div className="mt-7 flex items-start gap-3 rounded-xl border border-amber/30 bg-amber/[0.06] p-4">
                <AlertIcon className="mt-0.5 h-4 w-4 shrink-0 text-amber" />
                <p className="text-[13px] leading-relaxed text-muted">
                  Don&apos;t enter resident names or personal details. This is a tool for
                  procedures and policies, not case files.
                </p>
              </div>
            </div>

            <ul className="grid gap-px overflow-hidden rounded-2xl border border-line bg-line/60 sm:grid-cols-2">
              {REFUSALS.map((item) => (
                <li key={item} className="flex items-start gap-3 bg-card/85 p-5">
                  <svg
                    viewBox="0 0 20 20"
                    className="mt-0.5 h-4 w-4 shrink-0 text-rose"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.7"
                    strokeLinecap="round"
                    aria-hidden
                  >
                    <circle cx="10" cy="10" r="7.5" />
                    <path d="m7 7 6 6M13 7l-6 6" />
                  </svg>
                  <span className="text-[13.5px] leading-relaxed text-muted">{item}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* ---------------------------------------------------------- access */}
        <section id="access" className="scroll-mt-24 border-t border-line/60 py-16">
          <div className="lit relative overflow-hidden rounded-2xl border border-line bg-card/85 px-8 py-12 text-center">
            <div
              className="pointer-events-none absolute inset-0 opacity-[0.5]"
              style={{
                backgroundImage:
                  "radial-gradient(520px 220px at 50% 0%, rgba(56,217,240,0.1), transparent 70%)",
              }}
            />
            <div className="relative">
              <LogoMark className="mx-auto h-16 w-16" />
              <h2 className="display-loose mt-6 text-[1.9rem] text-text">Need access?</h2>
              <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-muted">
                Accounts are created by an administrator — there&apos;s no sign-up page. Ask
                the front office and you&apos;ll get an invitation link by email.
              </p>
              <div className="mt-7 flex flex-wrap justify-center gap-3">
                <a
                  href="tel:7708871220"
                  className="rounded-xl bg-amber px-5 py-2.5 text-sm font-semibold text-ink transition hover:brightness-110"
                >
                  Call 770-887-1220
                </a>
                <a
                  href="mailto:adikes@baldridgelodge.org"
                  className="rounded-xl border border-line px-5 py-2.5 text-sm text-muted transition hover:border-amber/45 hover:text-amber"
                >
                  adikes@baldridgelodge.org
                </a>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-line/60 px-6 py-8">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4">
          <Logo size="sm" subtitle={null} />
          <p className="font-mono text-[10px] tracking-[0.14em] text-faint uppercase">
            Internal use only · Not for residents or the public
          </p>
        </div>
      </footer>
    </>
  );
}
