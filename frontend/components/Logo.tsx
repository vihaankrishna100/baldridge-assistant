/* eslint-disable @next/next/no-img-element */

/**
 * Bald Ridge Lodge's actual logo, taken from baldridgelodge.org — not a
 * redrawing. Two assets in `public/`:
 *
 *   logo-mark.png  the square B mark, padded to a true square so it never
 *                  distorts in a fixed-size slot
 *   logo-full.png  the full lockup, mark plus the three-line wordmark
 *
 * Both are white on transparent, which is why they are only ever placed on a
 * dark surface. If the Lodge sends updated artwork, replace the files — no
 * code here needs to change.
 */

export function LogoMark({ className = "h-9 w-9" }: { className?: string }) {
  return (
    <img
      src="/logo-mark.png"
      alt=""
      aria-hidden="true"
      className={`${className} object-contain`}
    />
  );
}

export default function Logo({
  size = "md",
  subtitle = "Internal Assistant",
  /** Use the full lockup (mark + three-line wordmark) instead of mark + text. */
  lockup = false,
}: {
  size?: "sm" | "md" | "lg";
  subtitle?: string | null;
  lockup?: boolean;
}) {
  if (lockup) {
    const width = size === "lg" ? "w-56" : size === "sm" ? "w-32" : "w-44";
    return (
      <img
        src="/logo-full.png"
        alt="Bald Ridge Lodge"
        className={`${width} h-auto object-contain`}
      />
    );
  }

  const mark = size === "lg" ? "h-14 w-14" : size === "sm" ? "h-8 w-8" : "h-10 w-10";
  const type =
    size === "lg" ? "text-[19px]" : size === "sm" ? "text-[13px]" : "text-[15px]";

  return (
    <span className="flex items-center gap-3">
      <LogoMark className={`${mark} shrink-0`} />
      <span className="leading-none">
        <span
          className={`block font-semibold tracking-[0.02em] whitespace-nowrap text-text uppercase ${type}`}
        >
          Bald Ridge Lodge
        </span>
        {subtitle && (
          <span className="mt-1.5 hidden font-mono text-[10px] tracking-[0.16em] text-faint uppercase sm:block">
            {subtitle}
          </span>
        )}
      </span>
    </span>
  );
}
