/**
 * Bald Ridge Lodge's own mark: a bold B set inside a square frame, with the
 * crossbar breaking out through the left edge.
 *
 * Drawn as geometry rather than an image file so it stays crisp at every size
 * and needs no network fetch. If the Lodge supplies the original artwork, drop
 * it in `public/` and swap this component's body for an <img> — the rest of
 * the app only ever calls <LogoMark /> and <Logo />.
 */
export function LogoMark({ className = "h-9 w-9" }: { className?: string }) {
  return (
    <svg viewBox="0 0 100 100" className={className} aria-hidden="true">
      {/* The clever bit of this mark: the square's left edge doubles as the B's
          spine. The two bowls run straight into it rather than sitting inside
          a box, which is why it reads as one object. Lower bowl is wider than
          the upper. */}
      <rect
        x="8"
        y="8"
        width="84"
        height="84"
        fill="none"
        stroke="currentColor"
        strokeWidth="5"
      />
      <path d="M10.5 23 h44 a14 14 0 0 1 0 28 h-44 z" fill="currentColor" />
      <path d="M10.5 55 h52 a14.5 14.5 0 0 1 0 29 h-52 z" fill="currentColor" />
      {/* Counters are painted rather than knocked out, because currentColor
          can't be inverted. Override --logo-knockout wherever the mark sits on
          a surface other than the page background. */}
      <g fill="var(--logo-knockout, #070d18)">
        <rect x="27" y="31" width="26" height="12" />
        <rect x="27" y="63" width="34" height="13" />
      </g>
    </svg>
  );
}

export default function Logo({
  size = "md",
  subtitle = "Internal Assistant",
  stacked = false,
}: {
  size?: "sm" | "md" | "lg";
  subtitle?: string | null;
  /** Three-line wordmark, as the Lodge sets it. Needs vertical room. */
  stacked?: boolean;
}) {
  const mark = size === "lg" ? "h-14 w-14" : size === "sm" ? "h-8 w-8" : "h-10 w-10";
  const type =
    size === "lg" ? "text-[19px]" : size === "sm" ? "text-[13px]" : "text-[15px]";

  return (
    <span className="flex items-center gap-3">
      <LogoMark className={`${mark} shrink-0 text-text`} />
      <span className="leading-none">
        {stacked ? (
          <span
            className={`block font-semibold tracking-[0.01em] text-text uppercase ${type} leading-[1.06]`}
          >
            Bald
            <br />
            Ridge
            <br />
            Lodge
          </span>
        ) : (
          <span
            className={`block font-semibold tracking-[0.02em] whitespace-nowrap text-text uppercase ${type}`}
          >
            Bald Ridge Lodge
          </span>
        )}
        {subtitle && (
          <span className="mt-1.5 hidden font-mono text-[10px] tracking-[0.16em] text-faint uppercase sm:block">
            {subtitle}
          </span>
        )}
      </span>
    </span>
  );
}
