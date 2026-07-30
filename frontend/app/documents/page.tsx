"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import AppShell from "@/components/AppShell";
import { UploadIcon } from "@/components/Icons";
import { API_BASE, api, getToken } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";

type Doc = {
  id: string;
  title: string;
  filename: string;
  category: string;
  visibility: "staff" | "leadership";
  version: number;
  is_active: boolean;
  chunk_count: number;
  size_bytes: number;
  pii_flags: string;
  updated_at: string;
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10240 ? 1 : 0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function DocumentsPage() {
  const { user, loading } = useRequireAuth();
  const [docs, setDocs] = useState<Doc[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [query, setQuery] = useState("");

  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("General");
  const [visibility, setVisibility] = useState<"staff" | "leadership">("staff");
  const [file, setFile] = useState<File | null>(null);
  const [replaces, setReplaces] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const canManage = user?.role === "leadership" || user?.role === "admin";

  const load = useCallback(async () => {
    try {
      setDocs(await api<Doc[]>("/documents?include_inactive=true"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load documents.");
    }
  }, []);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  const upload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError("");
    setNotice("");

    const form = new FormData();
    form.append("file", file);
    form.append("title", title);
    form.append("category", category);
    form.append("visibility", visibility);
    if (replaces) form.append("replaces", replaces);

    try {
      const doc = await api<Doc>("/documents", { method: "POST", body: form, raw: true });
      setNotice(
        `“${doc.title}” added — ${doc.chunk_count} searchable sections.` +
          (doc.pii_flags ? ` Review needed: contains ${doc.pii_flags}.` : ""),
      );
      setTitle("");
      setFile(null);
      setReplaces("");
      if (fileRef.current) fileRef.current.value = "";
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setBusy(false);
    }
  };

  const toggleActive = async (doc: Doc) => {
    await api(`/documents/${doc.id}`, { method: "PATCH", body: { is_active: !doc.is_active } });
    await load();
  };

  const remove = async (doc: Doc) => {
    if (!confirm(`Permanently delete “${doc.title}”? This also removes it from search.`)) return;
    await api(`/documents/${doc.id}`, { method: "DELETE" });
    await load();
  };

  const download = async (doc: Doc) => {
    const res = await fetch(`${API_BASE}/documents/${doc.id}/download`, {
      headers: { Authorization: `Bearer ${getToken() ?? ""}` },
    });
    if (!res.ok) return setError("That file is no longer stored.");
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = doc.filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 30_000);
  };

  if (loading || !user) {
    return <div className="grid flex-1 place-items-center text-sm text-muted">Loading…</div>;
  }

  const filtered = docs.filter((d) =>
    `${d.title} ${d.category}`.toLowerCase().includes(query.toLowerCase()),
  );
  const grouped = filtered.reduce<Record<string, Doc[]>>((acc, d) => {
    (acc[d.category] ||= []).push(d);
    return acc;
  }, {});

  return (
    <AppShell>
      <div className="mb-7">
        <p className="eyebrow">The corpus</p>
        <h1 className="display-loose mt-3 text-[2rem] text-text">Document library</h1>
        <p className="mt-1.5 text-sm text-muted">
          Everything the assistant can answer from. Anything not here, it will refer to a person.
        </p>
      </div>

      {canManage && (
        <form
          onSubmit={upload}
          className="lit mb-8 rounded-2xl border border-line bg-card/75 p-6"
        >
          <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold text-text">
            <UploadIcon className="h-4 w-4 text-cyan" /> Add or update a document
          </h2>

          <div className="grid gap-3.5 sm:grid-cols-2">
            <label className="block sm:col-span-2">
              <span className="mb-1.5 block text-xs font-medium text-muted">
                File — PDF, Word, Markdown, CSV, or text
              </span>
              <input
                ref={fileRef}
                type="file"
                required
                accept=".pdf,.docx,.txt,.md,.markdown,.csv"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="w-full rounded-xl border border-line bg-ink/60 px-3.5 py-2.5 text-sm text-muted file:mr-3 file:rounded-lg file:border-0 file:bg-cyan/15 file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-cyan"
              />
            </label>

            <label className="block">
              <span className="mb-1.5 block text-xs font-medium text-muted">
                Title (optional — defaults to the filename)
              </span>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Volunteer Handbook 2026"
                className="w-full rounded-xl border border-line bg-ink/60 px-3.5 py-2.5 text-sm text-text outline-none focus:border-cyan/50"
              />
            </label>

            <label className="block">
              <span className="mb-1.5 block text-xs font-medium text-muted">Category</span>
              <input
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                placeholder="Policies"
                className="w-full rounded-xl border border-line bg-ink/60 px-3.5 py-2.5 text-sm text-text outline-none focus:border-cyan/50"
              />
            </label>

            <label className="block">
              <span className="mb-1.5 block text-xs font-medium text-muted">Who can see it</span>
              <select
                value={visibility}
                onChange={(e) => setVisibility(e.target.value as "staff" | "leadership")}
                className="w-full rounded-xl border border-line bg-ink/60 px-3.5 py-2.5 text-sm text-text outline-none focus:border-cyan/50"
              >
                <option value="staff">All staff</option>
                <option value="leadership">Leadership only</option>
              </select>
            </label>

            <label className="block">
              <span className="mb-1.5 block text-xs font-medium text-muted">
                Replaces (retires the old version)
              </span>
              <select
                value={replaces}
                onChange={(e) => setReplaces(e.target.value)}
                className="w-full rounded-xl border border-line bg-ink/60 px-3.5 py-2.5 text-sm text-text outline-none focus:border-cyan/50"
              >
                <option value="">Nothing — this is new</option>
                {docs
                  .filter((d) => d.is_active)
                  .map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.title} (v{d.version})
                    </option>
                  ))}
              </select>
            </label>
          </div>

          <div className="mt-4 flex items-center gap-3">
            <button
              type="submit"
              disabled={busy || !file}
              className="rounded-xl bg-cyan px-5 py-2 text-sm font-semibold text-ink transition enabled:hover:brightness-110 disabled:opacity-40"
            >
              {busy ? "Processing…" : "Upload"}
            </button>
            <span className="text-[11px] text-faint">
              Indexed immediately — no restart needed.
            </span>
          </div>
        </form>
      )}

      {notice && (
        <p className="mb-5 rounded-xl border border-mint/40 bg-mint/10 px-4 py-2.5 text-sm text-mint">
          {notice}
        </p>
      )}
      {error && (
        <p className="mb-5 rounded-xl border border-rose/40 bg-rose/10 px-4 py-2.5 text-sm text-rose">
          {error}
        </p>
      )}

      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Filter documents…"
        className="mb-5 w-full max-w-sm rounded-xl border border-line bg-ink/60 px-3.5 py-2.5 text-sm text-text outline-none focus:border-cyan/50"
      />

      {Object.keys(grouped).length === 0 ? (
        <p className="rounded-2xl border border-dashed border-line px-5 py-10 text-center text-sm text-muted">
          No documents yet. Until something is uploaded, every question is referred to a person.
        </p>
      ) : (
        Object.entries(grouped).map(([cat, items]) => (
          <section key={cat} className="mb-7">
            <h2 className="mb-2.5 font-mono text-[10px] tracking-[0.18em] text-faint uppercase">
              {cat}
            </h2>
            <ul className="space-y-2">
              {items.map((doc) => (
                <li
                  key={doc.id}
                  className={`flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3 ${
                    doc.is_active ? "border-line bg-card/50" : "border-line-soft bg-card/20 opacity-55"
                  }`}
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium text-text">{doc.title}</span>
                      {doc.version > 1 && (
                        <span className="rounded-md bg-white/8 px-1.5 py-0.5 text-[10px] text-muted">
                          v{doc.version}
                        </span>
                      )}
                      {doc.visibility === "leadership" && (
                        <span className="rounded-md bg-indigo/20 px-1.5 py-0.5 text-[10px] text-indigo">
                          Leadership only
                        </span>
                      )}
                      {!doc.is_active && (
                        <span className="rounded-md bg-white/8 px-1.5 py-0.5 text-[10px] text-faint">
                          Retired
                        </span>
                      )}
                      {doc.pii_flags && (
                        <span
                          title={`Contains ${doc.pii_flags}`}
                          className="rounded-md bg-amber/20 px-1.5 py-0.5 text-[10px] text-amber"
                        >
                          Review: {doc.pii_flags}
                        </span>
                      )}
                    </div>
                    <p className="mt-0.5 text-[11px] text-faint">
                      {doc.chunk_count} section{doc.chunk_count === 1 ? "" : "s"} ·{" "}
                      {formatSize(doc.size_bytes)} · updated{" "}
                      {new Date(doc.updated_at).toLocaleDateString()}
                    </p>
                  </div>

                  <div className="flex gap-1.5">
                    <button
                      onClick={() => void download(doc)}
                      className="rounded-lg border border-line px-2.5 py-1 text-xs text-muted transition hover:text-cyan"
                    >
                      Download
                    </button>
                    {canManage && (
                      <>
                        <button
                          onClick={() => void toggleActive(doc)}
                          className="rounded-lg border border-line px-2.5 py-1 text-xs text-muted transition hover:text-amber"
                        >
                          {doc.is_active ? "Retire" : "Restore"}
                        </button>
                        <button
                          onClick={() => void remove(doc)}
                          className="rounded-lg border border-line px-2.5 py-1 text-xs text-muted transition hover:text-rose"
                        >
                          Delete
                        </button>
                      </>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
    </AppShell>
  );
}
