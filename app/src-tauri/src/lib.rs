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
//!
//! The one command here is the exception, and it is not protocol-shaped: it is
//! the window's system menu, which no amount of markup can draw. See
//! `system_menu.rs`.

#[cfg(windows)]
mod system_menu;

/// Build and run the desktop app.
///
/// The sidecar is *not* spawned here. Tauri's shell plugin lets the frontend
/// start and stop it, which means the sidecar's lifetime is tied to the
/// window that uses it: closing the window reaps the child process. Spawning
/// from Rust instead would leave an orphan core running after the window
/// closed, still holding the sandbox container and the API key.
pub fn run() {
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        // Folder picker for the sandbox. `default` here is the permission set
        // in capabilities/default.json, not an implicit allow-all: the dialog
        // plugin's own capabilities gate which calls the frontend may make.
        .plugin(tauri_plugin_dialog::init());

    // The window draws its own title bar, so it also answers for the system
    // menu. Windows-only, and gated like any other command: the permission
    // `allow-show-system-menu` in capabilities/default.json is generated from
    // the name in build.rs, and without it the call is refused with a message
    // in the console rather than silently doing nothing.
    #[cfg(windows)]
    let builder = builder.invoke_handler(tauri::generate_handler![
        system_menu::show_system_menu
    ]);

    builder
        .run(tauri::generate_context!())
        .expect("failed to start the TONYAgent window");
}
