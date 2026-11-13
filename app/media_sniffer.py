import os
import re
import time
import requests

os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"

from playwright.sync_api import sync_playwright

def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]+', '_', name).strip()
    return cleaned[:100] if cleaned else f"media_{int(time.time())}"

def extract_url(raw_text: str):
    match = re.search(r"https?://[^\s\u4e00-\u9fa5]+", raw_text)
    return match.group(0) if match else None

def unique_filepath(folder: str, base_name: str, ext: str) -> str:
    os.makedirs(folder, exist_ok=True)
    candidate = os.path.join(folder, f"{base_name}{ext}")
    counter = 1
    while os.path.exists(candidate):
        candidate = os.path.join(folder, f"{base_name}_{counter}{ext}")
        counter += 1
    return candidate

class MediaSniffer:
    def __init__(self, download_root="Downloads", user_data_dir="browser_profile"):
        self.video_dir = os.path.join(download_root, "无水印视频")
        self.music_dir = os.path.join(download_root, "音乐下载")
        self.user_data_dir = user_data_dir
        os.makedirs(self.video_dir, exist_ok=True)
        os.makedirs(self.music_dir, exist_ok=True)

    def open_login_window(self, start_url="https://www.douyin.com"):
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=False,
                viewport={"width": 1024, "height": 720}
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(start_url)
            try:
                page.wait_for_event("close", timeout=300000)
            except Exception:
                pass
            ctx.close()

    def sniff_and_download_video(self, raw_text: str, show_browser: bool = True) -> dict:
        url = extract_url(raw_text)
        if not url:
            raise ValueError("未识别到有效链接")

        captured_urls = []
        page_title = ""

        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=False,
                viewport={"width": 460, "height": 820},
                user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            def on_response(response):
                try:
                    ct = response.headers.get("content-type", "").lower()
                    u = response.url
                    if ("video/" in ct or ".mp4" in u or "aweme/v1/play" in u or "video_id=" in u) and not u.endswith(".ts"):
                        clean_u = u.replace("playwm", "play")
                        if clean_u not in captured_urls:
                            captured_urls.append(clean_u)
                except Exception:
                    pass

            page.on("response", on_response)
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            for _ in range(90):
                if captured_urls:
                    page.wait_for_timeout(800)
                    break
                if page.is_closed():
                    break
                page.wait_for_timeout(500)

            if not page.is_closed():
                page_title = page.title() or "无水印短视频"

            if not captured_urls:
                ctx.close()
                raise RuntimeError("小窗关闭前未检测到视频流（如遇滑块验证，请先完成验证等待视频播放后再关闭）")

            target_url = captured_urls[-1]
            clean_title = sanitize_filename(re.sub(r"[-_|].*?(抖音|快手|小红书).*", "", page_title))
            save_path = unique_filepath(self.video_dir, clean_title, ".mp4")

            headers = {
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
                "Referer": url
            }
            with requests.get(target_url, headers=headers, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(save_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)

            ctx.close()

        return {
            "title": clean_title,
            "file_path": save_path
        }

    def sniff_and_download_music(self, raw_text: str, show_browser: bool = True) -> dict:
        url = extract_url(raw_text)
        if not url:
            raise ValueError("未识别到有效音乐链接")

        audio_urls = []
        song_title = ""
        lyrics_text = ""

        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=False,
                viewport={"width": 980, "height": 700}
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            def on_response(response):
                try:
                    ct = response.headers.get("content-type", "").lower()
                    u = response.url
                    if any(k in ct for k in ["audio/", "application/octet-stream"]) or any(ext in u.lower() for ext in [".mp3", ".m4a", ".flac", ".aac", "qqmusic.qq.com", "music.126.net"]):
                        if any(ext in u.lower() for ext in [".mp3", ".m4a", ".flac", ".aac", "vkey="]):
                            if u not in audio_urls:
                                audio_urls.append(u)
                except Exception:
                    pass

            page.on("response", on_response)
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)

            try:
                for selector in ["a[title='播放']", ".btn_play", ".mod_song_play", "button:has-text('播放')", ".u-btni-play"]:
                    btn = page.locator(selector).first
                    if btn.count() > 0:
                        btn.click(timeout=1500)
                        break
            except Exception:
                pass

            for _ in range(90):
                if audio_urls:
                    page.wait_for_timeout(800)
                    break
                if page.is_closed():
                    break
                page.wait_for_timeout(500)

            if not page.is_closed():
                raw_title = page.title() or ""
                song_title = re.sub(r"\s*[-_]\s*(单曲|专辑|在线免费下载|QQ音乐|网易云音乐).*", "", raw_title).strip()
                if not song_title:
                    song_title = f"音乐_{int(time.time())}"
                try:
                    lyrics_text = page.evaluate("() => document.body.innerText")[:1200]
                except Exception:
                    lyrics_text = ""

            if not audio_urls:
                ctx.close()
                raise RuntimeError("未嗅探到音频播放流（请先在小窗中登录账号并点击网页播放键，再重新提取）")

            target_audio = audio_urls[-1]
            ext = ".flac" if ".flac" in target_audio.lower() else (".mp3" if ".mp3" in target_audio.lower() else ".m4a")
            safe_name = sanitize_filename(song_title)
            save_path = unique_filepath(self.music_dir, safe_name, ext)

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
                "Referer": url
            }
            with requests.get(target_audio, headers=headers, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(save_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)

            ctx.close()

        return {
            "song_name": safe_name,
            "file_path": save_path,
            "lyrics_preview": lyrics_text.strip()
        }
