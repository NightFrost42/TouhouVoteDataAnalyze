"""无控制台窗口的 Windows 启动入口，失败时写日志并显示原生弹窗。"""

from pathlib import Path
import ctypes
import sys
import traceback


def report_error(details: str) -> None:
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    log_path = base / "launcher_error.log"
    try:
        log_path.write_text(details, encoding="utf-8")
    except OSError:
        pass
    message = f"程序启动失败。\n\n错误日志：{log_path}\n\n{details[-1200:]}"
    try:
        ctypes.windll.user32.MessageBoxW(None, message, "东方投票分析工具", 0x10)
    except Exception:
        pass


if __name__ == "__main__":
    try:
        from app import run

        run()
    except BaseException:
        report_error(traceback.format_exc())
