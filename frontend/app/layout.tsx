import type { Metadata } from "next";
import { Fraunces, IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import { THEME_KEY } from "@/lib/theme";

// Fraunces carries institutional warmth without reading as a tech startup —
// this is a children's home, not a SaaS product. Low WONK keeps it dignified.
const display = Fraunces({
  variable: "--font-display",
  subsets: ["latin"],
  // Variable axes require the variable weight range — hence no `weight` array.
  // SOFT/WONK/opsz are driven from CSS in the .display utilities.
  axes: ["SOFT", "WONK", "opsz"],
});

// Plex Sans is a workhorse built for dense technical reading at small sizes,
// which is what a policy answer on a phone at 2am actually is.
const sans = IBM_Plex_Sans({
  variable: "--font-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

const mono = IBM_Plex_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "Bald Ridge Lodge — Internal Assistant",
  description:
    "The staff assistant for Bald Ridge Lodge. Answers from our own documents, cites the page, and hands you to a person when it isn't sure.",
  robots: { index: false, follow: false, nocache: true },
};

const themeScript = `try{var t=localStorage.getItem("${THEME_KEY}");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      data-theme="dark"
      suppressHydrationWarning
      className={`${display.variable} ${sans.variable} ${mono.variable} h-full antialiased`}
    >
      <head>
        {/* Before first paint, so a saved light-mode choice never flashes dark. */}
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="grain flex min-h-full flex-col">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
