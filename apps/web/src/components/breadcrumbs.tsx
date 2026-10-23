"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";

import { useCase } from "@/lib/hooks";
import { SECTIONS } from "@/lib/sections";

// What a page below a section is: /jobs/<id> is a position, /documents/generated/<id> a document.
const ITEM: Record<string, string> = {
  phd: "Position",
  jobs: "Position",
  applications: "Application",
  documents: "Document",
};

/** Cases › case › section › item, on every case page. The last one is the current page. */
export function Breadcrumbs() {
  const { caseId } = useParams<{ caseId: string }>();
  const pathname = usePathname();
  const kase = useCase(caseId);
  const base = `/cases/${caseId}`;
  const [slug, ...rest] = pathname.slice(base.length).split("/").filter(Boolean);
  const section = SECTIONS.find((s) => s.slug === (slug ?? ""));
  const crumbs: { label: string; href: string }[] = [
    { label: "Cases", href: "/cases" },
    { label: kase.data?.name ?? "Case", href: base },
  ];
  if (slug && section) crumbs.push({ label: section.label, href: `${base}/${slug}` });
  if (slug && rest.length > 0) crumbs.push({ label: ITEM[slug] ?? "Details", href: pathname });

  return (
    <nav aria-label="Breadcrumb" className="mb-4 text-sm text-muted-foreground">
      <ol className="flex flex-wrap items-center gap-1">
        {crumbs.map((c, i) => {
          const last = i === crumbs.length - 1;
          return (
            <li key={c.href + i} className="flex items-center gap-1">
              {last ? (
                <span aria-current="page" className="max-w-[24ch] truncate text-foreground">
                  {c.label}
                </span>
              ) : (
                <>
                  <Link className="max-w-[24ch] truncate hover:underline" href={c.href}>
                    {c.label}
                  </Link>
                  <span aria-hidden>›</span>
                </>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
