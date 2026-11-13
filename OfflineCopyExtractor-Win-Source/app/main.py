import os
import sys
import platform
import traceback
import subprocess
from datetime import datetime

os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor, QFont
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QPlainTextEdit, QListWidget, QListWidgetItem,
    QFileDialog, QMessageBox, QFrame, QSystemTrayIcon, QMenu, QStackedWidget,
    QDialog
)

from database import HistoryManager
from asr_ocr_engine import LocalAiEngine
from media_sniffer import MediaSniffer

APP_VERSION = "v1.0.7"
APP_TITLE = f"全能离线文案与媒体提取工作台 ({APP_VERSION})"

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".flv", ".wmv", ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}


class ErrorReportDialog(QDialog):
    def __init__(self, summary_msg: str, full_log: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"提取异常诊断 ({APP_VERSION})")
        self.resize(560, 380)
        self.full_log = full_log

        self.setStyleSheet('''
            QDialog { background-color: #FFFFFF; }
            QLabel { font-family: "Microsoft YaHei"; color: #0F172A; }
            QPlainTextEdit {
                background-color: #F8FAFC; border: 1.5px solid #FECACA;
                border-radius: 10px; padding: 10px; font-family: "Consolas", "Microsoft YaHei";
                font-size: 12px; color: #7F1D1D;
            }
            QPushButton#ExportLogBtn {
                background-color: #DC2626; color: #FFFFFF; border: none; border-radius: 9px;
                padding: 9px 16px; font-size: 13px; font-weight: bold; font-family: "Microsoft YaHei";
            }
            QPushButton#ExportLogBtn:hover { background-color: #B91C1C; }
            QPushButton#SecondaryBtn {
                background-color: #F1F5F9; color: #1E293B; border: 1px solid #CBD5E1;
                border-radius: 9px; padding: 9px 14px; font-size: 12px; font-weight: bold; font-family: "Microsoft YaHei";
            }
            QPushButton#SecondaryBtn:hover { background-color: #E2E8F0; }
        ''')

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        hdr = QLabel(f"❌ 处理过程中出现问题（当前版本：{APP_VERSION}）")
        hdr.setStyleSheet("font-size: 15px; font-weight: bold; color: #DC2626;")
        layout.addWidget(hdr)

        lbl_sum = QLabel(summary_msg)
        lbl_sum.setWordWrap(True)
        lbl_sum.setStyleSheet("font-size: 13px; color: #334155;")
        layout.addWidget(lbl_sum)

        lbl_detail = QLabel("详细错误堆栈与环境日志（可导出发给开发者快速定位）：")
        lbl_detail.setStyleSheet("font-size: 12px; font-weight: bold; color: #475569;")
        layout.addWidget(lbl_detail)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlainText(full_log)
        layout.addWidget(self.log_view)

        btn_row = QHBoxLayout()
        btn_export = QPushButton("📥 导出错误日志 (.log / .txt)")
        btn_export.setObjectName("ExportLogBtn")
        btn_export.clicked.connect(self.export_log_file)

        btn_copy = QPushButton("📋 复制日志")
        btn_copy.setObjectName("SecondaryBtn")
        btn_copy.clicked.connect(self.copy_log)

        btn_close = QPushButton("关闭")
        btn_close.setObjectName("SecondaryBtn")
        btn_close.clicked.connect(self.accept)

        btn_row.addWidget(btn_export)
        btn_row.addWidget(btn_copy)
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def copy_log(self):
        QApplication.clipboard().setText(self.full_log)
        QMessageBox.information(self, "已复制", "完整错误日志已复制到剪贴板！")

    def export_log_file(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"错误诊断日志_{APP_VERSION}_{ts}.log"
        fpath, _ = QFileDialog.getSaveFileName(
            self, "导出错误诊断日志", default_name, "日志文件 (*.log);;文本文件 (*.txt)"
        )
        if fpath:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(self.full_log)
            QMessageBox.information(self, "导出成功", f"错误日志已保存至：\n{fpath}")


class CloseConfirmDialog(QDialog):
    """首次关闭主窗口时弹出的是否完全关闭还是最小化到托盘选择对话框"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"关闭提示 ({APP_VERSION})")
        self.setFixedSize(410, 195)
        self.choice = "cancel"

        self.setStyleSheet('''
            QDialog { background-color: #FFFFFF; }
            QLabel { font-family: "Microsoft YaHei"; color: #0F172A; }
            QPushButton#MinimizeBtn {
                background-color: #1677FF; color: #FFFFFF; border: none; border-radius: 9px;
                padding: 9px 14px; font-size: 13px; font-weight: bold; font-family: "Microsoft YaHei";
            }
            QPushButton#MinimizeBtn:hover { background-color: #0958D9; }
            QPushButton#QuitBtn {
                background-color: #FEF2F2; color: #DC2626; border: 1px solid #FECACA; border-radius: 9px;
                padding: 9px 14px; font-size: 13px; font-weight: bold; font-family: "Microsoft YaHei";
            }
            QPushButton#QuitBtn:hover { background-color: #FEE2E2; }
            QPushButton#CancelBtn {
                background-color: #F1F5F9; color: #475569; border: none; border-radius: 9px;
                padding: 9px 12px; font-size: 12px; font-weight: bold; font-family: "Microsoft YaHei";
            }
            QPushButton#CancelBtn:hover { background-color: #E2E8F0; }
        ''')

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        lbl_title = QLabel("您点击了关闭主窗口，请选择操作方式：")
        lbl_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #0F172A;")
        layout.addWidget(lbl_title)

        lbl_desc = QLabel("• 最小化到托盘：程序在后台继续运行（本次运行后续再点关闭将直接最小化，不再重复询问）。\n• 完全关闭软件：彻底退出所有进程。")
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("font-size: 12px; color: #475569; line-height: 1.4;")
        layout.addWidget(lbl_desc)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        btn_min = QPushButton("🔽 最小化到托盘")
        btn_min.setObjectName("MinimizeBtn")
        btn_min.clicked.connect(self._choose_minimize)

        btn_quit = QPushButton("⏻ 完全关闭软件")
        btn_quit.setObjectName("QuitBtn")
        btn_quit.clicked.connect(self._choose_quit)

        btn_cancel = QPushButton("取消")
        btn_cancel.setObjectName("CancelBtn")
        btn_cancel.clicked.connect(self.reject)

        btn_row.addWidget(btn_min, 3)
        btn_row.addWidget(btn_quit, 3)
        btn_row.addWidget(btn_cancel, 1)
        layout.addLayout(btn_row)

    def _choose_minimize(self):
        self.choice = "minimize"
        self.accept()

    def _choose_quit(self):
        self.choice = "quit"
        self.accept()


class PlainTextInput(QPlainTextEdit):
    def insertFromMimeData(self, source):
        if source.hasText():
            self.insertPlainText(source.text())
        else:
            super().insertFromMimeData(source)


class WorkerThread(QThread):
    finished_signal = pyqtSignal(dict)
    error_signal = pyqtSignal(str, str)
    show_browser_signal = pyqtSignal()
    hide_browser_signal = pyqtSignal()

    def __init__(self, task_type: str, payload, ai_engine: LocalAiEngine, sniffer: MediaSniffer, host_info_fn=None):
        super().__init__()
        self.task_type = task_type
        self.payload = payload
        self.ai = ai_engine
        self.sniffer = sniffer
        self.host_info_fn = host_info_fn

    def run(self):
        try:
            if self.task_type == "video_download_only":
                res = self.sniffer.sniff_and_download_video(
                    self.payload,
                    host_info_fn=self.host_info_fn,
                    on_embed_ready=self.show_browser_signal.emit,
                    on_embed_closed=self.hide_browser_signal.emit
                )
                summary = f"【无水印原画视频已保存】\n视频标题：{res['title']}\n本地路径：{res['file_path']}"
                self.finished_signal.emit({
                    "mode": "video_link",
                    "category": "无水印视频",
                    "source": self.payload,
                    "content": summary,
                    "media_path": res["file_path"]
                })
            elif self.task_type == "video_link":
                res = self.sniffer.sniff_and_download_video(
                    self.payload,
                    host_info_fn=self.host_info_fn,
                    on_embed_ready=self.show_browser_signal.emit,
                    on_embed_closed=self.hide_browser_signal.emit
                )
                text = self.ai.transcribe_media(res["file_path"])
                self.finished_signal.emit({
                    "mode": "video_link",
                    "category": "无水印视频",
                    "source": self.payload,
                    "content": text,
                    "media_path": res["file_path"]
                })
            elif self.task_type == "music_link":
                res = self.sniffer.sniff_and_download_music(
                    self.payload,
                    host_info_fn=self.host_info_fn,
                    on_embed_ready=self.show_browser_signal.emit,
                    on_embed_closed=self.hide_browser_signal.emit
                )
                summary = f"【已识别歌曲并自动重命名】\n歌曲文件名：{os.path.basename(res['file_path'])}\n保存位置：{res['file_path']}\n\n【网页歌词/页面信息摘录】\n{res['lyrics_preview']}"
                self.finished_signal.emit({
                    "mode": "music_link",
                    "category": "音乐下载",
                    "source": self.payload,
                    "content": summary,
                    "media_path": res["file_path"]
                })
            elif self.task_type == "article_link":
                text = self.ai.extract_article(self.payload)
                self.finished_signal.emit({
                    "mode": "article_link",
                    "category": "文章",
                    "source": self.payload,
                    "content": text,
                    "media_path": ""
                })
            elif self.task_type == "local_media":
                files = self.payload
                outputs = []
                for fpath in files:
                    fname = os.path.basename(fpath)
                    txt = self.ai.transcribe_media(fpath)
                    outputs.append(f"【文件：{fname}】\n{txt}")
                self.finished_signal.emit({
                    "mode": "local_media",
                    "category": "本地音视频",
                    "source": f"本地批量导入 ({len(files)} 个文件)：" + ", ".join([os.path.basename(x) for x in files]),
                    "content": "\n\n----------------------------------------\n\n".join(outputs),
                    "media_path": files[0] if len(files) == 1 else ""
                })
            elif self.task_type == "local_image":
                files = self.payload
                outputs = []
                for fpath in files:
                    fname = os.path.basename(fpath)
                    txt = self.ai.recognize_image(fpath)
                    outputs.append(f"【图片：{fname}】\n{txt}")
                self.finished_signal.emit({
                    "mode": "local_image",
                    "category": "图片",
                    "source": f"本地图片识别 ({len(files)} 张)：" + ", ".join([os.path.basename(x) for x in files]),
                    "content": "\n\n----------------------------------------\n\n".join(outputs),
                    "media_path": files[0] if len(files) == 1 else ""
                })
            elif self.task_type == "login_embed":
                self.sniffer.open_login_window(
                    self.payload,
                    host_info_fn=self.host_info_fn,
                    on_embed_ready=self.show_browser_signal.emit,
                    on_embed_closed=self.hide_browser_signal.emit
                )
        except Exception as e:
            self.hide_browser_signal.emit()
            tb = traceback.format_exc()
            now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            diag_report = (
                f"================ 软件异常诊断日志 ================\n"
                f"软件版本：{APP_VERSION}\n"
                f"发生时间：{now_ts}\n"
                f"执行任务：{self.task_type}\n"
                f"输入参数：{str(self.payload)[:300]}\n"
                f"操作系统：{platform.platform()} ({platform.machine()})\n"
                f"工作目录：{os.getcwd()}\n"
                f"错误摘要：{str(e)}\n"
                f"---------------- 详细堆栈追踪 ----------------\n"
                f"{tb}"
            )
            self.error_signal.emit(str(e), diag_report)


class FloatingCapsule(QWidget):
    """持续置顶悬浮窗：开启后无论主窗口是显示、切换功能、最小化还是托盘状态，始终持续显示，直到主动关闭悬浮窗"""
    restore_requested = pyqtSignal()
    quick_extract_requested = pyqtSignal(str)
    closed_by_user = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._drag_pos = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        container = QFrame()
        container.setStyleSheet('''
            QFrame {
                background-color: #0F172A;
                border-radius: 22px;
                border: 1.5px solid #38BDF8;
            }
            QLabel { color: #FFFFFF; font-weight: bold; font-size: 12px; border: none; }
            QPushButton {
                background-color: #1677FF; color: #FFFFFF; border: none;
                border-radius: 12px; padding: 5px 10px; font-size: 11px; font-weight: bold;
            }
            QPushButton:hover { background-color: #0958D9; }
        ''')
        c_layout = QHBoxLayout(container)
        c_layout.setContentsMargins(12, 6, 10, 6)
        c_layout.setSpacing(6)

        lbl = QLabel(f"● 悬浮提取 {APP_VERSION}")
        btn_clip = QPushButton("⚡ 粘链提取")
        btn_clip.clicked.connect(self._on_clip_click)

        btn_expand = QPushButton("主界面")
        btn_expand.setStyleSheet("background-color: #334155; color: #FFFFFF; padding: 5px 8px;")
        btn_expand.setToolTip("唤出主工作台（悬浮窗仍保持显示）")
        btn_expand.clicked.connect(self.restore_requested.emit)

        btn_hide_float = QPushButton("✕")
        btn_hide_float.setStyleSheet("background-color: #475569; color: #FFFFFF; padding: 5px 7px;")
        btn_hide_float.setToolTip("关闭悬浮窗")
        btn_hide_float.clicked.connect(self._on_close_float)

        c_layout.addWidget(lbl)
        c_layout.addWidget(btn_clip)
        c_layout.addWidget(btn_expand)
        c_layout.addWidget(btn_hide_float)
        layout.addWidget(container)

    def _on_close_float(self):
        self.hide()
        self.closed_by_user.emit()

    def _on_clip_click(self):
        clip_text = QApplication.clipboard().text().strip()
        if not clip_text:
            QMessageBox.information(self, "提示", "剪贴板为空，请先复制视频或音乐链接！")
            return
        self.quick_extract_requested.emit(clip_text)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1240, 760)
        self.setAcceptDrops(True)

        self.db = HistoryManager("history.db")
        self.ai_engine = LocalAiEngine()
        self.sniffer = MediaSniffer("Downloads", "browser_profile")
        self.current_mode = "video_link"
        self.is_pinned = False

        # 悬浮窗持续开启状态标记（一旦开启，无论主窗口如何操作都持续显示，直到主动关闭）
        self.floating_enabled = False
        # 本次软件启动后的“首次关闭主界面提示”标记（每次全新启动程序重置为 False）
        self.has_prompted_close_this_session = False

        self.mode_configs = {
            "video_link": {
                "title": "链接转文字 & 无水印视频下载",
                "placeholder": "粘贴抖音 / 快手 / 小红书分享口令或网页链接（自动清除富文本黑底格式）...",
                "category": "无水印视频",
                "input_text": "",
                "meta": "识别时间：暂无记录",
                "source": "",
                "content": "",
                "media_path": ""
            },
            "music_link": {
                "title": "QQ音乐 & 网易云音乐嗅探下载（自动按歌名重命名）",
                "placeholder": "粘贴 QQ音乐 或 网易云音乐单曲分享链接...",
                "category": "音乐下载",
                "input_text": "",
                "meta": "识别时间：暂无记录",
                "source": "",
                "content": "",
                "media_path": ""
            },
            "article_link": {
                "title": "文章 / 公众号链接转文字",
                "placeholder": "粘贴微信公众号或网页文章链接...",
                "category": "文章",
                "input_text": "",
                "meta": "识别时间：暂无记录",
                "source": "",
                "content": "",
                "media_path": ""
            },
            "local_media": {
                "title": "本地音视频批量转文字（支持拖拽文件到窗口任意位置）",
                "placeholder": "直接把本地视频/音频文件拖入窗口，或点击下方「选择文件并转写」...",
                "category": "本地音视频",
                "input_text": "",
                "meta": "识别时间：暂无记录",
                "source": "",
                "content": "",
                "media_path": ""
            },
            "local_image": {
                "title": "图片 / 截图离线识字（支持拖拽图片到窗口任意位置）",
                "placeholder": "直接把截图/图片拖入窗口，或点击下方「选择图片并识字」...",
                "category": "图片",
                "input_text": "",
                "meta": "识别时间：暂无记录",
                "source": "",
                "content": "",
                "media_path": ""
            }
        }

        self.floating_win = FloatingCapsule()
        self.floating_win.restore_requested.connect(self.bring_main_to_front)
        self.floating_win.quick_extract_requested.connect(self.handle_floating_extract)
        self.floating_win.closed_by_user.connect(self._on_floating_closed)

        self._init_tray()
        self._init_ui()
        self.switch_mode("video_link")

    def _create_app_icon(self) -> QIcon:
        pix = QPixmap(64, 64)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#1677FF"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(4, 4, 56, 56, 14, 14)
        painter.setPen(QColor("#FFFFFF"))
        painter.setFont(QFont("Microsoft YaHei", 26, QFont.Weight.Bold))
        painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "文")
        painter.end()
        return QIcon(pix)

    def _init_tray(self):
        self.setWindowIcon(self._create_app_icon())
        self.tray = QSystemTrayIcon(self._create_app_icon(), self)
        tray_menu = QMenu()
        act_show = QAction(f"显示主工作台 ({APP_VERSION})", self)
        act_show.triggered.connect(self.bring_main_to_front)
        act_float = QAction("开启 / 切换桌面悬浮窗", self)
        act_float.triggered.connect(self.toggle_floating_window)
        act_quit = QAction("彻底退出程序", self)
        act_quit.triggered.connect(self.quit_application_completely)

        tray_menu.addAction(act_show)
        tray_menu.addAction(act_float)
        tray_menu.addSeparator()
        tray_menu.addAction(act_quit)
        self.tray.setContextMenu(tray_menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.bring_main_to_front()

    def _init_ui(self):
        self.setStyleSheet('''
            QMainWindow { background-color: #F3F6FA; }
            QLabel, QPlainTextEdit, QListWidget { font-family: "Microsoft YaHei"; color: #0F172A; }
            QPushButton { font-family: "Microsoft YaHei"; }
            QPushButton#NavBtn {
                text-align: left; padding: 12px 14px; border-radius: 10px;
                border: none; background: transparent; font-size: 13px; font-weight: bold; color: #334155;
            }
            QPushButton#NavBtn:hover { background-color: #F1F5F9; color: #0F172A; }
            QPushButton#NavBtn[active="true"] { background-color: #E6F4FF; color: #0958D9; }
            QPushButton#PrimaryBtn {
                background-color: #1677FF; color: #FFFFFF; border: none; border-radius: 10px;
                padding: 10px 14px; font-size: 13px; font-weight: bold;
            }
            QPushButton#PrimaryBtn:hover { background-color: #0958D9; color: #FFFFFF; }
            QPushButton#PrimaryBtn:disabled { background-color: #94A3B8; color: #FFFFFF; }
            QPushButton#GreenBtn {
                background-color: #059669; color: #FFFFFF; border: none; border-radius: 10px;
                padding: 10px 14px; font-size: 13px; font-weight: bold;
            }
            QPushButton#GreenBtn:hover { background-color: #047857; color: #FFFFFF; }
            QPushButton#GreenBtn:disabled { background-color: #94A3B8; color: #FFFFFF; }
            QPushButton#SecondaryBtn {
                background-color: #FFFFFF; color: #1E293B; border: 1px solid #CBD5E1;
                border-radius: 9px; padding: 8px 12px; font-size: 12px; font-weight: bold;
            }
            QPushButton#SecondaryBtn:hover { background-color: #F8FAFC; border-color: #1677FF; color: #1677FF; }
            QPlainTextEdit {
                background-color: #F8FAFC; border: 1.5px solid #E2E8F0;
                border-radius: 12px; padding: 10px; font-size: 13px; color: #0F172A;
            }
            QPlainTextEdit:focus { border-color: #1677FF; background-color: #FFFFFF; }
        ''')

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        top_bar = QFrame()
        top_bar.setStyleSheet("background-color: #FFFFFF; border-bottom: 1px solid #E2E8F0;")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(18, 10, 18, 10)

        lbl_brand = QLabel(APP_TITLE)
        lbl_brand.setStyleSheet("font-size: 15px; font-weight: bold; color: #0F172A;")
        lbl_badge = QLabel(" 元数据直链无水印嗅探 · 任意界面拖入文件 · 独立工作区 ")
        lbl_badge.setStyleSheet("background-color: #E0F2FE; color: #0284C7; border-radius: 8px; padding: 3px 8px; font-size: 11px; font-weight: bold;")

        self.btn_pin = QPushButton("📌 置顶窗口")
        self.btn_pin.setObjectName("SecondaryBtn")
        self.btn_pin.clicked.connect(self.toggle_pin)

        self.btn_float = QPushButton("🎯 开启悬浮窗")
        self.btn_float.setObjectName("SecondaryBtn")
        self.btn_float.clicked.connect(self.toggle_floating_window)

        btn_tray = QPushButton("🔽 最小化托盘")
        btn_tray.setObjectName("SecondaryBtn")
        btn_tray.clicked.connect(self.minimize_to_tray)

        btn_dir = QPushButton("📁 打开下载目录")
        btn_dir.setObjectName("SecondaryBtn")
        btn_dir.clicked.connect(self.open_download_folder)

        lbl_top_ver = QLabel(f" {APP_VERSION} ")
        lbl_top_ver.setStyleSheet("background-color: #1677FF; color: #FFFFFF; border-radius: 8px; padding: 5px 10px; font-size: 12px; font-weight: bold;")

        top_layout.addWidget(lbl_brand)
        top_layout.addWidget(lbl_badge)
        top_layout.addStretch()
        top_layout.addWidget(self.btn_pin)
        top_layout.addWidget(self.btn_float)
        top_layout.addWidget(btn_tray)
        top_layout.addWidget(btn_dir)
        top_layout.addWidget(lbl_top_ver)
        root_layout.addWidget(top_bar)

        body_layout = QHBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setFixedWidth(220)
        sidebar.setStyleSheet("background-color: #FFFFFF; border-right: 1px solid #E2E8F0;")
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(12, 16, 12, 16)
        side_layout.setSpacing(6)

        self.nav_buttons = {}
        modes = [
            ("video_link", "🔗 链接转文字 + 去水印"),
            ("music_link", "🎵 QQ / 网易云音乐下载"),
            ("article_link", "📄 文章 / 公众号转文字"),
            ("local_media", "🎬 本地音视频批量转文字"),
            ("local_image", "🖼️ 图片 / 截图离线识字"),
        ]
        for key, label in modes:
            btn = QPushButton(label)
            btn.setObjectName("NavBtn")
            btn.setProperty("active", "true" if key == "video_link" else "false")
            btn.clicked.connect(lambda _, k=key: self.switch_mode(k))
            side_layout.addWidget(btn)
            self.nav_buttons[key] = btn

        side_layout.addStretch()
        lbl_tip = QLabel(f"💡 效率提示（{APP_VERSION}）：\n将音视频或图片拖入软件任意位置，会自动跳转到对应功能并立即开始提取！")
        lbl_tip.setWordWrap(True)
        lbl_tip.setStyleSheet("background-color: #F0F9FF; border: 1px solid #BAE6FD; border-radius: 10px; padding: 10px; font-size: 11px; color: #0369A1;")
        side_layout.addWidget(lbl_tip)
        body_layout.addWidget(sidebar)

        center_panel = QFrame()
        center_panel.setFixedWidth(430)
        center_panel.setStyleSheet("background-color: #F8FAFC; border-right: 1px solid #E2E8F0;")
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(16, 16, 16, 16)
        center_layout.setSpacing(10)

        self.lbl_mode_title = QLabel("链接转文字 & 无水印视频下载")
        self.lbl_mode_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #0F172A;")
        center_layout.addWidget(self.lbl_mode_title)

        self.input_edit = PlainTextInput()
        self.input_edit.setFixedHeight(90)
        center_layout.addWidget(self.input_edit)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_run = QPushButton("⚡ 提取文案 + 视频")
        self.btn_run.setObjectName("PrimaryBtn")
        self.btn_run.setStyleSheet("background-color: #1677FF; color: #FFFFFF; border: none; border-radius: 10px; padding: 10px 12px; font-size: 13px; font-weight: bold;")
        self.btn_run.clicked.connect(lambda: self.start_extract(download_only=False))

        self.btn_download_only = QPushButton("🎬 仅去水印下载")
        self.btn_download_only.setObjectName("GreenBtn")
        self.btn_download_only.setStyleSheet("background-color: #059669; color: #FFFFFF; border: none; border-radius: 10px; padding: 10px 12px; font-size: 13px; font-weight: bold;")
        self.btn_download_only.clicked.connect(lambda: self.start_extract(download_only=True))

        self.btn_browser = QPushButton("🌐 内嵌登录")
        self.btn_browser.setObjectName("SecondaryBtn")
        self.btn_browser.clicked.connect(self.open_login_browser)

        btn_row.addWidget(self.btn_run, 3)
        btn_row.addWidget(self.btn_download_only, 3)
        btn_row.addWidget(self.btn_browser, 2)
        center_layout.addLayout(btn_row)

        lbl_hist_hdr = QLabel("当前功能历史记录")
        lbl_hist_hdr.setStyleSheet("font-size: 12px; font-weight: bold; color: #475569; margin-top: 4px;")
        center_layout.addWidget(lbl_hist_hdr)

        self.history_list = QListWidget()
        self.history_list.setStyleSheet('''
            QListWidget { border: none; background: transparent; }
            QListWidget::item {
                background: #FFFFFF; border-radius: 10px; padding: 10px;
                margin-bottom: 8px; border: 1px solid #E2E8F0; color: #0F172A;
            }
            QListWidget::item:selected { border: 1.5px solid #1677FF; background: #F0F7FF; color: #0F172A; }
        ''')
        self.history_list.currentItemChanged.connect(self.on_history_selected)
        center_layout.addWidget(self.history_list)
        body_layout.addWidget(center_panel)

        self.right_stack = QStackedWidget()
        self.right_stack.setStyleSheet("background-color: #FFFFFF;")

        result_page = QWidget()
        right_layout = QVBoxLayout(result_page)
        right_layout.setContentsMargins(20, 16, 20, 16)
        right_layout.setSpacing(12)

        self.lbl_detail_meta = QLabel("识别时间：暂无记录")
        self.lbl_detail_meta.setStyleSheet("font-size: 12px; color: #475569;")
        right_layout.addWidget(self.lbl_detail_meta)

        self.lbl_media_file = QLabel("")
        self.lbl_media_file.setVisible(False)
        self.lbl_media_file.setStyleSheet("background-color: #ECFDF5; color: #065F46; border: 1px solid #A7F3D0; border-radius: 10px; padding: 10px; font-size: 12px; font-weight: bold;")
        right_layout.addWidget(self.lbl_media_file)

        lbl_src_title = QLabel("原始链接 & 来源（支持单独复制）")
        lbl_src_title.setStyleSheet("font-size: 12px; font-weight: bold; color: #1677FF;")
        right_layout.addWidget(lbl_src_title)

        self.detail_source = PlainTextInput()
        self.detail_source.setReadOnly(True)
        self.detail_source.setFixedHeight(64)
        right_layout.addWidget(self.detail_source)

        lbl_cnt_title = QLabel("识别的文案内容（可自由编辑或一键复制）")
        lbl_cnt_title.setStyleSheet("font-size: 12px; font-weight: bold; color: #1677FF;")
        right_layout.addWidget(lbl_cnt_title)

        self.detail_content = PlainTextInput()
        right_layout.addWidget(self.detail_content)

        bottom_bar = QHBoxLayout()
        btn_exp_txt = QPushButton("导出 TXT")
        btn_exp_txt.setObjectName("SecondaryBtn")
        btn_exp_txt.clicked.connect(lambda: self.export_current("txt"))

        btn_exp_doc = QPushButton("导出 Word")
        btn_exp_doc.setObjectName("SecondaryBtn")
        btn_exp_doc.clicked.connect(lambda: self.export_current("docx"))

        btn_exp_md = QPushButton("导出 Markdown")
        btn_exp_md.setObjectName("SecondaryBtn")
        btn_exp_md.clicked.connect(lambda: self.export_current("md"))

        btn_copy_src = QPushButton("复制链接")
        btn_copy_src.setObjectName("SecondaryBtn")
        btn_copy_src.clicked.connect(lambda: self.copy_text(self.detail_source.toPlainText()))

        btn_copy_all = QPushButton("一键复制正文")
        btn_copy_all.setObjectName("PrimaryBtn")
        btn_copy_all.setStyleSheet("background-color: #1677FF; color: #FFFFFF; border: none; border-radius: 10px; padding: 9px 18px; font-size: 13px; font-weight: bold;")
        btn_copy_all.clicked.connect(lambda: self.copy_text(self.detail_content.toPlainText()))

        bottom_bar.addWidget(btn_exp_txt)
        bottom_bar.addWidget(btn_exp_doc)
        bottom_bar.addWidget(btn_exp_md)
        bottom_bar.addStretch()
        bottom_bar.addWidget(btn_copy_src)
        bottom_bar.addWidget(btn_copy_all)
        right_layout.addLayout(bottom_bar)

        browser_page = QWidget()
        b_layout = QVBoxLayout(browser_page)
        b_layout.setContentsMargins(12, 10, 12, 12)
        b_layout.setSpacing(8)

        b_banner = QFrame()
        b_banner.setStyleSheet("background-color: #EFF6FF; border: 1px solid #BFDBFE; border-radius: 8px;")
        bb_layout = QHBoxLayout(b_banner)
        bb_layout.setContentsMargins(12, 6, 12, 6)
        lbl_b_tip = QLabel("🌐 内置浏览器正在解析无水印原始流（如遇登录或滑块验证，请直接在下方画面操作，捕获后自动下载并切回结果）")
        lbl_b_tip.setStyleSheet("font-size: 12px; font-weight: bold; color: #1D4ED8; border: none;")
        bb_layout.addWidget(lbl_b_tip)
        b_layout.addWidget(b_banner)

        self.browser_host = QFrame()
        self.browser_host.setStyleSheet("background-color: #0F172A; border-radius: 10px;")
        b_layout.addWidget(self.browser_host, 1)

        self.right_stack.addWidget(result_page)
        self.right_stack.addWidget(browser_page)

        body_layout.addWidget(self.right_stack, 1)
        root_layout.addLayout(body_layout, 1)

    def get_browser_host_info(self):
        return int(self.browser_host.winId()), max(500, self.browser_host.width()), max(400, self.browser_host.height())

    def show_embedded_browser(self):
        self.right_stack.setCurrentIndex(1)

    def hide_embedded_browser(self):
        self.right_stack.setCurrentIndex(0)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if not urls:
            return
        local_files = [u.toLocalFile() for u in urls if os.path.isfile(u.toLocalFile())]
        if not local_files:
            return

        media_files = [f for f in local_files if os.path.splitext(f)[1].lower() in VIDEO_EXTS]
        image_files = [f for f in local_files if os.path.splitext(f)[1].lower() in IMAGE_EXTS]

        if media_files:
            self.switch_mode("local_media")
            self._run_worker("local_media", media_files)
        elif image_files:
            self.switch_mode("local_image")
            self._run_worker("local_image", image_files)
        else:
            QMessageBox.information(self, "文件格式提示", "暂不支持该文件格式，请拖入常见的音视频或图片文件。")

    def toggle_pin(self):
        self.is_pinned = not self.is_pinned
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.is_pinned)
        self.show()
        self.btn_pin.setText("📌 已置顶" if self.is_pinned else "📌 置顶窗口")
        self._ensure_floating_persistent()

    # ---------------- 悬浮窗持续显示控制（开启后任何状态下持续显示） ----------------
    def _ensure_floating_persistent(self):
        if self.floating_enabled:
            self.floating_win.show()
            self.floating_win.raise_()

    def toggle_floating_window(self):
        self.floating_enabled = not self.floating_enabled
        if self.floating_enabled:
            self.floating_win.show()
            self.floating_win.raise_()
            self.btn_float.setText("🎯 悬浮窗已开启")
            self.btn_float.setStyleSheet("background-color: #E6F4FF; color: #0958D9; border: 1px solid #91CAFF; border-radius: 9px; padding: 8px 12px; font-size: 12px; font-weight: bold;")
        else:
            self.floating_win.hide()
            self.btn_float.setText("🎯 开启悬浮窗")
            self.btn_float.setStyleSheet("")

    def _on_floating_closed(self):
        self.floating_enabled = False
        self.btn_float.setText("🎯 开启悬浮窗")
        self.btn_float.setStyleSheet("")

    def bring_main_to_front(self):
        # 唤出主窗口时，如果悬浮窗处于开启状态，绝不隐藏悬浮窗，继续保持置顶显示
        self.showNormal()
        self.activateWindow()
        self.raise_()
        self._ensure_floating_persistent()

    def minimize_to_tray(self):
        # 最小化到托盘时，如果悬浮窗处于开启状态，依然保持悬浮窗持续显示
        self.hide()
        self._ensure_floating_persistent()
        self.tray.showMessage(f"全能提取工作台 {APP_VERSION}", "主窗口已最小化到系统托盘，双击托盘图标可随时恢复。", QSystemTrayIcon.MessageIcon.Information, 2000)

    def quit_application_completely(self):
        # 完全关闭软件并彻底退出进程（下次再打开时 has_prompted_close_this_session 自动重置为 False）
        self.floating_win.hide()
        self.tray.hide()
        QApplication.instance().quit()

    def closeEvent(self, event):
        # 每次启动后，第一次点击关闭主界面弹出询问框；选择最小化后第二次再点关闭直接最小化不再重复弹窗；
        # 若选择完全关闭软件，下次重新启动软件后的第一次关闭会再次弹出询问框，形成闭环循环。
        if not self.has_prompted_close_this_session:
            event.ignore()
            dlg = CloseConfirmDialog(self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                if dlg.choice == "quit":
                    self.quit_application_completely()
                elif dlg.choice == "minimize":
                    self.has_prompted_close_this_session = True
                    self.minimize_to_tray()
        else:
            event.ignore()
            self.minimize_to_tray()

    def handle_floating_extract(self, clip_text: str):
        if any(k in clip_text for k in ["y.qq.com", "music.163.com", "QQ音乐", "网易云"]):
            self.switch_mode("music_link")
        else:
            self.switch_mode("video_link")
        self.input_edit.setPlainText(clip_text)
        self.start_extract(download_only=False)
        self._ensure_floating_persistent()

    def switch_mode(self, mode_key: str):
        if self.current_mode in self.mode_configs:
            old_cfg = self.mode_configs[self.current_mode]
            old_cfg["input_text"] = self.input_edit.toPlainText()
            old_cfg["meta"] = self.lbl_detail_meta.text()
            old_cfg["source"] = self.detail_source.toPlainText()
            old_cfg["content"] = self.detail_content.toPlainText()

        self.current_mode = mode_key
        for k, btn in self.nav_buttons.items():
            btn.setProperty("active", "true" if k == mode_key else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        cfg = self.mode_configs[mode_key]
        self.lbl_mode_title.setText(cfg["title"])
        self.input_edit.setPlaceholderText(cfg["placeholder"])
        self.input_edit.setPlainText(cfg["input_text"])
        self.lbl_detail_meta.setText(cfg["meta"])
        self.detail_source.setPlainText(cfg["source"])
        self.detail_content.setPlainText(cfg["content"])

        if cfg["media_path"]:
            self.lbl_media_file.setVisible(True)
            self.lbl_media_file.setText(f"✅ 本地媒体已保存并自动重命名：{cfg['media_path']}")
        else:
            self.lbl_media_file.setVisible(False)

        if mode_key == "video_link":
            self.input_edit.setVisible(True)
            self.btn_run.setText("⚡ 提取文案 + 视频")
            self.btn_download_only.setVisible(True)
            self.btn_browser.setVisible(True)
        elif mode_key == "music_link":
            self.input_edit.setVisible(True)
            self.btn_run.setText("🎵 嗅探并下载音乐")
            self.btn_download_only.setVisible(False)
            self.btn_browser.setVisible(True)
        elif mode_key == "article_link":
            self.input_edit.setVisible(True)
            self.btn_run.setText("⚡ 立即提取文章")
            self.btn_download_only.setVisible(False)
            self.btn_browser.setVisible(False)
        elif mode_key == "local_media":
            self.input_edit.setVisible(False)
            self.btn_run.setText("📂 选择本地音视频转文字")
            self.btn_download_only.setVisible(False)
            self.btn_browser.setVisible(False)
        elif mode_key == "local_image":
            self.input_edit.setVisible(False)
            self.btn_run.setText("🖼️ 选择本地图片离线识字")
            self.btn_download_only.setVisible(False)
            self.btn_browser.setVisible(False)

        self.refresh_history()
        self._ensure_floating_persistent()

    def open_login_browser(self):
        url = "https://y.qq.com" if self.current_mode == "music_link" else "https://www.douyin.com"
        self.show_embedded_browser()
        self.worker = WorkerThread("login_embed", url, self.ai_engine, self.sniffer, host_info_fn=self.get_browser_host_info)
        self.worker.show_browser_signal.connect(self.show_embedded_browser)
        self.worker.hide_browser_signal.connect(self.hide_embedded_browser)
        self.worker.error_signal.connect(self.on_extract_error)
        self.worker.start()
        self._ensure_floating_persistent()

    def start_extract(self, download_only: bool = False):
        if self.current_mode in ["local_media", "local_image"]:
            filt = "音视频文件 (*.mp4 *.mov *.mkv *.avi *.mp3 *.wav *.m4a *.aac *.flac)" if self.current_mode == "local_media" else "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp)"
            files, _ = QFileDialog.getOpenFileNames(self, "选择要批量提取的文件", "", filt)
            if not files:
                return
            self._run_worker(self.current_mode, files)
        else:
            payload = self.input_edit.toPlainText().strip()
            if not payload:
                QMessageBox.warning(self, "提示", "请先粘贴链接或分享口令！")
                return
            task = "video_download_only" if (self.current_mode == "video_link" and download_only) else self.current_mode
            self._run_worker(task, payload)

    def _run_worker(self, task_type: str, payload):
        self.btn_run.setEnabled(False)
        self.btn_download_only.setEnabled(False)
        self._saved_btn_text = self.btn_run.text()
        self.btn_run.setText("⏳ 正在处理中...")

        self.worker = WorkerThread(task_type, payload, self.ai_engine, self.sniffer, host_info_fn=self.get_browser_host_info)
        self.worker.show_browser_signal.connect(self.show_embedded_browser)
        self.worker.hide_browser_signal.connect(self.hide_embedded_browser)
        self.worker.finished_signal.connect(self.on_extract_done)
        self.worker.error_signal.connect(self.on_extract_error)
        self.worker.start()
        self._ensure_floating_persistent()

    def on_extract_done(self, res: dict):
        self.btn_run.setEnabled(True)
        self.btn_download_only.setEnabled(True)
        self.btn_run.setText(getattr(self, "_saved_btn_text", "⚡ 立即提取"))
        self.hide_embedded_browser()

        self.db.add_record(res["category"], res["source"], res["content"], res.get("media_path", ""))
        self.refresh_history()
        if self.history_list.count() > 0:
            self.history_list.setCurrentRow(0)
        self._ensure_floating_persistent()

    def on_extract_error(self, err_msg: str, full_log: str):
        self.btn_run.setEnabled(True)
        self.btn_download_only.setEnabled(True)
        self.btn_run.setText(getattr(self, "_saved_btn_text", "⚡ 立即提取"))
        self.hide_embedded_browser()

        dlg = ErrorReportDialog(err_msg, full_log, self)
        dlg.exec()
        self._ensure_floating_persistent()

    def refresh_history(self):
        self.history_list.clear()
        cat = self.mode_configs[self.current_mode]["category"]
        records = self.db.get_records(cat)
        for r in records:
            preview = r["content"].replace("\n", " ")[:40]
            item = QListWidgetItem(f"[{r['category']}]  {r['extract_time']}\n{preview}...")
            item.setData(Qt.ItemDataRole.UserRole, r)
            self.history_list.addItem(item)

    def on_history_selected(self, current: QListWidgetItem, _):
        if not current:
            return
        r = current.data(Qt.ItemDataRole.UserRole)
        meta_str = f"识别时间：{r['extract_time']}   |   分类：{r['category']}"
        self.lbl_detail_meta.setText(meta_str)
        self.detail_source.setPlainText(r["source_info"])
        self.detail_content.setPlainText(r["content"])
        mpath = r.get("media_path", "")
        if mpath:
            self.lbl_media_file.setVisible(True)
            self.lbl_media_file.setText(f"✅ 本地媒体已保存并自动重命名：{mpath}")
        else:
            self.lbl_media_file.setVisible(False)

        cfg = self.mode_configs[self.current_mode]
        cfg["meta"] = meta_str
        cfg["source"] = r["source_info"]
        cfg["content"] = r["content"]
        cfg["media_path"] = mpath

    def copy_text(self, text: str):
        if text:
            QApplication.clipboard().setText(text)
            QMessageBox.information(self, "已复制", "内容已复制到剪贴板！")

    def export_current(self, fmt: str):
        cat = self.mode_configs[self.current_mode]["category"]
        records = self.db.get_records(cat)
        if not records:
            return
        ext_map = {"txt": "文本文件 (*.txt)", "docx": "Word 文档 (*.docx)", "md": "Markdown 文档 (*.md)"}
        fpath, _ = QFileDialog.getSaveFileName(self, "导出记录", f"{cat}_提取导出.{fmt}", ext_map[fmt])
        if fpath:
            HistoryManager.export_records(records, fpath, fmt)
            QMessageBox.information(self, "导出成功", f"已成功导出 {len(records)} 条记录至：\n{fpath}")

    def open_download_folder(self):
        os.makedirs("Downloads", exist_ok=True)
        path = os.path.abspath("Downloads")
        if sys.platform == "win32":
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", path])


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
