use crate::overlays::OverlayCtx;
use crate::ui::theme;
use crossterm::event::{KeyCode, KeyEvent};
use leanreel_core::domain::models::HistoryEntry;
use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::style::Style;
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, Cell, Clear, Paragraph, Row, Table, TableState};
use ratatui::Frame;

pub struct HistoryState {
    entries: Vec<HistoryEntry>,
    table_state: TableState,
    filter: HistoryFilter,
    show_detail: Option<usize>,
    scroll: usize,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum HistoryFilter {
    All,
    Success,
    Failed,
}

impl HistoryState {
    pub fn new(entries: Vec<HistoryEntry>) -> Self {
        Self {
            entries,
            table_state: TableState::default(),
            filter: HistoryFilter::All,
            show_detail: None,
            scroll: 0,
        }
    }

    fn filtered(&self) -> Vec<&HistoryEntry> {
        self.entries
            .iter()
            .filter(|e| match self.filter {
                HistoryFilter::All => true,
                HistoryFilter::Success => e.status == "completed",
                HistoryFilter::Failed => e.status == "failed" || e.status == "discarded",
            })
            .collect()
    }

    pub fn handle_key(&mut self, key: KeyEvent, _ctx: &mut OverlayCtx) {
        match key.code {
            KeyCode::Esc => {
                if self.show_detail.is_some() {
                    self.show_detail = None;
                }
            }
            KeyCode::Up => {
                if self.show_detail.is_some() {
                    self.scroll = self.scroll.saturating_sub(1);
                } else {
                    let idx = self.table_state.selected().unwrap_or(0);
                    if idx > 0 {
                        self.table_state.select(Some(idx - 1));
                    }
                }
            }
            KeyCode::Down => {
                if self.show_detail.is_some() {
                    self.scroll += 1;
                } else {
                    let idx = self.table_state.selected().unwrap_or(0);
                    let len = self.filtered().len();
                    if idx + 1 < len {
                        self.table_state.select(Some(idx + 1));
                    }
                }
            }
            KeyCode::Enter => {
                if let Some(idx) = self.table_state.selected() {
                    self.show_detail = Some(idx);
                }
            }
            KeyCode::Char('a') => self.filter = HistoryFilter::All,
            KeyCode::Char('s') => self.filter = HistoryFilter::Success,
            KeyCode::Char('f') => self.filter = HistoryFilter::Failed,
            _ => {}
        }
    }
}

pub fn render(f: &mut Frame, area: Rect, state: &HistoryState) {
    f.render_widget(Clear, area);

    let chunks = Layout::default()
        .direction(ratatui::layout::Direction::Vertical)
        .constraints([Constraint::Length(1), Constraint::Min(1)])
        .margin(2)
        .split(area);

    let filter_text = match state.filter {
        HistoryFilter::All => "[a:全部]",
        HistoryFilter::Success => "[s:成功]",
        HistoryFilter::Failed => "[f:失败]",
    };
    let title = Paragraph::new(Line::from(vec![
        Span::styled(" 任务历史 ", theme::accent()),
        Span::styled(filter_text, theme::dim()),
        Span::styled(" ESC:关闭 Enter:详情 ", theme::dim()),
    ]))
    .style(Style::default().bg(theme::BG));
    f.render_widget(title, chunks[0]);

    if let Some(detail_idx) = state.show_detail {
        let filtered = state.filtered();
        if let Some(entry) = filtered.get(detail_idx) {
            let detail = format!(
                "状态: {}\n源文件: {}\n输出: {}\n体积: {} -> {}\n节省: {:.1}%\n策略: {}\n编码器: {}\nCQ: {}\n耗时: {:.1}s\n\n命令:\n{}",
                entry.status,
                entry.source_path,
                entry.output_path,
                entry.source_size_bytes,
                entry.output_size_bytes,
                entry.savings_pct,
                entry.strategy_name,
                entry.encoder,
                entry.cq_value,
                entry.duration_ms as f64 / 1000.0,
                entry.ffmpeg_command,
            );
            let p = Paragraph::new(detail)
                .block(Block::default().borders(Borders::ALL).border_style(theme::border_style()))
                .scroll((state.scroll as u16, 0));
            f.render_widget(p, chunks[1]);
        }
    } else {
        let filtered = state.filtered();
        let header = Row::new(vec![
            Cell::from("状态"),
            Cell::from("源文件"),
            Cell::from("节省%"),
            Cell::from("策略"),
            Cell::from("编码器"),
            Cell::from("耗时"),
        ])
        .style(theme::bold());

        let rows: Vec<Row> = filtered
            .iter()
            .map(|e| {
                let status_style = match e.status.as_str() {
                    "completed" => theme::green(),
                    "failed" => theme::red(),
                    "discarded" => theme::yellow(),
                    _ => theme::dim(),
                };
                Row::new(vec![
                    Cell::from(Span::styled(&e.status, status_style)),
                    Cell::from(e.source_path.as_str()),
                    Cell::from(format!("{:.1}", e.savings_pct)),
                    Cell::from(e.strategy_name.as_str()),
                    Cell::from(e.encoder.as_str()),
                    Cell::from(format!("{:.1}s", e.duration_ms as f64 / 1000.0)),
                ])
            })
            .collect();

        let widths = [
            Constraint::Length(10),
            Constraint::Percentage(40),
            Constraint::Length(8),
            Constraint::Length(15),
            Constraint::Length(12),
            Constraint::Length(10),
        ];

        let table = Table::new(rows)
            .widths(&widths)
            .header(header)
            .block(
                Block::default()
                    .title(format!(" 共 {} 条记录 ", state.entries.len()))
                    .borders(Borders::ALL)
                    .border_style(theme::border_style()),
            )
            .highlight_style(theme::selected());

        let mut table_state = state.table_state.clone();
        f.render_stateful_widget(table, chunks[1], &mut table_state);
    }
}
