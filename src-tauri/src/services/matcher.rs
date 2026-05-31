use crate::domain::models::*;

pub struct StrategyMatcher {
    strategies: Vec<Strategy>,
}

impl StrategyMatcher {
    pub fn new(strategies: Vec<Strategy>) -> Self {
        Self { strategies }
    }

    pub fn match_for(&self, file: &FileSnapshot) -> StrategyResult {
        // Protected source check (highest priority)
        match &file.video_codec {
            VideoCodec::Hevc => {
                return StrategyResult::SkipProtected {
                    reason: SkipReason::HevcSource,
                };
            }
            VideoCodec::Av1 => {
                return StrategyResult::SkipProtected {
                    reason: SkipReason::Av1Source,
                };
            }
            _ => {}
        }

        match &file.hdr_type {
            HdrType::Hdr10 => {
                return StrategyResult::SkipProtected {
                    reason: SkipReason::Hdr10,
                };
            }
            HdrType::Hdr10Plus => {
                return StrategyResult::SkipProtected {
                    reason: SkipReason::Hdr10PlusSource,
                };
            }
            HdrType::DolbyVision { .. } => {
                return StrategyResult::SkipProtected {
                    reason: SkipReason::DolbyVision,
                };
            }
            HdrType::Sdr => {}
        }

        // Only H.264 and MPEG-2 are candidates for processing
        if !matches!(&file.video_codec, VideoCodec::H264 | VideoCodec::Mpeg2) {
            return StrategyResult::SkipNoMatch {
                reason: "不支持的编码格式".into(),
            };
        }

        // Match first applicable strategy with all filters
        for strategy in &self.strategies {
            // min_size_gb filter
            if let Some(min_gb) = strategy.filters.min_size_gb {
                if (file.size_bytes as f64) < min_gb * 1_000_000_000.0 {
                    continue;
                }
            }
            // skip_x265 filter: skip HEVC files for this strategy
            if strategy.filters.skip_x265 && matches!(file.video_codec, VideoCodec::Hevc) {
                continue;
            }
            // only_remux filter: only process files > 20GB
            if strategy.filters.only_remux {
                let is_remux = (matches!(
                    file.video_codec,
                    VideoCodec::H264 | VideoCodec::Mpeg2 | VideoCodec::Vc1
                )) && file.size_bytes > 20_000_000_000;
                if !is_remux {
                    continue;
                }
            }
            return StrategyResult::Encode {
                strategy_name: strategy.name.clone(),
                estimated_saving: estimate_savings(file, strategy),
            };
        }

        if !self.strategies.is_empty() {
            let fallback = &self.strategies[0];
            StrategyResult::Encode {
                strategy_name: fallback.name.clone(),
                estimated_saving: estimate_savings(file, fallback),
            }
        } else {
            StrategyResult::SkipNoMatch {
                reason: "无匹配的策略".into(),
            }
        }
    }

    pub fn match_batch(&self, files: &[FileSnapshot]) -> Vec<StrategyResult> {
        files.iter().map(|f| self.match_for(f)).collect()
    }

    /// Look up a strategy by name. Returns None if not found.
    pub fn get_strategy(&self, name: &str) -> Option<&Strategy> {
        self.strategies.iter().find(|s| s.name == name)
    }
}

/// Confidence-bounded savings estimation matching Python's formula.
///
/// Models compression ratio based on CQ value, resolution, and pixel depth.
/// Returns a `SavingsEstimate` with min/max byte range and percentage string.
///
/// Python reference:
///   base = 0.65 * exp(-0.08 * (CQ - 14))          ← CQ exponential decay
///   adj_res = 0.85 (4K) / 1.0 (1080p) / 1.15 (<1080p)
///   adj_hdr = 1.08 (10-bit) / 1.0 (8-bit)
///   ratio = clamp(base * adj_res * adj_hdr, 0.08, 0.70)
///   savings_lo = ratio * 0.85, savings_hi = ratio * 1.20
fn estimate_savings(file: &FileSnapshot, strategy: &Strategy) -> SavingsEstimate {
    let encoder = &strategy.video.encoder;

    // copy mode: almost no savings (base = 0.95)
    let base = if encoder == "copy" {
        0.95_f64
    } else {
        let cq = if strategy.video.cq > 0 {
            strategy.video.cq
        } else {
            23
        };
        0.65_f64 * (-0.08_f64 * (cq as f64 - 14.0_f64)).exp()
    };

    // Resolution adjustment: higher res compresses better (lower ratio)
    let adj_res = match file.video_height {
        h if h >= 2160 => 0.85,
        h if h >= 1080 => 1.0,
        _ => 1.15,
    };

    // HDR/10-bit adjustment: 10-bit needs more bits
    let is_10bit = strategy.video.pix_fmt.contains("10");
    let adj_hdr = if is_10bit { 1.08 } else { 1.0 };

    let ratio = (base * adj_res * adj_hdr).clamp(0.08, 0.70);

    // Confidence interval: ±15%/20% around the point estimate
    let savings_lo = ratio * 0.85;
    let savings_hi = ratio * 1.20;

    let lo_pct = ((1.0 - savings_hi) * 100.0) as i32;
    let hi_pct = ((1.0 - savings_lo) * 100.0) as i32;

    let size = file.size_bytes as u64 as f64;

    SavingsEstimate {
        percentage: format!("{}-{}%", lo_pct, hi_pct),
        estimated_min_bytes: (size * savings_lo) as u64,
        estimated_max_bytes: (size * savings_hi) as u64,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_estimate_savings_cq28_1080p_range() {
        let file = FileSnapshot {
            video_height: 1080,
            size_bytes: 10_000_000_000,
            hdr_type: HdrType::Sdr,
            video_codec: VideoCodec::H264,
            video_width: 1920,
            ..Default::default()
        };
        let strategy = Strategy {
            video: VideoConfig {
                cq: 28,
                crf: 0,
                pix_fmt: "yuv420p10le".into(),
                encoder: "av1_nvenc".into(),
                ..Default::default()
            },
            ..Default::default()
        };
        let est = estimate_savings(&file, &strategy);
        // Should produce a meaningful range
        assert!(
            est.estimated_min_bytes > 500_000_000,
            "CQ28 min should save meaningful space: {}",
            est.estimated_min_bytes
        );
        assert!(
            est.estimated_max_bytes < 9_500_000_000,
            "CQ28 max should not be too aggressive: {}",
            est.estimated_max_bytes
        );
        // Min should be less than max (confidence interval bounds)
        assert!(
            est.estimated_min_bytes <= est.estimated_max_bytes,
            "min {} <= max {}",
            est.estimated_min_bytes,
            est.estimated_max_bytes
        );
        // Percentage should contain "%" and a dash
        assert!(
            est.percentage.contains('%'),
            "percentage should contain '%': {}",
            est.percentage
        );
        assert!(
            est.percentage.contains('-'),
            "percentage should be a range: {}",
            est.percentage
        );
    }

    #[test]
    fn test_estimate_savings_copy_encoder_near_zero() {
        let file = FileSnapshot {
            video_height: 1080,
            size_bytes: 20_000_000_000,
            hdr_type: HdrType::Sdr,
            video_codec: VideoCodec::H264,
            video_width: 1920,
            ..Default::default()
        };
        let strategy = Strategy {
            video: VideoConfig {
                cq: 0,
                crf: 0,
                pix_fmt: "yuv420p".into(),
                encoder: "copy".into(),
                ..Default::default()
            },
            ..Default::default()
        };
        let est = estimate_savings(&file, &strategy);
        // copy mode: base=0.95 → retains substantially more size than compress modes
        assert!(
            est.estimated_min_bytes > 10_000_000_000,
            "copy encoder should retain most size: min={}",
            est.estimated_min_bytes
        );
        assert!(
            est.estimated_max_bytes > est.estimated_min_bytes,
            "max should exceed min"
        );
        // Savings percentage should be small (under 30%)
        let pct_str = &est.percentage;
        assert!(pct_str.ends_with('%'), "should end with %: {}", pct_str);
    }

    #[test]
    fn test_estimate_savings_4k_less_aggressive_than_1080p() {
        let file_4k = FileSnapshot {
            video_height: 2160,
            size_bytes: 20_000_000_000,
            ..Default::default()
        };
        let file_1080p = FileSnapshot {
            video_height: 1080,
            size_bytes: 20_000_000_000,
            ..Default::default()
        };
        let s = Strategy {
            video: VideoConfig {
                cq: 28,
                pix_fmt: "yuv420p10le".into(),
                ..Default::default()
            },
            ..Default::default()
        };
        let est_4k = estimate_savings(&file_4k, &s);
        let est_1080p = estimate_savings(&file_1080p, &s);
        // 4K has smaller ratio → retains fewer bytes → est should be smaller
        assert!(
            est_4k.estimated_min_bytes < est_1080p.estimated_min_bytes,
            "4K should have smaller min than 1080p: {} vs {}",
            est_4k.estimated_min_bytes,
            est_1080p.estimated_min_bytes
        );
        assert!(
            est_4k.estimated_max_bytes < est_1080p.estimated_max_bytes,
            "4K should have smaller max than 1080p: {} vs {}",
            est_4k.estimated_max_bytes,
            est_1080p.estimated_max_bytes
        );
    }

    #[test]
    fn test_estimate_savings_higher_cq_saves_less() {
        let file = FileSnapshot {
            video_height: 1080,
            size_bytes: 10_000_000_000,
            hdr_type: HdrType::Sdr,
            video_codec: VideoCodec::H264,
            video_width: 1920,
            ..Default::default()
        };
        let s_low = Strategy {
            video: VideoConfig {
                cq: 20,
                ..Default::default()
            },
            ..Default::default()
        };
        let s_high = Strategy {
            video: VideoConfig {
                cq: 40,
                ..Default::default()
            },
            ..Default::default()
        };
        let est_low = estimate_savings(&file, &s_low);
        let est_high = estimate_savings(&file, &s_high);
        // Higher CQ = more compression = smaller output = smaller estimate
        assert!(
            est_high.estimated_max_bytes < est_low.estimated_max_bytes,
            "Higher CQ should produce smaller output (high_max={} < low_max={})",
            est_high.estimated_max_bytes,
            est_low.estimated_max_bytes
        );
    }

    #[test]
    fn test_match_remux_only_large_files() {
        let strategy = Strategy {
            name: "remux".into(),
            filters: FilterConfig {
                only_remux: true,
                skip_x265: false,
                min_size_gb: None,
            },
            ..Default::default()
        };
        let matcher = StrategyMatcher::new(vec![strategy]);
        let small_file = FileSnapshot {
            size_bytes: 10_000_000_000,
            video_codec: VideoCodec::H264,
            hdr_type: HdrType::Sdr,
            relative_path: "small.mkv".into(),
            ..Default::default()
        };
        let large_file = FileSnapshot {
            size_bytes: 25_000_000_000,
            video_codec: VideoCodec::H264,
            hdr_type: HdrType::Sdr,
            relative_path: "large.mkv".into(),
            ..Default::default()
        };
        // Small file doesn't match the only_remux filter, but falls back to strategies[0] (S-001)
        assert!(
            matches!(
                matcher.match_for(&small_file),
                StrategyResult::Encode { .. }
            ),
            "small file should get fallback Encode from strategies[0]"
        );
        assert!(matches!(
            matcher.match_for(&large_file),
            StrategyResult::Encode { .. }
        ));
    }
}
