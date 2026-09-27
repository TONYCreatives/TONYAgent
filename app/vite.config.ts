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
    watch: {
      /*
       * Keep the watcher out of the Rust build directory.
       *
       * Vite's watcher walks the project root, which includes
       * src-tauri/target/. While cargo is building, those .exe files are held
       * open, and fs.watch on Windows fails with EBUSY -- which kills Vite
       * outright and takes `tauri dev` down with it:
       *
       *   Error: EBUSY: resource busy or locked, watch '...\build_script_build.exe'
       *   Error The "beforeDevCommand" terminated with a non-zero status code.
       *
       * Watching those files is also pointless: cargo owns them, and a change
       * to one is not something the frontend needs to react to.
       */
      ignored: ["**/src-tauri/**", "**/binaries/**"],
    },
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
