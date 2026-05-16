"""NAS 扫描性能诊断脚本 — 定位瓶颈到底是目录遍历还是编码探测"""
import os
import subprocess
import sys
import time

NAS_PATH = r"\\Nas\nas-toshiba-mg08\TV"
VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".ts", ".mov", ".wmv", ".m2ts", ".mts"}


def find_videos_scandir(root: str):
    results = []
    dirs_ok = 0
    dirs_fail = 0

    def walk(current):
        nonlocal dirs_ok, dirs_fail
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            dirs_ok += 1
                            walk(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            ext = os.path.splitext(entry.name)[1].lower()
                            if ext in VIDEO_EXTS:
                                results.append(entry.path)
                    except OSError:
                        dirs_fail += 1
        except OSError:
            dirs_fail += 1

    t0 = time.time()
    walk(root)
    elapsed = time.time() - t0
    return results, elapsed, dirs_ok, dirs_fail


def test_stat(files, sample=30):
    """测试 os.stat 延迟"""
    import random
    sample_files = random.sample(files, min(sample, len(files)))
    times = []
    fails = 0
    for f in sample_files:
        t0 = time.time()
        try:
            os.stat(f)
            times.append(time.time() - t0)
        except OSError:
            fails += 1
    if not times:
        return 0, 0, fails
    return sum(times) / len(times), max(times), fails


def test_ffprobe(files, ffprobe="ffprobe", sample=5):
    import random
    sample_files = random.sample(files, min(sample, len(files)))
    results = []
    for f in sample_files:
        t0 = time.time()
        try:
            r = subprocess.run(
                [
                    ffprobe, "-v", "quiet", "-print_format", "json",
                    "-show_format", "-show_streams",
                    "-probesize", "2M", "-analyzeduration", "500000",
                    f,
                ],
                capture_output=True, text=True, timeout=30,
            )
            elapsed = time.time() - t0
            results.append((os.path.basename(f), elapsed, r.returncode == 0, len(r.stdout)))
        except subprocess.TimeoutExpired:
            results.append((os.path.basename(f), 30.0, False, 0))
        except Exception as e:
            results.append((os.path.basename(f), time.time() - t0, False, str(e)[:60]))
    return results


def find_ffprobe():
    """尝试找到项目内置的 ffprobe"""
    import glob
    # 从脚本所在目录向上找
    start = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        pattern = os.path.join(start, "**", "ffprobe.exe")
        matches = glob.glob(pattern, recursive=True)
        for m in matches:
            # 排除 .worktrees 目录
            if ".worktrees" not in m:
                return m
        start = os.path.dirname(start)
    return "ffprobe"


def main():
    print("=== NAS 扫描性能诊断 ===")
    print(f"路径: {NAS_PATH}")
    print(f"路径存在: {os.path.exists(NAS_PATH)}")
    print()

    # 1. 遍历
    print("1/4 正在遍历目录...")
    files, scandir_t, dirs_ok, dirs_fail = find_videos_scandir(NAS_PATH)
    print(f"   耗时: {scandir_t:.1f}s | 目录: {dirs_ok} ok / {dirs_fail} fail")
    print(f"   视频文件数: {len(files)}")
    if not files:
        print("   [无视频文件，终止]")
        return
    print()

    # 2. stat 延迟
    print("2/4 测试 os.stat() 延迟...")
    avg_stat, max_stat, stat_fails = test_stat(files)
    print(f"   平均: {avg_stat*1000:.0f}ms | 最差: {max_stat*1000:.0f}ms | 失败: {stat_fails}")
    estimated_stat_total = avg_stat * len(files)
    print(f"   全量 stat 预估: {estimated_stat_total:.1f}s")
    print()

    # 3. ffprobe
    print("3/4 测试 ffprobe 探测 (probesize=2M, timeout=30s)...")
    ffprobe = find_ffprobe()
    print(f"   使用: {ffprobe}")
    probe_results = test_ffprobe(files, ffprobe)
    for name, elapsed, ok, detail in probe_results:
        if ok:
            print(f"   OK  {elapsed:.1f}s  {name}")
        else:
            print(f"   FAIL {elapsed:.1f}s  {name}  ({detail})")
    ok_times = [e for _, e, ok, _ in probe_results if ok]
    if ok_times:
        avg_probe = sum(ok_times) / len(ok_times)
        print(f"   平均探测: {avg_probe:.1f}s/文件")
    print()

    # 4. 预估总时长
    print("4/4 预估全量扫描总时长")
    workers = 4
    if ok_times:
        avg_probe = sum(ok_times) / len(ok_times)
        probe_total = (len(files) / workers) * avg_probe
    else:
        probe_total = 0
    total = scandir_t + estimated_stat_total + probe_total

    print(f"   目录遍历:     {scandir_t:.1f}s")
    print(f"   stat (全量):  {estimated_stat_total:.1f}s")
    print(f"   探测 ({workers} workers): {probe_total:.1f}s")
    print(f"   ──────────────────────────")
    print(f"   预估总时长:    {total:.1f}s ({total/60:.1f} min)")
    print()

    # 瓶颈判断
    parts = {"目录遍历": scandir_t, "stat": estimated_stat_total, "ffprobe探测": probe_total}
    worst = max(parts, key=parts.get)
    print(f"   瓶颈 → {worst} ({parts[worst]:.1f}s)")
    if parts[worst] == parts["目录遍历"] and parts[worst] > 30:
        print("   建议: scandir 遍历太慢，考虑增量扫描或缓存目录结构")
    if parts[worst] == parts["ffprobe探测"] and avg_probe > 5:
        print(f"   建议: 单文件探测仍然慢 ({avg_probe:.1f}s)，网络延迟可能是主因")


if __name__ == "__main__":
    main()
