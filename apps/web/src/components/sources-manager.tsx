"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type FormEvent } from "react";

import { ErrorAlert } from "@/components/error-alert";
import { FileDropZone } from "@/components/file-drop-zone";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  sourcesApi,
  type SourceImportOut,
  type SourceOut,
  type SourceTestOut,
} from "@/lib/api/client";

const CATEGORY: Record<string, string> = {
  company: "Company boards",
  board: "Job boards",
  academic: "Universities",
  custom: "Added by you",
  demo: "Demo",
};

/** Where NexScout looks for positions: the built-in catalog, your own sources, and the boards
 *  NexScout deliberately doesn't automate. */
export function SourcesManager() {
  const queryClient = useQueryClient();
  const list = useQuery({ queryKey: ["sources"], queryFn: sourcesApi.list });
  const manual = useQuery({ queryKey: ["sources-manual"], queryFn: sourcesApi.manual });
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("all");
  const [country, setCountry] = useState("");
  const [onlyOn, setOnlyOn] = useState(false);
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["sources"] });
  const bulk = useMutation({
    mutationFn: ({ keys, enabled }: { keys: string[]; enabled: boolean }) =>
      sourcesApi.bulk(keys, enabled),
    onSuccess: refresh,
  });

  const shown = useMemo(() => {
    const term = q.trim().toLowerCase();
    return (list.data ?? []).filter(
      (s) =>
        (category === "all" || s.category === category) &&
        (!onlyOn || s.enabled) &&
        (!country ||
          (s.countries ?? []).includes(country) ||
          (country === "REMOTE" && (s.countries ?? []).length === 0)) &&
        (!term || s.name.toLowerCase().includes(term) || s.provider.includes(term)),
    );
  }, [list.data, q, category, country, onlyOn]);
  const countries = useMemo(
    () => [...new Set((list.data ?? []).flatMap((s) => s.countries ?? []))].sort(),
    [list.data],
  );
  const enabledCount = (list.data ?? []).filter((s) => s.enabled).length;

  return (
    <section
      aria-labelledby="sources-heading"
      className="flex flex-col gap-4 rounded-xl border bg-card p-4"
    >
      <div>
        <h2 id="sources-heading" className="text-lg font-semibold">
          Where to look for positions
        </h2>
        <p className="text-sm text-muted-foreground">
          {enabledCount} of {(list.data ?? []).length} sources are on. NexScout reads each one
          through its public job-board API or feed (no logins, no scraping of sites that forbid it),
          and only on searches you start or your autopilot schedule.
        </p>
      </div>

      <AddSource onDone={refresh} />
      <ImportPortals onDone={refresh} />

      <div className="flex flex-wrap items-end gap-2">
        <div className="flex flex-col gap-1">
          <Label htmlFor="src-q">Search</Label>
          <Input
            id="src-q"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Company or board"
            className="w-48"
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="src-cat">Kind</Label>
          <select
            id="src-cat"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="h-8 rounded-lg border bg-background px-2 text-sm"
          >
            <option value="all">All</option>
            {Object.entries(CATEGORY).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="src-country">Country</Label>
          <select
            id="src-country"
            value={country}
            onChange={(e) => setCountry(e.target.value)}
            className="h-8 rounded-lg border bg-background px-2 text-sm"
          >
            <option value="">Any</option>
            <option value="REMOTE">Remote / worldwide</option>
            {countries.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
        <label className="flex items-center gap-1 text-sm">
          <input type="checkbox" checked={onlyOn} onChange={(e) => setOnlyOn(e.target.checked)} />{" "}
          Only turned on
        </label>
        <Button
          size="sm"
          variant="outline"
          disabled={!shown.length || bulk.isPending}
          onClick={() => bulk.mutate({ keys: shown.map((s) => s.key), enabled: true })}
        >
          Turn on all {shown.length} shown
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={!shown.length || bulk.isPending}
          onClick={() => bulk.mutate({ keys: shown.map((s) => s.key), enabled: false })}
        >
          Turn off shown
        </Button>
      </div>
      <ErrorAlert error={list.error ?? bulk.error} />
      <ul className="flex max-h-[32rem] flex-col gap-1 overflow-y-auto">
        {shown.map((s) => (
          <SourceRow key={s.key} source={s} onChange={refresh} />
        ))}
        {list.data && shown.length === 0 && (
          <li className="text-sm text-muted-foreground">No sources match.</li>
        )}
      </ul>

      <details className="text-sm">
        <summary className="cursor-pointer font-medium">
          Boards NexScout doesn&apos;t automate ({manual.data?.length ?? 0})
        </summary>
        <ul className="mt-2 flex flex-col gap-1">
          {(manual.data ?? []).map((m) => (
            <li key={m.name}>
              <a
                className="underline"
                href={m.url}
                target="_blank"
                rel="noopener noreferrer nofollow"
              >
                {m.name}
              </a>{" "}
              <span className="text-muted-foreground">{m.reason}</span>
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}

function SourceRow({ source: s, onChange }: { source: SourceOut; onChange: () => void }) {
  const [result, setResult] = useState<SourceTestOut | null>(null);
  const toggle = useMutation({
    mutationFn: () => sourcesApi.bulk([s.key], !s.enabled),
    onSuccess: onChange,
  });
  const test = useMutation({
    mutationFn: () => sourcesApi.test(s.key),
    onSuccess: (r) => {
      setResult(r);
      onChange();
    },
  });
  const remove = useMutation({ mutationFn: () => sourcesApi.remove(s.key), onSuccess: onChange });
  return (
    <li className="flex flex-col gap-1 rounded-lg border p-2 text-sm" aria-label={s.name}>
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 font-medium">
          <input
            type="checkbox"
            checked={s.enabled}
            onChange={() => toggle.mutate()}
            disabled={toggle.isPending}
          />
          {s.name}
        </label>
        <span className="text-xs text-muted-foreground">{s.provider}</span>
        {(s.countries ?? []).length > 0 && (
          <span className="font-mono text-xs text-muted-foreground">
            {(s.countries ?? []).join(" ")}
          </span>
        )}
        {s.kinds.some((k) => k !== "job") && <Badge variant="outline">PhD &amp; research</Badge>}
        {s.is_demo_data && <Badge variant="outline">Demo data</Badge>}
        {s.last_status === "ok" && (
          <span className="text-xs text-muted-foreground">last read: {s.last_count} postings</span>
        )}
        {s.last_status === "error" && <Badge variant="destructive">Last read failed</Badge>}
        <span className="ml-auto flex gap-1">
          {!s.is_demo_data && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => test.mutate()}
              disabled={test.isPending}
            >
              {test.isPending ? "Checking…" : "Check"}
            </Button>
          )}
          {s.origin === "custom" && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => remove.mutate()}
              disabled={remove.isPending}
            >
              Remove
            </Button>
          )}
        </span>
      </div>
      {s.last_status === "error" && s.last_error && (
        <p className="text-xs text-destructive">{s.last_error}</p>
      )}
      {result && (
        <p role="status" className="text-xs">
          {result.ok
            ? `Works: ${result.postings} postings now (e.g. ${result.sample.slice(0, 2).join("; ")})`
            : `Couldn't read it: ${result.error}`}
        </p>
      )}
      <ErrorAlert error={toggle.error ?? test.error ?? remove.error} />
    </li>
  );
}

function AddSource({ onDone }: { onDone: () => void }) {
  const [msg, setMsg] = useState<string | null>(null);
  const add = useMutation({
    mutationFn: sourcesApi.add,
    onSuccess: (r) => {
      setMsg(
        r.already_in_catalog
          ? `${r.name} is in the catalog; it's now on.`
          : `Added ${r.name} (${r.provider}): ${r.postings} postings right now.`,
      );
      onDone();
    },
  });
  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setMsg(null);
    add.mutate({
      url: String(f.get("url") ?? ""),
      name: String(f.get("name") ?? ""),
      kinds: f.get("phd") === "on" ? ["job", "phd"] : ["job"],
      countries: [],
    });
  }
  return (
    <form
      onSubmit={submit}
      className="flex flex-col gap-2 rounded-lg border p-3"
      aria-label="Add a source"
    >
      <p className="text-sm font-medium">Add any job board or careers page</p>
      <p className="text-xs text-muted-foreground">
        Paste an address: a company&apos;s board on Greenhouse, Lever, Ashby, Workable,
        SmartRecruiters, Recruitee, Personio, Teamtailor, Breezy, Workday or Rippling; a
        university&apos;s vacancy feed; any RSS feed; or a careers page. NexScout checks it can read
        postings before saving.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <div className="flex min-w-64 flex-1 flex-col gap-1">
          <Label htmlFor="add-url">Address</Label>
          <Input
            id="add-url"
            name="url"
            type="url"
            required
            placeholder="https://jobs.ashbyhq.com/company"
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="add-name">Name (optional)</Label>
          <Input id="add-name" name="name" className="w-48" />
        </div>
        <label className="flex items-center gap-1 text-sm">
          <input type="checkbox" name="phd" /> Has PhD positions
        </label>
        <Button type="submit" size="sm" disabled={add.isPending}>
          {add.isPending ? "Checking…" : "Add source"}
        </Button>
      </div>
      {msg && (
        <p role="status" className="text-sm">
          {msg}
        </p>
      )}
      <ErrorAlert error={add.error} title="Source not added" />
    </form>
  );
}

function ImportPortals({ onDone }: { onDone: () => void }) {
  const [report, setReport] = useState<SourceImportOut | null>(null);
  const imp = useMutation({
    mutationFn: sourcesApi.importPortals,
    onSuccess: (r) => {
      setReport(r);
      onDone();
    },
  });
  return (
    <div className="flex flex-col gap-2 rounded-lg border p-3">
      <FileDropZone
        label="Import a career-ops portals.yml"
        hint="Drop the file here, or click to choose it."
        accept=".yml,.yaml"
        maxBytes={2 * 1024 * 1024}
        disabled={imp.isPending}
        onFiles={async ([file]) => imp.mutate(await file.text())}
      />
      {report && (
        <div role="status" className="text-sm">
          Turned on {report.enabled_catalog.length} catalog sources and added {report.added.length}{" "}
          new ones.{" "}
          {report.unsupported.length > 0 && `${report.unsupported.length} entries can't be read:`}
          {report.unsupported.length > 0 && (
            <ul className="mt-1 max-h-40 list-disc overflow-y-auto pl-5 text-xs text-muted-foreground">
              {report.unsupported.map((u) => (
                <li key={u.name}>
                  {u.name}: {u.reason}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <ErrorAlert error={imp.error} title="Import failed" />
    </div>
  );
}
