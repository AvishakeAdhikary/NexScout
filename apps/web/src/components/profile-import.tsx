"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";

import { ErrorAlert } from "@/components/error-alert";
import { FileDropZone } from "@/components/file-drop-zone";
import { casesApi } from "@/lib/api/client";

/** Import a .nexscout profile as a new case (nothing existing changes). */
export function ProfileImport() {
  const queryClient = useQueryClient();
  const importIt = useMutation({
    mutationFn: casesApi.importProfile,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["cases"] }),
  });
  const r = importIt.data;

  return (
    <section
      aria-labelledby="import-heading"
      className="flex flex-col gap-3 rounded-xl border bg-card p-4"
    >
      <h2 id="import-heading" className="text-lg font-semibold">
        Import a profile
      </h2>
      <p className="text-sm text-muted-foreground">
        A <code>.nexscout</code> file exported from NexScout (on this computer or another one)
        becomes a new case with every entry, the mind map, snapshots, relationships and documents.
        Your existing cases aren&apos;t changed.
      </p>
      <FileDropZone
        label={importIt.isPending ? "Importing…" : "Choose a .nexscout file"}
        accept=".nexscout,.zip"
        maxBytes={100 * 1024 * 1024}
        disabled={importIt.isPending}
        onFiles={([file]) => file && importIt.mutate(file)}
      />
      <ErrorAlert error={importIt.error} title="Couldn't import that file" />
      {r && (
        <div role="status" className="rounded-md border p-3 text-sm">
          <p>
            Imported as{" "}
            <Link className="font-medium underline" href={`/cases/${r.case_id}`}>
              {r.case_name}
            </Link>
            : {r.counts.facts ?? 0} entries, {r.counts.documents ?? 0} documents,{" "}
            {r.counts.snapshots ?? 0} snapshots.
          </p>
          {r.warnings.length > 0 && (
            <details className="mt-1">
              <summary className="cursor-pointer">{r.warnings.length} note(s)</summary>
              <ul className="mt-1 list-disc pl-5 text-muted-foreground">
                {r.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </section>
  );
}
