import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { AppShell } from "@/components/guardian/AppShell";
import { getPlatformStatus } from "@/lib/platform";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Data Contract Guardian",
  description: "Fivetran MCP–grounded data contract reliability agent",
};

export const dynamic = "force-dynamic";

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const platform = await getPlatformStatus();

  return (
    <html lang="en">
      <body className={`${inter.variable} min-h-screen font-sans`}>
        <AppShell platform={platform}>{children}</AppShell>
      </body>
    </html>
  );
}
