import os
import sqlite3
from datetime import datetime
from docx import Document

class HistoryManager:
    def __init__(self, db_path="history.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    extract_time TEXT NOT NULL,
                    category TEXT NOT NULL,
                    source_info TEXT NOT NULL,
                    content TEXT NOT NULL,
                    media_path TEXT DEFAULT ''
                )
            ''')
            conn.commit()

    def add_record(self, category: str, source_info: str, content: str, media_path: str = "") -> str:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO records (extract_time, category, source_info, content, media_path) VALUES (?, ?, ?, ?, ?)",
                (now_str, category, source_info, content, media_path)
            )
            conn.commit()
        return now_str

    def get_records(self, category_filter: str = "全部"):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if category_filter == "全部":
                cur = conn.execute("SELECT * FROM records ORDER BY id DESC")
            else:
                cur = conn.execute("SELECT * FROM records WHERE category = ? ORDER BY id DESC", (category_filter,))
            return [dict(row) for row in cur.fetchall()]

    def delete_record(self, record_id: int):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
            conn.commit()

    @staticmethod
    def export_records(records: list, filepath: str, fmt: str):
        if fmt == "txt":
            with open(filepath, "w", encoding="utf-8") as f:
                for idx, r in enumerate(records, 1):
                    f.write(f"================ 记录 {idx} ================\n")
                    f.write(f"识别时间：{r['extract_time']}  |  分类：{r['category']}\n")
                    f.write(f"原始来源：{r['source_info']}\n")
                    if r.get("media_path"):
                        f.write(f"本地媒体：{r['media_path']}\n")
                    f.write(f"\n{r['content']}\n\n")
        elif fmt == "md":
            with open(filepath, "w", encoding="utf-8") as f:
                f.write("# 文案与媒体提取导出汇总\n\n")
                for r in records:
                    f.write(f"## {r['extract_time']}\n\n")
                    f.write(f"- **分类**：{r['category']}\n")
                    f.write(f"- **原始链接/来源**：{r['source_info']}\n")
                    if r.get("media_path"):
                        f.write(f"- **本地保存文件**：`{r['media_path']}`\n")
                    f.write(f"\n### 识别内容\n\n{r['content']}\n\n---\n\n")
        elif fmt == "docx":
            doc = Document()
            doc.add_heading("文案与媒体提取导出汇总", level=1)
            for r in records:
                doc.add_heading(r['extract_time'], level=2)
                p_meta = doc.add_paragraph()
                p_meta.add_run(f"分类：{r['category']}\n").bold = True
                p_meta.add_run(f"原始来源：{r['source_info']}")
                if r.get("media_path"):
                    doc.add_paragraph(f"本地保存媒体：{r['media_path']}")
                doc.add_paragraph(r['content'])
            doc.save(filepath)
