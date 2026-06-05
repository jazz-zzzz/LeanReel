use crate::overlays::OverlayCtx;
use crate::ui::theme;
use crossterm::event::{KeyCode, KeyEvent};
use leanreel_core::api::settings::AppSettings;
use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::style::Style;
use ratatui::text::{Line, Span};
use ratatui::widgets::{Clear, Paragraph};
use ratatui::Frame;

pub struct SettingsState {
    settings: AppSettings,
    field_focus: usize,
    ffprobe_input: String,
    ffmpeg_input: String,
}

impl SettingsState {
    pub fn new(settings: AppSettings) -> Self {
        Self {
            ffprobe_input: settings.ffprobe_path.clone(),
            ffmpeg_input: settings.ffmpeg_path.clone(),
            settings,
            field_focus: 0,
        }
    }

    pub fn handle_key(&mut self, key: KeyEvent, ctx: &mut OverlayCtx) {
        match key.code {
            KeyCode::Tab => {
                self.field_focus = (self.field_focus + 1) % 2;
            }
            KeyCode::BackTab => {
                self.field_focus = if self.field_focus == 0 { 1 } else { 0 };
            }
            KeyCode::Enter => {
                let ffp = if self.ffprobe_input.is_empty() {
                    None
                } else {
                    Some(self.ffprobe_input.as_str())
                };
                let ffm = if self.ffmpeg_input.is_empty() {
                    None
                } else {
                    Some(self.ffmpeg_input.as_str())
                };
                if let Ok(new_settings) =
                    leanreel_core::api::settings::save_settings(ffp, ffm, ctx.state)
                {
                    self.settings = new_settings;
                    *ctx.status_message = "设置已保存".into();
                } else {
                    *ctx.status_message = "保存设置失败".into();
                }
            }
            KeyCode::Backspace => {
                match self.field_focus {
                    0 => { self.ffprobe_input.pop(); }
                    1 => { self.ffmpeg_input.pop(); }
                    _ => {}
                }
            }
            KeyCode::Char(c) => {
                match self.field_focus {
                    0 => self.ffprobe_input.push(c),
                    1 => self.ffmpeg_input.push(c),
                    _ => {}
                }
            }
            _ => {}
        }
    }
}

pub fn render(f: &mut Frame, area: Rect, state: &SettingsState) {
    f.render_widget(Clear, area);

    let popup_area = centered_rect(60, 50, area);

    let chunks = Layout::default()
        .direction(ratatui::layout::Direction::Vertical)
        .constraints([
            Constraint::Length(1),
            Constraint::Length(3),
            Constraint::Length(3),
            Constraint::Length(3),
            Constraint::Length(2),
        ])
        .margin(1)
        .split(popup_area);

    let title = Paragraph::new(Line::from(vec![
        Span::styled(" 设置 ", theme::accent()),
        Span::styled(" ESC:关闭 Tab:切换 Enter:保存 ", theme::dim()),
    ]));
    f.render_widget(title, chunks[0]);

    let ffp_ok = if state.settings.ffprobe_ok { "✓" } else { "✗" };
    let ffp_style = if state.field_focus == 0 {
        theme::accent()
    } else {
        theme::dim()
    };
    let ffprobe_line = format!(
        " ffprobe [{}]: {}_",
        ffp_ok,
        state.ffprobe_input
    );
    f.render_widget(Paragraph::new(ffprobe_line).style(ffp_style), chunks[1]);

    let ffm_ok = if state.settings.ffmpeg_ok { "✓" } else { "✗" };
    let ffm_style = if state.field_focus == 1 {
        theme::accent()
    } else {
        theme::dim()
    };
    let ffmpeg_line = format!(
        " ffmpeg [{}]: {}_",
        ffm_ok,
        state.ffmpeg_input
    );
    f.render_widget(Paragraph::new(ffmpeg_line).style(ffm_style), chunks[2]);

    let gpu_ok = if state.settings.gpu_ok {
        format!("✓ {}", state.settings.gpu_info)
    } else {
        "✗ 未检测到GPU".into()
    };
    f.render_widget(Paragraph::new(format!(" GPU: {}", gpu_ok)).style(theme::dim()), chunks[3]);

    f.render_widget(
        Paragraph::new(" Enter=保存并检测  ESC=返回 ").style(theme::dim()),
        chunks[4],
    );
}

fn centered_rect(percent_x: u16, percent_y: u16, r: Rect) -> Rect {
    let popup_layout = Layout::default()
        .direction(ratatui::layout::Direction::Vertical)
        .constraints([
            Constraint::Percentage((100 - percent_y) / 2),
            Constraint::Percentage(percent_y),
            Constraint::Percentage((100 - percent_y) / 2),
        ])
        .split(r);

    Layout::default()
        .direction(ratatui::layout::Direction::Horizontal)
        .constraints([
            Constraint::Percentage((100 - percent_x) / 2),
            Constraint::Percentage(percent_x),
            Constraint::Percentage((100 - percent_x) / 2),
        ])
        .split(popup_layout[1])[1]
}
