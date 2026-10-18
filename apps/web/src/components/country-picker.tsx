"use client";

import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useId, useMemo, useState } from "react";

import { Input } from "@/components/ui/input";
import { sourcesApi } from "@/lib/api/client";

/** Pick countries (ISO 3166-1 codes) and groups (EU, Nordics, Europe, …) from the full list. */
export function CountryPicker({
  label,
  value,
  onChange,
  help,
}: {
  label: string;
  value: string[];
  onChange: (next: string[]) => void;
  help?: string;
}) {
  const id = useId();
  const geo = useQuery({ queryKey: ["geo"], queryFn: sourcesApi.geo, staleTime: Infinity });
  const [q, setQ] = useState("");
  const names = useMemo(() => {
    const m = new Map<string, string>();
    for (const c of geo.data?.countries ?? []) m.set(c.code, c.name);
    for (const g of geo.data?.groups ?? []) m.set(g.key, g.name);
    return m;
  }, [geo.data]);
  const matches = useMemo(() => {
    const term = q.trim().toLowerCase();
    if (!term) return [];
    // Exact name or code first, then names starting with the term, then names containing it;
    // on a tie a country comes before a group ("Germany" → Germany, not DACH).
    const rank = (name: string, code: string): number => {
      const n = name.toLowerCase();
      if (n === term || code.toLowerCase() === term) return 0;
      if (n.startsWith(term)) return 1;
      if (n.includes(term)) return 2;
      return -1;
    };
    const candidates = [
      ...(geo.data?.countries ?? []).map((c) => ({ code: c.code, name: c.name, score: rank(c.name, c.code) * 2 })),
      ...(geo.data?.groups ?? []).map((g) => ({
        code: g.key,
        name: `${g.name} (${g.codes.length})`,
        score: rank(g.name, g.key) * 2 + 1,
      })),
    ];
    return candidates
      .filter((x) => x.score >= 0 && !value.includes(x.code))
      .sort((a, b) => a.score - b.score || a.name.localeCompare(b.name))
      .slice(0, 8);
  }, [q, geo.data, value]);
  const add = (code: string) => {
    if (!value.includes(code)) onChange([...value, code]);
    setQ("");
  };
  const quick = ["EU", "EEA", "EUROPE", "NORDICS", "DACH", "BENELUX", "UKI"];

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {help && <p className="text-xs text-muted-foreground">{help}</p>}
      <ul className="flex flex-wrap gap-1" aria-label={`${label}: chosen`}>
        {value.map((code) => (
          <li key={code} className="flex items-center gap-1 rounded-full border bg-muted px-2 py-0.5 text-xs">
            {names.get(code) ?? code}
            <button
              type="button"
              aria-label={`Remove ${names.get(code) ?? code}`}
              onClick={() => onChange(value.filter((v) => v !== code))}
            >
              <X className="size-3" />
            </button>
          </li>
        ))}
        {value.length === 0 && <li className="text-xs text-muted-foreground">None chosen.</li>}
      </ul>
      <Input
        id={id}
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && matches[0]) {
            e.preventDefault();
            add(matches[0].code);
          }
        }}
        placeholder="Type a country or a group (e.g. Finland, EU, Nordic)"
        autoComplete="off"
      />
      {matches.length > 0 && (
        <ul className="flex flex-col rounded-md border text-sm" aria-label={`${label}: suggestions`}>
          {matches.map((m) => (
            <li key={m.code}>
              <button type="button" className="w-full px-2 py-1 text-left hover:bg-muted" onClick={() => add(m.code)}>
                {m.name}
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap gap-1 text-xs">
        {quick
          .filter((k) => !value.includes(k) && names.has(k))
          .map((k) => (
            <button key={k} type="button" className="rounded-full border px-2 py-0.5 hover:bg-muted" onClick={() => add(k)}>
              + {names.get(k)}
            </button>
          ))}
      </div>
    </div>
  );
}
