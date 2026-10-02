//! Rounded window corners, which Windows 11 gives every other app for free.
//!
//! `decorations: false` took the title bar away, and with it the rounded
//! corners the system was drawing around the window. They are not something
//! the compositor infers from a window having no caption -- it infers them
//! from a window *asking* for them, which is one attribute.
//!
//! **Why the native call and not a CSS `border-radius`.** A radius on `body`
//! needs a transparent window to be visible through, because the corner
//! outside the radius is painted by whatever is *behind* the window, and an
//! opaque window has nothing behind it but its own background. Turning the
//! window transparent to get there costs more than it looks: it puts the
//! whole window on the layered path, where the drop shadow, the resize
//! borders and the compositor's own corner masking all change behaviour --
//! and `WS_THICKFRAME` is the reason the window still snaps and resizes at
//! all (see `system_menu.rs`). Asking DWM for the corners keeps an ordinary
//! opaque window and gets exactly the corners every other Windows 11 window
//! has, including the radius Windows scales for the monitor's DPI.
//!
//! `DWMWCP_ROUND` rather than `DWMWCP_ROUNDSMALL`: the small radius is what
//! dialogs and menus get, and this is an application window. `DWMWCP_ROUND`
//! is also what the OS picks by default for a top-level window, so this asks
//! for the window it would have had anyway -- which matters, because the
//! point of the call is to stop losing something, not to add a style.
//!
//! **Applied once, at startup, and never again.** It is a window attribute
//! rather than a paint operation, so it survives a resize, a move between
//! monitors and a DPI change on its own; re-applying it per event would be
//! work for no observable difference. The one thing that does change it is
//! the caller, so this is deliberately *not* exposed as a command: a
//! frontend that could set it could also set it to something else, and there
//! is nothing in the UI that wants a different shape.
//!
//! **A failure is not fatal.** `DwmSetWindowAttribute` returns an `HRESULT`,
//! not a panic, and the plausible reasons for failure are all "this build of
//! Windows does not know the attribute" -- Windows 10, or a Win11 too old to
//! have it. A window with square corners is a cosmetic difference, so the
//! caller logs and carries on rather than refusing to open.

use tauri::WebviewWindow;

use windows_sys::Win32::Graphics::Dwm::{
    DwmSetWindowAttribute, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND,
};

/// `sizeof(enum)` as DWM wants it: the attribute value is a 4-byte enum.
const ENUM_SIZE: u32 = std::mem::size_of::<i32>() as u32;

/// Ask the compositor to round this window's corners.
///
/// Windows-only in practice, and `#[cfg(windows)]` at the one call site, so
/// this file only ever compiles where `Win32_Graphics_Dwm` exists.
pub fn round(window: &WebviewWindow) -> Result<(), String> {
    // `hwnd()` comes back as the `windows` crate's HWND, a newtype over the same
    // `*mut c_void` that windows-sys calls HWND. `.0` is the handle.
    let hwnd = window.hwnd().map_err(|error| error.to_string())?;

    // SAFETY: the only argument that is not the window's own handle is the
    // address of a local `i32` that outlives the call, and its length is that
    // local's own size, so DWM reads exactly four bytes that are initialised.
    let preference: i32 = DWMWCP_ROUND;
    let hr = unsafe {
        DwmSetWindowAttribute(
            hwnd.0,
            DWMWA_WINDOW_CORNER_PREFERENCE as u32,
            &preference as *const i32 as *const std::ffi::c_void,
            ENUM_SIZE,
        )
    };

    // `S_OK` is 0, and an HRESULT is a signed 32-bit status where anything
    // below zero is a failure code -- so the sign is the whole test, and it
    // is what `FAILED()` in C is.
    if hr < 0 {
        return Err(format!("DwmSetWindowAttribute refused the corner preference (0x{hr:08x})"));
    }
    Ok(())
}