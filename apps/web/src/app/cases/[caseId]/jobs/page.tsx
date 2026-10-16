"use client";

import { useParams } from "next/navigation";

import { OpportunityBoard } from "@/components/opportunity-board";

export default function JobsPage() {
  const { caseId } = useParams<{ caseId: string }>();
  return (
    <div className="flex flex-col gap-4">
      <header>
        <h1 className="text-2xl font-semibold">Job Opportunities</h1>
        <p className="text-muted-foreground">
          Jobs from your enabled sources, with duplicates merged and every fit estimate explained.
          Set strict or flexible experience matching in your{" "}
          <a className="underline" href="../profile#preferences">
            preferences
          </a>
          .
        </p>
      </header>
      <OpportunityBoard caseId={caseId} academic={false} />
    </div>
  );
}
