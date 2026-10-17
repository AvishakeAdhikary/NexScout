"use client";

import {
  Activity,
  Bot,
  Briefcase,
  FileText,
  GraduationCap,
  LayoutDashboard,
  MessageSquare,
  Network,
  Send,
  Settings,
  UserRound,
  Users,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";

import { useCase } from "@/lib/hooks";
import { SECTIONS } from "@/lib/sections";
import { cn } from "@/lib/utils";

const ICONS: Record<string, LucideIcon> = {
  "": LayoutDashboard,
  profile: UserRound,
  "mind-map": Network,
  phd: GraduationCap,
  jobs: Briefcase,
  applications: Send,
  documents: FileText,
  relationships: Users,
  assistant: MessageSquare,
  activity: Activity,
  autopilot: Bot,
  settings: Settings,
};

export function CaseNav() {
  const { caseId } = useParams<{ caseId: string }>();
  const pathname = usePathname();
  const kase = useCase(caseId);
  const base = `/cases/${caseId}`;

  return (
    <nav aria-label="Case sections" className="flex flex-col gap-1">
      <p className="mb-2 truncate px-2 font-heading text-sm font-semibold" title={kase.data?.name}>
        {kase.data?.name ?? " "}
      </p>
      <ul className="flex flex-row flex-wrap gap-0.5 md:flex-col">
        {SECTIONS.map((s) => {
          const href = s.slug ? `${base}/${s.slug}` : base;
          // Sub-pages (a position, a document, an application) keep their section highlighted.
          const active = s.slug ? pathname === href || pathname.startsWith(`${href}/`) : pathname === href;
          const Icon = ICONS[s.slug] ?? LayoutDashboard;
          return (
            <li key={s.slug || "dashboard"}>
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "group relative flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-sm text-muted-foreground hover:bg-muted hover:text-foreground",
                  active && "bg-primary/10 font-medium text-foreground hover:bg-primary/15",
                )}
              >
                <span
                  aria-hidden
                  className={cn(
                    "absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-primary opacity-0 transition-opacity duration-200",
                    active && "opacity-100",
                  )}
                />
                <Icon
                  aria-hidden
                  className={cn(
                    "size-4 shrink-0 transition-transform duration-200 group-hover:scale-110",
                    active ? "text-primary" : "text-muted-foreground",
                  )}
                />
                <span>{s.label}</span>
                {s.milestone !== undefined && (
                  <span className="ml-auto text-[10px] text-muted-foreground" aria-label="not available yet">
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
