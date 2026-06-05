use crate::app::App;
use ratatui::layout::{Constraint, Layout};
use ratatui::Frame;

use super::file_table;
use super::library_panel;
use super::status_bar;
use super::strategy_panel;
use super::title_bar;

pub fn render(f: &mut Frame, app: &mut App) {
    let area = f.size();

    let main_chunks = Layout::default()
        .direction(ratatui::layout::Direction::Vertical)
        .constraints([
            Constraint::Length(1),  // title bar
            Constraint::Min(1),     // main content
            Constraint::Length(1),  // status bar
        ])
        .split(area);

    title_bar::render(f, main_chunks[0], app.focus);

    let content_chunks = Layout::default()
        .direction(ratatui::layout::Direction::Horizontal)
        .constraints([
            Constraint::Percentage(25),
            Constraint::Percentage(50),
            Constraint::Percentage(25),
        ])
        .split(main_chunks[1]);

    let is_lib = matches!(app.focus, crate::app::Focus::Library);
    let is_file = matches!(app.focus, crate::app::Focus::FileTable);
    let is_strat = matches!(app.focus, crate::app::Focus::StrategyPanel);

    library_panel::render(f, content_chunks[0], &mut app.library_state, is_lib);
    file_table::render(f, content_chunks[1], &mut app.file_state, is_file);
    strategy_panel::render(f, content_chunks[2], &mut app.strategy_state, is_strat);

    status_bar::render(
        f,
        main_chunks[2],
        &app.status_message,
        &app.scan_progress,
        &app.encode_progress,
    );

    // Render overlay if active
    if let Some(ref overlay) = app.overlay {
        match overlay {
            crate::app::Overlay::History(state) => {
                crate::overlays::history::render(f, area, state);
            }
            crate::app::Overlay::Settings(state) => {
                crate::overlays::settings::render(f, area, state);
            }
            crate::app::Overlay::StrategyManager(state) => {
                crate::overlays::strategy_manager::render(f, area, state);
            }
        }
    }
}
