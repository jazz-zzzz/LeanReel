use crate::ui::theme;
use crossterm::event::{KeyCode, KeyEvent};
use leanreel_core::api::strategy::StrategyItem;
use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::style::Style;
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, List, ListItem, ListState, Paragraph};
use ratatui::Frame;

pub struct StrategyPanelState {
    pub strategies: Vec<StrategyItem>,
    pub delete_source: Option<bool>,
    pub list_state: ListState,
}

impl StrategyPanelState {
    pub fn new() -> Self {
        let mut state = Self {
            strategies: Vec::new(),
            delete_source: None,
            list_state: ListState::default(),
        };
        state.list_state.select(Some(0));
        state
    }

    pub fn selected_name(&self) -> &str {
        if let Some(idx) = self.list_state.selected() {
            if let Some(s) = self.strategies.get(idx) {
                return &s.name;
            }
        }
        ""
    }

    pub fn handle_key(&mut self, key: KeyEvent) {
        match key.code {
            KeyCode::Up => {
                let idx = self.list_state.selected().unwrap_or(0);
                if idx > 0 {
                    self.list_state.select(Some(idx - 1));
                }
            }
            KeyCode::Down => {
                let idx = self.list_state.selected().unwrap_or(0);
                if idx + 1 < self.strategies.len() {
                    self.list_state.select(Some(idx + 1));
                }
            }
            KeyCode::Char('d') => {
                self.delete_source = Some(!self.delete_source.unwrap_or(false));
            }
            _ => {}
        }
    }
}

pub fn render(f: &mut Frame, area: Rect, state: &mut StrategyPanelState, is_focused: bool) {
    let border_style = if is_focused {
        Style::default().fg(theme::ACCENT)
    } else {
        theme::border_style()
    };

    let chunks = Layout::default()
        .direction(ratatui::layout::Direction::Vertical)
        .constraints([Constraint::Min(3), Constraint::Length(5), Constraint::Length(2)])
        .split(area);

    // Strategy list
    let items: Vec<ListItem> = state
        .strategies
        .iter()
        .map(|s| {
            let tag = if s.gpu { "GPU" } else { "CPU" };
            let savings = if s.savings.is_empty() { "N/A" } else { &s.savings };
            ListItem::new(Line::from(vec![
                Span::styled(
                    format!(" {} ", tag),
                    if s.gpu {
                        Style::default().fg(theme::GREEN)
                    } else {
                        theme::dim()
                    },
                ),
                Span::raw(format!(" {}  CQ:{}  {}", s.name, s.cq, savings)),
            ]))
        })
        .collect();

    let list = List::new(items)
        .block(
            Block::default()
                .title(format!(" 策略 ({}) ", state.strategies.len()))
                .borders(Borders::ALL)
                .border_style(border_style),
        )
        .highlight_style(theme::selected());

    f.render_stateful_widget(list, chunks[0], &mut state.list_state);

    // Selected strategy detail
    if let Some(idx) = state.list_state.selected() {
        if let Some(s) = state.strategies.get(idx) {
            let detail = format!(
                " {} 编码器: {}  CQ: {}\n 预计节省: {}\n {}",
                s.name, s.encoder, s.cq, s.savings, s.description
            );
            let p = Paragraph::new(detail)
                .block(Block::default().borders(Borders::ALL).border_style(theme::border_style()));
            f.render_widget(p, chunks[1]);
        }
    }

    // Encode settings
    let delete_label = if state.delete_source.unwrap_or(false) {
        "☑ 编码后删除源文件 [d]"
    } else {
        "☐ 编码后删除源文件 [d]"
    };
    let btn_text = if state.selected_name().is_empty() {
        "[e] 开始编码 (请先选择策略)"
    } else {
        "[e] 开始编码"
    };

    let settings = format!("{}\n{}", delete_label, btn_text);
    let p = Paragraph::new(settings)
        .block(Block::default().borders(Borders::ALL).border_style(theme::border_style()))
        .style(theme::accent());
    f.render_widget(p, chunks[2]);
}
