import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Subnet Cleanse",
  description: "Track and resolve IP subnet reconciliation conflicts.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
