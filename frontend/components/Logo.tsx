/**
 * The mark reads two ways on purpose: a ridgeline of hills, and the pitched
 * roof of a lodge. The warm dot beneath is the lit window — the place is open,
 * somebody is awake. Beats stamping "BR" in a rounded square.
 */
export function LogoMark({
  className = "h-9 w-9",
  glow = true,
}: {
  className?: string;
  glow?: boolean;
}) {
  return (
    <svg viewBox="0 0 40 40" className={className} aria-hidden="true">
      <defs>
        <linearGradient id="ridge-stroke" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#38d9f0" />
          <stop offset="100%" stopColor="#6d76f5" />
        </linearGradient>
        <radialGradient id="ridge-lamp">
          <stop offset="0%" stopColor="#f0a63c" stopOpacity="0.85" />
          <stop offset="100%" stopColor="#f0a63c" stopOpacity="0" />
        </radialGradient>
      </defs>

      <rect
        x="1.5"
        y="1.5"
        width="37"
        height="37"
        rx="11"
        fill="#0c1424"
        stroke="url(#ridge-stroke)"
        strokeWidth="1.4"
        strokeOpacity="0.55"
      />

      {glow && <circle cx="20" cy="27" r="10" fill="url(#ridge-lamp)" />}

      {/* back ridge */}
      <path
        d="M7 25.5 L15.5 15 L21 21.5"
        fill="none"
        stroke="#6d76f5"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeOpacity="0.6"
      />
      {/* front ridge / roofline */}
      <path
        d="M12 27 L22.5 13.5 L33 27"
        fill="none"
        stroke="url(#ridge-stroke)"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* the lit window */}
      <circle cx="22.5" cy="24" r="2.1" fill="#f0a63c" />
    </svg>
  );
}

export default function Logo({
  size = "md",
  subtitle = "Internal Assistant",
}: {
  size?: "sm" | "md" | "lg";
  subtitle?: string | null;
}) {
  const mark = size === "lg" ? "h-12 w-12" : size === "sm" ? "h-8 w-8" : "h-9 w-9";
  const title = size === "lg" ? "text-lg" : "text-[15px]";

  return (
    <span className="flex items-center gap-3">
      <LogoMark className={mark} />
      <span className="leading-tight">
        <span className={`display block whitespace-nowrap ${title} text-text`}>
          Bald Ridge Lodge
        </span>
        {subtitle && (
          <span className="hidden font-mono text-[10px] tracking-[0.16em] text-faint uppercase sm:block">
            {subtitle}
          </span>
        )}
      </span>
    </span>
  );
}
