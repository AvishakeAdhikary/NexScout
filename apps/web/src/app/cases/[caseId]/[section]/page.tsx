"use client";

import { notFound, useParams } from "next/navigation";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { findSection } from "@/lib/sections";

// Sections that are not built yet. Each says so plainly. No mock data, no fake controls.
export default function SectionPage() {
  const { section: slug } = useParams<{ caseId: string; section: string }>();
  const section = findSection(slug);
  if (!section || !section.slug) notFound();

  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <h1 className="text-2xl font-semibold">{section.label}</h1>
      <p className="text-muted-foreground">{section.description}</p>
      <Alert>
        <AlertTitle>Not available yet</AlertTitle>
        <AlertDescription>
          This part of NexScout is still being built (planned for milestone {section.milestone}).
          Nothing on this page is working yet, and no data is being collected here.
        </AlertDescription>
      </Alert>
    </div>
  );
}
