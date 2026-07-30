import { LogoMark } from "@/components/Logo";
import { ShieldIcon } from "@/components/Icons";

const TOPICS = ["Incident reports", "Volunteer check-in", "Transportation", "Time off"];

/**
 * The floating product card. Rendered as real DOM rather than SVG so the text
 * uses the same faces and hinting as the rest of the app — at this size, SVG
 * text renders noticeably softer.
 */
export default function HeroCard() {
  return (
    <div className="relative mx-auto w-full max-w-[520px]">
      {/* ---------------- decorative arcs ---------------- */}
      {/* Radii deliberately exceed half the card width so the rings clear its
          edges — anything smaller just hides behind the panel. */}
      <svg
        viewBox="0 0 700 700"
        className="pointer-events-none absolute top-1/2 left-1/2 -z-10 h-[190%] w-[190%] -translate-x-1/2 -translate-y-1/2"
        aria-hidden="true"
      >
        <defs>
          <radialGradient id="hc-halo" cx="0.5" cy="0.5">
            <stop offset="0%" stopColor="#6d76f5" stopOpacity="0.19" />
            <stop offset="62%" stopColor="#6d76f5" stopOpacity="0.05" />
            <stop offset="100%" stopColor="#6d76f5" stopOpacity="0" />
          </radialGradient>
        </defs>
        <circle cx="350" cy="350" r="290" fill="url(#hc-halo)" />
        <circle cx="350" cy="350" r="232" fill="none" stroke="#31456a" strokeOpacity="0.85" />
        <circle
          cx="350"
          cy="350"
          r="292"
          fill="none"
          stroke="#2b3c5c"
          strokeOpacity="0.7"
          strokeDasharray="2 8"
        />
        <path
          d="M700 40 C 600 190, 430 250, 250 268 S 20 360, -20 560"
          fill="none"
          stroke="#2b3c5c"
          strokeOpacity="0.75"
        />
      </svg>

      {/* ---------------- the card ---------------- */}
      <div className="lit relative rounded-2xl border border-line bg-card/95 p-6 shadow-2xl shadow-black/55 backdrop-blur-sm sm:p-7">
        <div className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-2.5 rounded-xl border border-line-soft bg-ink/60 px-3 py-2">
            <LogoMark className="h-6 w-6" glow={false} />
            <span className="display whitespace-nowrap text-[13px] text-text">Bald Ridge Lodge</span>
          </span>
          <span className="flex shrink-0 items-center gap-2 rounded-full border border-mint/25 bg-mint/10 px-3 py-1.5 text-[11px] font-medium whitespace-nowrap text-mint">
            <span className="h-1.5 w-1.5 rounded-full bg-mint" />
            Cited answers
          </span>
        </div>

        <p className="eyebrow mt-7">One binder, one answer</p>
        <h2 className="display mt-2.5 text-[22px] leading-snug text-text">
          Ask plainly. Check the page.
        </h2>
        <p className="mt-3 text-[13.5px] leading-relaxed text-muted">
          Staff get a short answer, the exact document and page it came from, and the front
          office number whenever our documents don&apos;t actually cover the question.
        </p>

        <div className="mt-5 flex flex-wrap gap-2">
          {TOPICS.map((t) => (
            <span
              key={t}
              className="rounded-lg border border-line-soft bg-raised/70 px-2.5 py-1.5 text-[11.5px] text-muted"
            >
              {t}
            </span>
          ))}
        </div>

        {/* a real cited line, so the card demonstrates rather than describes */}
        <div className="mt-6 rounded-xl border border-line-soft bg-ink/55 p-4">
          <p className="text-[13.5px] leading-relaxed text-text">
            <span className="font-semibold">Within 24 hours</span>
            <span className="text-muted">, on Form IR-2.</span>
            <span className="ml-1.5 inline-flex h-[1.15rem] min-w-[1.15rem] items-center justify-center rounded-[5px] bg-cyan/15 px-1 align-baseline text-[0.7rem] font-semibold text-cyan">
              1
            </span>
          </p>
          <div className="mt-3 flex items-center gap-2.5 border-t border-line-soft pt-3">
            <span className="grid h-[1.15rem] min-w-[1.15rem] place-items-center rounded-[5px] bg-cyan/15 px-1 text-[0.7rem] font-semibold text-cyan">
              1
            </span>
            <span className="text-[12px] text-muted">Incident Reporting Policy</span>
            <span className="font-mono text-[11px] text-faint">· page 4</span>
          </div>
        </div>
      </div>

      {/* ---------------- floating callout ---------------- */}
      <div className="absolute -right-2 -bottom-9 flex max-w-[252px] items-start gap-2.5 rounded-xl border border-line bg-raised px-4 py-3 shadow-2xl shadow-black/60 sm:-right-10">
        <ShieldIcon className="mt-0.5 h-4 w-4 shrink-0 text-amber" />
        <span className="leading-tight">
          <span className="block text-[12.5px] font-medium text-text">Citation required</span>
          <span className="block text-[11.5px] text-faint">
            An uncited answer is discarded, not shown
          </span>
        </span>
      </div>
    </div>
  );
}
