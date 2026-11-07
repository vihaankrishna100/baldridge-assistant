"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import AppShell from "@/components/AppShell";
import StorageMeter, { type Storage } from "@/components/StorageMeter";
import TwoStepSetup from "@/components/TwoStepSetup";
import { api } from "@/lib/api";
import { useRequireAuth, type User } from "@/lib/auth";

type Stats = {
  users: number;
  documents: number;
  questions_30d: number;
  answered_30d: number;
  escalated_30d: number;
  answer_rate: number;
  window_days: number;
  index: { chunks: number; documents: number; semantic_enabled: boolean };
  coverage_gaps: { question: string; count: number }[];
  storage: Storage | null;
};

type Settings = {
  org_name: string;
  org_phone: string;
  org_email: string;
  contact_configured: boolean;
  require_2fa: boolean;
  twofa_exempt: string[];
  model: string;
  effort: string;
  retrieval_min_score: number;
  max_queries_per_hour: number;
  storage: string;
  email_enabled?: boolean;
  model_source?: "admin" | "server";
  server_model?: string;
  model_choices?: { id: string; label: string }[];
};

type Invite = { id: string; email: string; role: string; expires_at: string; expired: boolean };
type InviteResult = { email: string; invite_url: string; emailed: boolean; expires_at: string };

// navigator.clipboard only exists on https and localhost, and some browsers
// refuse it without a recent click. The hidden-textarea copy is the fallback.
async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const el = document.createElement("textarea");
    el.value = text;
    el.setAttribute("readonly", "");
    el.style.position = "fixed";
    el.style.opacity = "0";
    document.body.appendChild(el);
    el.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(el);
    return ok;
  }
}

function inviteMessage(orgName: string, inv: InviteResult): string {
  const org = orgName || "Bald Ridge Lodge";
  const until = new Date(inv.expires_at).toLocaleDateString(undefined, {
    month: "long",
    day: "numeric",
  });
  return (
    `Hi,\n\nYou've been invited to the ${org} Assistant, which answers questions from ` +
    `the Lodge's own policies and procedures.\n\n` +
    `Create your password here (the link works once and expires ${until}):\n` +
    `${inv.invite_url}\n\n` +
    `After setting a password you'll be asked to scan a QR code with an authenticator ` +
    `app on your phone (Google Authenticator or Microsoft Authenticator), then enter ` +
    `the 6-digit code it shows. Install one before you start.\n`
  );
}
type AuditRow = {
  id: number;
  at: string;
  user_email: string;
  action: string;
  target: string;
  detail: string;
  ip: string;
};

const ACTION_TONE: Record<string, string> = {
  login_failed: "text-amber",
  account_locked: "text-rose",
  "2fa_failed": "text-amber",
  meta_query_blocked: "text-rose",
  document_access_denied: "text-rose",
  question_escalated: "text-amber",
  document_deleted: "text-rose",
  user_deactivated: "text-rose",
};

export default function AdminPage() {
  const { user, loading } = useRequireAuth("admin");
  const [tab, setTab] = useState<"overview" | "people" | "permissions" | "audit">("overview");
  const [stats, setStats] = useState<Stats | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [audit, setAudit] = useState<AuditRow[]>([]);
  const [retention, setRetention] = useState<{ days: number; choices: number[] } | null>(null);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("staff");
  const [inviteResult, setInviteResult] = useState<InviteResult | null>(null);
  const [copied, setCopied] = useState<"" | "link" | "message" | "failed">("");
  const resultRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState("");
  const [twoStepDone, setTwoStepDone] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, cfg, u, i, a, r] = await Promise.all([
        api<Stats>("/admin/stats"),
        api<Settings>("/admin/settings"),
        api<User[]>("/admin/users"),
        api<Invite[]>("/admin/invites"),
        api<AuditRow[]>("/admin/audit?limit=150"),
        api<{ days: number; choices: number[] }>("/admin/audit/retention"),
      ]);
      setStats(s);
      setSettings(cfg);
      setUsers(u);
      setInvites(i);
      setAudit(a);
      setRetention(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the admin data.");
    }
  }, []);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  const changeRetention = async (days: number) => {
    setError("");
    try {
      await api("/admin/audit/retention", { method: "PUT", body: { days } });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not change how long the log is kept.");
    }
  };

  const clearAudit = async () => {
    if (!confirm("Clear the whole audit log? This can't be undone. The question stats reset too.")) return;
    setError("");
    try {
      await api("/admin/audit", { method: "DELETE" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not clear the audit log.");
    }
  };

  const createInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      const res = await api<InviteResult>("/admin/invites", {
        method: "POST",
        body: { email: inviteEmail, role: inviteRole },
      });
      showInvite(res);
      setInviteEmail("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the invitation.");
    }
  };

  const showInvite = (res: InviteResult) => {
    setInviteResult(res);
    setCopied("");
    // The list sits below the box, so after "New link" on a row the new
    // link would otherwise appear off-screen above the button pressed.
    requestAnimationFrame(() =>
      resultRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }),
    );
  };

  const copy = async (what: "link" | "message") => {
    if (!inviteResult) return;
    const text =
      what === "link" ? inviteResult.invite_url : inviteMessage(settings?.org_name ?? "", inviteResult);
    setCopied((await copyText(text)) ? what : "failed");
  };

  const resendInvite = async (inv: Invite) => {
    setError("");
    try {
      const res = await api<InviteResult>(`/admin/invites/${inv.id}/resend`, { method: "POST" });
      showInvite(res);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not resend the invitation.");
    }
  };

  if (loading || !user) {
    return <div className="grid flex-1 place-items-center text-sm text-muted">Loading…</div>;
  }

  // Allowed to skip the code and haven't turned it on themselves.
  const unprotected = (settings?.twofa_exempt ?? []).filter(
    (email) => !users.find((u) => u.email.toLowerCase() === email)?.totp_confirmed,
  );

  return (
    <AppShell>
      <div className="mb-6">
        <p className="eyebrow">Control</p>
        <h1 className="display-loose mt-3 text-[2rem] text-text">Administration</h1>
        <p className="mt-1.5 text-sm text-muted">Access, activity, and coverage.</p>
      </div>

      {settings && !settings.contact_configured && (
        <div className="mb-6 rounded-2xl border border-amber/45 bg-amber/8 p-4">
          <p className="text-sm font-medium text-amber">Fallback contact is not configured</p>
          <p className="mt-1 text-sm leading-relaxed text-muted">
            When the assistant can&apos;t answer, it currently tells staff to ask a supervisor
            because it has no number to give. Set <code className="text-cyan">ORG_PHONE</code> and{" "}
            <code className="text-cyan">ORG_EMAIL</code> in <code>backend/.env</code> and restart
            the API. It will never invent a number.
          </p>
        </div>
      )}

      {twoStepDone && (
        <p className="mb-6 rounded-2xl border border-mint/40 bg-mint/10 px-4 py-3 text-sm text-mint">
          Two-step sign-in is on. Next time you sign in, you&apos;ll enter a code after your
          password.
        </p>
      )}

      {unprotected.length > 0 && (
        <div className="mb-6 rounded-2xl border border-amber/40 bg-amber/8 p-4">
          <p className="text-sm font-medium text-amber">
            {unprotected.length === 1
              ? "Heads up: this account signs in with just a password"
              : `Heads up: ${unprotected.length} accounts sign in with just a password`}
          </p>
          <p className="mt-1 text-sm leading-relaxed text-muted">
            <span className="text-text">{unprotected.join(", ")}</span>{" "}
            {unprotected.length === 1 ? "doesn't" : "don't"} ask for a sign-in code the way
            other accounts do. Anyone who learns{" "}
            {unprotected.length === 1 ? "its" : "their"} password could open every document,
            including leadership-only ones. Turning on two-step sign-in fixes that: after the
            password, you also enter a 6-digit code from your phone or email.
          </p>
          {unprotected.includes(user.email.toLowerCase()) ? (
            <TwoStepSetup
              onDone={async () => {
                setTwoStepDone(true);
                await load();
              }}
            />
          ) : (
            <p className="mt-2 text-sm text-muted">
              Ask {unprotected.length === 1 ? "that person" : "those people"} to sign in and
              press &ldquo;Set up two-step sign-in&rdquo; on this page.
            </p>
          )}
        </div>
      )}

      <div className="mb-6 flex gap-1.5">
        {(["overview", "people", "permissions", "audit"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`rounded-lg px-3.5 py-1.5 text-sm capitalize transition ${
              tab === t ? "bg-cyan/12 text-cyan" : "text-muted hover:bg-white/5 hover:text-text"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {error && (
        <p className="mb-5 rounded-xl border border-rose/40 bg-rose/10 px-4 py-2.5 text-sm text-rose">
          {error}
        </p>
      )}

      {tab === "overview" && stats && (
        <div className="space-y-6">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Active staff" value={stats.users} />
            <Stat label="Live documents" value={stats.documents} />
            <Stat
              label={`Answered from docs (${stats.window_days}d)`}
              value={stats.answered_30d}
              hint={`${Math.round(stats.answer_rate * 100)}% of questions`}
            />
            <Stat
              label={`Referred to a person (${stats.window_days}d)`}
              value={stats.escalated_30d}
              hint="Working as designed"
              tone="amber"
            />
          </div>

          {stats.storage && (
            <StorageMeter
              storage={stats.storage}
              filesInGitHub={settings?.storage === "GitHubDocStore"}
            />
          )}

          <section className="rounded-2xl border border-line bg-card/70 p-6">
            <h2 className="text-sm font-semibold text-text">Where the documents fall short</h2>
            <p className="mt-1 mb-4 text-sm text-muted">
              Questions staff asked that nothing in the library answered. Each one is a candidate
              for a new policy document.
            </p>
            {stats.coverage_gaps.length === 0 ? (
              <p className="text-sm text-faint">Nothing yet.</p>
            ) : (
              <ul className="space-y-1.5">
                {stats.coverage_gaps.map((gap) => (
                  <li
                    key={gap.question}
                    className="flex items-start gap-3 rounded-lg bg-ink/40 px-3 py-2 text-sm"
                  >
                    <span className="mt-0.5 rounded-md bg-amber/20 px-1.5 text-[11px] text-amber">
                      {gap.count}×
                    </span>
                    <span className="text-muted">{gap.question}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {settings && (
            <section className="rounded-2xl border border-line bg-card/70 p-6">
              <h2 className="mb-4 text-sm font-semibold text-text">Settings</h2>
              <ModelPicker settings={settings} onChange={load} />
              <dl className="grid gap-x-8 gap-y-2.5 text-sm sm:grid-cols-2">
                <Row label="Searchable sections" value={String(stats.index.chunks)} />
                <Row
                  label="Question limit"
                  value={`${settings.max_queries_per_hour} per person, per hour`}
                />
                <Row
                  label="Phone-code sign-in"
                  value={
                    settings.require_2fa
                      ? settings.twofa_exempt.length
                        ? `On — ${settings.twofa_exempt.length} account${
                            settings.twofa_exempt.length === 1 ? " skips" : "s skip"
                          } it`
                        : "On for everyone"
                      : "Off"
                  }
                />
                <Row
                  label="Who staff are told to contact"
                  value={
                    settings.contact_configured
                      ? [settings.org_phone, settings.org_email].filter(Boolean).join(" · ")
                      : "Not configured"
                  }
                />
              </dl>
            </section>
          )}
        </div>
      )}

      {tab === "people" && (
        <div className="space-y-6">
          <TeamLogin team={users.find((u) => u.role === "team")} onChange={load} />

          <section className="rounded-2xl border border-line bg-card/70 p-6">
            <h2 className="text-sm font-semibold text-text">Invite a team member</h2>
            <p className="mt-1 mb-4 text-sm text-muted">
              Their own account, with their own history and two-factor. Use this for leadership,
              administrators, and anyone who should be able to see leadership-only documents.{" "}
              {settings?.email_enabled
                ? "The link is emailed to them, and shown here too."
                : "You'll get a link to copy and send them yourself, by email or text."}
            </p>
            <form onSubmit={createInvite} className="flex flex-wrap gap-2.5">
              <input
                type="email"
                required
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                placeholder="name@baldridgelodge.org"
                className="min-w-56 flex-1 rounded-xl border border-line bg-ink/60 px-3.5 py-2.5 text-sm text-text outline-none focus:border-cyan/50"
              />
              <select
                value={inviteRole}
                onChange={(e) => setInviteRole(e.target.value)}
                className="rounded-xl border border-line bg-ink/60 px-3.5 py-2.5 text-sm text-text outline-none focus:border-cyan/50"
              >
                <option value="staff">Staff</option>
                <option value="leadership">Leadership</option>
                <option value="admin">Administrator</option>
              </select>
              <button className="rounded-xl bg-cyan px-5 py-2 text-sm font-semibold text-ink transition hover:brightness-110">
                Create link
              </button>
            </form>

            {inviteResult && (
              <div ref={resultRef} className="mt-4 rounded-xl border border-mint/40 bg-mint/8 p-3.5">
                <p className="text-sm font-medium text-mint">
                  {inviteResult.emailed
                    ? `Emailed to ${inviteResult.email}`
                    : `Now send this link to ${inviteResult.email}`}
                </p>
                <p className="mt-1 text-xs leading-relaxed text-muted">
                  {inviteResult.emailed
                    ? "The link is also here in case they can't find the email. "
                    : "Copy it into an email or text from your own account. "}
                  It works once and expires in 7 days. Copy it now: it can&apos;t be shown again
                  after you leave this page. If it&apos;s lost, use &ldquo;New link&rdquo; below.
                </p>
                <code className="mt-2 block break-all rounded-lg bg-ink/60 p-2.5 font-mono text-xs text-cyan">
                  {inviteResult.invite_url}
                </code>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <button
                    onClick={() => void copy("link")}
                    className="rounded-lg bg-cyan px-3 py-1 text-xs font-semibold text-ink hover:brightness-110"
                  >
                    {copied === "link" ? "Link copied ✓" : "Copy link"}
                  </button>
                  <button
                    onClick={() => void copy("message")}
                    className="rounded-lg border border-line px-3 py-1 text-xs text-muted hover:text-cyan"
                  >
                    {copied === "message" ? "Message copied ✓" : "Copy a ready-to-send message"}
                  </button>
                  <a
                    href={`mailto:${encodeURIComponent(inviteResult.email)}?subject=${encodeURIComponent(
                      `Your ${settings?.org_name || "Bald Ridge Lodge"} Assistant invitation`,
                    )}&body=${encodeURIComponent(inviteMessage(settings?.org_name ?? "", inviteResult))}`}
                    className="rounded-lg border border-line px-3 py-1 text-xs text-muted hover:text-cyan"
                  >
                    Open in my email
                  </a>
                  {copied === "failed" && (
                    <span className="text-xs text-rose">
                      Couldn&apos;t copy. Select the link above and copy it by hand.
                    </span>
                  )}
                </div>
              </div>
            )}

            {invites.length > 0 && (
              <ul className="mt-5 space-y-1.5">
                {invites.map((inv) => (
                  <li
                    key={inv.id}
                    className="flex items-center gap-3 rounded-lg bg-ink/40 px-3 py-2 text-sm"
                  >
                    <span className="min-w-0 flex-1 break-words text-muted">
                      {inv.email}{" "}
                      <span className="text-faint">
                        · {inv.role} ·{" "}
                        {inv.expired ? (
                          <span className="text-amber">
                            expired {new Date(inv.expires_at).toLocaleDateString()}, never used
                          </span>
                        ) : (
                          <>expires {new Date(inv.expires_at).toLocaleDateString()}</>
                        )}
                      </span>
                    </span>
                    <button
                      onClick={() => void resendInvite(inv)}
                      title="Makes a fresh link to copy and send. Any earlier link stops working."
                      className={`text-xs ${inv.expired ? "text-cyan hover:brightness-110" : "text-faint hover:text-cyan"}`}
                    >
                      New link
                    </button>
                    <button
                      onClick={async () => {
                        await api(`/admin/invites/${inv.id}`, { method: "DELETE" });
                        await load();
                      }}
                      className="text-xs text-faint hover:text-rose"
                    >
                      Revoke
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="rounded-2xl border border-line bg-card/70 p-6">
            <h2 className="mb-4 text-sm font-semibold text-text">Accounts</h2>
            <ul className="space-y-2">
              {users.filter((u) => u.role !== "team").map((u) => (
                <li
                  key={u.id}
                  className={`flex flex-wrap items-center gap-3 rounded-xl border border-line px-4 py-3 ${
                    u.is_active ? "" : "opacity-50"
                  }`}
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-text">{u.full_name || u.email}</p>
                    <p className="text-[11px] text-faint">
                      {u.email} · {u.role}
                      {u.twofa_method === "email"
                        ? " · sign-in code by email"
                        : u.totp_confirmed
                          ? " · sign-in code from app"
                          : " · no sign-in code yet"}
                      {u.is_active ? "" : " · deactivated"}
                    </p>
                    {u.is_active && !u.last_login_at && (
                      <p className="mt-0.5 text-[11px] text-amber">
                        Hasn&apos;t finished signing in yet. They can sign in with their password
                        and scan the new QR code with an authenticator app (Google or Microsoft
                        Authenticator); the 6-digit code from the app finishes setup.
                      </p>
                    )}
                  </div>
                  <div className="flex gap-1.5">
                    <select
                      value={u.role}
                      onChange={async (e) => {
                        await api(`/admin/users/${u.id}/role`, {
                          method: "POST",
                          body: { role: e.target.value },
                        });
                        await load();
                      }}
                      className="rounded-lg border border-line bg-ink/60 px-2 py-1 text-xs text-muted"
                    >
                      <option value="staff">Staff</option>
                      <option value="leadership">Leadership</option>
                      <option value="admin">Admin</option>
                    </select>
                    <button
                      onClick={async () => {
                        await api(`/admin/users/${u.id}/reset-2fa`, { method: "POST" });
                        await load();
                      }}
                      className="rounded-lg border border-line px-2.5 py-1 text-xs text-muted hover:text-amber"
                    >
                      Reset sign-in code
                    </button>
                    <button
                      onClick={async () => {
                        const action = u.is_active ? "deactivate" : "activate";
                        await api(`/admin/users/${u.id}/${action}`, { method: "POST" });
                        await load();
                      }}
                      className="rounded-lg border border-line px-2.5 py-1 text-xs text-muted hover:text-rose"
                    >
                      {u.is_active ? "Deactivate" : "Reactivate"}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}

      {tab === "permissions" && <PermissionsEditor />}

      {tab === "audit" && (
        <section className="overflow-hidden rounded-2xl border border-line bg-card/50">
          <div className="flex flex-wrap items-end justify-between gap-3 border-b border-line px-5 py-3.5">
            <div>
              <h2 className="text-sm font-semibold text-text">Audit trail</h2>
              <p className="mt-0.5 text-xs text-muted">
                Every sign-in, document access, and question. Older entries are removed automatically.
              </p>
            </div>
            <div className="flex items-center gap-2">
              {retention && (
                <label className="flex items-center gap-2 text-xs text-muted">
                  Keep for
                  <select
                    value={retention.days}
                    onChange={(e) => void changeRetention(Number(e.target.value))}
                    className="rounded-lg border border-line bg-ink/60 px-2.5 py-1.5 text-xs text-text outline-none focus:border-cyan/50"
                  >
                    {retention.choices.map((d) => (
                      <option key={d} value={d}>
                        {d === 0 ? "Forever" : d === 1 ? "1 day" : `${d} days`}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <button
                onClick={() => void clearAudit()}
                className="rounded-lg border border-line px-3 py-1.5 text-xs text-muted hover:text-rose"
              >
                Clear log
              </button>
            </div>
          </div>
          <div className="max-h-[65vh] overflow-auto">
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 bg-raised text-[11px] tracking-wider text-faint uppercase">
                <tr>
                  <th className="px-4 py-2.5 font-medium">When</th>
                  <th className="px-4 py-2.5 font-medium">Who</th>
                  <th className="px-4 py-2.5 font-medium">Action</th>
                  <th className="px-4 py-2.5 font-medium">Detail</th>
                </tr>
              </thead>
              <tbody>
                {audit.map((row) => (
                  <tr key={row.id} className="border-t border-line-soft/60">
                    <td className="px-4 py-2 text-xs whitespace-nowrap text-faint">
                      {new Date(row.at).toLocaleString()}
                    </td>
                    <td className="px-4 py-2 text-xs text-muted">{row.user_email || "—"}</td>
                    <td
                      className={`px-4 py-2 font-mono text-xs ${ACTION_TONE[row.action] ?? "text-cyan"}`}
                    >
                      {row.action}
                    </td>
                    <td className="max-w-md truncate px-4 py-2 text-xs text-muted">
                      {[row.target, row.detail].filter(Boolean).join(" — ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </AppShell>
  );
}

function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: number;
  hint?: string;
  tone?: "amber";
}) {
  return (
    <div className="lit rounded-2xl border border-line bg-card/70 p-5">
      <p className="font-mono text-[10px] tracking-[0.16em] text-faint uppercase">{label}</p>
      <p className={`display mt-2 text-[1.9rem] ${tone === "amber" ? "text-amber" : "text-text"}`}>
        {value}
      </p>
      {hint && <p className="mt-0.5 text-[11px] text-faint">{hint}</p>}
    </div>
  );
}

function TeamLogin({ team, onChange }: { team?: User; onChange: () => Promise<void> }) {
  const [email, setEmail] = useState(team?.email ?? "");
  const [password, setPassword] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const active = Boolean(team?.is_active);

  useEffect(() => {
    setEmail(team?.email ?? "");
  }, [team?.email]);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api("/admin/team", { method: "PUT", body: { email, password } });
      setPassword("");
      setNotice(
        team
          ? "Saved. Everyone on the team login has been signed out — share the new details with staff."
          : "Team login created. Share the email and password with staff.",
      );
      await onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the team login.");
    } finally {
      setBusy(false);
    }
  };

  const turnOff = async () => {
    if (!confirm("Turn off the team login? Everyone using it is signed out immediately.")) return;
    setError("");
    setNotice("");
    try {
      await api("/admin/team", { method: "DELETE" });
      setNotice("Team login turned off.");
      await onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not turn off the team login.");
    }
  };

  return (
    <section className="rounded-2xl border border-line bg-card/70 p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="text-sm font-semibold text-text">Team login</h2>
        <span className={`text-xs ${active ? "text-mint" : "text-faint"}`}>
          {active ? "On" : team ? "Off" : "Not set up"}
        </span>
      </div>
      <p className="mt-1 mb-4 text-sm text-muted">
        One shared sign-in for all staff, so nobody has to make an account. It can ask questions
        about staff documents only — no leadership documents, no uploads — and each device keeps
        its own chat history. It signs in with a password alone, so change it whenever someone
        leaves; saving a new password signs everyone out.
      </p>

      <form onSubmit={save} className="flex flex-wrap gap-2.5">
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="staff@baldridgelodge.org"
          aria-label="Team login email"
          className="min-w-56 flex-1 rounded-xl border border-line bg-ink/60 px-3.5 py-2.5 text-sm text-text outline-none focus:border-cyan/50"
        />
        <input
          type="text"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder={team ? "New password" : "Password"}
          aria-label="Team login password"
          autoComplete="new-password"
          className="min-w-48 flex-1 rounded-xl border border-line bg-ink/60 px-3.5 py-2.5 font-mono text-sm text-text outline-none focus:border-cyan/50"
        />
        <button
          disabled={busy}
          className="rounded-xl bg-cyan px-5 py-2 text-sm font-semibold text-ink transition enabled:hover:brightness-110 disabled:opacity-40"
        >
          {busy ? "Saving…" : !team ? "Create team login" : active ? "Change" : "Turn on"}
        </button>
        {active && (
          <button
            type="button"
            onClick={() => void turnOff()}
            className="rounded-xl border border-line px-4 py-2 text-sm text-muted hover:text-rose"
          >
            Turn off
          </button>
        )}
      </form>
      <p className="mt-2 text-[11px] text-faint">
        At least 12 characters, with a letter and a number. The email doesn’t need to be a real
        inbox — it’s just what staff type to sign in.
      </p>

      {notice && <p className="mt-3 text-sm text-mint">{notice}</p>}
      {error && <p className="mt-3 text-sm text-rose">{error}</p>}
    </section>
  );
}

type PermissionsData = {
  permissions: { id: string; label: string; description: string }[];
  roles: { id: string; label: string }[];
  matrix: Record<string, string[]>;
  defaults: Record<string, string[]>;
};

function PermissionsEditor() {
  const [data, setData] = useState<PermissionsData | null>(null);
  const [draft, setDraft] = useState<Record<string, string[]>>({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);

  const apply = (d: PermissionsData) => {
    setData(d);
    setDraft(d.matrix);
  };

  useEffect(() => {
    api<PermissionsData>("/admin/permissions")
      .then(apply)
      .catch((e) =>
        setMessage({ text: e instanceof Error ? e.message : "Could not load permissions.", ok: false }),
      );
  }, []);

  if (!data) {
    return message ? (
      <p className="text-sm text-rose">{message.text}</p>
    ) : (
      <p className="text-sm text-muted">Loading…</p>
    );
  }

  const same = (a: string[] = [], b: string[] = []) =>
    a.length === b.length && [...a].sort().join() === [...b].sort().join();
  const dirty = data.roles.some((r) => !same(draft[r.id], data.matrix[r.id]));
  const isDefault = data.roles.every((r) => same(draft[r.id], data.defaults[r.id]));

  const toggle = (role: string, perm: string) => {
    setMessage(null);
    setDraft((d) => {
      const has = (d[role] ?? []).includes(perm);
      return { ...d, [role]: has ? d[role].filter((p) => p !== perm) : [...(d[role] ?? []), perm] };
    });
  };

  const save = async () => {
    setSaving(true);
    setMessage(null);
    try {
      apply(await api<PermissionsData>("/admin/permissions", { method: "PUT", body: { matrix: draft } }));
      setMessage({ text: "Saved. Everyone gets the new permissions within about a minute.", ok: true });
    } catch (e) {
      setMessage({ text: e instanceof Error ? e.message : "Could not save.", ok: false });
    } finally {
      setSaving(false);
    }
  };

  const reset = async () => {
    if (!confirm("Put every role back to the original permissions?")) return;
    setSaving(true);
    setMessage(null);
    try {
      apply(await api<PermissionsData>("/admin/permissions/reset", { method: "POST" }));
      setMessage({ text: "Back to the original permissions.", ok: true });
    } catch (e) {
      setMessage({ text: e instanceof Error ? e.message : "Could not reset.", ok: false });
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="rounded-2xl border border-line bg-card/70 p-6">
      <h2 className="text-sm font-semibold text-text">What each role can see and do</h2>
      <p className="mt-1 mb-5 text-sm text-muted">
        Tick what each role is allowed. Administrators always have everything, and only they can
        open this Admin page. A change applies to everyone with that role within about a minute,
        and is recorded in the audit log.
      </p>

      <div className="-mx-2 overflow-x-auto px-2">
        <table className="w-full min-w-[34rem] border-collapse text-sm">
          <thead>
            <tr className="border-b border-line text-left">
              <th className="py-2 pr-4 font-medium text-muted">Permission</th>
              {data.roles.map((r) => (
                <th key={r.id} className="px-2 py-2 text-center font-medium text-text">
                  {r.label}
                </th>
              ))}
              <th className="px-2 py-2 text-center font-medium text-faint">Admin</th>
            </tr>
          </thead>
          <tbody>
            {data.permissions.map((p) => (
              <tr key={p.id} className="border-b border-line-soft/50 align-top">
                <td className="py-3 pr-4">
                  <p className="text-text">{p.label}</p>
                  <p className="mt-0.5 text-xs text-faint">{p.description}</p>
                </td>
                {data.roles.map((r) => (
                  <td key={r.id} className="px-2 py-3 text-center">
                    <input
                      type="checkbox"
                      aria-label={`${r.label}: ${p.label}`}
                      checked={(draft[r.id] ?? []).includes(p.id)}
                      onChange={() => toggle(r.id, p.id)}
                      disabled={saving}
                      className="h-4 w-4 cursor-pointer accent-cyan"
                    />
                  </td>
                ))}
                <td className="px-2 py-3 text-center">
                  <input
                    type="checkbox"
                    checked
                    disabled
                    aria-label={`Admin: ${p.label} (always on)`}
                    className="h-4 w-4 accent-cyan opacity-50"
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-2.5">
        <button
          onClick={() => void save()}
          disabled={!dirty || saving}
          className="rounded-xl bg-cyan px-5 py-2 text-sm font-semibold text-ink transition hover:brightness-110 disabled:opacity-40"
        >
          {saving ? "Saving…" : "Save changes"}
        </button>
        {dirty && (
          <button
            onClick={() => {
              setDraft(data.matrix);
              setMessage(null);
            }}
            disabled={saving}
            className="rounded-xl border border-line px-4 py-2 text-sm text-muted hover:text-text"
          >
            Discard
          </button>
        )}
        {!isDefault && (
          <button
            onClick={() => void reset()}
            disabled={saving}
            className="rounded-xl border border-line px-4 py-2 text-sm text-muted hover:text-amber"
          >
            Reset to original
          </button>
        )}
        {dirty && <span className="text-xs text-amber">Unsaved changes</span>}
      </div>
      {message && (
        <p className={`mt-3 text-sm ${message.ok ? "text-mint" : "text-rose"}`}>{message.text}</p>
      )}
      <p className="mt-4 text-xs leading-relaxed text-faint">
        The team login is the shared account on the People tab. Someone who can manage documents
        but can&apos;t see leadership-only ones can only change and publish staff-level documents.
      </p>
    </section>
  );
}

function ModelPicker({ settings, onChange }: { settings: Settings; onChange: () => Promise<void> }) {
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);
  const choices = settings.model_choices ?? [];
  // "" means "use the server's setting", shown as its own option.
  const value = settings.model_source === "admin" ? settings.model : "";
  const serverLabel = choices.find((c) => c.id === settings.server_model)?.label.split(":")[0];

  const change = async (model: string) => {
    setSaving(true);
    setMessage(null);
    try {
      await api("/admin/model", { method: "PUT", body: { model } });
      await onChange();
      setMessage({ text: "Saved. New questions use it within about a minute.", ok: true });
    } catch (e) {
      setMessage({ text: e instanceof Error ? e.message : "Could not change the model.", ok: false });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mb-4 rounded-xl border border-line-soft/60 bg-ink/30 p-3.5">
      <label className="flex flex-wrap items-center justify-between gap-3 text-sm">
        <span className="text-muted">AI model answering questions</span>
        <select
          value={value}
          disabled={saving || choices.length === 0}
          onChange={(e) => void change(e.target.value)}
          className="max-w-full rounded-lg border border-line bg-ink/60 px-2.5 py-1.5 text-sm text-text outline-none focus:border-cyan/50"
        >
          <option value="">
            Server setting ({serverLabel ?? settings.server_model ?? settings.model})
          </option>
          {choices.map((c) => (
            <option key={c.id} value={c.id}>
              {c.label}
            </option>
          ))}
        </select>
      </label>
      <p className="mt-1.5 text-xs text-faint">
        In use now: <span className="text-text">{settings.model}</span>. If it ever declines a
        question on safety grounds, the question is asked again on Claude Opus 5.
      </p>
      {message && (
        <p className={`mt-1.5 text-xs ${message.ok ? "text-mint" : "text-rose"}`}>{message.text}</p>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 border-b border-line-soft/50 pb-2">
      <dt className="text-muted">{label}</dt>
      <dd className="text-right text-text">{value}</dd>
    </div>
  );
}
