use crate::app::EncodeTaskProgress;
use crate::ui::theme;
use ratatui::layout::Rect;
use ratatui::text::{Line, Span};
use ratatui::widgets::Paragraph;
use ratatui::Frame;
use std::collections::HashMap;

pub fn render(
    f: &mut Frame,
    area: Rect,
    status_message: &str,
    scan_progress: &Option<(usize, usize)>,
    encode_progress: &HashMap<String, EncodeTaskProgress>,
) {
    let mut spans = Vec::new();

    // Scan progress
    if let Some((done, total)) = scan_progress {
        if *total > 0 {
            let _pct = (*done as f64 / *total as f64 * 100.0) as u32;
            spans.push(Span::styled(
                format!(" Scan: {}/{} ", done, total),
                theme::dim(),
            ));
        }
    }

    // Encode progress
    let total = encode_progress.len();
    if total > 0 {
        let completed = encode_progress
            .values()
            .filter(|t| t.status == "completed" || t.status == "discarded")
            .count();
        spans.push(Span::styled(
            format!(" Enc: {}/{} ", completed, total),
            theme::accent(),
        ));
    }

    // Status message
    if !status_message.is_empty() {
        spans.push(Span::raw(format!(" {} ", status_message)));
    }

    // Key hints
    spans.push(Span::styled(
        " Tab:switch Arrows:nav Space:sel s:scan e:encode h:history g:settings m:strategies q:quit ",
        theme::dim(),
    ));

    let p = Paragraph::new(Line::from(spans)).style(theme::dim());
    f.render_widget(p, area);
}
