import type { Metadata, Viewport } from "next";
import { Bricolage_Grotesque, Geist_Mono } from "next/font/google";
import { CommandPalette } from "@/components/system/CommandPalette";
import { THEME_BOOTSTRAP_SCRIPT, ThemeProvider } from "@/components/system/ThemeProvider";
import "./globals.css";

/*
 * Bricolage Grotesque for display: a variable grotesque with real character,
 * and variable *width* as well as weight, which is what makes the kinetic
 * headline treatment possible without swapping faces.
 *
 * Geist Mono for everything that is data -- code, diffs, terminal, ids, token
 * counts. In this product most of the screen is data.
 */
const display = Bricolage_Grotesque({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
  axes: ["opsz", "wdth"],
});

const code = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-code",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Ṣāni' Studio",
  description:
    "The agentic IDE you can actually see into — plans before they run, risk before you approve, and a replayable record of everything the agent did.",
};

export const viewport: Viewport = {
  themeColor: "#08090d",
  colorScheme: "dark light",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="void" suppressHydrationWarning>
      <head>
        {/* Stamps the stored theme before first paint. A React effect is too
            late and produces a flash of the wrong theme. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP_SCRIPT }} />
      </head>
      <body className={`${display.variable} ${code.variable} h-full`}>
        <ThemeProvider>
          {children}
          <CommandPalette />
        </ThemeProvider>
      </body>
    </html>
  );
}
