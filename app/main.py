import os
import sys
import subprocess

os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor, QFont
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QTextEdit, QListWidget, QListWidgetItem,
    QFileDialog, QMessageBox, QFrame, QSystemTrayIcon, QMenu
)

from database import HistoryManager
from asr_ocr_engine import LocalAiEngine
from media_sniffer import MediaSniffer


class WorkerThread(QThread):
    finished_signal = pyqtSignal(dict)
    error_signal = pyqtSignal(str)

    def __init__(self, task_type: str, payload, ai_engine: LocalAiEngine, sniffer: MediaSniffer):
        super().__init__()
        self.task_type = task_type
        self.payload = payload
        self.ai = ai_engine
        self.sniffer = sniffer

    def run(self):
        try:
            if self.task_type == "video_link":
                res = self.sniffer.sniff_and_download_video(self.payload, show_browser=True)
                text = self.ai.transcribe_media(res["file_path"])
                self.finished_signal.emit({
                    "category": "无水印视频",
                    "source": self.payload,
                    "content": text,
                    "media_path": res["file_path"]
                })
            elif self.task_type == "music_link":
                res = self.sniffer.sniff_and_download_music(self.payload, show_browser=True)
                summary = f"【已识别歌曲并自动重命名】\n歌曲文件名：{os.path.basename(res['file_path'])}\n保存位置：{res['file_path']}\n\n【网页歌词/页面信息摘录】\n{res['lyrics_preview']}"
                self.finished_signal.emit({
                    "category": "音乐下载",
                    "source": self.payload,
                    "content": summary,
                    "media_path": res["file_path"]
                })
            elif self.task_type == "article_link":
                text = self.ai.extract_article(self.payload)
                self.finished_signal.emit({
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
                    "category": "图片",
                    "source": f"本地图片识别 ({len(files)} 张)：" + ", ".join([os.path.basename(x) for x in files]),
                    "content": "\n\n----------------------------------------\n\n".join(outputs),
                    "media_path": files[0] if len(files) == 1 else ""
                })
        except Exception as e:
            self.error_signal.emit(str(e))


class FloatingCapsule(QWidget):
    restore_requested = pyqtSignal()
    quick_extract_requested = pyqtSignal(str)

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
        c_layout.setSpacing(8)

        lbl = QLabel("● 悬浮提取")
        btn_clip = QPushButton("⚡ 粘链提取")
        btn_clip.clicked.connect(self._on_clip_click)

        btn_expand = QPushButton("↗")
        btn_expand.setStyleSheet("background-color: #334155; color: #FFFFFF; padding: 5px 8px;")
        btn_expand.clicked.connect(self.restore_requested.emit)

        c_layout.addWidget(lbl)
        c_layout.addWidget(btn_clip)
        c_layout.addWidget(btn_expand)
        layout.addWidget(container)

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
        self.setWindowTitle("全能离线文案与媒体提取工作台（即开即用完整版）")
        self.resize(1180, 740)

        self.db = HistoryManager("history.db")
        self.ai_engine = LocalAiEngine()
        self.sniffer = MediaSniffer("Downloads", "browser_profile")
        self.current_mode = "video_link"
        self.current_filter = "全部"
        self.current_record = None
        self.is_pinned = False

        self.floating_win = FloatingCapsule()
        self.floating_win.restore_requested.connect(self.restore_from_floating)
        self.floating_win.quick_extract_requested.connect(self.handle_floating_extract)

        self._init_tray()
        self._init_ui()
        self.refresh_history()

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
        act_show = QAction("显示主工作台", self)
        act_show.triggered.connect(self.restore_from_tray)
        act_float = QAction("切换桌面悬浮窗", self)
        act_float.triggered.connect(self.switch_to_floating)
        act_quit = QAction("彻底退出程序", self)
        act_quit.triggered.connect(QApplication.instance().quit)

        tray_menu.addAction(act_show)
        tray_menu.addAction(act_float)
        tray_menu.addSeparator()
        tray_menu.addAction(act_quit)
        self.tray.setContextMenu(tray_menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.restore_from_tray()

    def _init_ui(self):
        self.setStyleSheet('''
            QMainWindow { background-color: #F3F6FA; }
            QLabel, QTextEdit, QListWidget { font-family: "Microsoft YaHei"; color: #0F172A; }
            QPushButton { font-family: "Microsoft YaHei"; }
            QPushButton#NavBtn {
                text-align: left; padding: 11px 14px; border-radius: 10px;
                border: none; background: transparent; font-size: 13px; font-weight: bold; color: #334155;
            }
            QPushButton#NavBtn:hover { background-color: #F1F5F9; color: #0F172A; }
            QPushButton#NavBtn[active="true"] { background-color: #E6F4FF; color: #0958D9; }
            QPushButton#PrimaryBtn {
                background-color: #1677FF; color: #FFFFFF; border: none; border-radius: 10px;
                padding: 10px 18px; font-size: 14px; font-weight: bold;
            }
            QPushButton#PrimaryBtn:hover { background-color: #0958D9; color: #FFFFFF; }
            QPushButton#PrimaryBtn:disabled { background-color: #94A3B8; color: #FFFFFF; }
            QPushButton#SecondaryBtn {
                background-color: #FFFFFF; color: #1E293B; border: 1px solid #CBD5E1;
                border-radius: 9px; padding: 8px 12px; font-size: 12px; font-weight: bold;
            }
            QPushButton#SecondaryBtn:hover { background-color: #F8FAFC; border-color: #1677FF; color: #1677FF; }
            QTextEdit {
                background-color: #F8FAFC; border: 1.5px solid #E2E8F0;
                border-radius: 12px; padding: 10px; font-size: 13px; color: #0F172A;
            }
            QTextEdit:focus { border-color: #1677FF; background-color: #FFFFFF; }
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

        lbl_brand = QLabel("全能离线文案与媒体提取工作台")
        lbl_brand.setStyleSheet("font-size: 15px; font-weight: bold; color: #0F172A;")
        lbl_badge = QLabel(" 内置语音模型 + OCR模型 + 嗅探浏览器 · 即开即用 ")
        lbl_badge.setStyleSheet("background-color: #E0F2FE; color: #0284C7; border-radius: 8px; padding: 3px 8px; font-size: 11px; font-weight: bold;")

        self.btn_pin = QPushButton("📌 置顶窗口")
        self.btn_pin.setObjectName("SecondaryBtn")
        self.btn_pin.clicked.connect(self.toggle_pin)

        btn_float = QPushButton("🎯 悬浮窗")
        btn_float.setObjectName("SecondaryBtn")
        btn_float.clicked.connect(self.switch_to_floating)

        btn_tray = QPushButton("🔽 最小化托盘")
        btn_tray.setObjectName("SecondaryBtn")
        btn_tray.clicked.connect(self.minimize_to_tray)

        btn_dir = QPushButton("📁 打开下载目录")
        btn_dir.setObjectName("SecondaryBtn")
        btn_dir.clicked.connect(self.open_download_folder)

        top_layout.addWidget(lbl_brand)
        top_layout.addWidget(lbl_badge)
        top_layout.addStretch()
        top_layout.addWidget(self.btn_pin)
        top_layout.addWidget(btn_float)
        top_layout.addWidget(btn_tray)
        top_layout.addWidget(btn_dir)
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
        lbl_tip = QLabel("保存目录：./Downloads/\n历史数据库：./history.db\n支持多选文件批量队列转写")
        lbl_tip.setStyleSheet("background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 10px; padding: 10px; font-size: 11px; color: #475569;")
        side_layout.addWidget(lbl_tip)
        body_layout.addWidget(sidebar)

        center_panel = QFrame()
        center_panel.setFixedWidth(420)
        center_panel.setStyleSheet("background-color: #F8FAFC; border-right: 1px solid #E2E8F0;")
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(16, 16, 16, 16)
        center_layout.setSpacing(12)

        self.lbl_mode_title = QLabel("链接转文字 & 无水印视频保存")
        self.lbl_mode_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #0F172A;")
        center_layout.addWidget(self.lbl_mode_title)

        self.input_edit = QTextEdit()
        self.input_edit.setFixedHeight(92)
        self.input_edit.setPlaceholderText("粘贴抖音 / 快手 / 小红书分享口令或网页链接，自动弹出小窗识别无水印视频并离线转写文案...")
        center_layout.addWidget(self.input_edit)

        btn_row = QHBoxLayout()
        self.btn_run = QPushButton("⚡ 立即提取")
        self.btn_run.setObjectName("PrimaryBtn")
        self.btn_run.setStyleSheet("background-color: #1677FF; color: #FFFFFF; border: none; border-radius: 10px; padding: 10px 16px; font-size: 14px; font-weight: bold;")
        self.btn_run.clicked.connect(self.start_extract)

        btn_browser = QPushButton("🌐 小窗登录/过验证")
        btn_browser.setObjectName("SecondaryBtn")
        btn_browser.clicked.connect(self.open_login_browser)

        btn_row.addWidget(self.btn_run, 2)
        btn_row.addWidget(btn_browser, 1)
        center_layout.addLayout(btn_row)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(4)
        for cat in ["全部", "无水印视频", "音乐下载", "本地音视频", "文章", "图片"]:
            b = QPushButton(cat)
            b.setStyleSheet("padding: 5px 8px; border-radius: 8px; font-size: 11px; font-weight: bold; background-color: #E2E8F0; color: #1E293B; border: none;")
            b.clicked.connect(lambda _, c=cat: self.set_filter(c))
            filter_row.addWidget(b)
        center_layout.addLayout(filter_row)

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

        right_panel = QFrame()
        right_panel.setStyleSheet("background-color: #FFFFFF;")
        right_layout = QVBoxLayout(right_panel)
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

        self.detail_source = QTextEdit()
        self.detail_source.setReadOnly(True)
        self.detail_source.setFixedHeight(64)
        right_layout.addWidget(self.detail_source)

        lbl_cnt_title = QLabel("识别的文案内容（可自由编辑或一键复制）")
        lbl_cnt_title.setStyleSheet("font-size: 12px; font-weight: bold; color: #1677FF;")
        right_layout.addWidget(lbl_cnt_title)

        self.detail_content = QTextEdit()
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

        body_layout.addWidget(right_panel, 1)
        root_layout.addLayout(body_layout, 1)

    def toggle_pin(self):
        self.is_pinned = not self.is_pinned
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.is_pinned)
        self.show()
        self.btn_pin.setText("📌 已置顶" if self.is_pinned else "📌 置顶窗口")

    def switch_to_floating(self):
        self.hide()
        self.floating_win.show()

    def restore_from_floating(self):
        self.floating_win.hide()
        self.showNormal()
        self.activateWindow()

    def minimize_to_tray(self):
        self.hide()
        self.floating_win.hide()
        self.tray.showMessage("全能提取工作台", "程序已最小化到系统托盘，双击图标可随时恢复。", QSystemTrayIcon.MessageIcon.Information, 2000)

    def restore_from_tray(self):
        self.floating_win.hide()
        self.showNormal()
        self.activateWindow()

    def closeEvent(self, event):
        event.ignore()
        self.minimize_to_tray()

    def handle_floating_extract(self, clip_text: str):
        self.input_edit.setPlainText(clip_text)
        if any(k in clip_text for k in ["y.qq.com", "music.163.com", "QQ音乐", "网易云"]):
            self.switch_mode("music_link")
        else:
            self.switch_mode("video_link")
        self.start_extract()

    def switch_mode(self, mode_key: str):
        self.current_mode = mode_key
        for k, btn in self.nav_buttons.items():
            btn.setProperty("active", "true" if k == mode_key else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        titles = {
            "video_link": ("链接转文字 & 无水印视频保存", "粘贴抖音 / 快手 / 小红书分享口令或网页链接..."),
            "music_link": ("QQ音乐 & 网易云音乐嗅探下载（自动按歌名重命名）", "粘贴 QQ音乐 或 网易云音乐单曲分享链接..."),
            "article_link": ("文章 / 公众号链接转文字", "粘贴微信公众号或网页文章链接..."),
            "local_media": ("本地音视频批量转文字（支持多选文件队列）", "点击下方「立即提取」弹出多选文件框，一次性批量转写..."),
            "local_image": ("图片 / 截图离线识字（支持多张批量识别）", "点击下方「立即提取」选择本地图片或截图..."),
        }
        t, ph = titles[mode_key]
        self.lbl_mode_title.setText(t)
        self.input_edit.setPlaceholderText(ph)

    def open_login_browser(self):
        url = "https://y.qq.com" if self.current_mode == "music_link" else "https://www.douyin.com"
        QMessageBox.information(self, "小窗登录提示", "即将打开内置浏览器窗口。登录账号或完成滑块验证后，直接关闭浏览器窗口即可自动保存登录状态。")
        self.sniffer.open_login_window(url)

    def start_extract(self):
        if self.current_mode in ["local_media", "local_image"]:
            filt = "音视频文件 (*.mp4 *.mov *.mkv *.avi *.mp3 *.wav *.m4a *.aac *.flac)" if self.current_mode == "local_media" else "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp)"
            files, _ = QFileDialog.getOpenFileNames(self, "选择要批量提取的文件", "", filt)
            if not files:
                return
            payload = files
        else:
            payload = self.input_edit.toPlainText().strip()
            if not payload:
                QMessageBox.warning(self, "提示", "请先粘贴链接或分享口令！")
                return

        self.btn_run.setEnabled(False)
        self.btn_run.setText("⏳ 正在处理中...")

        self.worker = WorkerThread(self.current_mode, payload, self.ai_engine, self.sniffer)
        self.worker.finished_signal.connect(self.on_extract_done)
        self.worker.error_signal.connect(self.on_extract_error)
        self.worker.start()

    def on_extract_done(self, res: dict):
        self.btn_run.setEnabled(True)
        self.btn_run.setText("⚡ 立即提取")
        self.db.add_record(res["category"], res["source"], res["content"], res.get("media_path", ""))
        self.refresh_history()
        if self.history_list.count() > 0:
            self.history_list.setCurrentRow(0)

    def on_extract_error(self, err_msg: str):
        self.btn_run.setEnabled(True)
        self.btn_run.setText("⚡ 立即提取")
        QMessageBox.critical(self, "提取失败", f"处理过程中出现问题：\n{err_msg}")

    def set_filter(self, cat: str):
        self.current_filter = cat
        self.refresh_history()

    def refresh_history(self):
        self.history_list.clear()
        records = self.db.get_records(self.current_filter)
        for r in records:
            preview = r["content"].replace("\n", " ")[:42]
            item = QListWidgetItem(f"[{r['category']}]  {r['extract_time']}\n{preview}...")
            item.setData(Qt.ItemDataRole.UserRole, r)
            self.history_list.addItem(item)

    def on_history_selected(self, current: QListWidgetItem, _):
        if not current:
            return
        r = current.data(Qt.ItemDataRole.UserRole)
        self.current_record = r
        self.lbl_detail_meta.setText(f"识别时间：{r['extract_time']}   |   分类：{r['category']}")
        self.detail_source.setPlainText(r["source_info"])
        self.detail_content.setPlainText(r["content"])
        if r.get("media_path"):
            self.lbl_media_file.setVisible(True)
            self.lbl_media_file.setText(f"✅ 本地媒体已保存并自动重命名：{r['media_path']}")
        else:
            self.lbl_media_file.setVisible(False)

    def copy_text(self, text: str):
        if text:
            QApplication.clipboard().setText(text)
            QMessageBox.information(self, "已复制", "内容已复制到剪贴板！")

    def export_current(self, fmt: str):
        records = self.db.get_records(self.current_filter)
        if not records:
            return
        ext_map = {"txt": "文本文件 (*.txt)", "docx": "Word 文档 (*.docx)", "md": "Markdown 文档 (*.md)"}
        fpath, _ = QFileDialog.getSaveFileName(self, "导出记录", f"文案提取导出.{fmt}", ext_map[fmt])
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
