import type { Metadata, Viewport } from "next";
import { Archivo, Instrument_Serif, Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import { THEME_INIT_SCRIPT } from "@/lib/theme";

// One type system for both themes (ADR-025). Archivo + Instrument Serif are used only by the story header.
const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains" });
const archivo = Archivo({ subsets: ["latin"], weight: ["800"], variable: "--font-archivo" });
const instrument = Instrument_Serif({ subsets: ["latin"], weight: ["400"], variable: "--font-instrument" });

export const metadata: Metadata = {
  title: "SIGNAL",
  description: "Personal tech-intelligence: radar, studio, lab, gym.",
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, title: "SIGNAL", statusBarStyle: "default" },
  icons: { icon: "/icon-192.png", apple: "/icon-192.png" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#eeeff2" },
    { media: "(prefers-color-scheme: dark)", color: "#07080a" },
  ],
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    // The inline script sets data-theme before first paint, so React must not complain about the attribute.
    <html lang="en" className={`${inter.variable} ${mono.variable} ${archivo.variable} ${instrument.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="min-h-dvh">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
