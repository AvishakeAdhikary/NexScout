"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";

import { cn } from "@/lib/utils";
import { SECTIONS } from "@/lib/sections";
import { useCase } from "@/lib/hooks";

export function CaseNav() {
  const { caseId } = useParams<{ caseId: string }>();
  const pathname = usePathname();
  const kase = useCase(caseId);
  const base = `/cases/${caseId}`;

  return (
    <nav aria-label="Case sections" className="flex flex-col gap-1">
      <p className="mb-2 truncate px-2 text-sm font-semibold" title={kase.data?.name}>
        {kase.data?.name ?? " "}
      </p>
      <ul className="flex flex-col gap-0.5">
        {SECTIONS.map((s) => {
          const href = s.slug ? `${base}/${s.slug}` : base;
          const active = pathname === href;
          return (
            <li key={s.slug || "dashboard"}>
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center justify-between rounded-md px-2 py-1.5 text-sm hover:bg-muted",
                  active && "bg-muted font-medium",
                )}
              >
                <span>{s.label}</span>
                {s.milestone !== undefined && (
                  <span className="text-[10px] text-muted-foreground" aria-label="not available yet">
                    soon
                  </span>
                )}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
