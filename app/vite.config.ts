import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Tauri serves the built assets from a custom protocol, so asset URLs must be
// relative. Absolute "/assets/..." paths resolve against the protocol root and
// 404 in a packaged build while working fine in `vite dev`.
export default defineConfig({
  plugins: [react()],
  base: "./",
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
  },
  build: {
    // Match the webview engines Tauri ships against. es2021 is safe for the
    // WebView2 runtime on Windows and the WKWebView on macOS.
    target: "es2021",
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
  },
});
