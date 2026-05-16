"""逐个文件探测，找出导致卡死的文件"""
import os
import subprocess
import sys
import time
import glob as globmod

NAS_PATH = r"\\Nas\nas-toshiba-mg08\TV"
VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".ts", ".mov", ".wmv", ".m2ts", ".mts"}

# ---- 找 ffprobe ----
def find_ffprobe():
    start = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        for m in globmod.glob(os.path.join(start, "**", "ffprobe.exe"), recursive=True):
            if ".worktrees" not in m:
                return m
        start = os.path.dirname(start)
    return "ffprobe"

# ---- 收集文件 ----
print(f"正在遍历: {NAS_PATH}")
t0 = time.time()
all_files = []

def walk(d):
    try:
        with os.scandir(d) as entries:
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        walk(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        ext = os.path.splitext(entry.name)[1].lower()
                        if ext in VIDEO_EXTS:
                            all_files.append(entry.path)
                except OSError:
                    pass
    except OSError:
        pass

walk(NAS_PATH)
print(f"  找到 {len(all_files)} 个视频文件 (耗时 {time.time()-t0:.1f}s)")
print()

# ---- 逐个探测 ----
ffprobe = find_ffprobe()
print(f"ffprobe: {ffprobe}")
print(f"逐个探测 (超时 15s/文件)...")
print()

ok_count = 0
fail_count = 0
slow_files = []  # >5s 的文件
total = len(all_files)
t_start = time.time()

for i, f in enumerate(all_files):
    name = os.path.basename(f)
    t_file = time.time()
    try:
        r = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams",
             "-probesize", "2M", "-analyzeduration", "500000", f],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15,
        )
        elapsed = time.time() - t_file
        if r.returncode == 0 and r.stdout:
            ok_count += 1
            if elapsed > 5:
                slow_files.append((name, elapsed))
                print(f"  [{i+1}/{total}] SLOW {elapsed:.1f}s  {name}")
        else:
            fail_count += 1
            print(f"  [{i+1}/{total}] FAIL {elapsed:.1f}s  {name}  (rc={r.returncode})", flush=True)
    except subprocess.TimeoutExpired:
        fail_count += 1
        elapsed = time.time() - t_file
        slow_files.append((name, elapsed))
        print(f"  [{i+1}/{total}] TIMEOUT {elapsed:.1f}s  {name}", flush=True)
    except Exception as e:
        fail_count += 1
        print(f"  [{i+1}/{total}] ERROR  {name}  ({e})", flush=True)

    # 每 50 个报告一次进度
    if (i + 1) % 50 == 0:
        elapsed_total = time.time() - t_start
        rate = (i + 1) / elapsed_total
        eta = (total - i - 1) / rate
        print(f"  --- 进度: {i+1}/{total} | "
              f"成功: {ok_count} | 失败: {fail_count} | "
              f"速率: {rate:.1f}/s | 预计剩余: {eta:.0f}s ---", flush=True)

print()
print("=" * 50)
elapsed_total = time.time() - t_start
print(f"完成! 总计 {total} 个文件, 耗时 {elapsed_total:.1f}s")
print(f"  成功: {ok_count}  失败: {fail_count}")
print(f"  平均: {elapsed_total/total:.1f}s/文件")
if slow_files:
    print(f"  慢文件 (>5s, 共 {len(slow_files)} 个):")
    for name, dur in sorted(slow_files, key=lambda x: -x[1])[:10]:
        print(f"    {dur:.1f}s  {name}")
