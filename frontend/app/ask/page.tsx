"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import AppShell from "@/components/AppShell";
import Answer from "@/components/Answer";
import EscalationCard, { type Escalation } from "@/components/EscalationCard";
import { ArrowIcon, SearchIcon } from "@/components/Icons";
import { API_BASE, ask, getToken, type SourceRef } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";

type Turn =
  | { kind: "question"; id: string; text: string }
  | {
      kind: "answer";
      id: string;
      text: string;
      sources: SourceRef[];
      citations: SourceRef[];
      streaming: boolean;
      escalation: Escalation | null;
    };

const STARTERS = [
  "What's the check-in procedure for volunteers?",
  "How soon does an incident report need to be filed?",
  "Who signs off on a purchase request?",
  "What do I do if a resident misses curfew?",
];

async function downloadDocument(id: string) {
  // The API is bearer-authenticated, so a plain <a href> would 401.
  const res = await fetch(`${API_BASE}/documents/${id}/download`, {
    headers: { Authorization: `Bearer ${getToken() ?? ""}` },
  });
  if (!res.ok) return;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank", "noopener,noreferrer");
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export default function ChatPage() {
  const { user, loading } = useRequireAuth();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [openSource, setOpenSource] = useState<SourceRef | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  const send = useCallback(
    async (question: string) => {
      const trimmed = question.trim();
      if (!trimmed || busy) return;

      setError("");
      setInput("");
      setBusy(true);

      const answerId = `a-${Date.now()}`;
      setTurns((prev) => [
        ...prev,
        { kind: "question", id: `q-${Date.now()}`, text: trimmed },
        {
          kind: "answer",
          id: answerId,
          text: "",
          sources: [],
          citations: [],
          streaming: true,
          escalation: null,
        },
      ]);

      const patch = (fn: (turn: Extract<Turn, { kind: "answer" }>) => void) =>
        setTurns((prev) =>
          prev.map((t) => {
            if (t.kind !== "answer" || t.id !== answerId) return t;
            const next = { ...t };
            fn(next);
            return next;
          }),
        );

      await ask(trimmed, conversationId, {
        onMeta: (data) => {
          setConversationId(data.conversation_id);
          patch((t) => {
            t.sources = data.sources;
          });
        },
        onDelta: (text) =>
          patch((t) => {
            t.text += text;
          }),
        onDone: (data) => {
          patch((t) => {
            t.streaming = false;
            if (data.escalated) {
              t.escalation = data as Escalation;
              t.text = "";
            } else {
              if (typeof data.text === "string" && data.text) t.text = data.text;
              t.citations = (data.citations as SourceRef[]) ?? [];
            }
          });
        },
        onError: (message) => {
          setError(message);
          patch((t) => {
            t.streaming = false;
          });
        },
      });

      setBusy(false);
      textareaRef.current?.focus();
    },
    [busy, conversationId],
  );

  if (loading || !user) {
    return <div className="grid flex-1 place-items-center text-sm text-muted">Loading…</div>;
  }

  return (
    <AppShell>
      <div className="mx-auto flex min-h-[calc(100vh-14rem)] max-w-3xl flex-col">
        {turns.length === 0 ? (
          <div className="reveal py-4">
            <p className="eyebrow">Ask the binder</p>
            <h1 className="display-loose mt-4 text-[2.1rem] leading-tight text-text">
              Hi {user.full_name?.split(" ")[0] || "there"} — what do you
              <br className="hidden sm:block" /> need to look up?
            </h1>
            <p className="mt-4 max-w-lg text-sm leading-relaxed text-muted">
              I answer from Bald Ridge Lodge&apos;s own handbooks, policies, and procedures, and
              I cite the exact document and page. If the documents don&apos;t cover it, I&apos;ll
              point you to a person instead of guessing.
            </p>

            <div className="mt-8 grid gap-2.5 sm:grid-cols-2">
              {STARTERS.map((starter) => (
                <button
                  key={starter}
                  onClick={() => void send(starter)}
                  className="group flex items-start gap-3 rounded-xl border border-line bg-card/55 px-4 py-3.5 text-left text-sm text-muted transition hover:border-cyan/40 hover:bg-card hover:text-text"
                >
                  <SearchIcon className="mt-0.5 h-4 w-4 shrink-0 text-faint transition group-hover:text-cyan" />
                  <span className="flex-1">{starter}</span>
                  <ArrowIcon className="mt-0.5 h-3.5 w-3.5 shrink-0 opacity-0 transition group-hover:translate-x-0.5 group-hover:opacity-60" />
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-6 pb-4">
            {turns.map((turn) =>
              turn.kind === "question" ? (
                <div key={turn.id} className="flex justify-end">
                  <div className="max-w-[85%] animate-fade-up rounded-2xl rounded-br-md border border-indigo/25 bg-indigo/15 px-4 py-2.5 text-[15px] text-text">
                    {turn.text}
                  </div>
                </div>
              ) : (
                <div key={turn.id} className="animate-fade-up">
                  {turn.escalation ? (
                    <EscalationCard data={turn.escalation} />
                  ) : (
                    <div className="lit rounded-2xl border border-line bg-card/80 p-6">
                      <Answer
                        text={turn.text}
                        sources={turn.citations.length ? turn.citations : turn.sources}
                        streaming={turn.streaming}
                        onCite={(n) =>
                          setOpenSource(
                            (turn.citations.length ? turn.citations : turn.sources).find(
                              (s) => s.n === n,
                            ) ?? null,
                          )
                        }
                      />

                      {!turn.streaming && turn.citations.length > 0 && (
                        <div className="mt-5 border-t border-line-soft pt-4">
                          <p className="mb-2.5 text-[11px] font-medium tracking-wider text-faint uppercase">
                            Sources
                          </p>
                          <ul className="space-y-1.5">
                            {turn.citations.map((c) => (
                              <li key={c.n}>
                                <button
                                  onClick={() => setOpenSource(c)}
                                  className="flex w-full items-start gap-2.5 rounded-lg px-2 py-1.5 text-left transition hover:bg-white/5"
                                >
                                  <span className="mt-0.5 grid h-[1.15rem] min-w-[1.15rem] place-items-center rounded-[5px] bg-cyan/15 px-1 text-[0.7rem] font-semibold text-cyan">
                                    {c.n}
                                  </span>
                                  <span className="min-w-0 text-sm">
                                    <span className="text-text">{c.document_title}</span>
                                    <span className="text-faint">
                                      {c.heading ? ` · ${c.heading}` : ""}
                                      {c.page ? ` · p.${c.page}` : ""}
                                    </span>
                                  </span>
                                </button>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ),
            )}
            <div ref={bottomRef} />
          </div>
        )}

        {error && (
          <p className="mt-4 rounded-xl border border-rose/40 bg-rose/10 px-4 py-2.5 text-sm text-rose">
            {error}
          </p>
        )}

        <form
          onSubmit={(e) => {
            e.preventDefault();
            void send(input);
          }}
          className="sticky bottom-6 mt-auto pt-6"
        >
          <div className="rounded-2xl border border-line bg-raised/95 p-2 shadow-2xl shadow-black/50 backdrop-blur-xl transition focus-within:border-cyan/45">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send(input);
                }
              }}
              rows={2}
              maxLength={2000}
              disabled={busy}
              placeholder="Ask about a procedure, policy, or form…"
              className="w-full resize-none bg-transparent px-3 py-2 text-[15px] text-text outline-none placeholder:text-faint disabled:opacity-50"
            />
            <div className="flex items-center justify-between gap-3 px-3 pb-1">
              <span className="text-[11px] text-faint">
                Don&apos;t include resident names or personal details.
              </span>
              <button
                type="submit"
                disabled={busy || !input.trim()}
                className="flex items-center gap-1.5 rounded-xl bg-cyan px-4 py-1.5 text-sm font-semibold text-ink transition enabled:hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-35"
              >
                {busy ? "Looking…" : "Ask"}
                {!busy && <ArrowIcon className="h-3.5 w-3.5" />}
              </button>
            </div>
          </div>
        </form>
      </div>

      {openSource && (
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-5 backdrop-blur-sm"
          onClick={() => setOpenSource(null)}
        >
          <div
            className="lit max-h-[80vh] w-full max-w-2xl animate-fade-up overflow-auto rounded-2xl border border-line bg-card p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="display text-[17px] text-text">{openSource.document_title}</h2>
                <p className="mt-0.5 text-xs text-faint">
                  {openSource.heading}
                  {openSource.page ? ` · page ${openSource.page}` : ""}
                </p>
              </div>
              <button
                onClick={() => setOpenSource(null)}
                className="rounded-lg px-2 py-1 text-sm text-muted hover:bg-white/5"
              >
                Close
              </button>
            </div>

            {openSource.excerpt && (
              <p className="mt-4 rounded-xl border border-line-soft bg-ink/60 p-4 text-sm leading-relaxed whitespace-pre-wrap text-muted">
                {openSource.excerpt}
              </p>
            )}

            <button
              onClick={() => void downloadDocument(openSource.document_id)}
              className="mt-4 inline-block rounded-xl border border-line px-4 py-2 text-sm text-cyan transition hover:bg-cyan/10"
            >
              Open the full document
            </button>
          </div>
        </div>
      )}
    </AppShell>
  );
}
