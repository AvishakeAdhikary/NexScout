"use client";

import { useParams } from "next/navigation";

import { OpportunityBoard } from "@/components/opportunity-board";

export default function PhdPage() {
  const { caseId } = useParams<{ caseId: string }>();
  return (
    <div className="flex flex-col gap-4">
      <header>
        <h1 className="text-2xl font-semibold">PhD Opportunities</h1>
        <p className="text-muted-foreground">
          Doctoral positions, postdocs, and funded research roles, matched against your confirmed
          profile. Researching requirements and supervisors in depth, and preparing documents, come
          in a later release.
        </p>
      </header>
      <OpportunityBoard caseId={caseId} academic />
    </div>
  );
}
