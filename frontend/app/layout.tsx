import type { ReactNode } from "react";
import { Inter } from "next/font/google";
import { NavBar } from "./components/NavBar";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans", display: "swap" });

export const metadata = {
  title: "DBCaaS",
  description: "Schema-agnostic data connectivity with agentic data quality scoring",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <body>
        <NavBar />
        {children}
      </body>
    </html>
  );
}
