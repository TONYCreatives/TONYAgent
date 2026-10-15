import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Relative asset URLs. The page is served from a loopback HTTP server whose port
// is picked at runtime (`window/host.py`'s `AssetServer`), so "/assets/..."
// would resolve against that server's root rather than against the page -- which
// happens to work today and did not when a Rust shell served the same files from
// a custom protocol, where it 404d in the packaged build while working fine in
// `vite dev`. Relative is the form that does not depend on who is serving.
export default defineConfig({
  plugins: [react()],
  base: "./",
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    watch: {
      /*
       * Keep the watcher out of the two directories this repo writes while it is
       * running something else.
       *
       * `.tmp/` is where `npm test` emits its compiled tests (`tsconfig.test.json`
       * outDir), and it is rewritten wholesale on every run -- so a dev server
       * watching it would reload the page every time somebody ran the suite, or
       * once per file if the writes raced. `dist/` is the build output this
       * server does not consume.
       *
       * The list used to name `src-tauri/target` and `binaries`, which no longer
       * exist: a cargo build held .exe files open there, and fs.watch on Windows
       * fails with EBUSY on a locked file, which killed Vite outright:
       *
       *   Error: EBUSY: resource busy or locked, watch '...\build_script_build.exe'
       *
       * That failure mode is gone with the Rust shell. Ignoring directories that
       * do not exist is not.
       */
      ignored: ["**/.tmp/**", "**/dist/**"],
    },
  },
  build: {
    // Match the webviews this app is actually hosted in: the WebView2 runtime on
    // Windows and WKWebView on macOS. es2021 is safe for both, and it is the one
    // target the two engines agree on -- a newer one would ship syntax the older
    // WebView2 builds on Windows 10 cannot parse.
    target: "es2021",
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      /*
       * Two pages, one bundle.
       *
       * `pet.html` is the desktop pet's window. It is a second entry point rather
       * than a second build so that the card and the app share the mark, the
       * tokens and the host bridge -- two builds would be two copies of the same
       * CSS waiting to drift -- and so that one `npm run build` produces
       * everything the shell serves.
       *
       * Both keys are named explicitly: an entry list turns Vite's default
       * `index.html` off, so leaving one out is a build with no app in it.
       */
      input: {
        index: "index.html",
        pet: "pet.html",
      },
    },
  },
});
