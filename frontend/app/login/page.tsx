"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import Logo from "@/components/Logo";
import ThemeToggle from "@/components/ThemeToggle";
import { LockIcon } from "@/components/Icons";
import { api } from "@/lib/api";
import { useAuth, type User } from "@/lib/auth";

type LoginResponse = {
  status: "ok" | "2fa_required" | "2fa_setup_required";
  challenge_token?: string;
  access_token?: string;
  user?: User;
  method?: "app" | "email";
  sent_to?: string;
};

type SetupResponse = { secret: string; otpauth_uri: string; qr_svg: string };

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { signIn } = useAuth();

  const [step, setStep] = useState<"credentials" | "verify" | "enroll">("credentials");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [challenge, setChallenge] = useState("");
  const [setup, setSetup] = useState<SetupResponse | null>(null);
  const [sentTo, setSentTo] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState(params.get("expired") ? "Your session expired. Please sign in again." : "");
  const [busy, setBusy] = useState(false);

  const finish = (res: LoginResponse) => {
    if (res.status === "ok" && res.access_token && res.user) {
      signIn(res.access_token, res.user);
      router.push("/ask");
    }
  };

  const submitCredentials = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await api<LoginResponse>("/auth/login", {
        method: "POST",
        body: { email, password },
      });
      if (res.status === "ok") return finish(res);

      setChallenge(res.challenge_token ?? "");
      if (res.status === "2fa_setup_required") {
        const s = await api<SetupResponse>("/auth/2fa/setup", {
          method: "POST",
          body: { challenge_token: res.challenge_token },
        });
        setSetup(s);
        setStep("enroll");
      } else {
        setSentTo(res.method === "email" ? (res.sent_to ?? "your email") : "");
        setStep("verify");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  };

  const submitCode = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const endpoint = step === "enroll" ? "/auth/2fa/confirm" : "/auth/2fa/verify";
      finish(
        await api<LoginResponse>(endpoint, {
          method: "POST",
          body: { challenge_token: challenge, code },
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Verification failed.");
      setCode("");
    } finally {
      setBusy(false);
    }
  };

  const resend = async () => {
    setError("");
    setNotice("");
    try {
      const res = await api<LoginResponse>("/auth/2fa/resend", {
        method: "POST",
        body: { challenge_token: challenge },
      });
      setChallenge(res.challenge_token ?? "");
      setCode("");
      setNotice("A new code is on its way. Use the newest one.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send a new code.");
    }
  };


  const input =
    "w-full rounded-lg border border-line bg-card px-3.5 py-2.5 text-[15px] text-text transition outline-none placeholder:text-faint focus:border-cyan focus:ring-2 focus:ring-cyan/20";

  return (
    <div className="grid min-h-screen lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      {/* Brand panel — navy in both themes, as on the Lodge's own site. */}
      <aside className="relative hidden flex-col justify-between overflow-hidden bg-brand p-10 text-white lg:flex">
        <Link href="/" aria-label="Bald Ridge Lodge home">
          <Logo lockup size="md" tone="#ffffff" />
        </Link>
        <div className="max-w-sm">
          <p className="font-display text-[1.6rem] leading-snug font-semibold">
            Policy answers you can check, from the Lodge&apos;s own documents.
          </p>
          <p className="mt-4 text-[15px] leading-relaxed text-white/70">
            Every answer cites the document and page it came from. When the documents don&apos;t
            cover something, you&apos;ll be pointed to a person.
          </p>
        </div>
        <p className="text-[13px] text-white/55">Bald Ridge Lodge · Cumming, Georgia</p>
      </aside>

      <div className="flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 sm:px-8">
          <Link href="/" className="lg:invisible">
            <Logo size="sm" subtitle={null} />
          </Link>
          <ThemeToggle />
        </div>

        <div className="flex flex-1 items-center justify-center px-5 pb-16 sm:px-8">
          <div className="w-full max-w-sm animate-fade-up">
            {step === "credentials" && (
              <form onSubmit={submitCredentials} className="space-y-5">
                <div>
                  <h1 className="display text-[1.6rem] text-text">Sign in</h1>
                  <p className="mt-1.5 text-[15px] text-muted">
                    Use the email and password you were given.
                  </p>
                </div>

                <label className="block">
                  <span className="mb-1.5 block text-[14px] font-medium text-text">Email</span>
                  <input
                    type="email"
                    required
                    autoComplete="username"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className={input}
                  />
                </label>

                <label className="block">
                  <span className="mb-1.5 block text-[14px] font-medium text-text">Password</span>
                  <input
                    type="password"
                    required
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className={input}
                  />
                </label>

                <SubmitButton busy={busy} label="Sign in" />

                <p className="text-[13.5px] leading-relaxed text-faint">
                  No account? Accounts are set up by an administrator — ask the front office.
                </p>
              </form>
            )}

            {step === "enroll" && setup && (
              <form onSubmit={submitCode} className="space-y-5">
                <div>
                  <h1 className="display text-[1.6rem] text-text">Set up two-step sign-in</h1>
                  <p className="mt-1.5 text-[15px] leading-relaxed text-muted">
                    This assistant can open private documents, so each account needs a second
                    step. Scan this code with Google Authenticator, Microsoft Authenticator, or
                    Authy.
                  </p>
                </div>

                <div
                  className="mx-auto w-44 rounded-lg border border-line bg-white p-3 [&_svg]:h-full [&_svg]:w-full"
                  dangerouslySetInnerHTML={{ __html: setup.qr_svg }}
                />

                <details className="text-[13.5px] text-muted">
                  <summary className="cursor-pointer">Can&apos;t scan? Type this key instead</summary>
                  <code className="mt-2 block rounded-lg bg-raised p-2.5 font-mono text-[13px] break-all text-text">
                    {setup.secret}
                  </code>
                </details>

                <CodeInput value={code} onChange={setCode} />
                <SubmitButton busy={busy} label="Confirm and sign in" />
              </form>
            )}

            {step === "verify" && (
              <form onSubmit={submitCode} className="space-y-5">
                <div>
                  <h1 className="display text-[1.6rem] text-text">Enter your code</h1>
                  <p className="mt-1.5 text-[15px] leading-relaxed text-muted">
                    {sentTo
                      ? `We emailed a 6-digit code to ${sentTo}. It expires in 10 minutes.`
                      : "Open your authenticator app and enter the 6-digit code for Bald Ridge Lodge."}
                  </p>
                </div>
                <CodeInput value={code} onChange={setCode} />
                <SubmitButton busy={busy} label="Sign in" />
                {sentTo && (
                  <button
                    type="button"
                    onClick={() => void resend()}
                    className="w-full text-center text-[14px] font-medium text-cyan hover:underline"
                  >
                    Didn&apos;t get it? Send a new code
                  </button>
                )}
                {notice && <p className="text-center text-[14px] text-mint">{notice}</p>}
              </form>
            )}

            {error && (
              <p
                role="alert"
                className="mt-5 rounded-lg border border-rose/40 bg-rose/8 px-3.5 py-2.5 text-[14px] text-rose"
              >
                {error}
              </p>
            )}

            <p className="mt-10 flex items-start gap-2 text-[13px] leading-relaxed text-faint">
              <LockIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>
                For Bald Ridge Lodge staff only. You&apos;re signed out when you close the tab,
                and document views are logged.
              </span>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

function CodeInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <input
      inputMode="numeric"
      autoComplete="one-time-code"
      required
      maxLength={6}
      autoFocus
      aria-label="Six-digit code"
      value={value}
      onChange={(e) => onChange(e.target.value.replace(/\D/g, ""))}
      placeholder="000000"
      className="w-full rounded-lg border border-line bg-card px-3.5 py-3 text-center font-mono text-2xl tracking-[0.35em] text-text transition outline-none placeholder:text-faint/60 focus:border-cyan focus:ring-2 focus:ring-cyan/20"
    />
  );
}

function SubmitButton({ busy, label }: { busy: boolean; label: string }) {
  return (
    <button
      type="submit"
      disabled={busy}
      className="w-full rounded-lg bg-cyan py-2.5 text-[15px] font-semibold text-ink transition enabled:hover:opacity-90 disabled:opacity-50"
    >
      {busy ? "One moment…" : label}
    </button>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="grid min-h-screen place-items-center text-muted">…</div>}>
      <LoginForm />
    </Suspense>
  );
}
