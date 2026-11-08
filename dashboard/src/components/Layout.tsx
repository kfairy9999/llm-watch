import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { getMeta } from "@/api";
import { SyntheticBanner } from "@/components/SyntheticBanner";
import { SYNTHETIC_DISCLAIMER } from "@/copy";
import type { Meta } from "@/types";

const LINKS = [
  { to: "/", label: "Overview", end: true },
  { to: "/calls", label: "Calls", end: false },
  { to: "/evals", label: "Evals", end: false },
];

export function Layout() {
  const [meta, setMeta] = useState<Meta | null>(null);

  useEffect(() => {
    let cancelled = false;
    getMeta()
      .then((next) => {
        if (!cancelled) setMeta(next);
      })
      .catch(() => {
        if (!cancelled) setMeta(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const disclaimer = meta ? meta.disclaimer : SYNTHETIC_DISCLAIMER;

  return (
    <div className="min-h-screen md:grid md:grid-cols-[232px_1fr]">
      <aside className="flex items-center gap-4 overflow-x-auto bg-[#1c2421] px-4 py-3 text-[#e7efe9] md:flex-col md:items-stretch md:gap-6 md:px-5 md:py-6">
        <div className="shrink-0">
          <p className="nums text-[10px] tracking-[0.18em] text-[#9eb0a6] uppercase">Flight recorder</p>
          <p className="font-display text-2xl leading-none text-[#f4f1ea]">llm-watch</p>
        </div>
        <nav className="flex gap-1 md:flex-col">
          {LINKS.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.end}
              className={({ isActive }) =>
                `rounded-md px-3 py-1.5 text-sm ${
                  isActive ? "bg-[#31443c] text-white" : "text-[#c5d2cb] hover:bg-[#28332e]"
                }`
              }
            >
              {link.label}
            </NavLink>
          ))}
        </nav>
        {meta ? (
          <p className="nums hidden text-[11px] leading-relaxed text-[#9eb0a6] md:mt-auto md:block">
            {meta.synthetic_calls.toLocaleString("en-US")} synthetic
            <br />
            {meta.recorded_calls.toLocaleString("en-US")} recorded
          </p>
        ) : null}
      </aside>
      <div className="min-w-0">
        {disclaimer ? <SyntheticBanner disclaimer={disclaimer} /> : null}
        <main className="px-4 py-6 md:px-8 md:py-8">
          <Outlet context={meta} />
        </main>
      </div>
    </div>
  );
}
