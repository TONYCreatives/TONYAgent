//! The window's system menu, which `decorations: false` took away with the bar.
//!
//! Turning the decorations off removed more than three glyphs. The window still
//! carries `WS_SYSMENU` -- tao keeps the style and simply tells `WM_NCCALCSIZE`
//! that the client area is the whole window -- so the OS is still holding a real
//! menu with Restore, Move, Size, Minimize, Maximize and Close on it, each item
//! already carrying the enabled state that belongs to it: Restore greyed on a
//! normal window, Maximize greyed on a maximized one, Size greyed on a minimized
//! one. Building that menu here would mean reimplementing those rules and
//! getting the two greyed-out items subtly wrong.
//!
//! So this asks for the real one and shows it: `GetSystemMenu` for the menu the
//! OS already has, `TrackPopupMenu` to put it on screen at the cursor. Move and
//! Size then come back as the system's own move and size loops -- arrow keys and
//! all -- instead of a drag the app would have to reimplement.
//!
//! **Why not `WM_SYSCOMMAND` + `SC_KEYMENU`,** which is the message the OS sends
//! itself for Alt+Space and looks like the tidier way in: measured, it does
//! nothing to this window. `scripts/verify_system_menu.py` posts it from outside
//! the app, with no frontend and no IPC in the way, and no menu appears. A
//! frameless tao window does not pass that command to `DefWindowProc`.
//!
//! Two other decisions:
//!
//! - `TPM_RETURNCMD`, so the chosen item comes back as a value instead of the
//!   menu posting it. The command is then posted by hand, which keeps the
//!   window's own message loop as the thing that acts on it -- the same thing
//!   that happens when a user clicks a system menu with the mouse.
//! - At the cursor, not at the press. Windows puts the system menu at the
//!   pointer, and F10 opens it there too, which is why both routes agree without
//!   either having to be told where the bar is.

use tauri::WebviewWindow;

#[tauri::command]
pub fn show_system_menu(window: WebviewWindow) -> Result<(), String> {
    use windows_sys::Win32::Foundation::POINT;
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        GetCursorPos, GetSystemMenu, PostMessageW, TrackPopupMenu, TPM_LEFTALIGN,
        TPM_RETURNCMD, TPM_RIGHTBUTTON, TPM_TOPALIGN, WM_SYSCOMMAND,
    };

    // `hwnd()` comes back as the `windows` crate's HWND, a newtype over the same
    // `*mut c_void` that windows-sys calls HWND. `.0` is the handle.
    let hwnd = window.hwnd().map_err(|error| error.to_string())?;

    // SAFETY: every call below is made with the window's own handle and a menu
    // that handle owns. `GetSystemMenu(hwnd, FALSE)` returns the live menu -- no
    // copy, so nothing to leak -- and each pointer argument is either null or
    // the address of a local that outlives the call.
    unsafe {
        let hmenu = GetSystemMenu(hwnd.0, 0);
        if hmenu.is_null() {
            return Err("this window has no system menu".into());
        }

        let mut at = POINT { x: 0, y: 0 };
        GetCursorPos(&mut at);

        // Blocks until the menu is dismissed, which is what a menu is: it runs a
        // modal loop on this thread and dispatches the window's messages while
        // it is up. The webview is a separate process, so the app keeps painting
        // and the command's promise settles when the menu closes.
        let chosen = TrackPopupMenu(
            hmenu,
            TPM_LEFTALIGN | TPM_TOPALIGN | TPM_RIGHTBUTTON | TPM_RETURNCMD,
            at.x,
            at.y,
            0,
            hwnd.0,
            std::ptr::null(),
        );

        // Zero is the menu being dismissed -- Escape, or a click elsewhere. There
        // is nothing to report and nothing to undo.
        if chosen > 0 && PostMessageW(hwnd.0, WM_SYSCOMMAND, chosen as usize, 0) == 0 {
            return Err("the window refused the menu command it had just been given".into());
        }
    }
    Ok(())
}
