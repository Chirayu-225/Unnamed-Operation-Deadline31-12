"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Live scan" },
  { href: "/schema", label: "Schema scan" },
  { href: "/eval", label: "Eval dashboard" },
];

export function NavBar() {
  const pathname = usePathname();
  return (
    <nav
      style={{
        position: "sticky",
        top: 0,
        zIndex: 20,
        display: "flex",
        alignItems: "center",
        gap: "0.25rem",
        padding: "0.875rem 1.5rem",
        borderBottom: "1px solid var(--gridline)",
        background: "color-mix(in srgb, var(--surface-1) 85%, transparent)",
        backdropFilter: "blur(10px)",
        WebkitBackdropFilter: "blur(10px)",
      }}
    >
      <span
        style={{
          fontWeight: 700,
          fontSize: "0.9375rem",
          letterSpacing: "-0.01em",
          color: "var(--text-primary)",
          marginRight: "1rem",
        }}
      >
        DBCaaS
      </span>
      {LINKS.map((l) => {
        const active = pathname === l.href;
        return (
          <Link key={l.href} href={l.href} className={`nav-link${active ? " active" : ""}`}>
            {l.label}
          </Link>
        );
      })}
    </nav>
  );
}
