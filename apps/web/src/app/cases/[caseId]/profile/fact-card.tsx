"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ErrorAlert } from "@/components/error-alert";
import { FactForm, type LinkOption } from "@/components/fact-form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { factsApi, type FactOut } from "@/lib/api/client";
import { SECTION_FIELDS, STATUS_LABELS } from "@/lib/profile-schema";

function summary(fact: FactOut): string[] {
  const data = fact.data as Record<string, unknown>;
  return SECTION_FIELDS[fact.section]
    .filter((f) => data[f.key] != null && f.type !== "textarea")
    .map((f) => {
      const v = data[f.key];
      return `${f.label}: ${Array.isArray(v) ? v.join(", ") : String(v)}`;
    });
}

export function FactCard({
  fact,
  caseId,
  linkOptions = [],
  labels = {},
  selected,
  onSelect,
}: {
  fact: FactOut;
  caseId: string;
  linkOptions?: LinkOption[];
  /** id -> label, to show what this entry is part of. */
  labels?: Record<string, string>;
  selected?: boolean;
  onSelect?: (selected: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [showSource, setShowSource] = useState(false);
  const evidence = useQuery({
    queryKey: ["evidence", fact.id],
    queryFn: () => factsApi.evidence(fact.id),
    enabled: showSource,
  });
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["facts", caseId] });
    queryClient.invalidateQueries({ queryKey: ["gaps", caseId] });
  };
  const update = useMutation({
    mutationFn: (body: Parameters<typeof factsApi.update>[1]) => factsApi.update(fact.id, body),
    onSuccess: () => {
      setEditing(false);
      invalidate();
    },
  });
  const remove = useMutation({ mutationFn: () => factsApi.remove(fact.id), onSuccess: invalidate });
  const meta = fact.meta as {
    warnings?: string[];
    edited_by_user?: boolean;
    generated?: boolean;
    model?: string | null;
    is_mock?: boolean;
  };
  const description = (fact.data as Record<string, unknown>).description;
  const partOf = ((fact.data as Record<string, unknown>).related_fact_ids as string[] | undefined) ?? [];
  const pending = fact.review_state === "pending";

  return (
    <article
      className="rounded-lg border p-3"
      aria-labelledby={`fact-${fact.id}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex items-start gap-2">
          {onSelect && (
            <input
              type="checkbox"
              className="mt-1"
              aria-label={`Select ${fact.label}`}
              checked={!!selected}
              onChange={(e) => onSelect(e.target.checked)}
            />
          )}
          <h4 id={`fact-${fact.id}`} className="font-medium">
            {fact.label}
          </h4>
        </div>
        <div className="flex flex-wrap gap-1">
          <Badge variant="outline">{STATUS_LABELS[fact.status] ?? fact.status}</Badge>
          {meta.edited_by_user && <Badge variant="outline">Edited by you</Badge>}
          {meta.generated &&
            (meta.is_mock ? (
              <Badge variant="destructive">Mock text, not written by AI</Badge>
            ) : (
              <Badge variant="outline">Drafted by {meta.model ?? "an AI model"}</Badge>
            ))}
          {fact.is_private && <Badge variant="secondary">Private</Badge>}
        </div>
      </div>
      {!editing && (
        <>
          <ul className="mt-1 text-sm text-muted-foreground">
            {summary(fact).map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          {partOf.length > 0 && (
            <p className="mt-1 text-sm">
              Part of: {partOf.map((id) => labels[id] ?? "an entry that was deleted").join(", ")}
            </p>
          )}
          {typeof description === "string" && (
            <p className="mt-1 whitespace-pre-line text-sm">{description}</p>
          )}
          {meta.warnings && meta.warnings.length > 0 && (
            <p className="mt-2 text-sm text-amber-700 dark:text-amber-400" role="note">
              Please check: {meta.warnings.join(" ")}
            </p>
          )}
        </>
      )}
      {editing && (
        <div className="mt-3">
          <FactForm
            section={fact.section}
            initial={fact.data as Record<string, unknown>}
            linkOptions={linkOptions}
            selfId={fact.id}
            submitLabel={pending ? "Save and accept" : "Save"}
            pending={update.isPending}
            onCancel={() => setEditing(false)}
            onSubmit={(data) =>
              update.mutate({
                version: fact.version,
                data,
                review_state: pending ? "accepted" : undefined,
              })
            }
          />
        </div>
      )}

      {showSource && (
        <div className="mt-2 rounded bg-muted p-2 text-sm">
          {evidence.isPending && <p>Loading source…</p>}
          {evidence.data?.map((ev) => (
            <figure key={ev.id}>
              <figcaption className="text-xs text-muted-foreground">
                {ev.kind === "document"
                  ? `From your document${ev.page ? `, page ${ev.page}` : ""}${ev.document_id ? "" : " (file since deleted)"}`
                  : ev.kind === "user_entry"
                    ? "Entered by you"
                    : ev.kind === "merge"
                      ? "Merge note"
                      : "From a link"}
              </figcaption>
              {ev.excerpt && (
                <blockquote className="mt-1 whitespace-pre-line border-l-2 pl-2">{ev.excerpt}</blockquote>
              )}
            </figure>
          ))}
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        {pending && !editing && (
          <>
            <Button
              size="sm"
              onClick={() => update.mutate({ version: fact.version, review_state: "accepted" })}
              disabled={update.isPending}
            >
              Accept
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => update.mutate({ version: fact.version, review_state: "rejected" })}
              disabled={update.isPending}
            >
              Reject
            </Button>
          </>
        )}
        {!editing && (
          <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
            {pending ? "Edit, then accept" : "Edit"}
          </Button>
        )}
        <Button
          size="sm"
          variant="ghost"
          aria-expanded={showSource}
          onClick={() => setShowSource((s) => !s)}
        >
          {showSource ? "Hide source" : "Show source"}
        </Button>
        {!pending && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => update.mutate({ version: fact.version, is_private: !fact.is_private })}
          >
            {fact.is_private ? "Make shareable" : "Make private"}
          </Button>
        )}
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            if (window.confirm(`Delete “${fact.label}”?`)) remove.mutate();
          }}
        >
          Delete
        </Button>
      </div>
      <ErrorAlert error={update.error ?? remove.error} />
    </article>
  );
}
