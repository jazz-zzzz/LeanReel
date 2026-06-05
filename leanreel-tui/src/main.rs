mod app;
mod ui;
mod overlays;

use app::App;
use crossterm::{
    event::{self, Event},
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use ratatui::backend::CrosstermBackend;
use ratatui::Terminal;
use std::io;
use std::sync::Arc;

#[tokio::main]
async fn main() -> io::Result<()> {
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    let app_state = leanreel_core::create_app_state()
        .map_err(|e| io::Error::new(io::ErrorKind::Other, e))?;
    let app_state = Arc::new(app_state);

    // Load strategies from disk
    if let Ok(strategies) = leanreel_core::api::strategy::load_strategies_from_disk() {
        if !strategies.is_empty() {
            if let Ok(mut matcher) = app_state.matcher.lock() {
                *matcher = leanreel_core::services::matcher::StrategyMatcher::new(strategies);
            }
        }
    }

    // Load ffprobe/ffmpeg paths from config
    if let Ok(store) = app_state.store.lock() {
        app_state.prober.load_from_config(&store);
        app_state.ffmpeg.load_from_config(&store);
    }

    let (event_tx, event_rx) = tokio::sync::mpsc::unbounded_channel();

    // Wire scanner progress
    let tx = event_tx.clone();
    if let Ok(mut scanner) = app_state.scanner.lock() {
        scanner.on_progress = Some(Box::new(move |done, total| {
            let _ = tx.send(AppEvent::ScanProgress { done, total });
        }));
        let tx2 = event_tx.clone();
        let matcher = app_state.matcher.clone();
        scanner.on_result = Some(Box::new(move |snapshot| {
            if let Ok(m) = matcher.lock() {
                let entry = leanreel_core::api::scan::build_entry(snapshot, &m);
                let _ = tx2.send(AppEvent::ScanResult(entry));
            }
        }));
    }

    // Wire encode progress
    let tx = event_tx.clone();
    app_state.worker.set_progress_emitter(Box::new(move |job_id, stage, progress, status| {
        let _ = tx.send(AppEvent::EncodeProgress {
            job_id: job_id.to_string(),
            stage: stage.to_string(),
            progress,
            status: status.to_string(),
        });
    }));

    let mut app = App::new(app_state, event_rx, event_tx.clone());

    // Spawn input reader
    let input_tx = event_tx.clone();
    tokio::spawn(async move {
        loop {
            if event::poll(std::time::Duration::from_millis(16)).unwrap_or(false) {
                if let Ok(Event::Key(key)) = event::read() {
                    if input_tx.send(AppEvent::Key(key)).is_err() {
                        break;
                    }
                } else if let Ok(Event::Resize(_, _)) = event::read() {
                    let _ = input_tx.send(AppEvent::Resize);
                }
            }
        }
    });

    // Spawn tick timer for periodic refresh
    let tick_tx = event_tx;
    tokio::spawn(async move {
        let mut interval = tokio::time::interval(std::time::Duration::from_millis(200));
        loop {
            interval.tick().await;
            if tick_tx.send(AppEvent::Tick).is_err() {
                break;
            }
        }
    });

    let result = app.run(&mut terminal).await;

    disable_raw_mode()?;
    execute!(
        terminal.backend_mut(),
        LeaveAlternateScreen
    )?;
    terminal.show_cursor()?;

    result
}

pub enum AppEvent {
    Key(event::KeyEvent),
    Tick,
    ScanProgress { done: usize, total: usize },
    ScanResult(leanreel_core::api::scan::FileEntry),
    EncodeProgress {
        job_id: String,
        stage: String,
        progress: f64,
        status: String,
    },
    Error(String),
    Resize,
}
