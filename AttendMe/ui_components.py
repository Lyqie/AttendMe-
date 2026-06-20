"""
UI components for AttendMe — modern, glass-morphism styled PySide6 widgets.

Components:
  ScoreRingWidget   – animated circular progress ring with glow
  HistoryChart      – custom QPainter trend chart with gradient fill
  StatsPanel        – today's statistics summary
  FloatingWidget    – main collapsed floating window
  ExpandedWindow    – detailed view with chart + stats
  SystemTray        – system tray icon with context menu
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import (
    QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRectF, Qt,
    QTimer, Property, Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QFont, QIcon, QLinearGradient, QMouseEvent,
    QPainter, QPainterPath, QPen, QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMenu, QPushButton,
    QSystemTrayIcon, QVBoxLayout, QWidget,
)

from data_manager import DataManager

# ── Theme constants ───────────────────────────────────────────────────────────

COLOR_BG = QColor(18, 18, 22, 230)          # dark glass background
COLOR_SURFACE = QColor(30, 30, 38, 200)     # card surface
COLOR_BORDER = QColor(255, 255, 255, 25)    # subtle border
COLOR_TEXT = QColor(235, 235, 245)           # primary text
COLOR_TEXT_DIM = QColor(160, 160, 175)       # secondary text
COLOR_GREEN = QColor(46, 213, 115)           # high focus
COLOR_ORANGE = QColor(255, 165, 2)           # medium focus
COLOR_RED = QColor(255, 71, 87)              # low focus
COLOR_ACCENT = QColor(99, 140, 255)          # interactive accent


def _score_color(score: int) -> QColor:
    """Return a smooth interpolated color for the given score: red→orange→green."""
    t = max(0, min(100, score)) / 100.0
    if t < 0.5:
        # red → orange
        r = COLOR_RED.red() + (COLOR_ORANGE.red() - COLOR_RED.red()) * (t * 2)
        g = COLOR_RED.green() + (COLOR_ORANGE.green() - COLOR_RED.green()) * (t * 2)
        b = COLOR_RED.blue() + (COLOR_ORANGE.blue() - COLOR_RED.blue()) * (t * 2)
    else:
        # orange → green
        s = (t - 0.5) * 2
        r = COLOR_ORANGE.red() + (COLOR_GREEN.red() - COLOR_ORANGE.red()) * s
        g = COLOR_ORANGE.green() + (COLOR_GREEN.green() - COLOR_ORANGE.green()) * s
        b = COLOR_ORANGE.blue() + (COLOR_GREEN.blue() - COLOR_ORANGE.blue()) * s
    return QColor(int(r), int(g), int(b))


def _truncate(text: str, max_len: int = 28) -> str:
    """Truncate text with ellipsis if too long."""
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "…"


# ═══════════════════════════════════════════════════════════════════════════════
# Score Ring Widget
# ═══════════════════════════════════════════════════════════════════════════════

class ScoreRingWidget(QWidget):
    """Animated circular progress ring with glow effect and central score display."""

    scoreChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._score: int = 0
        self._display_score: float = 0.0
        self._anim: QPropertyAnimation | None = None
        self.setFixedSize(150, 150)
        self.setAttribute(Qt.WA_TranslucentBackground)

    # ── animated property ─────────────────────────────────────────────────

    def get_display_score(self) -> float:
        return self._display_score

    def set_display_score(self, value: float) -> None:
        self._display_score = value
        self.update()

    displayScore = Property(float, get_display_score, set_display_score)

    def set_score(self, new_score: int, animate: bool = True) -> None:
        if new_score == self._score and animate:
            return
        old = self._score
        self._score = max(0, min(100, new_score))

        if animate and self.isVisible():
            self._anim = QPropertyAnimation(self, b"displayScore")
            self._anim.setDuration(500)
            self._anim.setStartValue(float(old))
            self._anim.setEndValue(float(self._score))
            self._anim.setEasingCurve(QEasingCurve.OutCubic)
            self._anim.start()
        else:
            self._display_score = float(self._score)
            self.update()

        self.scoreChanged.emit(self._score)

    def score(self) -> int:
        return self._score

    # ── painting ──────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        radius = min(w, h) / 2.0 - 10
        ring_width = 9.0

        color = _score_color(int(self._display_score))
        angle_span = int(self._display_score) / 100.0 * 360.0

        # ── background track ──
        pen_track = QPen(QColor(255, 255, 255, 20), ring_width, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen_track)
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(cx - radius, cy - radius, radius * 2, radius * 2),
                  90 * 16, -360 * 16)

        # ── glow layer ──
        glow_color = QColor(color.red(), color.green(), color.blue(), 60)
        pen_glow = QPen(glow_color, ring_width + 8, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen_glow)
        p.drawArc(QRectF(cx - radius, cy - radius, radius * 2, radius * 2),
                  90 * 16, -int(angle_span * 16))

        # ── progress arc ──
        pen_arc = QPen(color, ring_width, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen_arc)
        p.drawArc(QRectF(cx - radius, cy - radius, radius * 2, radius * 2),
                  90 * 16, -int(angle_span * 16))

        # ── inner gradient circle ──
        inner_radius = radius - ring_width - 4
        gradient = QRadialGradient(cx, cy - inner_radius * 0.3, inner_radius * 1.4)
        gradient.setColorAt(0, QColor(45, 45, 55, 180))
        gradient.setColorAt(1, QColor(20, 20, 28, 220))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(gradient))
        p.drawEllipse(QPoint(int(cx), int(cy)), int(inner_radius), int(inner_radius))

        # ── score text ──
        font_score = QFont("Segoe UI", 34, QFont.Light)
        p.setFont(font_score)
        p.setPen(QColor(255, 255, 255, 240))
        p.drawText(QRectF(0, cy - 32, w, 50), Qt.AlignHCenter | Qt.AlignVCenter,
                   str(int(self._display_score)))

        # ── category label ──
        font_cat = QFont("Segoe UI", 9, QFont.Normal)
        p.setFont(font_cat)
        cat, cat_color = self._category_info()
        p.setPen(cat_color)
        p.drawText(QRectF(0, cy + 14, w, 20), Qt.AlignHCenter, cat)

        p.end()

    def _category_info(self) -> tuple[str, QColor]:
        s = int(self._display_score)
        if s >= 80:
            return ("专注", COLOR_GREEN)
        elif s >= 40:
            return ("一般", COLOR_ORANGE)
        return ("分心", COLOR_RED)


# ═══════════════════════════════════════════════════════════════════════════════
# History Chart (custom QPainter — zero extra dependencies)
# ═══════════════════════════════════════════════════════════════════════════════

class HistoryChart(QWidget):
    """Trend chart displaying attention scores over time with gradient fill.

    Painted entirely with QPainter — no pyqtgraph / matplotlib dependency.
    """

    CHART_BG = QColor(24, 24, 30)
    GRID_COLOR = QColor(255, 255, 255, 12)
    LINE_COLOR = QColor(99, 140, 255)
    FILL_TOP = QColor(99, 140, 255, 55)
    FILL_BOTTOM = QColor(99, 140, 255, 5)
    THRESHOLD_HIGH = QColor(46, 213, 115, 70)
    THRESHOLD_LOW = QColor(255, 71, 87, 50)

    MARGIN_L = 38
    MARGIN_R = 12
    MARGIN_T = 10
    MARGIN_B = 28

    def __init__(self, data_manager: DataManager, parent: QWidget | None = None):
        super().__init__(parent)
        self._dm = data_manager
        self._range_minutes = 15
        self._points: list[tuple[float, float]] = []  # (timestamp, score)
        self._hover_index: int = -1
        self.setMinimumHeight(180)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)

    def set_range(self, minutes: int) -> None:
        self._range_minutes = minutes
        self.refresh()

    def refresh(self) -> None:
        snapshots = self._dm.get_recent_scores(self._range_minutes)
        pts: list[tuple[float, float]] = []
        for s in snapshots:
            try:
                ts = datetime.strptime(s["timestamp"], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            pts.append((ts.timestamp(), float(s["score"])))
        self._points = pts
        self.update()

    # ── coordinate mapping ────────────────────────────────────────────────

    def _plot_rect(self) -> QRectF:
        r = self.rect()
        return QRectF(
            r.left() + self.MARGIN_L, r.top() + self.MARGIN_T,
            r.width() - self.MARGIN_L - self.MARGIN_R,
            r.height() - self.MARGIN_T - self.MARGIN_B,
        )

    def _to_pixel(self, t: float, score: float, pr: QRectF) -> QPointF:
        """Map (timestamp, score) → pixel coordinates within the plot rect."""
        now = datetime.now().timestamp()
        t_min = now - self._range_minutes * 60
        t_range = max(1, now - t_min)

        x = pr.left() + (t - t_min) / t_range * pr.width()
        y = pr.bottom() - (score / 100.0) * pr.height()
        return QPointF(x, y)

    # ── painting ──────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        pr = self._plot_rect()

        # Background
        path_bg = QPainterPath()
        path_bg.addRoundedRect(QRectF(self.rect()), 12, 12)
        p.fillPath(path_bg, QBrush(self.CHART_BG))

        # Clip to plot area
        p.save()
        p.setClipRect(pr)

        # ── grid lines ──
        pen_grid = QPen(self.GRID_COLOR, 1, Qt.DotLine)
        p.setPen(pen_grid)
        for y_val in (0, 25, 50, 75, 100):
            y = pr.bottom() - (y_val / 100.0) * pr.height()
            p.drawLine(QPointF(pr.left(), y), QPointF(pr.right(), y))

        # ── threshold bands ──
        y80 = pr.bottom() - 0.8 * pr.height()
        y40 = pr.bottom() - 0.4 * pr.height()

        # High zone (80-100)
        p.fillRect(QRectF(pr.left(), pr.top(), pr.width(), y80 - pr.top()),
                   QColor(46, 213, 115, 10))

        # Low zone (0-40)
        p.fillRect(QRectF(pr.left(), y40, pr.width(), pr.bottom() - y40),
                   QColor(255, 71, 87, 10))

        # Threshold lines
        pen_h = QPen(self.THRESHOLD_HIGH, 1, Qt.DashLine)
        p.setPen(pen_h)
        p.drawLine(QPointF(pr.left(), y80), QPointF(pr.right(), y80))
        pen_l = QPen(self.THRESHOLD_LOW, 1, Qt.DashLine)
        p.setPen(pen_l)
        p.drawLine(QPointF(pr.left(), y40), QPointF(pr.right(), y40))

        # ── data ──
        if len(self._points) >= 2:
            pixels = [self._to_pixel(t, s, pr) for t, s in self._points]

            # Gradient fill below curve
            fill_path = QPainterPath()
            fill_path.moveTo(pixels[0].x(), pr.bottom())
            for pt in pixels:
                fill_path.lineTo(pt)
            fill_path.lineTo(pixels[-1].x(), pr.bottom())
            fill_path.closeSubpath()

            grad = QLinearGradient(0, pr.top(), 0, pr.bottom())
            grad.setColorAt(0, self.FILL_TOP)
            grad.setColorAt(1, self.FILL_BOTTOM)
            p.fillPath(fill_path, QBrush(grad))

            # Line
            pen_line = QPen(self.LINE_COLOR, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            p.setPen(pen_line)
            line_path = QPainterPath()
            line_path.moveTo(pixels[0])
            for pt in pixels[1:]:
                line_path.lineTo(pt)
            p.drawPath(line_path)

            # Data point dots
            dot_pen = QPen(QColor(24, 24, 30), 1.5)
            dot_brush = QBrush(self.LINE_COLOR)
            p.setPen(dot_pen)
            p.setBrush(dot_brush)
            for pt in pixels:
                p.drawEllipse(pt, 3.5, 3.5)

            # ── hover highlight ──
            if 0 <= self._hover_index < len(pixels):
                hp = pixels[self._hover_index]
                p.setPen(QPen(QColor(255, 255, 255, 180), 2))
                p.setBrush(QBrush(self.LINE_COLOR.lighter(130)))
                p.drawEllipse(hp, 6, 6)

        # ── no-data placeholder ──
        elif len(self._points) == 0:
            p.setPen(QColor(160, 160, 175, 120))
            font = QFont("Segoe UI", 11)
            p.setFont(font)
            p.drawText(pr, Qt.AlignCenter, "等待数据…")

        p.restore()

        # ── Y-axis labels ──
        font_axis = QFont("Segoe UI", 8)
        p.setFont(font_axis)
        p.setPen(QColor(160, 160, 175))
        for y_val in (0, 25, 50, 75, 100):
            y = pr.bottom() - (y_val / 100.0) * pr.height()
            label = str(y_val)
            tw = p.fontMetrics().horizontalAdvance(label)
            p.drawText(QPointF(pr.left() - 6 - tw, y + 4), label)

        # ── X-axis time labels ──
        if len(self._points) >= 2:
            now = datetime.now().timestamp()
            t_min = now - self._range_minutes * 60
            # Show ~5 evenly spaced labels
            count = min(5, len(self._points))
            for i in range(count):
                frac = i / max(1, count - 1)
                t = t_min + frac * (now - t_min)
                x = pr.left() + frac * pr.width()
                label = datetime.fromtimestamp(t).strftime("%H:%M")
                tw = p.fontMetrics().horizontalAdvance(label)
                p.drawText(QPointF(x - tw / 2, pr.bottom() + 16), label)

        p.end()

    # ── mouse hover ───────────────────────────────────────────────────────

    def mouseMoveEvent(self, event) -> None:
        pr = self._plot_rect()
        mx = event.position().x()

        if len(self._points) < 2 or not pr.contains(event.position()):
            self._hover_index = -1
            self.setToolTip("")
            self.update()
            return

        pixels = [self._to_pixel(t, s, pr) for t, s in self._points]

        # Find nearest data point
        nearest = 0
        best_dist = float("inf")
        for i, pt in enumerate(pixels):
            dist = abs(pt.x() - mx)
            if dist < best_dist:
                best_dist = dist
                nearest = i

        # Only highlight if within reasonable distance
        max_gap = pr.width() / max(1, len(self._points)) * 2
        if best_dist <= max_gap:
            self._hover_index = nearest
            t, s = self._points[nearest]
            ts_str = datetime.fromtimestamp(t).strftime("%H:%M:%S")
            self.setToolTip(f"{ts_str}  —  {int(s)} 分")
        else:
            self._hover_index = -1
            self.setToolTip("")

        self.update()

    def leaveEvent(self, event) -> None:
        self._hover_index = -1
        self.setToolTip("")
        self.update()


# ═══════════════════════════════════════════════════════════════════════════════
# Stats Panel
# ═══════════════════════════════════════════════════════════════════════════════

class StatsPanel(QWidget):
    """Displays today's statistics: focus time, average score, interruptions."""

    def __init__(self, data_manager: DataManager, parent: QWidget | None = None):
        super().__init__(parent)
        self._dm = data_manager
        self.setStyleSheet(self._sheet())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(6)

        title = QLabel("📊 今日统计")
        title.setStyleSheet("font-size:13px; font-weight:600; color:#d0d0d8;")
        layout.addWidget(title)

        self._focus_label = QLabel("专注时长: --")
        self._avg_label = QLabel("平均分数: --")
        self._interrupt_label = QLabel("打断次数: --")

        for lbl in (self._focus_label, self._avg_label, self._interrupt_label):
            lbl.setStyleSheet("font-size:12px; color:#a0a0b0; padding:2px 0;")
            layout.addWidget(lbl)

    @staticmethod
    def _sheet() -> str:
        return f"""
            QWidget {{
                background: rgba(30,30,38,180);
                border: 1px solid rgba(255,255,255,15);
                border-radius: 12px;
            }}
        """

    def refresh(self) -> None:
        stats = self._dm.get_today_stats()
        self._focus_label.setText(f"专注时长: {stats['focus_minutes']} 分钟")
        self._avg_label.setText(f"平均分数: {stats['avg_score']}")
        self._interrupt_label.setText(f"打断次数: {stats['interruptions']}")


# ═══════════════════════════════════════════════════════════════════════════════
# Glass-effect base
# ═══════════════════════════════════════════════════════════════════════════════

def _apply_frosted_glass(widget: QWidget, radius: int = 18) -> None:
    """Enable acrylic/frosted-glass backdrop on Windows 11 via DWM."""
    import ctypes
    try:
        hwnd = int(widget.winId())
        DWMWA_SYSTEMBACKDROP_TYPE = 38
        DWMSBT_ACRYLIC = 3
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_SYSTEMBACKDROP_TYPE,
            ctypes.byref(ctypes.c_int(DWMSBT_ACRYLIC)),
            ctypes.sizeof(ctypes.c_int),
        )
        # Dark mode
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(ctypes.c_int(1)),
            ctypes.sizeof(ctypes.c_int),
        )
    except Exception:
        pass  # fall back to custom painting


def _glass_sheet() -> str:
    """Shared stylesheet for glass-morphism surfaces."""
    return f"""
        QWidget {{
            background: rgba(18,18,22,220);
            border: 1px solid rgba(255,255,255,12);
            border-radius: 18px;
        }}
        QLabel {{ color: {COLOR_TEXT.name()}; background: transparent; border: none; }}
    """


def _button_sheet(base_color: str) -> str:
    return f"""
        QPushButton {{
            background: rgba({base_color}, 40);
            color: {COLOR_TEXT.name()};
            border: 1px solid rgba(255,255,255,10);
            border-radius: 8px;
            padding: 5px 12px;
            font-size: 11px;
        }}
        QPushButton:hover {{
            background: rgba({base_color}, 80);
            border: 1px solid rgba(255,255,255,25);
        }}
        QPushButton:pressed {{
            background: rgba({base_color}, 120);
        }}
    """


# ═══════════════════════════════════════════════════════════════════════════════
# Floating Widget (collapsed)
# ═══════════════════════════════════════════════════════════════════════════════

class FloatingWidget(QWidget):
    """Main floating overlay — ring, window title, action buttons."""

    def __init__(self, data_manager: DataManager,
                 on_ignore: callable = None,
                 on_expand: callable = None):
        super().__init__(None)
        self._dm = data_manager
        self._on_ignore = on_ignore
        self._on_expand = on_expand
        self._drag_pos: QPoint | None = None

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
            Qt.Tool | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(190, 260)

        # Attempt frosted glass
        self._apply_glass()

        # Drop shadow via QGraphicsDropShadowEffect on a container doesn't work
        # for top-level frameless well, so we skip it on the outer widget.

        self._setup_ui()
        self.setStyleSheet(_glass_sheet())

    def _apply_glass(self) -> None:
        _apply_frosted_glass(self)

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 12, 8, 10)
        main_layout.setSpacing(6)

        # ── Ring ──
        self.ring = ScoreRingWidget()
        ring_container = QHBoxLayout()
        ring_container.setAlignment(Qt.AlignHCenter)
        ring_container.addWidget(self.ring)
        main_layout.addLayout(ring_container)

        # ── Window title ──
        self.title_label = QLabel("—")
        self.title_label.setAlignment(Qt.AlignHCenter)
        self.title_label.setWordWrap(False)
        self.title_label.setStyleSheet(
            "font-size:10px; color:#b0b0bb; background:transparent; border:none; "
            "padding:2px 6px;"
        )
        main_layout.addWidget(self.title_label)

        # ── Buttons ──
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)
        btn_layout.setAlignment(Qt.AlignHCenter)

        self.ignore_btn = QPushButton("忽略 5 分钟")
        self.ignore_btn.setStyleSheet(_button_sheet("255,165,2"))
        self.ignore_btn.setCursor(Qt.PointingHandCursor)
        self.ignore_btn.clicked.connect(self._on_ignore_clicked)

        self.expand_btn = QPushButton("展开")
        self.expand_btn.setStyleSheet(_button_sheet("99,140,255"))
        self.expand_btn.setCursor(Qt.PointingHandCursor)
        self.expand_btn.clicked.connect(self._on_expand_clicked)

        btn_layout.addWidget(self.ignore_btn)
        btn_layout.addWidget(self.expand_btn)
        main_layout.addLayout(btn_layout)

        # ── context menu ──
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def set_window_title(self, title: str) -> None:
        self.title_label.setText(_truncate(title or "—", 24))
        self.title_label.setToolTip(title)

    def set_safe_title(self, text: str) -> None:
        """Set the title label to an arbitrary string (e.g. status message)."""
        self.title_label.setText(text)

    # ── dragging ──────────────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    # ── glass painting ────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 18, 18)
        p.fillPath(path, QBrush(QColor(18, 18, 22, 225)))
        p.setPen(QPen(QColor(255, 255, 255, 20), 1))
        p.drawPath(path)
        p.end()

    # ── callbacks ─────────────────────────────────────────────────────────

    def _on_ignore_clicked(self) -> None:
        if self._on_ignore:
            self._on_ignore()

    def _on_expand_clicked(self) -> None:
        if self._on_expand:
            self._on_expand()

    def _show_context_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #1e1e26; color: #e0e0e8; border: 1px solid #333;
                border-radius: 8px; padding: 4px;
            }
            QMenu::item { padding: 6px 24px; border-radius: 4px; }
            QMenu::item:selected { background: rgba(99,140,255,40); }
        """)
        menu.addAction("添加到白名单", self._add_to_whitelist)
        menu.addAction("忽略 5 分钟", self._on_ignore_clicked)
        menu.addSeparator()
        menu.addAction("导出 JSON…", self._export_json)
        menu.addAction("退出", QApplication.quit)
        menu.exec(self.mapToGlobal(pos))

    def _add_to_whitelist(self) -> None:
        title = self.title_label.text()
        if title and title != "—":
            self._dm.add_whitelist(title, "title")

    def _export_json(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "导出注意力数据", "attendme_export.json",
            "JSON Files (*.json)"
        )
        if path:
            saved = self._dm.export_json(path)
            self.title_label.setText(f"已导出: {saved.split('/')[-1]}")
            QTimer.singleShot(3000, lambda: self.title_label.setText("—"))


# ═══════════════════════════════════════════════════════════════════════════════
# Expanded Window
# ═══════════════════════════════════════════════════════════════════════════════

class ExpandedWindow(QWidget):
    """Detailed view showing ring, trend chart, and statistics."""

    def __init__(self, data_manager: DataManager, parent: QWidget | None = None):
        super().__init__(parent)
        self._dm = data_manager

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
            Qt.Tool | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(520, 600)
        _apply_frosted_glass(self)

        self._drag_pos: QPoint | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 14, 16, 14)
        main_layout.setSpacing(10)

        # ── Title bar ──
        title_bar = QHBoxLayout()
        title = QLabel("AttendMe · 专注监测")
        title.setStyleSheet("font-size:14px; font-weight:600; color:#d8d8e0; "
                            "background:transparent; border:none;")
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(_button_sheet("255,71,87"))
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self.hide)
        title_bar.addWidget(title)
        title_bar.addStretch()
        title_bar.addWidget(close_btn)
        main_layout.addLayout(title_bar)

        # ── Top row: ring + stats ──
        top_row = QHBoxLayout()
        top_row.setSpacing(16)

        self.ring = ScoreRingWidget()

        self.stats = StatsPanel(self._dm)

        top_row.addWidget(self.ring)
        top_row.addWidget(self.stats, 1)
        main_layout.addLayout(top_row)

        # ── Time range tabs ──
        range_layout = QHBoxLayout()
        range_layout.setSpacing(6)
        self._range_btns: dict[int, QPushButton] = {}
        for mins in (5, 15, 60):
            btn = QPushButton(f"{mins} 分钟")
            btn.setCheckable(True)
            btn.setStyleSheet(_button_sheet("99,140,255"))
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked, m=mins: self._on_range_changed(m))
            self._range_btns[mins] = btn
            range_layout.addWidget(btn)
        range_layout.addStretch()
        self._range_btns[15].setChecked(True)
        main_layout.addLayout(range_layout)

        # ── Chart ──
        self.chart = HistoryChart(self._dm)
        main_layout.addWidget(self.chart, 1)

        # ── Export button ──
        export_layout = QHBoxLayout()
        export_btn = QPushButton("导出 JSON")
        export_btn.setStyleSheet(_button_sheet("99,140,255"))
        export_btn.setCursor(Qt.PointingHandCursor)
        export_btn.clicked.connect(self._export_json)
        export_layout.addStretch()
        export_layout.addWidget(export_btn)
        main_layout.addLayout(export_layout)

    def _on_range_changed(self, minutes: int) -> None:
        for m, btn in self._range_btns.items():
            btn.setChecked(m == minutes)
        self.chart.set_range(minutes)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        self.stats.refresh()
        self.chart.refresh()

    def _export_json(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "导出注意力数据", "attendme_export.json", "JSON Files (*.json)"
        )
        if path:
            self._dm.export_json(path)

    # ── dragging ──────────────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and event.position().y() < 40:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 18, 18)
        p.fillPath(path, QBrush(QColor(18, 18, 22, 235)))
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.drawPath(path)
        p.end()


# ═══════════════════════════════════════════════════════════════════════════════
# System Tray
# ═══════════════════════════════════════════════════════════════════════════════

class SystemTray(QSystemTrayIcon):
    """System tray icon with context menu for quick access."""

    def __init__(self, on_show_float: callable, on_show_expanded: callable,
                 on_quit: callable, parent=None):
        # Create a simple colored icon programmatically
        icon = self._make_icon()
        super().__init__(icon, parent)

        self.setToolTip("AttendMe — 注意力监测")

        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background: #1e1e26; color: #e0e0e8; border: 1px solid #333;
                border-radius: 8px; padding: 4px;
            }
            QMenu::item { padding: 6px 24px; border-radius: 4px; }
            QMenu::item:selected { background: rgba(99,140,255,40); }
        """)
        menu.addAction("显示悬浮窗", on_show_float)
        menu.addAction("展开详情", on_show_expanded)
        menu.addSeparator()
        menu.addAction("退出", on_quit)
        self.setContextMenu(menu)

        self.activated.connect(self._on_activated)

    @staticmethod
    def _make_icon() -> QIcon:
        """Generate a simple 64x64 icon with a colored circle."""
        from PySide6.QtGui import QPixmap
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QBrush(COLOR_ACCENT))
        p.setPen(Qt.NoPen)
        p.drawEllipse(8, 8, 48, 48)
        p.setPen(QPen(Qt.white, 3))
        font = QFont("Segoe UI", 20, QFont.Bold)
        p.setFont(font)
        p.drawText(QRectF(0, 0, 64, 64), Qt.AlignCenter, "A")
        p.end()
        return QIcon(pixmap)

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self.contextMenu().actions()[1].trigger()  # "展开详情"
