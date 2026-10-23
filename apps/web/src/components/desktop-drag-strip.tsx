"use client";

import { useSyncExternalStore } from "react";

import { inDesktopApp } from "@/lib/desktop";

const noSubscription = () => () => {};

/** Pages without the top bar (sign in, register) still need something to move the desktop
 *  app's frameless window by. Nothing is rendered in a browser. */
export function DesktopDragStrip() {
  const desktop = useSyncExternalStore(noSubscription, inDesktopApp, () => false);
  if (!desktop) return null;
  return <div aria-hidden className="desktop-titlebar fixed inset-x-0 top-0 z-50 h-14" />;
}
