//! Tauri shell for TONYAgent.
//!
//! Deliberately thin. The Python core in `tonyagent.core` owns conversation
//! state, tool execution and sandboxing; the React layer in `app/src` owns
//! rendering. This crate does exactly three things: open a window, register
//! the shell plugin so the frontend can spawn the core as a sidecar, and
//! register the dialog plugin so it can ask for a project folder.
//!
//! The wire protocol between them is specified in
//! `src/tonyagent/headless/server.py` and implemented once, in
//! `app/src/backend.ts`. Nothing protocol-shaped belongs here — a second
//! implementation in Rust would be a second thing to keep in sync with the
//! Python one, for no benefit.

/// Build and run the desktop app.
///
/// The sidecar is *not* spawned here. Tauri's shell plugin lets the frontend
/// start and stop it, which means the sidecar's lifetime is tied to the
/// window that uses it: closing the window reaps the child process. Spawning
/// from Rust instead would leave an orphan core running after the window
/// closed, still holding the sandbox container and the API key.
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        // Folder picker for the sandbox. `default` here is the permission set
        // in capabilities/default.json, not an implicit allow-all: the dialog
        // plugin's own capabilities gate which calls the frontend may make.
        .plugin(tauri_plugin_dialog::init())
        .run(tauri::generate_context!())
        .expect("failed to start the TONYAgent window");
}
