import type { Metadata } from "next";
import "@dnb/eufemia/style";
import "./globals.css";

export const metadata: Metadata = {
  title: "Familieportalen",
  description: "Familiens lokale skjerm for uke, gjøremål og FamilyBot-drift.",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="no">
      <body>{children}</body>
    </html>
  );
}
