# PyInstaller spec for LeanReel
# Usage: pyinstaller build.spec

a = Analysis(
    ['leanreel/main.py'],
    pathex=[],
    binaries=[
        ('leanreel/resources/ffmpeg/ffmpeg.exe', 'leanreel/resources/ffmpeg'),
        ('leanreel/resources/ffmpeg/ffprobe.exe', 'leanreel/resources/ffmpeg'),
        ('leanreel/resources/dovi_tool/dovi_tool.exe', 'leanreel/resources/dovi_tool'),
    ],
    datas=[
        ('leanreel/resources/strategies', 'leanreel/resources/strategies'),
    ],
    hiddenimports=['PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets'],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name='LeanReel',
    icon=None,
    console=False,
)
