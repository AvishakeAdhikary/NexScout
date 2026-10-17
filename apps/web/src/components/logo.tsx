import { useId } from "react";

import { cn } from "@/lib/utils";

/**
 * NexScout mark: a telescope on a tripod under a twinkling star, on a night-sky gradient tile.
 * Pure SVG, so it scales to any size; the star's twinkle respects reduced-motion settings.
 */
export function LogoMark({ size = 32, className, title }: { size?: number; className?: string; title?: string }) {
  const id = `ns${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      className={cn("shrink-0", className)}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    >
      <defs>
        <linearGradient id={`${id}-sky`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#4f46e5" />
          <stop offset="0.55" stopColor="#7c3aed" />
          <stop offset="1" stopColor="#0891b2" />
        </linearGradient>
        <radialGradient id={`${id}-glow`} cx="0.8" cy="0.2" r="0.6">
          <stop offset="0" stopColor="#fff" stopOpacity="0.35" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </radialGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill={`url(#${id}-sky)`} />
      <rect width="32" height="32" rx="9" fill={`url(#${id}-glow)`} />
      <g fill="#fff">
        <g transform="rotate(-28 16 17)">
          <rect x="5" y="14.4" width="2.6" height="2.4" rx="0.6" opacity="0.85" />
          <rect x="7.5" y="13" width="13" height="5.2" rx="1.6" opacity="0.95" />
          <rect x="20.5" y="12" width="4" height="7.2" rx="1.4" />
        </g>
        <circle cx="14.6" cy="19.2" r="1.5" />
      </g>
      <path
        d="M14.6 19.6 10.2 27.4M14.6 19.6l4.4 7.8M14.6 19.6v7.8"
        stroke="#fff"
        strokeWidth="1.7"
        strokeLinecap="round"
        fill="none"
        opacity="0.9"
      />
      <path
        className="logo-star"
        fill="#fff"
        d="M26 3.6l.75 1.95L28.7 6.3l-1.95.75L26 9l-.75-1.95L23.3 6.3l1.95-.75z"
      />
      <circle cx="21" cy="4.6" r="0.6" fill="#fff" opacity="0.6" />
      <circle cx="28.6" cy="11.2" r="0.5" fill="#fff" opacity="0.5" />
    </svg>
  );
}

export function Logo({ size = 30, className }: { size?: number; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <LogoMark size={size} />
      <span className="font-heading text-lg font-semibold tracking-tight">
        Nex<span className="bg-gradient-to-r from-indigo-400 via-violet-400 to-cyan-400 bg-clip-text text-transparent dark:from-indigo-300 dark:via-violet-300 dark:to-cyan-300">Scout</span>
      </span>
    </span>
  );
}
