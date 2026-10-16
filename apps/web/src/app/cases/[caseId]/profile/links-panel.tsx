"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { ErrorAlert } from "@/components/error-alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { relationshipsApi } from "@/lib/api/client";

const KIND_LABELS: Record<string, string> = {
  linkedin: "LinkedIn",
  github: "GitHub",
  google_scholar: "Google Scholar",
  orcid: "ORCID",
  researchgate: "ResearchGate",
  website: "Website",
  other: "Other",
};

export function LinksPanel({ caseId }: { caseId: string }) {
  const queryClient = useQueryClient();
  const links = useQuery({
    queryKey: ["links", caseId],
    queryFn: () => relationshipsApi.links(caseId),
  });
  const [url, setUrl] = useState("");
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["links", caseId] });
  const add = useMutation({
    mutationFn: () => relationshipsApi.addLink(caseId, url),
    onSuccess: () => {
      setUrl("");
      invalidate();
    },
  });
  const remove = useMutation({ mutationFn: relationshipsApi.removeLink, onSuccess: invalidate });

  function submit(event: FormEvent) {
    event.preventDefault();
    add.mutate();
  }

  return (
    <section id="links" aria-labelledby="links-heading" className="flex flex-col gap-3">
      <h2 id="links-heading" className="text-xl font-semibold">
        Profile links
      </h2>
      <p className="text-sm text-muted-foreground">
        Links to LinkedIn, GitHub, ORCID, Google Scholar, or your own site. NexScout stores the
        address only. It does not log in to or copy data from these sites.
      </p>
      {links.data && links.data.length > 0 && (
        <ul className="flex flex-col gap-1">
          {links.data.map((l) => (
            <li key={l.id} className="flex items-center justify-between gap-2 rounded border px-3 py-2 text-sm">
              <span>
                <span className="font-medium">{KIND_LABELS[l.kind] ?? l.kind}</span>{" "}
                <a href={l.url} target="_blank" rel="noopener noreferrer nofollow" className="underline">
                  {l.url}
                </a>
              </span>
              <Button size="sm" variant="ghost" onClick={() => remove.mutate(l.id)}>
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
        <div className="flex min-w-72 flex-1 flex-col gap-1">
          <Label htmlFor="link-url">Add a link</Label>
          <Input
            id="link-url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://github.com/yourname"
            required
            maxLength={2048}
          />
        </div>
        <Button type="submit" disabled={add.isPending}>
          Add link
        </Button>
      </form>
      <ErrorAlert error={add.error ?? remove.error} />
    </section>
  );
}
