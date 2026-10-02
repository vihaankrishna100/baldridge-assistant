/**
 * Bald Ridge Lodge's actual logo, from baldridgelodge.org. Two assets in
 * `public/`, both white on transparent:
 *
 *   logo-mark.png  the square B mark (160×160)
 *   logo-full.png  mark plus the three-line wordmark (382×153)
 *
 * They are drawn as CSS masks (.brand-logo) so the same file renders white on
 * navy and navy on paper. To use new artwork, replace the files and, if the
 * proportions change, the aspect ratio below.
 */

export function LogoMark({
  className = "h-9 w-9",
  tone,
}: {
  className?: string;
  /** Force a colour, e.g. white on the always-navy sign-in panel. */
  tone?: string;
}) {
  return (
    <span
      role="img"
      aria-hidden="true"
      className={`brand-logo shrink-0 ${className}`}
      style={{
        maskImage: "url(/logo-mark.png)",
        WebkitMaskImage: "url(/logo-mark.png)",
        ...(tone ? { backgroundColor: tone } : {}),
      }}
    />
  );
}

export default function Logo({
  size = "md",
  subtitle = "Staff Assistant",
  lockup = false,
  tone,
  collapse = false,
}: {
  size?: "sm" | "md" | "lg";
  subtitle?: string | null;
  /** The full lockup (mark + three-line wordmark) instead of mark + text. */
  lockup?: boolean;
  tone?: string;
  /** Show only the mark on phone-width screens, to leave room in a header. */
  collapse?: boolean;
}) {
  if (lockup) {
    const width = size === "lg" ? "w-52" : size === "sm" ? "w-28" : "w-40";
    return (
      <span
        role="img"
        aria-label="Bald Ridge Lodge"
        className={`brand-logo ${width}`}
        style={{
          aspectRatio: "382 / 153",
          maskImage: "url(/logo-full.png)",
          WebkitMaskImage: "url(/logo-full.png)",
          ...(tone ? { backgroundColor: tone } : {}),
        }}
      />
    );
  }

  const mark = size === "lg" ? "h-12 w-12" : size === "sm" ? "h-7 w-7" : "h-9 w-9";
  const type = size === "lg" ? "text-[18px]" : size === "sm" ? "text-[13px]" : "text-[14px]";

  return (
    <span className="flex items-center gap-2.5">
      <LogoMark className={mark} tone={tone} />
      <span className={`leading-none ${collapse ? "hidden sm:block" : ""}`}>
        <span
          className={`block font-display font-bold tracking-[0.04em] whitespace-nowrap uppercase ${type}`}
          style={tone ? { color: tone } : { color: "var(--logo)" }}
        >
          Bald Ridge Lodge
        </span>
        {subtitle && (
          <span className="mt-1 hidden text-[12px] text-faint sm:block">{subtitle}</span>
        )}
      </span>
    </span>
  );
}
