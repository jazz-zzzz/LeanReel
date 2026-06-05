use std::process::Command;

/// DoviTool wrapper — Dolby Vision RPU extraction and injection.
pub struct DoviTool;

impl DoviTool {
    pub fn get_dovi_tool_path() -> String {
        std::env::var("DOVI_TOOL_PATH").unwrap_or_else(|_| "dovi_tool".to_string())
    }

    pub fn extract_rpu(input_file: &str, rpu_output: &str) -> Result<(), String> {
        let cmd = Self::get_dovi_tool_path();
        let output = Command::new(&cmd)
            .args(["extract-rpu", input_file, "-o", rpu_output])
            .output()
            .map_err(|e| format!("dovi_tool extract-rpu failed: {}", e))?;
        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(format!("dovi_tool extract-rpu error: {}", stderr.trim()));
        }
        Ok(())
    }

    pub fn inject_rpu(encoded_file: &str, rpu_file: &str, output: &str) -> Result<(), String> {
        let cmd = Self::get_dovi_tool_path();
        let result = Command::new(&cmd)
            .args([
                "inject-rpu",
                "-i",
                encoded_file,
                "--rpu-in",
                rpu_file,
                "-o",
                output,
            ])
            .output()
            .map_err(|e| format!("dovi_tool inject-rpu failed: {}", e))?;
        if !result.status.success() {
            let stderr = String::from_utf8_lossy(&result.stderr);
            return Err(format!("dovi_tool inject-rpu error: {}", stderr.trim()));
        }
        Ok(())
    }

    pub fn needs_dovi_processing(
        hdr_type: &crate::domain::models::HdrType,
        dv_handling: &str,
    ) -> bool {
        matches!(
            hdr_type,
            crate::domain::models::HdrType::DolbyVision {
                profile: crate::domain::models::DvProfile::Profile7
            }
        ) && dv_handling == "reinject_rpu"
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn test_needs_dovi_processing() {
        let dv_p7 = crate::domain::models::HdrType::DolbyVision {
            profile: crate::domain::models::DvProfile::Profile7,
        };
        assert!(DoviTool::needs_dovi_processing(&dv_p7, "reinject_rpu"));
        assert!(!DoviTool::needs_dovi_processing(
            &crate::domain::models::HdrType::Sdr,
            "reinject_rpu"
        ));
    }
}
