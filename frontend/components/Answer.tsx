"use client";

import { Fragment } from "react";
import type { SourceRef } from "@/lib/api";

/**
 * Minimal renderer for the answer text. Deliberately not a full markdown
 * parser: the model is prompted for short policy answers, and rendering only a
 * known-safe subset means no raw HTML from document text can ever reach the DOM.
 */

const CITATION = /\[(\d{1,2})\]/g;
const INLINE = /(\*\*[^*]+\*\*|`[^`]+`)/g;

function renderInline(text: string, sources: SourceRef[], onCite?: (n: number) => void) {
  const out: React.ReactNode[] = [];
  let key = 0;

  for (const segment of text.split(INLINE)) {
    if (!segment) continue;

    if (segment.startsWith("**") && segment.endsWith("**")) {
      out.push(
        <strong key={key++} className="font-semibold text-text">
          {segment.slice(2, -2)}
        </strong>,
      );
      continue;
    }
    if (segment.startsWith("`") && segment.endsWith("`")) {
      out.push(
        <code
          key={key++}
          className="rounded bg-raised px-1.5 py-0.5 font-mono text-[0.85em] text-cyan"
        >
          {segment.slice(1, -1)}
        </code>,
      );
      continue;
    }

    let last = 0;
    CITATION.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = CITATION.exec(segment)) !== null) {
      if (match.index > last) out.push(<Fragment key={key++}>{segment.slice(last, match.index)}</Fragment>);
      const n = Number(match[1]);
      const source = sources.find((s) => s.n === n);
      // Leading margin only: a trailing one leaves a visible gap before the
      // sentence's closing period.
      out.push(
        <button
          key={key++}
          type="button"
          onClick={() => onCite?.(n)}
          title={source ? `${source.document_title}${source.page ? ` — page ${source.page}` : ""}` : undefined}
          className="ml-0.5 inline-flex h-[1.15rem] min-w-[1.15rem] items-center justify-center rounded-[5px] bg-cyan/15 px-1 align-baseline text-[0.7rem] font-semibold text-cyan transition hover:bg-cyan/30"
        >
          {n}
        </button>,
      );
      last = match.index + match[0].length;
    }
    if (last < segment.length) out.push(<Fragment key={key++}>{segment.slice(last)}</Fragment>);
  }
  return out;
}

export default function Answer({
  text,
  sources,
  streaming,
  onCite,
}: {
  text: string;
  sources: SourceRef[];
  streaming?: boolean;
  onCite?: (n: number) => void;
}) {
  const blocks: React.ReactNode[] = [];
  const lines = text.split("\n");
  let bullets: string[] = [];
  let numbers: string[] = [];
  let key = 0;

  const flushBullets = () => {
    if (!bullets.length) return;
    blocks.push(
      <ul key={key++} className="my-2 space-y-1.5 pl-1">
        {bullets.map((item, i) => (
          <li key={i} className="flex gap-2.5">
            <span className="mt-[0.55em] h-1.5 w-1.5 shrink-0 rounded-full bg-cyan/70" />
            <span>{renderInline(item, sources, onCite)}</span>
          </li>
        ))}
      </ul>,
    );
    bullets = [];
  };

  const flushNumbers = () => {
    if (!numbers.length) return;
    blocks.push(
      <ol key={key++} className="my-2 space-y-1.5">
        {numbers.map((item, i) => (
          <li key={i} className="flex gap-2.5">
            <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-md bg-indigo/20 text-[11px] font-semibold text-indigo">
              {i + 1}
            </span>
            <span>{renderInline(item, sources, onCite)}</span>
          </li>
        ))}
      </ol>,
    );
    numbers = [];
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    const heading = line.match(/^#{1,4}\s+(.*)$/);

    if (bullet) {
      flushNumbers();
      bullets.push(bullet[1]);
      continue;
    }
    if (numbered) {
      flushBullets();
      numbers.push(numbered[1]);
      continue;
    }
    flushBullets();
    flushNumbers();

    if (heading) {
      blocks.push(
        <h3 key={key++} className="mt-4 mb-1.5 text-sm font-semibold tracking-wide text-cyan">
          {heading[1]}
        </h3>,
      );
      continue;
    }
    if (!line.trim()) continue;

    blocks.push(
      <p key={key++} className="my-2 leading-relaxed">
        {renderInline(line, sources, onCite)}
      </p>,
    );
  }
  flushBullets();
  flushNumbers();

  return (
    <div className={`text-[15px] text-text/95 ${streaming ? "caret" : ""}`}>
      {blocks.length ? blocks : <p className="text-muted">Thinking…</p>}
    </div>
  );
}
