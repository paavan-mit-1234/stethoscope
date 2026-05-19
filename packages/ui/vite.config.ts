import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Tauri wraps this dev server later (Phase 2 shell). Relative base so the
// built bundle works inside the Tauri webview from the filesystem.
export default defineConfig({
  plugins: [react()],
  base: "./",
  clearScreen: false,
  server: {
    host: "127.0.0.1",
    port: 1420,
    strictPort: true,
  },
});
