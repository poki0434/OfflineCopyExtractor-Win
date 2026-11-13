import os
import re
import sys
import subprocess
import tempfile
import numpy as np
import soundfile as sf
import sherpa_onnx
import imageio_ffmpeg
import requests
from bs4 import BeautifulSoup
from rapidocr_onnxruntime import RapidOCR

def get_resource_path(rel_path: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, rel_path)
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, rel_path)

class LocalAiEngine:
    def __init__(self):
        self.recognizer = None
        self.ocr = None

    def init_asr(self):
        if self.recognizer is not None:
            return
        model_dir = get_resource_path("models")
        model_path = os.path.join(model_dir, "model.int8.onnx")
        if not os.path.exists(model_path):
            model_path = os.path.join(model_dir, "model.onnx")
        tokens_path = os.path.join(model_dir, "tokens.txt")

        self.recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=model_path,
            tokens=tokens_path,
            num_threads=max(2, os.cpu_count() or 4),
            use_itn=True,
            language="auto"
        )

    def init_ocr(self):
        if self.ocr is None:
            self.ocr = RapidOCR()

    def transcribe_media(self, input_path: str) -> str:
        self.init_asr()
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        tmp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        try:
            cmd = [
                ffmpeg_exe, "-y", "-i", input_path,
                "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                tmp_wav
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

            samples, sample_rate = sf.read(tmp_wav, dtype="float32")
            if samples.ndim > 1:
                samples = samples[:, 0]

            # 20秒长音频自动切片，防止长段退化或吞字
            chunk_len = 20 * sample_rate
            total_len = len(samples)
            if total_len == 0:
                return "未检测到有效音轨"

            results = []
            for start in range(0, total_len, chunk_len):
                chunk = samples[start:start + chunk_len]
                if len(chunk) < int(0.3 * sample_rate):
                    continue
                stream = self.recognizer.create_stream()
                stream.accept_waveform(sample_rate, chunk)
                self.recognizer.decode_stream(stream)
                txt = stream.result.text.strip()
                if txt:
                    results.append(txt)

            full_text = "".join(results).strip()
            return full_text if full_text else "未识别到清晰人声"
        finally:
            if os.path.exists(tmp_wav):
                os.remove(tmp_wav)

    def recognize_image(self, image_path: str) -> str:
        self.init_ocr()
        result, _ = self.ocr(image_path)
        if not result:
            return "未识别到图片文字"
        lines = [item[1] for item in result if item[1].strip()]
        return "\n".join(lines)

    @staticmethod
    def extract_article(raw_text: str) -> str:
        match = re.search(r"https?://[^\s\u4e00-\u9fa5]+", raw_text)
        if not match:
            return "未在输入中检测到有效网页链接"
        url = match.group(0)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        wx_content = soup.find(id="js_content")
        if wx_content:
            paragraphs = [p.get_text(strip=True) for p in wx_content.find_all(["p", "section", "h1", "h2", "h3"]) if p.get_text(strip=True)]
            dedup = []
            for p in paragraphs:
                if not dedup or dedup[-1] != p:
                    dedup.append(p)
            return "\n\n".join(dedup)

        paragraphs = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 8]
        return "\n\n".join(paragraphs) if paragraphs else soup.get_text("\n", strip=True)
