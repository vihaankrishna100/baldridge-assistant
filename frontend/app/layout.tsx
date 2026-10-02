import type { Metadata } from "next";
import { IBM_Plex_Mono, Montserrat, Source_Sans_3 } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import { THEME_KEY } from "@/lib/theme";

// Montserrat is the Lodge's own typeface on baldridgelodge.org.
const heading = Montserrat({
  variable: "--font-heading",
  subsets: ["latin"],
  weight: ["500", "600", "700"],
});

// Montserrat is wide for long reading, so answers and policy text are set in
// Source Sans 3, a humanist face that sits comfortably beside it.
const body = Source_Sans_3({
  variable: "--font-body",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

const mono = IBM_Plex_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "Bald Ridge Lodge — Staff Assistant",
  description:
    "The staff assistant for Bald Ridge Lodge. Answers from our own documents, cites the page, and hands you to a person when it isn't sure.",
  robots: { index: false, follow: false, nocache: true },
};

// Runs before first paint so a saved light-mode choice never flashes dark.
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
      className={`${heading.variable} ${body.variable} ${mono.variable} h-full antialiased`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="flex min-h-full flex-col">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
