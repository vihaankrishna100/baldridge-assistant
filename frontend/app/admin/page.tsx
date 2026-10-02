"use client";

import { useCallback, useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import StorageMeter, { type Storage } from "@/components/StorageMeter";
import { api } from "@/lib/api";
import { useRequireAuth, type User } from "@/lib/auth";

type Stats = {
  users: number;
  documents: number;
  questions_30d: number;
  answered_30d: number;
  escalated_30d: number;
  answer_rate: number;
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
};

type Invite = { id: string; email: string; role: string; expires_at: string };
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
  const [tab, setTab] = useState<"overview" | "people" | "audit">("overview");
  const [stats, setStats] = useState<Stats | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [audit, setAudit] = useState<AuditRow[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("staff");
  const [inviteLink, setInviteLink] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [s, cfg, u, i, a] = await Promise.all([
        api<Stats>("/admin/stats"),
        api<Settings>("/admin/settings"),
        api<User[]>("/admin/users"),
        api<Invite[]>("/admin/invites"),
        api<AuditRow[]>("/admin/audit?limit=150"),
      ]);
      setStats(s);
      setSettings(cfg);
      setUsers(u);
      setInvites(i);
      setAudit(a);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the admin data.");
    }
  }, []);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  const createInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      const res = await api<{ invite_url: string }>("/admin/invites", {
        method: "POST",
        body: { email: inviteEmail, role: inviteRole },
      });
      setInviteLink(res.invite_url);
      setInviteEmail("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the invitation.");
    }
  };

  if (loading || !user) {
    return <div className="grid flex-1 place-items-center text-sm text-muted">Loading…</div>;
  }

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

      {settings && settings.twofa_exempt.length > 0 && (
        <div className="mb-6 rounded-2xl border border-amber/40 bg-amber/8 p-4">
          <p className="text-sm font-medium text-amber">
            {settings.twofa_exempt.length === 1
              ? "Heads up: this account signs in with just a password"
              : `Heads up: ${settings.twofa_exempt.length} accounts sign in with just a password`}
          </p>
          <p className="mt-1 text-sm leading-relaxed text-muted">
            <span className="text-text">{settings.twofa_exempt.join(", ")}</span> doesn&apos;t
            need the code from a phone app that other accounts use. That&apos;s convenient, but
            anyone who learns {settings.twofa_exempt.length === 1 ? "its" : "their"} password
            could open every document, including leadership-only ones. Keep the password long and
            don&apos;t share it. When you&apos;re ready for the extra protection, ask whoever set
            up this assistant to turn on the phone-code step for{" "}
            {settings.twofa_exempt.length === 1 ? "it" : "them"}.
          </p>
        </div>
      )}

      <div className="mb-6 flex gap-1.5">
        {(["overview", "people", "audit"] as const).map((t) => (
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
              label="Answered from docs (30d)"
              value={stats.answered_30d}
              hint={`${Math.round(stats.answer_rate * 100)}% of questions`}
            />
            <Stat
              label="Referred to a person (30d)"
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
              <dl className="grid gap-x-8 gap-y-2.5 text-sm sm:grid-cols-2">
                <Row label="AI model" value={settings.model} />
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
              administrators, and anyone who should be able to see leadership-only documents.
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

            {inviteLink && (
              <div className="mt-4 rounded-xl border border-mint/40 bg-mint/8 p-3.5">
                <p className="text-xs text-mint">
                  Send this link to the new team member. It expires in 7 days and is shown only
                  once — nothing stores the link itself.
                </p>
                <code className="mt-2 block break-all rounded-lg bg-ink/60 p-2.5 font-mono text-xs text-cyan">
                  {inviteLink}
                </code>
                <button
                  onClick={() => void navigator.clipboard.writeText(inviteLink)}
                  className="mt-2 rounded-lg border border-line px-3 py-1 text-xs text-muted hover:text-cyan"
                >
                  Copy
                </button>
              </div>
            )}

            {invites.length > 0 && (
              <ul className="mt-5 space-y-1.5">
                {invites.map((inv) => (
                  <li
                    key={inv.id}
                    className="flex items-center gap-3 rounded-lg bg-ink/40 px-3 py-2 text-sm"
                  >
                    <span className="flex-1 text-muted">
                      {inv.email}{" "}
                      <span className="text-faint">
                        · {inv.role} · expires {new Date(inv.expires_at).toLocaleDateString()}
                      </span>
                    </span>
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
                      {u.totp_confirmed ? " · 2FA active" : " · 2FA not set up"}
                      {u.is_active ? "" : " · deactivated"}
                    </p>
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
                      Reset 2FA
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

      {tab === "audit" && (
        <section className="overflow-hidden rounded-2xl border border-line bg-card/50">
          <div className="border-b border-line px-5 py-3.5">
            <h2 className="text-sm font-semibold text-text">Audit trail</h2>
            <p className="mt-0.5 text-xs text-muted">
              Every sign-in, document access, and question. Append-only.
            </p>
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

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 border-b border-line-soft/50 pb-2">
      <dt className="text-muted">{label}</dt>
      <dd className="text-right text-text">{value}</dd>
    </div>
  );
}
