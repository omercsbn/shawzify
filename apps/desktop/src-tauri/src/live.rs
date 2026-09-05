//! Live performance scheduling in Rust.
//!
//! The scheduler lives here rather than in Python because key timing is the one
//! thing that must not be at the mercy of the GIL or IPC latency. It works from
//! absolute target instants against a monotonic clock, so error never
//! accumulates, and it re-checks Warframe's focus before every event.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};

use crate::warframe;

#[derive(Debug, Clone, Deserialize)]
pub struct LiveEvent {
    /// Seconds from the start of the performance.
    pub at: f64,
    /// Fret state: "0", "1", "2", "3", "12", "13", "23" or "123".
    pub fret: String,
    /// Strings to pluck, e.g. "1" or "123".
    pub string: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct LiveBindings {
    pub string1: String,
    pub string2: String,
    pub string3: String,
    pub fret1: String,
    pub fret2: String,
    pub fret3: String,
}

impl Default for LiveBindings {
    fn default() -> Self {
        Self {
            string1: "1".into(),
            string2: "2".into(),
            string3: "3".into(),
            fret1: "left".into(),
            fret2: "down".into(),
            fret3: "right".into(),
        }
    }
}

impl LiveBindings {
    fn string_key(&self, ch: char) -> Option<&str> {
        match ch {
            '1' => Some(&self.string1),
            '2' => Some(&self.string2),
            '3' => Some(&self.string3),
            _ => None,
        }
    }

    fn fret_keys(&self, fret: &str) -> Vec<&str> {
        if fret == "0" {
            return Vec::new();
        }
        fret.chars()
            .filter_map(|c| match c {
                '1' => Some(self.fret1.as_str()),
                '2' => Some(self.fret2.as_str()),
                '3' => Some(self.fret3.as_str()),
                _ => None,
            })
            .collect()
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct LiveTiming {
    #[serde(default)]
    pub playback_offset_ms: f64,
    #[serde(default = "default_fret_gap")]
    pub fret_to_string_ms: f64,
    #[serde(default = "default_string_gap")]
    pub inter_string_ms: f64,
    #[serde(default = "default_hold")]
    pub key_hold_ms: f64,
}

fn default_fret_gap() -> f64 {
    12.0
}
fn default_string_gap() -> f64 {
    4.0
}
fn default_hold() -> f64 {
    14.0
}

impl Default for LiveTiming {
    fn default() -> Self {
        Self {
            playback_offset_ms: 0.0,
            fret_to_string_ms: default_fret_gap(),
            inter_string_ms: default_string_gap(),
            key_hold_ms: default_hold(),
        }
    }
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct LiveStats {
    pub fired: usize,
    pub total: usize,
    pub mean_error_ms: f64,
    pub max_error_ms: f64,
    pub stopped_early: bool,
    pub stop_reason: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct LiveTick {
    pub index: usize,
    pub total: usize,
    pub position_seconds: f64,
    pub fret: String,
    pub string: String,
}

/// A running performance. Dropping or stopping it releases every held key.
pub struct LiveSession {
    stop: Arc<AtomicBool>,
}

impl LiveSession {
    pub fn stop(&self) {
        self.stop.store(true, Ordering::SeqCst);
    }
}

/// Sleep until `target`, coarsely at first and then spinning the last 1.5 ms.
///
/// Windows' default timer granularity is around 15 ms, which is far too coarse
/// for musical timing; the spin absorbs that without burning a whole core.
fn wait_until(start: Instant, target: Duration, stop: &AtomicBool) -> bool {
    const SPIN_MARGIN: Duration = Duration::from_micros(1500);
    loop {
        if stop.load(Ordering::SeqCst) {
            return false;
        }
        let elapsed = start.elapsed();
        if elapsed >= target {
            return true;
        }
        let remaining = target - elapsed;
        if remaining > SPIN_MARGIN {
            // Cap each sleep so a stop request is noticed promptly.
            thread::sleep(std::cmp::min(remaining - SPIN_MARGIN, Duration::from_millis(20)));
        } else {
            std::hint::spin_loop();
        }
    }
}

/// Run a performance on a background thread.
///
/// `on_tick` is called for each event and `on_finish` once at the end, both from
/// the worker thread.
pub fn play<T, F>(
    events: Vec<LiveEvent>,
    bindings: LiveBindings,
    timing: LiveTiming,
    require_focus: bool,
    on_tick: T,
    on_finish: F,
) -> LiveSession
where
    T: Fn(LiveTick) + Send + 'static,
    F: FnOnce(LiveStats) + Send + 'static,
{
    let stop = Arc::new(AtomicBool::new(false));
    let worker_stop = Arc::clone(&stop);

    thread::spawn(move || {
        warframe::set_playing(true);
        let mut stats = LiveStats {
            total: events.len(),
            ..Default::default()
        };
        let mut errors: Vec<f64> = Vec::with_capacity(events.len());
        let mut held: Vec<String> = Vec::new();

        let offset = timing.playback_offset_ms / 1000.0;
        let start = Instant::now();

        for (index, event) in events.iter().enumerate() {
            if worker_stop.load(Ordering::SeqCst) {
                stats.stopped_early = true;
                stats.stop_reason = Some("Stopped".into());
                break;
            }
            if require_focus && !warframe::window_status().focused {
                stats.stopped_early = true;
                stats.stop_reason =
                    Some("Warframe is no longer the active window.".into());
                break;
            }

            let target = event.at + offset;
            if target < 0.0 {
                continue;
            }
            if !wait_until(start, Duration::from_secs_f64(target), &worker_stop) {
                stats.stopped_early = true;
                stats.stop_reason = Some("Stopped".into());
                break;
            }

            let actual = start.elapsed().as_secs_f64();
            errors.push((actual - target).abs() * 1000.0);

            // Change the fret only when it differs: a run of notes on one fret
            // should hold it, exactly as a player would.
            let wanted: Vec<String> = bindings
                .fret_keys(&event.fret)
                .into_iter()
                .map(str::to_string)
                .collect();
            if wanted != held {
                for key in held.iter().rev() {
                    warframe::key_up(key);
                }
                held.clear();
                for key in &wanted {
                    warframe::key_down(key);
                    held.push(key.clone());
                }
                if !held.is_empty() && timing.fret_to_string_ms > 0.0 {
                    thread::sleep(Duration::from_secs_f64(timing.fret_to_string_ms / 1000.0));
                }
            }

            let keys: Vec<String> = event
                .string
                .chars()
                .filter_map(|c| bindings.string_key(c).map(str::to_string))
                .collect();
            for (i, key) in keys.iter().enumerate() {
                warframe::key_down(key);
                if i + 1 < keys.len() && timing.inter_string_ms > 0.0 {
                    thread::sleep(Duration::from_secs_f64(timing.inter_string_ms / 1000.0));
                }
            }
            if timing.key_hold_ms > 0.0 {
                thread::sleep(Duration::from_secs_f64(timing.key_hold_ms / 1000.0));
            }
            for key in &keys {
                warframe::key_up(key);
            }

            stats.fired += 1;
            on_tick(LiveTick {
                index,
                total: events.len(),
                position_seconds: actual,
                fret: event.fret.clone(),
                string: event.string.clone(),
            });
        }

        warframe::release_all();
        warframe::set_playing(false);
        if !errors.is_empty() {
            stats.mean_error_ms = errors.iter().sum::<f64>() / errors.len() as f64;
            stats.max_error_ms = errors.iter().cloned().fold(0.0, f64::max);
        }
        on_finish(stats);
    });

    LiveSession { stop }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::AtomicUsize;

    #[test]
    fn default_bindings_map_frets_and_strings() {
        let b = LiveBindings::default();
        assert_eq!(b.fret_keys("0").len(), 0);
        assert_eq!(b.fret_keys("1"), vec!["left"]);
        assert_eq!(b.fret_keys("123"), vec!["left", "down", "right"]);
        assert_eq!(b.string_key('2'), Some("2"));
        assert_eq!(b.string_key('9'), None);
    }

    #[test]
    fn wait_until_respects_a_stop_request() {
        let stop = AtomicBool::new(false);
        let start = Instant::now();
        stop.store(true, Ordering::SeqCst);
        assert!(!wait_until(start, Duration::from_secs(10), &stop));
        assert!(start.elapsed() < Duration::from_millis(200));
    }

    #[test]
    fn wait_until_is_accurate() {
        let stop = AtomicBool::new(false);
        let start = Instant::now();
        assert!(wait_until(start, Duration::from_millis(50), &stop));
        let elapsed = start.elapsed().as_secs_f64();
        assert!(elapsed >= 0.049, "returned too early: {elapsed}");
        assert!(elapsed < 0.085, "returned too late: {elapsed}");
    }

    #[test]
    fn scheduler_does_not_accumulate_drift() {
        // 40 events at 25 ms spacing. Without focus checking and with no real
        // key output on non-Windows, this measures the scheduler itself.
        let events: Vec<LiveEvent> = (0..40)
            .map(|i| LiveEvent {
                at: i as f64 * 0.025,
                fret: "0".into(),
                string: "1".into(),
            })
            .collect();
        let counter = Arc::new(AtomicUsize::new(0));
        let seen = Arc::clone(&counter);
        let (tx, rx) = std::sync::mpsc::channel();

        let timing = LiveTiming {
            playback_offset_ms: 0.0,
            fret_to_string_ms: 0.0,
            inter_string_ms: 0.0,
            key_hold_ms: 0.0,
        };
        let _session = play(
            events,
            LiveBindings::default(),
            timing,
            false,
            move |_tick| {
                seen.fetch_add(1, Ordering::SeqCst);
            },
            move |stats| {
                let _ = tx.send(stats);
            },
        );

        let stats = rx
            .recv_timeout(Duration::from_secs(10))
            .expect("performance did not finish");
        assert_eq!(stats.fired, 40);
        assert_eq!(counter.load(Ordering::SeqCst), 40);
        assert!(!stats.stopped_early);
        // The last event is a full second in; drift must not have piled up.
        assert!(stats.max_error_ms < 25.0, "max error {}", stats.max_error_ms);
        assert!(stats.mean_error_ms < 8.0, "mean error {}", stats.mean_error_ms);
    }

    #[test]
    fn stopping_ends_the_performance_early() {
        let events: Vec<LiveEvent> = (0..200)
            .map(|i| LiveEvent {
                at: i as f64 * 0.05,
                fret: "0".into(),
                string: "1".into(),
            })
            .collect();
        let (tx, rx) = std::sync::mpsc::channel();
        let session = play(
            events,
            LiveBindings::default(),
            LiveTiming::default(),
            false,
            |_t| {},
            move |stats| {
                let _ = tx.send(stats);
            },
        );
        thread::sleep(Duration::from_millis(120));
        session.stop();
        let stats = rx
            .recv_timeout(Duration::from_secs(5))
            .expect("performance did not stop");
        assert!(stats.stopped_early);
        assert!(stats.fired < 200);
    }
}
