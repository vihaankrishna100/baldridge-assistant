/** Hand-drawn 24px stroke icons. Consistent 1.6 weight, round caps. */

type P = { className?: string };
const base = "h-4 w-4";

function Svg({ className = base, children }: P & { children: React.ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export const AskIcon = (p: P) => (
  <Svg {...p}>
    <path d="M21 11.5a8.4 8.4 0 0 1-9 8.4L4 21l1.1-3.7A8.4 8.4 0 1 1 21 11.5Z" />
    <path d="M9.6 9.4a2.4 2.4 0 1 1 3.3 2.2c-.6.3-.9.8-.9 1.4v.4" />
    <path d="M12 16.3h.01" />
  </Svg>
);

export const DocumentsIcon = (p: P) => (
  <Svg {...p}>
    <path d="M8 3h6l5 5v11a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z" />
    <path d="M14 3v5h5" />
    <path d="M9.5 13h5M9.5 16.5h3" />
  </Svg>
);

export const AdminIcon = (p: P) => (
  <Svg {...p}>
    <path d="M12 3 4.5 6v5.6c0 4.3 3 8.2 7.5 9.4 4.5-1.2 7.5-5.1 7.5-9.4V6L12 3Z" />
    <path d="m9.2 11.8 2 2 3.6-3.8" />
  </Svg>
);

export const CiteIcon = (p: P) => (
  <Svg {...p}>
    <path d="M4 6h10M4 10h13M4 14h7" />
    <circle cx="17" cy="16.5" r="4" />
    <path d="m15.4 16.6 1.1 1.1 2-2.2" />
  </Svg>
);

export const HandoffIcon = (p: P) => (
  <Svg {...p}>
    <path d="M15.5 14.2v2.6a1.7 1.7 0 0 1-1.9 1.7 15 15 0 0 1-6.5-2.3 14.6 14.6 0 0 1-4.5-4.5A14.9 14.9 0 0 1 .3 5.1 1.7 1.7 0 0 1 2 3.2h2.6a1.7 1.7 0 0 1 1.7 1.5c.1.8.3 1.6.6 2.4a1.7 1.7 0 0 1-.4 1.8l-1.1 1.1a13.6 13.6 0 0 0 4.5 4.5l1.1-1.1a1.7 1.7 0 0 1 1.8-.4c.8.3 1.6.5 2.4.6a1.7 1.7 0 0 1 1.5 1.7Z" />
    <path d="M17 4h6M20 1v6" />
  </Svg>
);

export const LockIcon = (p: P) => (
  <Svg {...p}>
    <rect x="4.5" y="10.5" width="15" height="10" rx="2.2" />
    <path d="M8 10.5V7.4a4 4 0 0 1 8 0v3.1" />
    <path d="M12 14.6v2.2" />
  </Svg>
);

export const ShieldIcon = (p: P) => (
  <Svg {...p}>
    <path d="M12 3 4.5 6v5.6c0 4.3 3 8.2 7.5 9.4 4.5-1.2 7.5-5.1 7.5-9.4V6L12 3Z" />
    <path d="M12 8.6v4.2M12 16h.01" />
  </Svg>
);

export const UploadIcon = (p: P) => (
  <Svg {...p}>
    <path d="M4 15.5V18a2.5 2.5 0 0 0 2.5 2.5h11A2.5 2.5 0 0 0 20 18v-2.5" />
    <path d="M12 15.5V4M8 7.6 12 3.6l4 4" />
  </Svg>
);

export const SearchIcon = (p: P) => (
  <Svg {...p}>
    <circle cx="11" cy="11" r="6.5" />
    <path d="m16 16 4.5 4.5" />
  </Svg>
);

export const ArrowIcon = (p: P) => (
  <Svg {...p}>
    <path d="M4.5 12h14M13 6.5 18.5 12 13 17.5" />
  </Svg>
);

export const SignOutIcon = (p: P) => (
  <Svg {...p}>
    <path d="M10 20.5H6a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2h4" />
    <path d="M15.5 16 20 12l-4.5-4M20 12H9.5" />
  </Svg>
);

export const AlertIcon = (p: P) => (
  <Svg {...p}>
    <path d="M12 4.2 2.8 20h18.4L12 4.2Z" />
    <path d="M12 10v4M12 17h.01" />
  </Svg>
);
