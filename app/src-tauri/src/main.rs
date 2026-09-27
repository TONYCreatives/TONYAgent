// Hide the console window that Windows would otherwise attach to a release
// build. In debug the console stays, so `println!` and debugger attach both
// keep working during development.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tonyagent_app_lib::run()
}
