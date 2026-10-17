// Setup window preload: exactly two IPC calls, both validated again in the main process.
import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("nexscoutSetup", {
  chooseFolder: (): Promise<string | null> => ipcRenderer.invoke("setup:choose-folder"),
  save: (config: unknown): Promise<{ ok: boolean; error?: string }> =>
    ipcRenderer.invoke("setup:save", config),
});
