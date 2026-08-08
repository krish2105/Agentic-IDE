import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Ṣāni' Studio",
  description: "An agentic coding IDE with visible autonomy",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="h-full">{children}</body>
    </html>
  );
}
