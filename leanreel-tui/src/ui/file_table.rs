use crate::app::Focus;
use crate::ui::theme;
use crossterm::event::{KeyCode, KeyEvent};
use leanreel_core::api::scan::FileEntry;
use ratatui::layout::{Constraint, Rect};
use ratatui::style::Style;
use ratatui::text::Span;
use ratatui::widgets::{Block, Borders, Cell, Row, Table, TableState};
use ratatui::Frame;
use std::collections::HashSet;

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum SortColumn {
    Name,
    Codec,
    Hdr,
    Resolution,
    Size,
    Strategy,
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum FilterMode {
    All,
    Processable,
    Protected,
    ProbeFailed,
    Checked,
}

pub struct FileTableState {
    pub files: Vec<FileEntry>,
    selected_indices: HashSet<usize>,
    sort_column: SortColumn,
    sort_ascending: bool,
    filter: FilterMode,
    table_state: TableState,
    anchor_index: Option<usize>,
}

impl FileTableState {
    pub fn new() -> Self {
        let mut state = Self {
            files: Vec::new(),
            selected_indices: HashSet::new(),
            sort_column: SortColumn::Name,
            sort_ascending: true,
            filter: FilterMode::All,
            table_state: TableState::default(),
            anchor_index: None,
        };
        state.table_state.select(Some(0));
        state
    }

    fn filtered_files(&self) -> Vec<&FileEntry> {
        self.files
            .iter()
            .filter(|f| match self.filter {
                FilterMode::All => true,
                FilterMode::Processable => f.decision_status == "processable",
                FilterMode::Protected => f.decision_status == "protected",
                FilterMode::ProbeFailed => f.decision_status == "probe_failed",
                FilterMode::Checked => self
                    .selected_indices
                    .contains(&self.files.iter().position(|x| x.key == f.key).unwrap_or(usize::MAX)),
            })
            .collect()
    }

    fn sorted_files(&self) -> Vec<&FileEntry> {
        let mut files = self.filtered_files();
        files.sort_by(|a, b| {
            let cmp = match self.sort_column {
                SortColumn::Name => a.name.to_lowercase().cmp(&b.name.to_lowercase()),
                SortColumn::Codec => a.codec.cmp(&b.codec),
                SortColumn::Hdr => a.hdr.cmp(&b.hdr),
                SortColumn::Resolution => (a.width * a.height).cmp(&(b.width * b.height)),
                SortColumn::Size => a.size.cmp(&b.size),
                SortColumn::Strategy => a.decision_text.cmp(&b.decision_text),
            };
            if self.sort_ascending { cmp } else { cmp.reverse() }
        });
        files
    }

    pub fn selected_keys(&self) -> Vec<String> {
        self.files
            .iter()
            .enumerate()
            .filter(|(i, _)| self.selected_indices.contains(i))
            .map(|(_, f)| f.key.clone())
            .collect()
    }

    pub fn handle_key(&mut self, key: KeyEvent) {
        match key.code {
            KeyCode::Up => {
                let idx = self.table_state.selected().unwrap_or(0);
                if idx > 0 {
                    self.table_state.select(Some(idx - 1));
                }
            }
            KeyCode::Down => {
                let sorted = self.sorted_files();
                let idx = self.table_state.selected().unwrap_or(0);
                if idx + 1 < sorted.len() {
                    self.table_state.select(Some(idx + 1));
                }
            }
            KeyCode::Char(' ') => {
                if let Some(idx) = self.table_state.selected() {
                    let sorted = self.sorted_files();
                    if let Some(entry) = sorted.get(idx) {
                        if entry.decision_status == "processable" {
                            let orig_idx = self
                                .files
                                .iter()
                                .position(|f| f.key == entry.key)
                                .unwrap_or(idx);
                            if self.selected_indices.contains(&orig_idx) {
                                self.selected_indices.remove(&orig_idx);
                            } else {
                                self.selected_indices.insert(orig_idx);
                            }
                        }
                    }
                }
            }
            KeyCode::Char('1') => { self.sort_column = SortColumn::Name; self.sort_ascending = !self.sort_ascending; }
            KeyCode::Char('2') => { self.sort_column = SortColumn::Codec; self.sort_ascending = !self.sort_ascending; }
            KeyCode::Char('3') => { self.sort_column = SortColumn::Hdr; self.sort_ascending = !self.sort_ascending; }
            KeyCode::Char('4') => { self.sort_column = SortColumn::Resolution; self.sort_ascending = !self.sort_ascending; }
            KeyCode::Char('5') => { self.sort_column = SortColumn::Size; self.sort_ascending = !self.sort_ascending; }
            KeyCode::Char('6') => { self.sort_column = SortColumn::Strategy; self.sort_ascending = !self.sort_ascending; }
            KeyCode::Char('f') => {
                self.filter = match self.filter {
                    FilterMode::All => FilterMode::Processable,
                    FilterMode::Processable => FilterMode::Protected,
                    FilterMode::Protected => FilterMode::ProbeFailed,
                    FilterMode::ProbeFailed => FilterMode::Checked,
                    FilterMode::Checked => FilterMode::All,
                };
                self.table_state.select(Some(0));
            }
            _ => {}
        }
    }
}

pub fn render(f: &mut Frame, area: Rect, state: &mut FileTableState, is_focused: bool) {
    let border_style = if is_focused {
        Style::default().fg(theme::ACCENT)
    } else {
        theme::border_style()
    };

    let sort_indicator = |col: SortColumn| -> &str {
        if state.sort_column == col {
            if state.sort_ascending { " ▲" } else { " ▼" }
        } else {
            ""
        }
    };

    let filter_label = match state.filter {
        FilterMode::All => "全部",
        FilterMode::Processable => "可处理",
        FilterMode::Protected => "受保护",
        FilterMode::ProbeFailed => "探测失败",
        FilterMode::Checked => "已勾选",
    };

    let header = Row::new(vec![
        Cell::from("✓"),
        Cell::from(format!("名称{}", sort_indicator(SortColumn::Name))),
        Cell::from(format!("编码{}", sort_indicator(SortColumn::Codec))),
        Cell::from(format!("HDR{}", sort_indicator(SortColumn::Hdr))),
        Cell::from(format!("分辨率{}", sort_indicator(SortColumn::Resolution))),
        Cell::from(format!("大小{}", sort_indicator(SortColumn::Size))),
        Cell::from(format!("策略{}  [f:{}]", sort_indicator(SortColumn::Strategy), filter_label)),
    ]).style(theme::bold());

    let sorted = state.sorted_files();
    let rows: Vec<Row> = sorted
        .iter()
        .enumerate()
        .map(|(i, f)| {
            let orig_idx = state.files.iter().position(|x| x.key == f.key).unwrap_or(i);
            let checked = if state.selected_indices.contains(&orig_idx) { "☑" } else { "☐" };
            let style = match f.decision_status.as_str() {
                "processable" => Style::default(),
                "protected" => theme::yellow(),
                "probe_failed" => theme::red(),
                "pending" => theme::dim(),
                _ => theme::dim(),
            };
            Row::new(vec![
                Cell::from(if f.decision_status == "processable" { checked } else { " " }),
                Cell::from(f.name.clone()),
                Cell::from(f.codec.clone()),
                Cell::from(f.hdr.clone()),
                Cell::from(format!("{}x{}", f.width, f.height)),
                Cell::from(f.size_display.clone()),
                Cell::from(f.decision_text.clone()),
            ]).style(style)
        })
        .collect();

    let widths = [
        Constraint::Length(2),
        Constraint::Percentage(28),
        Constraint::Length(8),
        Constraint::Length(9),
        Constraint::Length(11),
        Constraint::Length(10),
        Constraint::Percentage(22),
    ];

    let count = sorted.len();
    let selected = state.selected_indices.len();
    let title = if selected > 0 {
        format!(" 文件 ({} 个, 已选 {}) ", count, selected)
    } else {
        format!(" 文件 ({} 个) ", count)
    };

    let table = Table::new(rows)
        .widths(&widths)
        .header(header)
        .block(Block::default().title(title).borders(Borders::ALL).border_style(border_style))
        .highlight_style(theme::selected());

    f.render_stateful_widget(table, area, &mut state.table_state);
}
