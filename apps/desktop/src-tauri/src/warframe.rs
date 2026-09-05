//! Warframe window detection and safe keyboard output.
//!
//! Everything here uses ordinary, documented user-space Windows APIs:
//! `FindWindowW`/`GetForegroundWindow` to see whether the game is focused, and
//! `SendInput` to synthesise key presses. That is the same mechanism a macro
//! keyboard or an on-screen keyboard uses.
//!
//! Explicitly NOT done, by design: no DLL injection, no reading or writing the
//! game's memory, no hooking of game internals, nothing that touches anti-cheat.
//! If the game is not the focused window, no key is sent at all.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct WindowStatus {
    pub found: bool,
    pub focused: bool,
    pub title: Option<String>,
    pub supported: bool,
}

/// Set while a performance is running, so a stop request is seen immediately.
static PLAYING: AtomicBool = AtomicBool::new(false);

pub fn set_playing(value: bool) {
    PLAYING.store(value, Ordering::SeqCst);
}

pub fn is_playing() -> bool {
    PLAYING.load(Ordering::SeqCst)
}

#[cfg(windows)]
mod imp {
    use super::WindowStatus;
    use windows_sys::Win32::Foundation::HWND;
    use windows_sys::Win32::UI::Input::KeyboardAndMouse::{
        MapVirtualKeyW, SendInput, INPUT, INPUT_KEYBOARD, KEYBDINPUT, KEYEVENTF_EXTENDEDKEY,
        KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE, MAPVK_VK_TO_VSC,
    };
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        FindWindowW, GetForegroundWindow, GetWindowTextW,
    };

    const TITLES: [&str; 1] = ["Warframe"];

    fn wide(text: &str) -> Vec<u16> {
        text.encode_utf16().chain(std::iter::once(0)).collect()
    }

    pub fn status() -> WindowStatus {
        unsafe {
            for title in TITLES {
                let handle: HWND = FindWindowW(std::ptr::null(), wide(title).as_ptr());
                if handle.is_null() {
                    continue;
                }
                let mut buffer = [0u16; 256];
                let length = GetWindowTextW(handle, buffer.as_mut_ptr(), buffer.len() as i32);
                let text = if length > 0 {
                    Some(String::from_utf16_lossy(&buffer[..length as usize]))
                } else {
                    Some(title.to_string())
                };
                return WindowStatus {
                    found: true,
                    focused: GetForegroundWindow() == handle,
                    title: text,
                    supported: true,
                };
            }
            WindowStatus {
                found: false,
                focused: false,
                title: None,
                supported: true,
            }
        }
    }

    /// Send one key event. Scan codes are used because that is what games read.
    pub fn send_key(vk: u16, up: bool, extended: bool) {
        unsafe {
            let scan = MapVirtualKeyW(vk as u32, MAPVK_VK_TO_VSC) as u16;
            let mut flags = KEYEVENTF_SCANCODE;
            if up {
                flags |= KEYEVENTF_KEYUP;
            }
            if extended {
                flags |= KEYEVENTF_EXTENDEDKEY;
            }
            let mut input = INPUT {
                r#type: INPUT_KEYBOARD,
                Anonymous: std::mem::zeroed(),
            };
            input.Anonymous.ki = KEYBDINPUT {
                wVk: 0,
                wScan: scan,
                dwFlags: flags,
                time: 0,
                dwExtraInfo: 0,
            };
            SendInput(1, &input, std::mem::size_of::<INPUT>() as i32);
        }
    }
}

#[cfg(not(windows))]
mod imp {
    use super::WindowStatus;

    pub fn status() -> WindowStatus {
        WindowStatus {
            found: false,
            focused: false,
            title: None,
            supported: false,
        }
    }

    pub fn send_key(_vk: u16, _up: bool, _extended: bool) {}
}

pub fn window_status() -> WindowStatus {
    imp::status()
}

/// Virtual-key code for a binding name, or None if the name is unknown.
pub fn virtual_key(name: &str) -> Option<(u16, bool)> {
    let lower = name.to_ascii_lowercase();
    let extended = matches!(lower.as_str(), "left" | "right" | "up" | "down");
    let code = match lower.as_str() {
        "0" => 0x30,
        "1" => 0x31,
        "2" => 0x32,
        "3" => 0x33,
        "4" => 0x34,
        "5" => 0x35,
        "6" => 0x36,
        "7" => 0x37,
        "8" => 0x38,
        "9" => 0x39,
        "left" => 0x25,
        "up" => 0x26,
        "right" => 0x27,
        "down" => 0x28,
        "space" => 0x20,
        "tab" => 0x09,
        "escape" | "esc" => 0x1B,
        "enter" | "return" => 0x0D,
        "shift" => 0x10,
        "ctrl" | "control" => 0x11,
        "alt" => 0x12,
        other if other.len() == 1 && other.chars().all(|c| c.is_ascii_lowercase()) => {
            0x41 + (other.as_bytes()[0] - b'a') as u16
        }
        _ => return None,
    };
    Some((code, extended))
}

/// Keys currently held by us, so a stop can release exactly those.
static HELD: Mutex<Vec<(u16, bool)>> = Mutex::new(Vec::new());

pub fn key_down(name: &str) -> bool {
    let Some((vk, extended)) = virtual_key(name) else {
        return false;
    };
    imp::send_key(vk, false, extended);
    let mut held = HELD.lock().unwrap();
    if !held.iter().any(|(v, _)| *v == vk) {
        held.push((vk, extended));
    }
    true
}

pub fn key_up(name: &str) -> bool {
    let Some((vk, extended)) = virtual_key(name) else {
        return false;
    };
    imp::send_key(vk, true, extended);
    HELD.lock().unwrap().retain(|(v, _)| *v != vk);
    true
}

/// Release everything we are holding. Called on stop, focus loss and shutdown.
pub fn release_all() {
    let held: Vec<(u16, bool)> = { HELD.lock().unwrap().drain(..).collect() };
    for (vk, extended) in held.into_iter().rev() {
        imp::send_key(vk, true, extended);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn known_bindings_resolve_to_virtual_keys() {
        for name in ["1", "2", "3", "left", "down", "right", "space", "tab", "escape", "n", "l", "m"] {
            assert!(virtual_key(name).is_some(), "unknown binding: {name}");
        }
    }

    #[test]
    fn arrow_keys_are_extended() {
        assert!(virtual_key("left").unwrap().1);
        assert!(virtual_key("down").unwrap().1);
        assert!(!virtual_key("1").unwrap().1);
    }

    #[test]
    fn letters_map_to_their_virtual_key() {
        assert_eq!(virtual_key("a").unwrap().0, 0x41);
        assert_eq!(virtual_key("z").unwrap().0, 0x5A);
    }

    #[test]
    fn unknown_bindings_are_rejected() {
        assert!(virtual_key("").is_none());
        assert!(virtual_key("mouse4").is_none());
        assert!(virtual_key("f13").is_none());
    }

    #[test]
    fn window_status_is_always_answerable() {
        let status = window_status();
        // On a machine without Warframe this must report cleanly, not panic.
        assert!(!status.found || status.title.is_some());
    }

    #[test]
    fn playing_flag_round_trips() {
        set_playing(true);
        assert!(is_playing());
        set_playing(false);
        assert!(!is_playing());
    }
}
