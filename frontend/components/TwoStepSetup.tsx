"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type Options = { method: "" | "app" | "email"; email_available: boolean };
type AppSetup = { enroll_token: string; secret: string; qr_svg: string };
type EmailSetup = { enroll_token: string; sent_to: string };

export default function TwoStepSetup({ onDone }: { onDone: () => void | Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<Options | null>(null);
  const [app, setApp] = useState<AppSetup | null>(null);
  const [email, setEmail] = useState<EmailSetup | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open || options) return;
    api<Options>("/auth/2fa/options")
      .then(setOptions)
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load the options."));
  }, [open, options]);

  const reset = () => {
    setApp(null);
    setEmail(null);
    setCode("");
    setError("");
  };

  const start = async (method: "app" | "email") => {
    reset();
    setBusy(true);
    try {
      const res = await api<AppSetup | EmailSetup>("/auth/2fa/enroll", {
        method: "POST",
        body: { method },
      });
      if (method === "app") setApp(res as AppSetup);
      else setEmail(res as EmailSetup);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start setup.");
    } finally {
      setBusy(false);
    }
  };

  const confirm = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/auth/2fa/enroll/confirm", {
        method: "POST",
        body: { enroll_token: (app ?? email)?.enroll_token, code },
      });
      setOpen(false);
      reset();
      await onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That code didn't work.");
      setCode("");
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mt-3 rounded-xl bg-amber px-4 py-2 text-sm font-semibold text-ink transition hover:brightness-110"
      >
        Set up two-step sign-in
      </button>
    );
  }

  return (
    <div className="mt-4 rounded-xl border border-line bg-ink/50 p-4">
      {!app && !email && (
        <>
          <p className="text-sm text-text">How would you like to get your sign-in code?</p>
          <div className="mt-3 grid gap-2.5 sm:grid-cols-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => void start("app")}
              className="rounded-xl border border-line bg-card/70 p-3.5 text-left transition hover:border-cyan/50 disabled:opacity-50"
            >
              <span className="block text-sm font-medium text-text">Authenticator app</span>
              <span className="mt-0.5 block text-xs text-muted">
                Google Authenticator, Microsoft Authenticator, or Authy on your phone. Most secure.
              </span>
            </button>
            <button
              type="button"
              disabled={busy || !options?.email_available}
              onClick={() => void start("email")}
              className="rounded-xl border border-line bg-card/70 p-3.5 text-left transition hover:border-cyan/50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <span className="block text-sm font-medium text-text">Email</span>
              <span className="mt-0.5 block text-xs text-muted">
                {options && !options.email_available
                  ? "Not available yet — email sending hasn't been connected."
                  : "We email you a code each time you sign in."}
              </span>
            </button>
          </div>
        </>
      )}

      {(app || email) && (
        <form onSubmit={confirm} className="space-y-3">
          {app && (
            <>
              <p className="text-sm text-text">
                1. Open your authenticator app and add an account by scanning this code.
              </p>
              <div
                className="w-40 rounded-xl bg-white p-2.5 [&_svg]:h-full [&_svg]:w-full"
                dangerouslySetInnerHTML={{ __html: app.qr_svg }}
              />
              <details className="text-xs text-muted">
                <summary className="cursor-pointer">Can&apos;t scan? Type this key instead</summary>
                <code className="mt-2 block break-all rounded-lg bg-ink/60 p-2.5 font-mono text-cyan">
                  {app.secret}
                </code>
              </details>
              <p className="text-sm text-text">2. Enter the 6-digit code the app shows.</p>
            </>
          )}
          {email && (
            <p className="text-sm text-text">
              We emailed a 6-digit code to {email.sent_to}. Enter it below — it expires in 10
              minutes.
            </p>
          )}
          <input
            inputMode="numeric"
            autoComplete="one-time-code"
            required
            maxLength={6}
            autoFocus
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
            placeholder="000000"
            aria-label="Six-digit code"
            className="w-44 rounded-xl border border-line bg-ink/70 px-3 py-2.5 text-center font-mono text-xl tracking-[0.35em] text-text outline-none focus:border-cyan/50"
          />
          <div className="flex flex-wrap gap-2">
            <button
              disabled={busy || code.length !== 6}
              className="rounded-xl bg-cyan px-4 py-2 text-sm font-semibold text-ink transition enabled:hover:brightness-110 disabled:opacity-40"
            >
              {busy ? "Checking…" : "Turn on"}
            </button>
            <button
              type="button"
              onClick={reset}
              className="rounded-xl border border-line px-4 py-2 text-sm text-muted hover:text-text"
            >
              Back
            </button>
          </div>
        </form>
      )}

      {error && <p className="mt-3 text-sm text-rose">{error}</p>}

      {!app && !email && (
        <button
          type="button"
          onClick={() => {
            setOpen(false);
            reset();
          }}
          className="mt-3 text-xs text-muted hover:text-text"
        >
          Cancel
        </button>
      )}
    </div>
  );
}
