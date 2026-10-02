"use client";

import { use, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import ThemeToggle from "@/components/ThemeToggle";
import { api } from "@/lib/api";
import { useAuth, type User } from "@/lib/auth";

type InviteInfo = { email: string; role: string; org_name: string };
type SetupResponse = { secret: string; otpauth_uri: string; qr_svg: string };
type AcceptResponse = {
  status: "ok" | "2fa_setup_required";
  challenge_token?: string;
  access_token?: string;
  user?: User;
};

export default function InvitePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  const router = useRouter();
  const { signIn } = useAuth();

  const [info, setInfo] = useState<InviteInfo | null>(null);
  const [loadError, setLoadError] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [challenge, setChallenge] = useState("");
  const [setup, setSetup] = useState<SetupResponse | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<InviteInfo>(`/auth/invite/${token}`)
      .then(setInfo)
      .catch((e) => setLoadError(e instanceof Error ? e.message : "This invitation is not valid."));
  }, [token]);

  const accept = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password !== confirm) {
      setError("The two passwords don't match.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const res = await api<AcceptResponse>("/auth/invite/accept", {
        method: "POST",
        body: { token, full_name: fullName, password },
      });
      if (res.status === "ok" && res.access_token && res.user) {
        signIn(res.access_token, res.user);
        router.push("/ask");
        return;
      }
      setChallenge(res.challenge_token ?? "");
      setSetup(
        await api<SetupResponse>("/auth/2fa/setup", {
          method: "POST",
          body: { challenge_token: res.challenge_token },
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the account.");
    } finally {
      setBusy(false);
    }
  };

  const confirmTotp = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await api<AcceptResponse>("/auth/2fa/confirm", {
        method: "POST",
        body: { challenge_token: challenge, code },
      });
      if (res.access_token && res.user) {
        signIn(res.access_token, res.user);
        router.push("/ask");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "That code didn't match.");
      setCode("");
    } finally {
      setBusy(false);
    }
  };

  if (loadError) {
    return (
      <div className="grid min-h-screen place-items-center px-5">
        <div className="max-w-md rounded-2xl border border-rose/40 bg-rose/8 p-7 text-center">
          <h1 className="font-semibold text-text">Invitation unavailable</h1>
          <p className="mt-2 text-sm text-muted">{loadError}</p>
        </div>
      </div>
    );
  }

  if (!info) {
    return <div className="grid min-h-screen place-items-center text-sm text-muted">Loading…</div>;
  }

  return (
    <div className="grid min-h-screen place-items-center px-5 py-10">
      <ThemeToggle className="fixed top-5 right-5 z-10" />
      <div className="w-full max-w-md animate-fade-up rounded-2xl border border-line bg-card/80 p-7">
        {!setup ? (
          <form onSubmit={accept} className="space-y-4">
            <div>
              <h1 className="text-lg font-semibold text-text">Join {info.org_name}</h1>
              <p className="mt-1 text-sm text-muted">
                Setting up the account for <span className="text-cyan">{info.email}</span>.
              </p>
            </div>

            <label className="block">
              <span className="mb-1.5 block text-xs font-medium text-muted">Full name</span>
              <input
                required
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                className="w-full rounded-xl border border-line bg-ink/60 px-3.5 py-2.5 text-sm text-text outline-none focus:border-cyan/50"
              />
            </label>

            <label className="block">
              <span className="mb-1.5 block text-xs font-medium text-muted">
                Password (at least 12 characters)
              </span>
              <input
                type="password"
                required
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-xl border border-line bg-ink/60 px-3.5 py-2.5 text-sm text-text outline-none focus:border-cyan/50"
              />
            </label>

            <label className="block">
              <span className="mb-1.5 block text-xs font-medium text-muted">Confirm password</span>
              <input
                type="password"
                required
                autoComplete="new-password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                className="w-full rounded-xl border border-line bg-ink/60 px-3.5 py-2.5 text-sm text-text outline-none focus:border-cyan/50"
              />
            </label>

            <button
              type="submit"
              disabled={busy}
              className="w-full rounded-xl bg-cyan py-2.5 text-sm font-semibold text-ink transition enabled:hover:brightness-110 disabled:opacity-50"
            >
              {busy ? "Creating…" : "Create account"}
            </button>
          </form>
        ) : (
          <form onSubmit={confirmTotp} className="space-y-4">
            <div>
              <h1 className="text-lg font-semibold text-text">One more step</h1>
              <p className="mt-1 text-sm leading-relaxed text-muted">
                Scan this with your authenticator app, then enter the 6-digit code.
              </p>
            </div>
            <div
              className="mx-auto w-44 rounded-xl bg-white p-3 [&_svg]:h-full [&_svg]:w-full"
              dangerouslySetInnerHTML={{ __html: setup.qr_svg }}
            />
            <input
              inputMode="numeric"
              required
              maxLength={6}
              autoFocus
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
              placeholder="000000"
              className="w-full rounded-xl border border-line bg-ink/60 px-3.5 py-3 text-center font-mono text-2xl tracking-[0.4em] text-text outline-none focus:border-cyan/50"
            />
            <button
              type="submit"
              disabled={busy}
              className="w-full rounded-xl bg-cyan py-2.5 text-sm font-semibold text-ink transition enabled:hover:brightness-110 disabled:opacity-50"
            >
              {busy ? "Verifying…" : "Finish setup"}
            </button>
          </form>
        )}

        {error && (
          <p className="mt-4 rounded-xl border border-rose/40 bg-rose/10 px-3.5 py-2.5 text-sm text-rose">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
