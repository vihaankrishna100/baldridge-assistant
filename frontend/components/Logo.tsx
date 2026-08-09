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
    <svg viewBox="0 0 64 64" className={className} aria-hidden="true">
      {/* frame */}
      <rect
        x="10"
        y="7"
        width="46"
        height="50"
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
      />
      {/* crossbar, breaking through the frame on the left */}
      <rect x="2" y="28.5" width="26" height="7" fill="currentColor" />
      {/* stem */}
      <rect x="21" y="16" width="8" height="32" fill="currentColor" />
      {/* upper bowl */}
      <path
        d="M29 16h9a7.5 7.5 0 0 1 0 15h-9z"
        fill="currentColor"
      />
      {/* lower bowl, slightly wider — the way the original sits */}
      <path
        d="M29 33h11a7.5 7.5 0 0 1 0 15H29z"
        fill="currentColor"
      />
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
