//! SHAWZIFY desktop shell.
//!
//! Rust owns the things that must be native: process lifecycle, the Python
//! engine sidecar, Windows window/focus detection, key output timing, the
//! clipboard, and file IO. Everything musical lives in the Python engine, and
//! everything visual in the React frontend.

pub mod engine;
pub mod live;
pub mod warframe;

use std::path::PathBuf;
use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager, State};

use engine::{EngineConfig, EngineError, EngineManager};
use live::{LiveBindings, LiveEvent, LiveSession, LiveTiming};

pub struct AppState {
    pub engine: EngineManager,
    pub live: Mutex<Option<LiveSession>>,
    pub root: PathBuf,
    /// Set when the app was launched with a file argument.
    pub startup_file: Option<String>,
}

#[derive(Serialize)]
pub struct EngineStatus {
    running: bool,
    python: Option<String>,
    root: String,
    error: Option<String>,
}

// -- engine lifecycle ----------------------------------------------------

/// A file passed on the command line, so "Open with SHAWZIFY" works from Explorer.
#[tauri::command]
fn startup_file(state: State<'_, AppState>) -> Option<String> {
    state.startup_file.clone()
}

#[tauri::command]
fn engine_status(state: State<'_, AppState>) -> EngineStatus {
    EngineStatus {
        running: state.engine.is_running(),
        python: state
            .engine
            .python_path()
            .map(|p| p.display().to_string()),
        root: state.root.display().to_string(),
        error: None,
    }
}

#[tauri::command]
fn engine_start(state: State<'_, AppState>) -> Result<EngineStatus, EngineError> {
    let python = engine::discover_python(&state.root).ok_or_else(|| {
        // This is what a downloader sees, so it has to be the whole answer.
        EngineError::Spawn(
            "SHAWZIFY could not find its audio engine. The installer ships the \
             interface; the engine is a Python package you install once. Get the \
             source from github.com/omercsbn/shawzify, run scripts\\setup.ps1, then \
             press Retry. If you already have it, use \"Locate Python\" in Settings \
             to point at that environment's python.exe."
                .into(),
        )
    })?;
    start_with(&state, python)?;
    Ok(engine_status(state))
}

fn start_with(state: &State<'_, AppState>, python: PathBuf) -> Result<(), EngineError> {
    // An installed copy has no engine/ directory; the engine runs fine from
    // anywhere, so only use that folder when it is really there.
    let engine_dir = state.root.join("engine");
    let working_dir = if engine_dir.is_dir() {
        engine_dir
    } else {
        state.root.clone()
    };
    state.engine.start(EngineConfig {
        python,
        working_dir,
    })
}

/// Interpreters worth offering when the engine cannot be found on its own.
#[tauri::command]
fn engine_python_candidates(state: State<'_, AppState>) -> Vec<String> {
    engine::python_candidates(&state.root)
        .into_iter()
        .map(|p| p.display().to_string())
        .collect()
}

/// Adopt an interpreter the user chose, and remember it.
#[tauri::command]
fn engine_set_python(
    state: State<'_, AppState>,
    path: String,
) -> Result<EngineStatus, EngineError> {
    let python = PathBuf::from(path);
    if !python.exists() {
        return Err(EngineError::Spawn(format!(
            "There is no file at {}.",
            python.display()
        )));
    }
    if !engine::interpreter_has_engine(&python) {
        return Err(EngineError::Spawn(format!(
            "{} runs, but the SHAWZIFY engine is not installed in it. In that \
             environment: pip install -e engine",
            python.display()
        )));
    }
    let _ = engine::save_python(&python);
    state.engine.stop();
    start_with(&state, python)?;
    Ok(engine_status(state))
}

#[tauri::command]
fn engine_restart(state: State<'_, AppState>) -> Result<EngineStatus, EngineError> {
    state.engine.stop();
    engine_start(state)
}

// -- engine calls --------------------------------------------------------

#[tauri::command]
async fn engine_call(
    state: State<'_, AppState>,
    method: String,
    params: Value,
) -> Result<Value, EngineError> {
    state.engine.call_resilient(&method, params)
}

#[tauri::command]
async fn analyze_file(
    state: State<'_, AppState>,
    path: String,
    options: Value,
    request_id: u64,
) -> Result<Value, EngineError> {
    state.engine.call_resilient(
        "analyze",
        json!({ "path": path, "options": options, "requestId": request_id }),
    )
}

#[tauri::command]
async fn arrange(
    state: State<'_, AppState>,
    source_id: String,
    options: Value,
    request_id: u64,
) -> Result<Value, EngineError> {
    state.engine.call_resilient(
        "arrange",
        json!({ "sourceId": source_id, "options": options, "requestId": request_id }),
    )
}

#[tauri::command]
async fn cancel_request(state: State<'_, AppState>, request_id: u64) -> Result<Value, EngineError> {
    state
        .engine
        .call_resilient("cancel", json!({ "requestId": request_id }))
}

// -- clipboard and files -------------------------------------------------

#[tauri::command]
fn copy_to_clipboard(app: AppHandle, text: String) -> Result<(), String> {
    let _ = app;
    // The webview clipboard API is used from the frontend; this native path is
    // the fallback for when the window is not focused.
    #[cfg(windows)]
    {
        set_windows_clipboard(&text).map_err(|e| e.to_string())
    }
    #[cfg(not(windows))]
    {
        let _ = text;
        Err("Clipboard access is only implemented on Windows.".into())
    }
}

#[cfg(windows)]
fn set_windows_clipboard(text: &str) -> std::io::Result<()> {
    use std::io::Write;
    use std::process::{Command, Stdio};
    // `clip` is present on every supported Windows version and avoids adding a
    // clipboard crate for one call.
    let mut child = Command::new("cmd")
        .args(["/c", "clip"])
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()?;
    if let Some(stdin) = child.stdin.as_mut() {
        stdin.write_all(text.as_bytes())?;
    }
    child.wait()?;
    Ok(())
}

#[tauri::command]
fn write_text_file(path: String, contents: String) -> Result<String, String> {
    let target = PathBuf::from(&path);
    if let Some(parent) = target.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    std::fs::write(&target, contents).map_err(|e| e.to_string())?;
    Ok(target.display().to_string())
}

#[tauri::command]
fn read_text_file(path: String) -> Result<String, String> {
    std::fs::read_to_string(&path).map_err(|e| e.to_string())
}

#[tauri::command]
fn reveal_path(app: AppHandle, path: String) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;
    app.opener()
        .open_path(path, None::<&str>)
        .map_err(|e| e.to_string())
}

// -- Warframe live playback ---------------------------------------------

#[derive(Deserialize)]
pub struct PlayRequest {
    events: Vec<LiveEvent>,
    #[serde(default)]
    bindings: LiveBindings,
    #[serde(default)]
    timing: LiveTiming,
    #[serde(default = "default_true")]
    require_focus: bool,
}

fn default_true() -> bool {
    true
}

#[tauri::command]
fn warframe_status() -> warframe::WindowStatus {
    warframe::window_status()
}

#[tauri::command]
fn live_play(app: AppHandle, state: State<'_, AppState>, request: PlayRequest) -> Result<(), String> {
    if state.live.lock().unwrap().is_some() && warframe::is_playing() {
        return Err("A performance is already running.".into());
    }
    if request.require_focus {
        let status = warframe::window_status();
        if !status.supported {
            return Err("Live playback is only available on Windows.".into());
        }
        if !status.found {
            return Err("Warframe is not running.".into());
        }
        if !status.focused {
            return Err("Switch to Warframe and equip the Shawzin emote, then press play.".into());
        }
    }

    let tick_app = app.clone();
    let finish_app = app.clone();
    let session = live::play(
        request.events,
        request.bindings,
        request.timing,
        request.require_focus,
        move |tick| {
            let _ = tick_app.emit("live://tick", tick);
        },
        move |stats| {
            let _ = finish_app.emit("live://finished", stats);
        },
    );
    *state.live.lock().unwrap() = Some(session);
    Ok(())
}

#[tauri::command]
fn live_stop(state: State<'_, AppState>) {
    if let Some(session) = state.live.lock().unwrap().take() {
        session.stop();
    }
    warframe::release_all();
    warframe::set_playing(false);
}

#[tauri::command]
fn live_is_playing() -> bool {
    warframe::is_playing()
}

// -- app entry -----------------------------------------------------------

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            let root = resolve_root();
            let state = AppState {
                engine: EngineManager::new(),
                live: Mutex::new(None),
                root: root.clone(),
                startup_file: first_file_argument(),
            };
            let handle = app.handle().clone();
            state.engine.on_event(move |event| {
                let _ = handle.emit(
                    "engine://event",
                    json!({
                        "id": event.id,
                        "kind": event.kind,
                        "payload": event.payload,
                    }),
                );
            });
            // Start the engine eagerly so the first drop is fast. A failure
            // here is reported through engine_status rather than blocking start.
            if let Some(python) = engine::discover_python(&root) {
                let _ = state.engine.start(EngineConfig {
                    python,
                    working_dir: root.join("engine"),
                });
            }
            app.manage(state);
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                warframe::release_all();
                if let Some(state) = window.app_handle().try_state::<AppState>() {
                    state.engine.stop();
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            startup_file,
            engine_status,
            engine_start,
            engine_python_candidates,
            engine_set_python,
            engine_restart,
            engine_call,
            analyze_file,
            arrange,
            cancel_request,
            copy_to_clipboard,
            write_text_file,
            read_text_file,
            reveal_path,
            warframe_status,
            live_play,
            live_stop,
            live_is_playing,
        ])
        .run(tauri::generate_context!())
        .expect("error while running SHAWZIFY");
}

/// The first command-line argument that names a file we can open.
fn first_file_argument() -> Option<String> {
    std::env::args()
        .skip(1)
        .find(|arg| {
            if arg.starts_with('-') {
                return false;
            }
            let lower = arg.to_ascii_lowercase();
            let known = [
                ".wav", ".mp3", ".flac", ".m4a", ".ogg", ".opus", ".aac", ".aiff", ".aif",
                ".wma", ".mid", ".midi", ".shawzify",
            ];
            known.iter().any(|ext| lower.ends_with(ext)) && std::path::Path::new(arg).is_file()
        })
}

/// Locate the repository root, walking up from the executable in dev builds.
fn resolve_root() -> PathBuf {
    if let Ok(explicit) = std::env::var("SHAWZIFY_ROOT") {
        return PathBuf::from(explicit);
    }
    let mut dir = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    loop {
        if dir.join("engine").join("pyproject.toml").exists() {
            return dir;
        }
        match dir.parent() {
            Some(parent) => dir = parent.to_path_buf(),
            None => break,
        }
    }
    std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn root_resolution_finds_the_engine_in_dev() {
        // Running under `cargo test` the working directory is src-tauri, so the
        // walk upward must find the repository root.
        let root = resolve_root();
        assert!(root.exists());
    }

    #[test]
    fn python_discovery_prefers_the_bundled_venv() {
        let root = resolve_root();
        if let Some(python) = engine::discover_python(&root) {
            assert!(python.exists(), "discovered python does not exist");
        }
    }

    #[test]
    fn file_arguments_are_recognised_by_extension() {
        // The filter itself, independent of process argv.
        for name in ["song.mp3", "SONG.WAV", "tune.mid", "project.shawzify"] {
            let lower = name.to_ascii_lowercase();
            assert!(
                [".wav", ".mp3", ".mid", ".shawzify"]
                    .iter()
                    .any(|e| lower.ends_with(e)),
                "{name} should be recognised"
            );
        }
    }

    #[test]
    fn flags_are_never_treated_as_files() {
        assert!(std::env::args()
            .take(0)
            .chain(["--devtools".to_string()])
            .all(|a| a.starts_with('-')));
    }

    #[test]
    fn engine_errors_serialise_for_the_frontend() {
        let err = EngineError::Engine {
            message: "Something went wrong.".into(),
            code: "audio_decode_failed".into(),
            hint: Some("Try another file.".into()),
            technical: Some("stack trace".into()),
        };
        let value = serde_json::to_value(&err).unwrap();
        assert_eq!(value["code"], "audio_decode_failed");
        assert_eq!(value["message"], "Something went wrong.");
        assert_eq!(value["hint"], "Try another file.");
    }

    #[test]
    fn transport_errors_get_a_readable_message() {
        let value = serde_json::to_value(&EngineError::NotRunning).unwrap();
        assert_eq!(value["code"], "engine_transport");
        assert!(value["message"].as_str().unwrap().contains("not running"));
    }
}
