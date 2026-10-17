// App window preload: exposes only harmless facts. No Node, no IPC to privileged code.
import { contextBridge } from "electron";

contextBridge.exposeInMainWorld("nexscoutDesktop", {
  isDesktop: true,
  platform: process.platform,
});
