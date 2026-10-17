"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";

const NEXT: Record<string, string> = { dark: "light", light: "system", system: "dark" };
const LABEL: Record<string, string> = { dark: "Dark", light: "Light", system: "Match system" };

// True only after hydration: the stored theme isn't known during server rendering.
const useMounted = () =>
  useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );

export function ThemeToggle() {
  const { theme = "dark", setTheme } = useTheme();
  const mounted = useMounted();
  const current = mounted ? theme : "dark";
  const Icon = current === "light" ? Sun : current === "system" ? Monitor : Moon;
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => setTheme(NEXT[current] ?? "dark")}
      aria-label={`Theme: ${LABEL[current]}. Switch to ${LABEL[NEXT[current] ?? "dark"]}`}
      title={`Theme: ${LABEL[current]}`}
    >
      <Icon className="size-4 transition-transform duration-300 hover:rotate-12" aria-hidden />
    </Button>
  );
}
