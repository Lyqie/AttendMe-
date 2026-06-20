"""
AttendMe — 云端多模态注意力检测系统

Entry point. Wires together screen capture, model inference, data persistence,
and the PySide6 UI.

Uses DashScope (Alibaba Cloud) API for Qwen VL model inference.

Usage:
    python main.py                    # start with default config
    python main.py --config my.json   # custom config path

Prerequisites:
    1. 在 config.json 中填写 api_key（DashScope API Key）
    2. 或设置环境变量 DASHSCOPE_API_KEY
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QMessageBox

from data_manager import DataManager
from model_inference import CloudVLClient, InferenceWorker, SYSTEM_PROMPT
from screen_capture import ScreenCapture
from ui_components import ExpandedWindow, FloatingWidget, SystemTray

CONFIG_PATH = Path(__file__).parent / "config.json"


# ── Config loader ─────────────────────────────────────────────────────────────

def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        print(f"[AttendMe] 配置文件 {path} 不存在，使用默认值。")
        return _default_config()
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _default_config() -> dict[str, Any]:
    return {
        "model": {"provider": "dashscope", "model_name": "qwen3.5-vl-flash",
                   "api_key": "", "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                   "timeout_seconds": 30, "max_retries": 2},
        "capture": {"interval_seconds": 4, "monitor_index": 0,
                     "max_dimension": 1024, "image_quality": 75},
        "ui": {"opacity": 0.94, "always_on_top": True,
                "collapsed_size": [190, 260], "expanded_size": [520, 600],
                "position": [60, 120], "frosted_glass": True},
        "whitelist": {"process_names": [], "window_titles": []},
        "ignore_duration_minutes": 5,
    }


# ── Main application ──────────────────────────────────────────────────────────

class AttendMeApp:
    """Orchestrates the entire attention monitoring pipeline."""

    def __init__(self, config: dict[str, Any]):
        self._cfg = config

        # Data layer
        self._dm = DataManager()
        self._seed_whitelist_from_config()

        # Screen capture
        cap = config["capture"]
        self._capture = ScreenCapture(
            monitor_index=cap.get("monitor_index", 0),
            max_dimension=cap.get("max_dimension", 1024),
            quality=cap.get("image_quality", 75),
        )

        # Model client (cloud API)
        mdl = config["model"]
        self._client = CloudVLClient(
            api_key=mdl.get("api_key", ""),
            base_url=mdl.get("api_base", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            model=mdl.get("model_name", "qwen3.5-vl-flash"),
            timeout=mdl.get("timeout_seconds", 30),
        )
        self._worker = InferenceWorker(self._client)

        # UI
        self._float = FloatingWidget(
            self._dm,
            on_ignore=self._on_ignore,
            on_expand=self._on_expand,
        )
        self._expanded = ExpandedWindow(self._dm)

        # System tray
        self._tray = SystemTray(
            on_show_float=self._float.show,
            on_show_expanded=self._on_expand,
            on_quit=self._shutdown,
        )

        # Capture timer
        interval_ms = cap.get("interval_seconds", 4) * 1000
        self._timer = QTimer()
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._tick)

        # Signal wiring
        self._worker.result_ready.connect(self._on_result)
        self._worker.error_occurred.connect(self._on_error)
        self._expanded.ring.set_score(0, animate=False)

        # State
        self._last_process = ""
        self._last_title = ""
        self._error_count = 0
        self._max_errors = 3

    # ── lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        ui = self._cfg.get("ui", {})
        pos = ui.get("position", [60, 120])
        self._float.move(pos[0], pos[1])
        self._float.show()

        # Check API connectivity
        print("[AttendMe] 检查 API 连接…")
        if self._client.health_check():
            print("[AttendMe] ✓ API 已连接")
            models = self._client.list_models()
            vl_models = [m for m in models if "vl" in m.lower()]
            if vl_models:
                print(f"[AttendMe] 可用 VL 模型: {', '.join(vl_models)}")
            print(f"[AttendMe] 当前使用: {self._client._model}")
        else:
            print("[AttendMe] ⚠ 无法连接 API — 请确认 api_key 已配置")
            self._float.set_safe_title("⚠ API 未连接")
            QMessageBox.warning(
                self._float, "API 未连接",
                "无法连接到 DashScope API。\n\n"
                "请确认：\n"
                "1. 在 config.json 中填写了 api_key\n"
                "2. 或设置了环境变量 DASHSCOPE_API_KEY\n\n"
                "配置后重新启动 AttendMe。"
            )

        self._tray.show()
        self._timer.start()
        print(f"[AttendMe] 开始监测，间隔 {self._cfg['capture']['interval_seconds']} 秒")
        # Run first tick immediately
        QTimer.singleShot(500, self._tick)

    def _shutdown(self) -> None:
        print("[AttendMe] 正在退出…")
        self._timer.stop()
        self._worker.stop()
        self._dm.close()
        self._float.close()
        self._expanded.close()
        QApplication.quit()

    # ── main loop tick ────────────────────────────────────────────────────

    def _tick(self) -> None:
        """Captures screen, checks whitelist/ignore, and queues inference."""
        # Clean expired ignores
        self._dm.cleanup_expired_ignores()

        # Capture
        try:
            img_b64 = self._capture.capture_to_base64()
            process, title = self._capture.get_active_window_info()
        except Exception as exc:
            print(f"[AttendMe] 截图失败: {exc}")
            return

        self._last_process = process
        self._last_title = title

        # Update floating window title
        self._float.set_window_title(title or process or "—")

        # Check whitelist → skip model, assign high score
        is_wl = self._dm.is_whitelisted(process, title)
        # Also check config whitelist
        wl_cfg = self._cfg.get("whitelist", {})
        config_wl = False
        for pname in wl_cfg.get("process_names", []):
            if pname.lower() in process.lower():
                config_wl = True
                break
        if not config_wl:
            for wtitle in wl_cfg.get("window_titles", []):
                if wtitle.lower() in title.lower():
                    config_wl = True
                    break

        if is_wl or config_wl:
            self._on_result({
                "score": 95, "category": "high",
                "activity": "whitelisted",
                "reasoning": "用户已将此应用加入白名单",
                "_inference_time": 0,
            })
            return

        # Check ignore list
        if self._dm.is_ignored(process, title):
            self._on_result({
                "score": 80, "category": "medium",
                "activity": "ignored",
                "reasoning": "用户已暂时忽略此窗口",
                "_inference_time": 0,
            })
            return

        # Queue model inference
        self._worker.infer(img_b64, SYSTEM_PROMPT)

    # ── signals ───────────────────────────────────────────────────────────

    def _on_result(self, result: dict[str, Any]) -> None:
        score = result.get("score", 50)
        category = result.get("category", "medium")
        activity = result.get("activity", "")
        reasoning = result.get("reasoning", "")

        # Store to DB
        self._dm.add_snapshot(
            score=score, category=category, activity=activity,
            reasoning=reasoning, process=self._last_process,
            window_title=self._last_title,
            ignored=(activity in ("whitelisted", "ignored")),
        )

        # Update UI
        self._float.ring.set_score(score)
        self._expanded.ring.set_score(score, animate=False)  # sync but no anim

        # Update expanded window if visible
        if self._expanded.isVisible():
            self._expanded.refresh()

        self._error_count = 0  # reset error counter on success
        elapsed = result.get("_inference_time", 0)
        print(f"[AttendMe] 分数={score} 类别={category} 活动={activity} "
              f"耗时={elapsed:.1f}s")

    def _on_error(self, message: str) -> None:
        self._error_count += 1
        print(f"[AttendMe] 错误 ({self._error_count}/{self._max_errors}): {message}")

        if self._error_count >= self._max_errors:
            self._float.set_safe_title("⚠ 推理异常")
            self._timer.stop()
            QMessageBox.critical(
                self._float, "推理错误",
                f"连续 {self._max_errors} 次推理失败:\n{message}\n\n"
                "请检查 API Key 和网络连接。\n"
                "可在托盘菜单中重启监测。"
            )

    # ── actions ───────────────────────────────────────────────────────────

    def _on_ignore(self) -> None:
        duration = self._cfg.get("ignore_duration_minutes", 5)
        self._dm.add_ignore(self._last_process, self._last_title, duration)
        self._float.set_safe_title(f"已忽略 {duration} 分钟")
        QTimer.singleShot(3000, lambda: self._float.set_window_title(
            self._last_title or "—"))

    def _on_expand(self) -> None:
        if self._expanded.isVisible():
            self._expanded.hide()
        else:
            # Position next to floating widget
            fg = self._float.geometry()
            self._expanded.move(fg.right() + 12, fg.top())
            self._expanded.refresh()
            self._expanded.show()

    def _seed_whitelist_from_config(self) -> None:
        """Copy config-level whitelist entries into the DB on first run."""
        wl = self._cfg.get("whitelist", {})
        for pname in wl.get("process_names", []):
            self._dm.add_whitelist(pname, "process")
        for wtitle in wl.get("window_titles", []):
            self._dm.add_whitelist(wtitle, "title")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AttendMe — 本地注意力检测系统"
    )
    parser.add_argument("--config", type=Path, default=CONFIG_PATH,
                        help="配置文件路径 (默认: config.json)")
    parser.add_argument("--no-float", action="store_true",
                        help="启动时不显示悬浮窗，仅驻留托盘")
    args = parser.parse_args()

    config = load_config(args.config)

    app = QApplication(sys.argv)
    app.setApplicationName("AttendMe")
    app.setQuitOnLastWindowClosed(False)  # keep alive in tray

    # Dark palette
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(18, 18, 22))
    palette.setColor(QPalette.WindowText, QColor(235, 235, 245))
    app.setPalette(palette)

    monitor = AttendMeApp(config)
    monitor.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
