//! Managing the Python engine sidecar.
//!
//! The engine runs as a child process speaking newline-delimited JSON over
//! stdin/stdout. Nothing is bound to a network socket, so there is no port for
//! anything outside this machine to reach, and no auth problem to get wrong.
//!
//! Requests carry an id; responses and progress events carry it back, so the
//! frontend can run several operations and cancel one without touching others.

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{channel, Sender};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// How long a single engine call may take before we give up on it.
const CALL_TIMEOUT: Duration = Duration::from_secs(900);

#[derive(Debug, thiserror::Error)]
pub enum EngineError {
    #[error("The SHAWZIFY audio engine is not running.")]
    NotRunning,
    #[error("The SHAWZIFY audio engine could not be started: {0}")]
    Spawn(String),
    #[error("The SHAWZIFY audio engine stopped responding.")]
    Disconnected,
    #[error("The SHAWZIFY audio engine took too long and was cancelled.")]
    Timeout,
    #[error("{message}")]
    Engine {
        message: String,
        code: String,
        hint: Option<String>,
        technical: Option<String>,
    },
    #[error("{0}")]
    Protocol(String),
}

impl serde::Serialize for EngineError {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let value = match self {
            EngineError::Engine {
                message,
                code,
                hint,
                technical,
            } => json!({
                "code": code,
                "message": message,
                "hint": hint,
                "technical": technical,
            }),
            other => json!({
                "code": "engine_transport",
                "message": other.to_string(),
                "hint": Option::<String>::None,
                "technical": Option::<String>::None,
            }),
        };
        value.serialize(serializer)
    }
}

/// A progress or log line pushed by the engine, forwarded to the frontend.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EngineEvent {
    pub id: u64,
    pub kind: String,
    #[serde(default)]
    pub payload: Value,
}

type Pending = Arc<Mutex<HashMap<u64, Sender<Result<Value, EngineError>>>>>;
type EventSink = Arc<Mutex<Option<Box<dyn Fn(EngineEvent) + Send + 'static>>>>;

pub struct EngineHandle {
    child: Child,
    stdin: ChildStdin,
    pending: Pending,
    next_id: u64,
    pub python: PathBuf,
}

pub struct EngineManager {
    inner: Mutex<Option<EngineHandle>>,
    /// Set once at startup; used to respawn after a crash.
    config: Mutex<Option<EngineConfig>>,
    events: EventSink,
}

#[derive(Clone, Debug)]
pub struct EngineConfig {
    pub python: PathBuf,
    pub working_dir: PathBuf,
}

impl EngineManager {
    pub fn new() -> Self {
        Self {
            inner: Mutex::new(None),
            config: Mutex::new(None),
            events: Arc::new(Mutex::new(None)),
        }
    }

    pub fn on_event<F: Fn(EngineEvent) + Send + 'static>(&self, f: F) {
        *self.events.lock().unwrap() = Some(Box::new(f));
    }

    pub fn is_running(&self) -> bool {
        self.inner.lock().unwrap().is_some()
    }

    pub fn python_path(&self) -> Option<PathBuf> {
        self.inner.lock().unwrap().as_ref().map(|h| h.python.clone())
    }

    /// Start the engine, replacing any existing one.
    pub fn start(&self, config: EngineConfig) -> Result<(), EngineError> {
        self.stop();
        let handle = spawn_engine(&config, Arc::clone(&self.events))?;
        *self.config.lock().unwrap() = Some(config);
        *self.inner.lock().unwrap() = Some(handle);
        Ok(())
    }

    pub fn stop(&self) {
        if let Some(mut handle) = self.inner.lock().unwrap().take() {
            let _ = handle.stdin.write_all(b"{\"method\":\"shutdown\",\"id\":0}\n");
            let _ = handle.stdin.flush();
            std::thread::sleep(Duration::from_millis(120));
            let _ = handle.child.kill();
            let _ = handle.child.wait();
        }
    }

    /// Send a request and block until the engine answers.
    pub fn call(&self, method: &str, params: Value) -> Result<Value, EngineError> {
        let (tx, rx) = channel();
        let id = {
            let mut guard = self.inner.lock().unwrap();
            let handle = guard.as_mut().ok_or(EngineError::NotRunning)?;
            handle.next_id += 1;
            let id = handle.next_id;
            handle.pending.lock().unwrap().insert(id, tx);
            let request = json!({ "id": id, "method": method, "params": params });
            let line = serde_json::to_string(&request)
                .map_err(|e| EngineError::Protocol(e.to_string()))?;
            handle
                .stdin
                .write_all(line.as_bytes())
                .and_then(|_| handle.stdin.write_all(b"\n"))
                .and_then(|_| handle.stdin.flush())
                .map_err(|_| EngineError::Disconnected)?;
            id
        };

        match rx.recv_timeout(CALL_TIMEOUT) {
            Ok(result) => result,
            Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {
                self.forget(id);
                Err(EngineError::Timeout)
            }
            Err(_) => {
                self.forget(id);
                Err(EngineError::Disconnected)
            }
        }
    }

    fn forget(&self, id: u64) {
        if let Some(handle) = self.inner.lock().unwrap().as_ref() {
            handle.pending.lock().unwrap().remove(&id);
        }
    }

    /// Call, restarting the engine once if it has died.
    pub fn call_resilient(&self, method: &str, params: Value) -> Result<Value, EngineError> {
        match self.call(method, params.clone()) {
            Err(EngineError::NotRunning) | Err(EngineError::Disconnected) => {
                let config = self.config.lock().unwrap().clone();
                match config {
                    Some(config) => {
                        self.start(config)?;
                        self.call(method, params)
                    }
                    None => Err(EngineError::NotRunning),
                }
            }
            other => other,
        }
    }
}

impl Default for EngineManager {
    fn default() -> Self {
        Self::new()
    }
}

fn spawn_engine(config: &EngineConfig, events: EventSink) -> Result<EngineHandle, EngineError> {
    let mut command = Command::new(&config.python);
    command
        .arg("-u") // unbuffered, so progress arrives while work is happening
        .arg("-m")
        .arg("shawzify_engine.server")
        .current_dir(&config.working_dir)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);

    let mut child = command
        .spawn()
        .map_err(|e| EngineError::Spawn(format!("{} ({})", e, config.python.display())))?;

    let stdin = child.stdin.take().ok_or(EngineError::Disconnected)?;
    let stdout = child.stdout.take().ok_or(EngineError::Disconnected)?;
    let stderr = child.stderr.take();

    let pending: Pending = Arc::new(Mutex::new(HashMap::new()));
    let reader_pending = Arc::clone(&pending);

    std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines() {
            let Ok(line) = line else { break };
            if line.trim().is_empty() {
                continue;
            }
            let Ok(value) = serde_json::from_str::<Value>(&line) else {
                continue;
            };
            let id = value.get("id").and_then(Value::as_u64).unwrap_or(0);
            let kind = value
                .get("type")
                .and_then(Value::as_str)
                .unwrap_or("result")
                .to_string();

            if kind == "event" {
                let event = EngineEvent {
                    id,
                    kind: value
                        .get("event")
                        .and_then(Value::as_str)
                        .unwrap_or("progress")
                        .to_string(),
                    payload: value.get("payload").cloned().unwrap_or(Value::Null),
                };
                if let Ok(guard) = events.lock() {
                    if let Some(sink) = guard.as_ref() {
                        sink(event);
                    }
                }
                continue;
            }

            let sender = reader_pending.lock().unwrap().remove(&id);
            if let Some(sender) = sender {
                let outcome = if let Some(error) = value.get("error") {
                    Err(EngineError::Engine {
                        message: error
                            .get("message")
                            .and_then(Value::as_str)
                            .unwrap_or("The audio engine reported an error.")
                            .to_string(),
                        code: error
                            .get("code")
                            .and_then(Value::as_str)
                            .unwrap_or("engine_error")
                            .to_string(),
                        hint: error
                            .get("hint")
                            .and_then(Value::as_str)
                            .map(str::to_string),
                        technical: error
                            .get("technical")
                            .and_then(Value::as_str)
                            .map(str::to_string),
                    })
                } else {
                    Ok(value.get("result").cloned().unwrap_or(Value::Null))
                };
                let _ = sender.send(outcome);
            }
        }
        // The engine died: fail everything still waiting instead of hanging.
        let mut guard = reader_pending.lock().unwrap();
        for (_, sender) in guard.drain() {
            let _ = sender.send(Err(EngineError::Disconnected));
        }
    });

    if let Some(stderr) = stderr {
        std::thread::spawn(move || {
            let reader = BufReader::new(stderr);
            for line in reader.lines().map_while(Result::ok) {
                if !line.trim().is_empty() {
                    eprintln!("[engine] {line}");
                }
            }
        });
    }

    Ok(EngineHandle {
        child,
        stdin,
        pending,
        next_id: 0,
        python: config.python.clone(),
    })
}

/// Find the Python interpreter that has the engine installed.
///
/// The bundled venv is tried first so a normal install never depends on what
/// happens to be on PATH; `SHAWZIFY_PYTHON` overrides everything for developers.
pub fn discover_python(project_root: &Path) -> Option<PathBuf> {
    if let Ok(explicit) = std::env::var("SHAWZIFY_PYTHON") {
        let path = PathBuf::from(explicit);
        if path.exists() {
            return Some(path);
        }
    }
    let venv = if cfg!(windows) {
        "engine/.venv/Scripts/python.exe"
    } else {
        "engine/.venv/bin/python"
    };
    let mut dir = Some(project_root.to_path_buf());
    while let Some(current) = dir {
        let candidate = current.join(venv);
        if candidate.exists() {
            return Some(candidate);
        }
        dir = current.parent().map(Path::to_path_buf);
    }
    for name in ["python3", "python", "py"] {
        if let Ok(found) = which(name) {
            return Some(found);
        }
    }
    None
}

fn which(name: &str) -> Result<PathBuf, ()> {
    let paths = std::env::var_os("PATH").ok_or(())?;
    let exts: Vec<String> = if cfg!(windows) {
        std::env::var("PATHEXT")
            .unwrap_or_else(|_| ".EXE;.CMD;.BAT".into())
            .split(';')
            .map(|s| s.to_lowercase())
            .collect()
    } else {
        vec![String::new()]
    };
    for dir in std::env::split_paths(&paths) {
        for ext in &exts {
            let candidate = dir.join(format!("{name}{ext}"));
            if candidate.is_file() {
                return Ok(candidate);
            }
        }
    }
    Err(())
}

/// Where the repository (and therefore the engine) lives, in dev and when bundled.
pub fn project_root() -> PathBuf {
    if let Ok(explicit) = std::env::var("SHAWZIFY_ROOT") {
        return PathBuf::from(explicit);
    }
    std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(Path::to_path_buf))
        .unwrap_or_else(|| PathBuf::from("."))
}
