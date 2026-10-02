"use client";

import Link from "next/link";
import HeroCard from "@/components/HeroCard";
import Logo, { LogoMark } from "@/components/Logo";
import ThemeToggle from "@/components/ThemeToggle";
import { AlertIcon, ArrowIcon, LockIcon } from "@/components/Icons";
import { useAuth } from "@/lib/auth";

const STEPS = [
  {
    title: "Ask the way you'd ask a coworker",
    body: "Plain words are fine. “Can I drive a resident to an appointment?” works as well as the policy's own wording.",
  },
  {
    title: "Get a short answer and the page",
    body: "Every answer names the document and page it came from, so you can open the original and read it for yourself.",
  },
  {
    title: "Not covered? You get a person",
    body: "If our documents don't answer it, the assistant says so and gives you the front office's number. It doesn't guess.",
  },
];

// Leading with the limits is deliberate: in a home for young people, what a
// tool refuses to do is more reassuring than what it claims it can.
const REFUSALS = [
  "Guess at a policy we haven't written down",
  "Answer questions about a resident by name",
  "Give legal, medical, or clinical advice",
  "Make up a phone number, deadline, or dollar amount",
  "Show staff a leadership-only document",
  "Follow instructions hidden inside an uploaded file",
];

export default function LandingPage() {
  const { user, loading } = useAuth();
  const cta = loading ? "…" : user ? "Open the assistant" : "Sign in";

  return (
    <>
      <header className="sticky top-0 z-30 border-b border-line bg-ink/90 backdrop-blur">
        <div className="mx-auto flex h-16 w-full max-w-6xl items-center gap-6 px-4 sm:px-6">
          <Logo collapse />
          <nav className="ml-auto hidden items-center gap-7 md:flex" aria-label="Page">
            <a href="#how" className="text-[14px] font-medium text-muted transition-colors hover:text-text">
              How it works
            </a>
            <a href="#limits" className="text-[14px] font-medium text-muted transition-colors hover:text-text">
              What it won&apos;t do
            </a>
            <a href="#access" className="text-[14px] font-medium text-muted transition-colors hover:text-text">
              Get access
            </a>
          </nav>
          <div className="ml-auto flex items-center gap-2 md:ml-2">
            <ThemeToggle />
            <Link
              href={user ? "/ask" : "/login"}
              className="rounded-lg bg-cyan px-4 py-2 text-[14px] font-semibold text-ink transition hover:opacity-90"
            >
              {cta}
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 sm:px-6">
        <section className="grid items-center gap-12 py-14 lg:grid-cols-[1fr_1fr] lg:gap-16 lg:py-24">
          <div>
            <p className="eyebrow">Bald Ridge Lodge · Staff Assistant</p>
            <h1 className="display mt-4 text-[2.25rem] leading-[1.12] text-text sm:text-[2.9rem]">
              Policy answers you can check.
            </h1>
            <p className="mt-5 max-w-lg text-[16.5px] leading-relaxed text-muted">
              Ask about any Bald Ridge procedure and get a short answer taken straight from our
              own documents, with the page it came from. When the documents don&apos;t cover
              it, you&apos;ll be pointed to a person instead.
            </p>

            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link
                href={user ? "/ask" : "/login"}
                className="group inline-flex items-center gap-2 rounded-lg bg-cyan px-5 py-3 text-[15px] font-semibold text-ink transition hover:opacity-90"
              >
                {user ? "Open the assistant" : "Sign in to ask a question"}
                <ArrowIcon className="h-4 w-4 transition group-hover:translate-x-0.5" />
              </Link>
              <a
                href="#limits"
                className="rounded-lg border border-line px-5 py-3 text-[15px] font-medium text-text transition hover:bg-raised"
              >
                What it won&apos;t do
              </a>
            </div>

            <p className="mt-6 flex items-center gap-2 text-[13px] text-faint">
              <LockIcon className="h-3.5 w-3.5" />
              For Lodge staff, by invitation. Every question and document view is logged.
            </p>
          </div>

          <HeroCard />
        </section>

        <section id="how" className="scroll-mt-20 border-t border-line py-16">
          <h2 className="display text-[1.6rem] text-text">How it works</h2>
          <ol className="mt-8 grid gap-8 md:grid-cols-3">
            {STEPS.map(({ title, body }, i) => (
              <li key={title}>
                <span className="grid h-8 w-8 place-items-center rounded-full border border-line font-display text-[13px] font-bold text-gold">
                  {i + 1}
                </span>
                <h3 className="mt-4 font-display text-[16px] font-semibold text-text">{title}</h3>
                <p className="mt-2 text-[15px] leading-relaxed text-muted">{body}</p>
              </li>
            ))}
          </ol>
        </section>

        <section id="limits" className="scroll-mt-20 border-t border-line py-16">
          <div className="grid gap-10 lg:grid-cols-[0.9fr_1.1fr]">
            <div>
              <h2 className="display text-[1.6rem] text-text">What it won&apos;t do</h2>
              <p className="mt-4 max-w-md text-[15.5px] leading-relaxed text-muted">
                A wrong answer about a procedure is worse than no answer, so the assistant is
                built to stop rather than improvise — and to tell you when it has.
              </p>
              <div className="mt-6 flex items-start gap-3 rounded-lg border border-amber/35 bg-amber/8 p-4">
                <AlertIcon className="mt-0.5 h-4 w-4 shrink-0 text-amber" />
                <p className="text-[14px] leading-relaxed text-text">
                  Please don&apos;t enter residents&apos; names or personal details. This is for
                  procedures and policies, not case files.
                </p>
              </div>
            </div>

            <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-card">
              {REFUSALS.map((item) => (
                <li key={item} className="flex items-center gap-3 px-5 py-3.5">
                  <svg
                    viewBox="0 0 20 20"
                    className="h-4 w-4 shrink-0 text-faint"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    aria-hidden
                  >
                    <path d="m6 6 8 8M14 6l-8 8" />
                  </svg>
                  <span className="text-[15px] text-text">{item}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section id="access" className="scroll-mt-20 border-t border-line py-16">
          <div className="flex flex-col items-start gap-6 rounded-xl border border-line bg-card p-8 sm:flex-row sm:items-center">
            <LogoMark className="h-12 w-12" />
            <div className="flex-1">
              <h2 className="font-display text-[1.25rem] font-bold text-text">Need access?</h2>
              <p className="mt-1.5 max-w-xl text-[15px] leading-relaxed text-muted">
                Accounts are set up by an administrator — there&apos;s no sign-up page. Contact
                the front office and you&apos;ll get an invitation by email.
              </p>
            </div>
            <div className="flex flex-wrap gap-2.5">
              <a
                href="tel:7708871220"
                className="rounded-lg bg-cyan px-4 py-2.5 text-[14px] font-semibold text-ink transition hover:opacity-90"
              >
                Call 770-887-1220
              </a>
              <a
                href="mailto:adikes@baldridgelodge.org"
                className="rounded-lg border border-line px-4 py-2.5 text-[14px] font-medium text-text transition hover:bg-raised"
              >
                Email the office
              </a>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-line py-8">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-4 sm:px-6">
          <Logo size="sm" subtitle={null} />
          <p className="text-[13px] text-faint">
            © {new Date().getFullYear()} Bald Ridge Lodge · Cumming, Georgia · For staff use only
          </p>
        </div>
      </footer>
    </>
  );
}
