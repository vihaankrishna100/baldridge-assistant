/**
 * A still of the assistant answering a real-shaped question. Built from the
 * same tokens as the app, so it shows exactly what staff will see in either
 * theme.
 */
export default function HeroCard() {
  return (
    <div className="surface mx-auto w-full max-w-[500px] overflow-hidden rounded-xl border border-line bg-card">
      <div className="flex items-center justify-between border-b border-line px-5 py-3">
        <span className="font-display text-[13px] font-semibold text-text">Ask a question</span>
        <span className="text-[12px] text-faint">Answers from Lodge documents</span>
      </div>

      <div className="space-y-5 px-5 py-6">
        <div className="ml-auto w-fit max-w-[85%] rounded-lg bg-raised px-3.5 py-2.5 text-[14px] text-text">
          How soon do I need to file an incident report?
        </div>

        <div className="text-[14.5px] leading-relaxed text-text">
          Within <strong className="font-semibold">24 hours</strong> of the incident, on Form
          IR-2. Your shift supervisor signs it before it goes to the program director.
          <Cite n={1} />
        </div>

        <div className="rounded-lg border border-line-soft">
          <div className="flex items-center gap-2.5 px-3.5 py-2.5">
            <Cite n={1} />
            <span className="text-[13px] font-medium text-text">Incident Reporting Policy</span>
            <span className="ml-auto text-[12px] text-faint">Page 4</span>
          </div>
        </div>
      </div>

      <div className="border-t border-line bg-raised/60 px-5 py-3 text-[12.5px] text-muted">
        Not covered in the documents? You&apos;ll be pointed to the front office instead of a
        guess.
      </div>
    </div>
  );
}

function Cite({ n }: { n: number }) {
  return (
    <span className="ml-1 inline-grid h-[1.2rem] min-w-[1.2rem] place-items-center rounded bg-cyan/12 px-1 align-[0.1em] text-[11px] font-semibold text-cyan">
      {n}
    </span>
  );
}
