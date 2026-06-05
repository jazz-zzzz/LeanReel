use crate::overlays::OverlayCtx;
use crate::ui::theme;
use crossterm::event::{KeyCode, KeyEvent};
use leanreel_core::api::strategy::StrategyItem;
use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, Clear, List, ListItem, ListState, Paragraph};
use ratatui::Frame;

pub struct StrategyManagerState {
    strategies: Vec<StrategyItem>,
    list_state: ListState,
    show_edit: bool,
    edit_name: String,
    edit_encoder: String,
    edit_cq: String,
    edit_description: String,
    edit_field: usize,
}

impl StrategyManagerState {
    pub fn new(strategies: Vec<StrategyItem>) -> Self {
        let mut state = Self {
            strategies,
            list_state: ListState::default(),
            show_edit: false,
            edit_name: String::new(),
            edit_encoder: String::new(),
            edit_cq: String::new(),
            edit_description: String::new(),
            edit_field: 0,
        };
        state.list_state.select(Some(0));
        state
    }

    pub fn handle_key(&mut self, key: KeyEvent, ctx: &mut OverlayCtx) {
        if self.show_edit {
            match key.code {
                KeyCode::Esc => self.show_edit = false,
                KeyCode::Tab => self.edit_field = (self.edit_field + 1) % 4,
                KeyCode::BackTab => self.edit_field = if self.edit_field == 0 { 3 } else { self.edit_field - 1 },
                KeyCode::Enter => {
                    let strategy_json = serde_json::json!({
                        "name": self.edit_name,
                        "description": self.edit_description,
                        "is_preset": false,
                        "video": {
                            "encoder": self.edit_encoder,
                            "cq": self.edit_cq.parse::<i32>().unwrap_or(23),
                            "crf": 0,
                            "preset": "medium",
                            "pix_fmt": "",
                            "x265_params": "",
                            "gpu": false,
                            "nv_preset": "",
                            "rc": "",
                        },
                        "hdr": { "mode": "pass_through", "dv_handling": "" },
                        "audio": { "mode": "keep_original", "preferred_languages": ["chi","zho","eng"] },
                        "subtitle": { "mode": "keep_original" },
                        "filters": { "skip_x265": false, "min_size_gb": null, "only_remux": false },
                        "estimated_savings": "",
                        "quality_impact": "",
                        "sort_order": 0,
                    }).to_string();

                    let _ = leanreel_core::api::strategy::save_strategy(
                        &self.edit_name,
                        &strategy_json,
                        ctx.state,
                    );
                    ctx.needs_refresh_strategies = true;
                    self.show_edit = false;
                    *ctx.status_message = format!("策略已保存: {}", self.edit_name);
                }
                KeyCode::Backspace => {
                    match self.edit_field {
                        0 => { self.edit_name.pop(); }
                        1 => { self.edit_encoder.pop(); }
                        2 => { self.edit_cq.pop(); }
                        3 => { self.edit_description.pop(); }
                        _ => {}
                    }
                }
                KeyCode::Char(c) => {
                    match self.edit_field {
                        0 => self.edit_name.push(c),
                        1 => self.edit_encoder.push(c),
                        2 => self.edit_cq.push(c),
                        3 => self.edit_description.push(c),
                        _ => {}
                    }
                }
                _ => {}
            }
        } else {
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
                KeyCode::Enter => {
                    if let Some(idx) = self.list_state.selected() {
                        if let Some(s) = self.strategies.get(idx) {
                            self.edit_name = s.name.clone();
                            self.edit_encoder = s.encoder.clone();
                            self.edit_cq = s.cq.to_string();
                            self.edit_description = s.description.clone();
                            self.show_edit = true;
                        }
                    }
                }
                KeyCode::Char('n') => {
                    self.edit_name = format!("新策略 {}", self.strategies.len() + 1);
                    self.edit_encoder = "hevc_nvenc".into();
                    self.edit_cq = "28".into();
                    self.edit_description = String::new();
                    self.show_edit = true;
                }
                KeyCode::Char('d') => {
                    if let Some(idx) = self.list_state.selected() {
                        if let Some(s) = self.strategies.get(idx) {
                            let _ = leanreel_core::api::strategy::delete_strategy(&s.name, ctx.state);
                            ctx.needs_refresh_strategies = true;
                            *ctx.status_message = format!("已删除: {}", s.name);
                        }
                    }
                }
                KeyCode::Char('j') => {
                    let idx = self.list_state.selected().unwrap_or(0);
                    if idx + 1 < self.strategies.len() {
                        self.strategies.swap(idx, idx + 1);
                        self.list_state.select(Some(idx + 1));
                        let entries: Vec<leanreel_core::api::strategy::SortOrderEntry> = self
                            .strategies
                            .iter()
                            .enumerate()
                            .map(|(i, s)| leanreel_core::api::strategy::SortOrderEntry {
                                name: s.name.clone(),
                                sort_order: i as i32,
                            })
                            .collect();
                        let _ = leanreel_core::api::strategy::save_strategy_order(&entries, ctx.state);
                    }
                }
                KeyCode::Char('k') => {
                    let idx = self.list_state.selected().unwrap_or(0);
                    if idx > 0 {
                        self.strategies.swap(idx, idx - 1);
                        self.list_state.select(Some(idx - 1));
                        let entries: Vec<leanreel_core::api::strategy::SortOrderEntry> = self
                            .strategies
                            .iter()
                            .enumerate()
                            .map(|(i, s)| leanreel_core::api::strategy::SortOrderEntry {
                                name: s.name.clone(),
                                sort_order: i as i32,
                            })
                            .collect();
                        let _ = leanreel_core::api::strategy::save_strategy_order(&entries, ctx.state);
                    }
                }
                _ => {}
            }
        }
    }
}

pub fn render(f: &mut Frame, area: Rect, state: &StrategyManagerState) {
    f.render_widget(Clear, area);
    let main_area = Rect {
        x: area.x + 4,
        y: area.y + 2,
        width: area.width.saturating_sub(8),
        height: area.height.saturating_sub(4),
    };

    if state.show_edit {
        let chunks = Layout::default()
            .direction(ratatui::layout::Direction::Vertical)
            .constraints([
                Constraint::Length(1),
                Constraint::Length(3),
                Constraint::Length(3),
                Constraint::Length(3),
                Constraint::Length(3),
                Constraint::Length(2),
            ])
            .split(main_area);

        let title = Paragraph::new(Line::from(vec![
            Span::styled(" 编辑策略 ", theme::accent()),
            Span::styled(" Enter:保存 Esc:取消 ", theme::dim()),
        ]));
        f.render_widget(title, chunks[0]);

        let fields = ["名称", "编码器", "CQ", "描述"];
        let values = [
            &state.edit_name,
            &state.edit_encoder,
            &state.edit_cq,
            &state.edit_description,
        ];
        for i in 0..4 {
            let style = if state.edit_field == i {
                theme::accent()
            } else {
                theme::dim()
            };
            let line = format!(" {}: {}_", fields[i], values[i]);
            f.render_widget(Paragraph::new(line).style(style), chunks[i + 1]);
        }

        f.render_widget(
            Paragraph::new(" Tab:切换字段  Enter:保存  ESC:返回 ").style(theme::dim()),
            chunks[5],
        );
    } else {
        let chunks = Layout::default()
            .direction(ratatui::layout::Direction::Vertical)
            .constraints([Constraint::Length(1), Constraint::Min(1), Constraint::Length(1)])
            .split(main_area);

        let title = Paragraph::new(Line::from(vec![
            Span::styled(" 策略管理 ", theme::accent()),
            Span::styled(" n:新建 d:删除 Enter:编辑 j/k:排序 ESC:关闭 ", theme::dim()),
        ]));
        f.render_widget(title, chunks[0]);

        let items: Vec<ListItem> = state
            .strategies
            .iter()
            .map(|s| {
                ListItem::new(Line::from(vec![
                    Span::raw(format!(" {}  {}  CQ:{}  ", s.name, s.encoder, s.cq)),
                    Span::styled(&s.savings, theme::dim()),
                ]))
            })
            .collect();

        let list = List::new(items)
            .block(
                Block::default()
                    .title(format!(" {} 个策略 ", state.strategies.len()))
                    .borders(Borders::ALL)
                    .border_style(theme::border_style()),
            )
            .highlight_style(theme::selected());

        let mut list_state = state.list_state.clone();
        f.render_stateful_widget(list, chunks[1], &mut list_state);

        f.render_widget(
            Paragraph::new(" j/k:移动排序  n:新建  d:删除  Enter:编辑  ESC:关闭 ").style(theme::dim()),
            chunks[2],
        );
    }
}
