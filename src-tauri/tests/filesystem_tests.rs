use leanreel_rs_lib::infrastructure::filesystem::find_video_files;
use std::fs;
use std::path::Path;

#[test]
fn test_nonexistent_directory_returns_empty() {
    let (files, warnings) = find_video_files(Path::new("./definitely_not_real_12345"));
    assert!(
        files.is_empty(),
        "Nonexistent dir should return empty vec, got {:?}",
        files
    );
    assert!(!warnings.is_empty(), "Unavailable roots must be reported");
}

#[test]
fn test_not_a_directory_returns_empty() {
    let tmp = std::env::temp_dir().join("leanreel_test_file.txt");
    fs::write(&tmp, "test").unwrap();
    let (files, _) = find_video_files(&tmp);
    fs::remove_file(&tmp).ok();
    assert!(
        files.is_empty(),
        "File path should return empty vec, got {:?}",
        files
    );
}

#[test]
fn test_empty_directory_returns_empty() {
    let dir = std::env::temp_dir().join("leanreel_test_empty_dir");
    fs::create_dir_all(&dir).unwrap();
    let (files, _) = find_video_files(&dir);
    fs::remove_dir_all(&dir).ok();
    assert!(files.is_empty());
}

#[test]
fn test_filters_by_extension() {
    let dir = std::env::temp_dir().join("leanreel_test_filter");
    fs::create_dir_all(&dir).unwrap();
    fs::write(dir.join("video.mkv"), b"x").unwrap();
    fs::write(dir.join("video.MP4"), b"x").unwrap();
    fs::write(dir.join("video.AVI"), b"x").unwrap();
    fs::write(dir.join("video.webm"), b"x").unwrap();
    fs::write(dir.join("readme.txt"), b"x").unwrap();
    fs::write(dir.join("poster.jpg"), b"x").unwrap();

    let (files, _) = find_video_files(&dir);
    fs::remove_dir_all(&dir).ok();

    assert_eq!(
        files.len(),
        4,
        "Should find 4 video files, ignoring .txt and .jpg"
    );
    let names: Vec<&str> = files
        .iter()
        .map(|(_, p)| p.file_name().unwrap().to_str().unwrap())
        .collect();
    assert!(names.contains(&"video.mkv"));
    assert!(names.contains(&"video.MP4"));
    assert!(names.contains(&"video.AVI"));
    assert!(names.contains(&"video.webm"));
}

#[test]
fn test_returns_relative_paths() {
    let dir = std::env::temp_dir().join("leanreel_test_relpath");
    fs::create_dir_all(&dir.join("subdir")).unwrap();
    fs::write(dir.join("subdir").join("movie.mkv"), b"x").unwrap();

    let (files, _) = find_video_files(&dir);
    fs::remove_dir_all(&dir).ok();

    assert_eq!(files.len(), 1);
    let (rel, abs) = &files[0];
    assert_eq!(
        rel, "subdir/movie.mkv",
        "Relative path should use forward slashes"
    );
    assert!(
        abs.ends_with("subdir/movie.mkv"),
        "Absolute path should end with relative: {:?}",
        abs
    );
}
