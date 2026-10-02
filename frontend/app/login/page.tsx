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

  return (
    <>
      <div className="atmosphere" />
      <div className="ledger" />
      <ThemeToggle className="fixed top-5 right-5 z-10" />
      <div className="grid min-h-screen place-items-center px-5 py-10">
      <div className="w-full max-w-md">
        <Link href="/" className="mb-8 inline-flex">
          <Logo lockup size="lg" />
        </Link>

        <div className="lit animate-fade-up rounded-2xl border border-line bg-card/85 p-7 shadow-2xl shadow-shade/40">
          {step === "credentials" && (
            <form onSubmit={submitCredentials} className="space-y-4">
              <div>
                <h2 className="display text-[21px] text-text">Sign in</h2>
                <p className="mt-1 text-sm text-muted">
                  Staff accounts are created by invitation only.
                </p>
              </div>

              <label className="block">
                <span className="mb-1.5 block font-mono text-[10px] tracking-[0.14em] text-faint uppercase">Work email</span>
                <input
                  type="email"
                  required
                  autoComplete="username"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full rounded-xl border border-line bg-ink/70 px-3.5 py-2.5 text-sm text-text transition outline-none focus:border-cyan/50 focus:ring-2 focus:ring-cyan/15"
                />
              </label>

              <label className="block">
                <span className="mb-1.5 block font-mono text-[10px] tracking-[0.14em] text-faint uppercase">Password</span>
                <input
                  type="password"
                  required
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full rounded-xl border border-line bg-ink/70 px-3.5 py-2.5 text-sm text-text transition outline-none focus:border-cyan/50 focus:ring-2 focus:ring-cyan/15"
                />
              </label>

              <SubmitButton busy={busy} label="Continue" />
            </form>
          )}

          {step === "enroll" && setup && (
            <form onSubmit={submitCode} className="space-y-4">
              <div>
                <h2 className="display text-[21px] text-text">Set up two-step sign-in</h2>
                <p className="mt-1 text-sm leading-relaxed text-muted">
                  This assistant can read private documents, so every account needs a second
                  factor. Scan this with Google Authenticator, Authy, or 1Password.
                </p>
              </div>

              <div
                className="mx-auto w-44 rounded-xl bg-white p-3 [&_svg]:h-full [&_svg]:w-full"
                dangerouslySetInnerHTML={{ __html: setup.qr_svg }}
              />

              <details className="text-xs text-muted">
                <summary className="cursor-pointer">Can&apos;t scan? Enter the key manually</summary>
                <code className="mt-2 block break-all rounded-lg bg-ink/60 p-2.5 font-mono text-cyan">
                  {setup.secret}
                </code>
              </details>

              <CodeInput value={code} onChange={setCode} />
              <SubmitButton busy={busy} label="Confirm and sign in" />
            </form>
          )}

          {step === "verify" && (
            <form onSubmit={submitCode} className="space-y-4">
              <div>
                <h2 className="display text-[21px] text-text">Verification code</h2>
                <p className="mt-1 text-sm text-muted">
                  {sentTo
                    ? `We emailed a 6-digit code to ${sentTo}. It expires in 10 minutes.`
                    : "Enter the 6-digit code from your authenticator app."}
                </p>
              </div>
              <CodeInput value={code} onChange={setCode} />
              <SubmitButton busy={busy} label="Sign in" />
              {sentTo && (
                <button
                  type="button"
                  onClick={() => void resend()}
                  className="w-full text-center text-xs text-muted hover:text-cyan"
                >
                  Didn&apos;t get it? Send a new code
                </button>
              )}
              {notice && <p className="text-center text-xs text-mint">{notice}</p>}
            </form>
          )}

          {error && (
            <p className="mt-4 rounded-xl border border-rose/40 bg-rose/10 px-3.5 py-2.5 text-sm text-rose">
              {error}
            </p>
          )}
        </div>

        <p className="mt-6 flex items-start justify-center gap-2 text-center text-[11px] leading-relaxed text-faint">
          <LockIcon className="mt-px h-3.5 w-3.5 shrink-0" />
          <span>
            Authorized personnel only. Sessions end when you close the browser tab, and every
            document access is recorded in the audit log.
          </span>
        </p>
      </div>
      </div>
    </>
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
      value={value}
      onChange={(e) => onChange(e.target.value.replace(/\D/g, ""))}
      placeholder="000000"
      className="w-full rounded-xl border border-line bg-ink/70 px-3.5 py-3.5 text-center font-mono text-2xl tracking-[0.4em] text-text transition outline-none focus:border-cyan/50 focus:ring-2 focus:ring-cyan/15"
    />
  );
}

function SubmitButton({ busy, label }: { busy: boolean; label: string }) {
  return (
    <button
      type="submit"
      disabled={busy}
      className="w-full rounded-xl bg-cyan py-3 text-sm font-semibold text-ink transition enabled:hover:brightness-110 disabled:opacity-50"
    >
      {busy ? "Working…" : label}
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
