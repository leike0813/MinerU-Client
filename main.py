# Nuitka project options for reproducible builds
#
# 基础构建模式（跨平台）
# nuitka-project: --standalone
#
# 启用 PySide6 插件并携带常用 Qt 插件
# nuitka-project: --enable-plugin=pyside6
# nuitka-project: --include-qt-plugins=sensible,styles
#
# 避免将测试代码打进发行包
# nuitka-project: --follow-imports
# nuitka-project: --nofollow-import-to=tests
#
# 打包产物与清理策略
# nuitka-project: --output-dir=dist
# nuitka-project: --remove-output
#
# 运行所需的非 Python 数据文件（相对主脚本路径）
# nuitka-project: --include-data-files={MAIN_DIRECTORY}/ui/theme/dark.qss=ui/theme/dark.qss
# nuitka-project: --include-data-files={MAIN_DIRECTORY}/docs/API_DOC.md=docs/API_DOC.md
# nuitka-project: --include-data-files={MAIN_DIRECTORY}/docs/ARCHITECTURE.md=docs/ARCHITECTURE.md
#
# Windows 平台隐藏控制台窗口（不弹出黑框）
# nuitka-project-if: {OS} == "Windows":
#    nuitka-project: --windows-console-mode=disable

"""Application entry point for the MinerU desktop client."""

from app import run


if __name__ == "__main__":
    # Defer execution to the high-level bootstrap defined in app.run.
    run()
