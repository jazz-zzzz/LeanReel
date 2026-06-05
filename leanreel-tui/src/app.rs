use crate::AppEvent;
use crate::overlays::history::HistoryState;
use crate::overlays::settings::SettingsState;
use crate::overlays::strategy_manager::StrategyManagerState;
use crate::overlays::OverlayCtx;
use crate::ui::file_table::FileTableState;
use crate::ui::library_panel::{LibraryAction, LibraryPanelState};
use crate::ui::strategy_panel::StrategyPanelState;
use crossterm::event::{KeyCode, KeyEvent};
use leanreel_core::AppState;
use ratatui::Terminal;
use ratatui::backend::CrosstermBackend;
use std::collections::HashMap;
use std::io;
use std::sync::Arc;
use tokio::sync::mpsc::UnboundedReceiver;

pub struct App {
    pub state: Arc<AppState>,
    event_rx: UnboundedReceiver<AppEvent>,
    event_tx: tokio::sync::mpsc::UnboundedSender<AppEvent>,
    pub focus: Focus,
    pub library_state: LibraryPanelState,
    pub file_state: FileTableState,
    pub strategy_state: StrategyPanelState,
    pub overlay: Option<Overlay>,
    pub status_message: String,
    pub scan_progress: Option<(usize, usize)>,
    pub encode_progress: HashMap<String, EncodeTaskProgress>,
    pub should_quit: bool,
}

#[derive(Debug, Clone)]
pub struct EncodeTaskProgress {
    pub stage: String,
    pub progress: f64,
    pub status: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Focus {
    Library,
    FileTable,
    StrategyPanel,
}

impl Focus {
    fn next(self) -> Self {
        match self {
            Focus::Library => Focus::FileTable,
            Focus::FileTable => Focus::StrategyPanel,
            Focus::StrategyPanel => Focus::Library,
        }
    }

    fn prev(self) -> Self {
        match self {
            Focus::Library => Focus::StrategyPanel,
            Focus::FileTable => Focus::Library,
            Focus::StrategyPanel => Focus::FileTable,
        }
    }
}

pub enum Overlay {
    History(HistoryState),
    Settings(SettingsState),
    StrategyManager(StrategyManagerState),
}

impl App {
    pub fn new(
        state: Arc<AppState>,
        event_rx: UnboundedReceiver<AppEvent>,
        event_tx: tokio::sync::mpsc::UnboundedSender<AppEvent>,
    ) -> Self {
        Self {
            state,
            event_rx,
            event_tx,
            focus: Focus::Library,
            library_state: LibraryPanelState::new(),
            file_state: FileTableState::new(),
            strategy_state: StrategyPanelState::new(),
            overlay: None,
            status_message: String::new(),
            scan_progress: None,
            encode_progress: HashMap::new(),
            should_quit: false,
        }
    }

    pub async fn run(&mut self, terminal: &mut Terminal<CrosstermBackend<io::Stdout>>) -> io::Result<()> {
        self.refresh_libraries();
        self.refresh_strategies();

        loop {
            terminal.draw(|f| {
                crate::ui::layout::render(f, self);
            })?;

            if self.should_quit {
                return Ok(());
            }

            match self.event_rx.recv().await {
                Some(AppEvent::Key(key)) => self.handle_key(key),
                Some(AppEvent::Tick) => {}
                Some(AppEvent::ScanProgress { done, total }) => {
                    self.scan_progress = Some((done, total));
                }
                Some(AppEvent::ScanResult(entry)) => {
                    self.file_state.files.push(entry);
                }
                Some(AppEvent::EncodeProgress { job_id, stage, progress, status }) => {
                    self.encode_progress.insert(job_id, EncodeTaskProgress {
                        stage,
                        progress,
                        status,
                    });
                }
                Some(AppEvent::Error(msg)) => {
                    self.status_message = msg;
                }
                Some(AppEvent::Resize) => {}
                None => break,
            }
        }
        Ok(())
    }

    fn handle_key(&mut self, key: KeyEvent) {
        if self.overlay.is_some() {
            match key.code {
                KeyCode::Esc => {
                    self.overlay = None;
                }
                _ => {
                    let state = &self.state;
                    let status_message = &mut self.status_message;
                    let mut ctx = OverlayCtx {
                        state,
                        status_message,
                        needs_refresh_strategies: false,
                    };
                    let mut overlay = self.overlay.take();
                    if let Some(ref mut ov) = overlay {
                        match ov {
                            Overlay::History(s) => s.handle_key(key, &mut ctx),
                            Overlay::Settings(s) => s.handle_key(key, &mut ctx),
                            Overlay::StrategyManager(s) => s.handle_key(key, &mut ctx),
                        }
                    }
                    self.overlay = overlay;
                    if ctx.needs_refresh_strategies {
                        self.refresh_strategies();
                    }
                }
            }
            return;
        }

        match key.code {
            KeyCode::Char('q') => self.should_quit = true,
            KeyCode::Tab => self.focus = self.focus.next(),
            KeyCode::BackTab => self.focus = self.focus.prev(),
            KeyCode::Char('s') => self.start_scan(),
            KeyCode::Char('e') => self.start_encode(),
            KeyCode::Char('h') => self.open_history(),
            KeyCode::Char('g') => self.open_settings(),
            KeyCode::Char('m') => self.open_strategy_manager(),
            KeyCode::Esc => {}
            _ => {
                let app_state = &self.state;
                match self.focus {
                    Focus::Library => {
                        let action = self.library_state.handle_key(key, app_state);
                        match action {
                            LibraryAction::RefreshLibraries => self.refresh_libraries(),
                            LibraryAction::RefreshFiles(id) => self.refresh_files(id),
                            LibraryAction::SetStatus(msg) => self.status_message = msg,
                            LibraryAction::LoadFolders(lib_id) => {
                                self.library_state.load_folders(app_state, lib_id);
                            }
                            LibraryAction::None => {}
                        }
                    }
                    Focus::FileTable => {
                        self.file_state.handle_key(key);
                    }
                    Focus::StrategyPanel => {
                        self.strategy_state.handle_key(key);
                    }
                }
            }
        }
    }

    pub fn refresh_libraries(&mut self) {
        if let Ok(libs) = leanreel_core::api::library::list_libraries(&self.state) {
            self.library_state.libraries = libs;
        }
    }

    pub fn refresh_strategies(&mut self) {
        if let Ok(result) = leanreel_core::api::strategy::load_strategies(&self.state) {
            self.strategy_state.strategies = result.strategies;
        }
    }

    pub fn refresh_files(&mut self, folder_id: i64) {
        if let Ok(result) = leanreel_core::api::scan::get_folder_files(folder_id, &self.state) {
            self.file_state.files = result.files;
        }
    }

    fn start_scan(&mut self) {
        let folder_id = self.library_state.selected_folder_id();
        let path = self.library_state.selected_folder_path();
        if folder_id == 0 || path.is_empty() {
            self.status_message = "请先选择一个文件夹".into();
            return;
        }

        let state = self.state.clone();
        let tx = self.event_tx.clone();
        let path_clone = path.clone();

        self.status_message = format!("正在扫描: {}", path);

        tokio::spawn(async move {
            let state_arc = state;
            match leanreel_core::api::scan::scan_directory(path_clone, folder_id, state_arc.clone()).await {
                Ok(result) => {
                    for file in &result.files {
                        let _ = tx.send(AppEvent::ScanResult(file.clone()));
                    }
                    let _ = tx.send(AppEvent::ScanProgress { done: 0, total: 0 });
                }
                Err(e) => {
                    let _ = tx.send(AppEvent::Error(e));
                }
            }
        });
    }

    fn start_encode(&mut self) {
        let selected_files: Vec<String> = self.file_state.selected_keys();
        if selected_files.is_empty() {
            self.status_message = "请先选择文件".into();
            return;
        }
        if self.strategy_state.selected_name().is_empty() {
            self.status_message = "请先选择策略".into();
            return;
        }

        let strategy_name = self.strategy_state.selected_name().to_string();
        let delete_source = self.strategy_state.delete_source;
        let _file_count = selected_files.len();

        match leanreel_core::api::encode::start_encode(
            selected_files,
            &strategy_name,
            delete_source,
            None,
            None,
            &self.state,
        ) {
            Ok(result) => {
                self.status_message = format!("已提交 {} 个编码任务", result.jobs.len());
            }
            Err(e) => {
                self.status_message = format!("编码启动失败: {}", e);
            }
        }
    }

    fn open_history(&mut self) {
        if let Ok(entries) = leanreel_core::api::history::get_history(&self.state) {
            self.overlay = Some(Overlay::History(HistoryState::new(entries)));
        }
    }

    fn open_settings(&mut self) {
        if let Ok(settings) = leanreel_core::api::settings::get_settings(&self.state) {
            self.overlay = Some(Overlay::Settings(SettingsState::new(settings)));
        }
    }

    fn open_strategy_manager(&mut self) {
        if let Ok(result) = leanreel_core::api::strategy::load_strategies(&self.state) {
            self.overlay = Some(Overlay::StrategyManager(StrategyManagerState::new(
                result.strategies,
            )));
        }
    }

    pub fn is_overlay_open(&self) -> bool {
        self.overlay.is_some()
    }
}
