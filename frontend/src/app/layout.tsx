import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SentinelHealth AI",
  description: "AI-powered disease outbreak detection and forecasting for public health agencies.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
