import os
import re
import sys
import json
import time
import ctypes
import urllib.parse
import requests

os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"

from playwright.sync_api import sync_playwright

DESKTOP_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

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

def embed_chromium_into_widget(title_keyword: str, parent_hwnd: int, width: int, height: int):
    if sys.platform != "win32" or not parent_hwnd:
        return None
    user32 = ctypes.windll.user32
    GWL_STYLE = -16
    WS_CHILD = 0x40000000
    WS_VISIBLE = 0x10000000
    WS_CAPTION = 0x00C00000
    WS_THICKFRAME = 0x00040000

    found_hwnd = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def enum_cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                t = buf.value
                if title_keyword in t and ("Chromium" in t or "Chrome" in t or "抖音" in t or "快手" in t or "小红书" in t or "QQ音乐" in t or "网易云" in t or "about:blank" in t):
                    found_hwnd.append(hwnd)
        return True

    for _ in range(25):
        user32.EnumWindows(enum_cb, 0)
        if found_hwnd:
            break
        time.sleep(0.15)

    if not found_hwnd:
        return None

    child_hwnd = found_hwnd[0]
    style = user32.GetWindowLongW(child_hwnd, GWL_STYLE)
    style = (style & ~WS_CAPTION & ~WS_THICKFRAME) | WS_CHILD | WS_VISIBLE
    user32.SetWindowLongW(child_hwnd, GWL_STYLE, style)
    user32.SetParent(child_hwnd, parent_hwnd)
    user32.MoveWindow(child_hwnd, 0, 0, max(300, width), max(200, height), True)
    return child_hwnd


def _walk_json_for_clean_media(obj, candidates: list, titles: list):
    if isinstance(obj, dict):
        for tk in ("desc", "title", "caption", "noteTitle"):
            val = obj.get(tk)
            if isinstance(val, str) and len(val.strip()) > 2 and not titles:
                titles.append(val.strip())

        if "play_addr" in obj and isinstance(obj["play_addr"], dict):
            ulist = obj["play_addr"].get("url_list") or []
            for u in ulist:
                if isinstance(u, str) and u.startswith("http"):
                    clean_u = u.replace("playwm", "play")
                    if "watermark=0" in clean_u or "playwm" not in u:
                        candidates.insert(0, clean_u)
                    else:
                        candidates.append(clean_u)

        if "masterUrl" in obj and isinstance(obj["masterUrl"], str) and obj["masterUrl"].startswith("http"):
            candidates.insert(0, obj["masterUrl"])

        if "mainMvUrls" in obj and isinstance(obj["mainMvUrls"], list):
            for item in obj["mainMvUrls"]:
                if isinstance(item, dict) and isinstance(item.get("url"), str):
                    candidates.insert(0, item["url"])

        for k, v in obj.items():
            if k in ("download_addr", "downloadAddr", "wm_video_url"):
                continue
            _walk_json_for_clean_media(v, candidates, titles)

    elif isinstance(obj, list):
        for item in obj:
            _walk_json_for_clean_media(item, candidates, titles)


class MediaSniffer:
    def __init__(self, download_root="Downloads", user_data_dir="browser_profile"):
        self.video_dir = os.path.join(download_root, "无水印视频")
        self.music_dir = os.path.join(download_root, "音乐下载")
        self.user_data_dir = user_data_dir
        os.makedirs(self.video_dir, exist_ok=True)
        os.makedirs(self.music_dir, exist_ok=True)

    def _launch_desktop_context(self, p, width=1024, height=680):
        return p.chromium.launch_persistent_context(
            user_data_dir=self.user_data_dir,
            headless=False,
            viewport={"width": width, "height": height},
            user_agent=DESKTOP_UA,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                f"--window-size={width},{height}"
            ],
            ignore_default_args=["--enable-automation"]
        )

    def open_login_window(self, start_url="https://www.douyin.com", host_info_fn=None, on_embed_ready=None, on_embed_closed=None):
        with sync_playwright() as p:
            w, h = (920, 620)
            hwnd = 0
            if host_info_fn:
                hwnd, w, h = host_info_fn()
            ctx = self._launch_desktop_context(p, width=w, height=h)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            if on_embed_ready:
                on_embed_ready()
            embed_chromium_into_widget("", hwnd, w, h)
            page.goto(start_url)
            try:
                page.wait_for_event("close", timeout=300000)
            except Exception:
                pass
            ctx.close()
            if on_embed_closed:
                on_embed_closed()

    def sniff_and_download_video(self, raw_text: str, host_info_fn=None, on_embed_ready=None, on_embed_closed=None) -> dict:
        url = extract_url(raw_text)
        if not url:
            raise ValueError("未识别到有效链接")

        api_clean_urls = []
        stream_fallback_urls = []
        extracted_titles = []

        with sync_playwright() as p:
            w, h = (920, 620)
            hwnd = 0
            if host_info_fn:
                hwnd, w, h = host_info_fn()

            ctx = self._launch_desktop_context(p, width=w, height=h)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            page.add_init_script('''
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.__CLEAN_MEDIA_JSONS__ = [];
                const origParse = JSON.parse;
                JSON.parse = function(text, reviver) {
                    const res = origParse.apply(this, arguments);
                    try {
                        if (typeof text === 'string' && (text.includes('play_addr') || text.includes('masterUrl') || text.includes('mainMvUrls'))) {
                            window.__CLEAN_MEDIA_JSONS__.push(res);
                        }
                    } catch (e) {}
                    return res;
                };
            ''')

            if on_embed_ready:
                on_embed_ready()
            embed_chromium_into_widget("", hwnd, w, h)

            def on_response(response):
                try:
                    ct = response.headers.get("content-type", "").lower()
                    u = response.url
                    if "application/json" in ct or "text/plain" in ct:
                        if any(k in u for k in ("aweme/detail", "aweme/post", "feed", "note", "graphql", "video")):
                            body_txt = response.text()
                            if any(k in body_txt for k in ("play_addr", "masterUrl", "mainMvUrls")):
                                data = json.loads(body_txt)
                                _walk_json_for_clean_media(data, api_clean_urls, extracted_titles)

                    if ("video/" in ct or ".mp4" in u or "aweme/v1/play" in u) and not u.endswith(".ts"):
                        if "watermark=1" in u or "download" in u:
                            return
                        cl = int(response.headers.get("content-length", "0") or 0)
                        if cl > 0 and cl < 80000:
                            return
                        clean_u = u.replace("playwm", "play")
                        if clean_u not in stream_fallback_urls:
                            stream_fallback_urls.append(clean_u)
                except Exception:
                    pass

            page.on("response", on_response)
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            for _ in range(90):
                if not api_clean_urls and not page.is_closed():
                    try:
                        hooked = page.evaluate('''() => {
                            const out = [...(window.__CLEAN_MEDIA_JSONS__ || [])];
                            const rd = document.getElementById('RENDER_DATA');
                            if (rd && rd.textContent) {
                                try { out.push(JSON.parse(decodeURIComponent(rd.textContent))); } catch(e) {}
                            }
                            if (window.__INITIAL_STATE__) {
                                out.push(window.__INITIAL_STATE__);
                            }
                            const vids = Array.from(document.querySelectorAll('video')).map(v => v.currentSrc || v.src).filter(s => s && s.startsWith('http'));
                            return { jsons: out, videoSrcs: vids };
                        }''')
                        for j in hooked.get("jsons", []):
                            _walk_json_for_clean_media(j, api_clean_urls, extracted_titles)
                        for vs in hooked.get("videoSrcs", []):
                            if vs not in stream_fallback_urls:
                                stream_fallback_urls.insert(0, vs.replace("playwm", "play"))
                    except Exception:
                        pass

                if api_clean_urls or stream_fallback_urls:
                    page.wait_for_timeout(1000)
                    break
                if page.is_closed():
                    break
                page.wait_for_timeout(500)

            page_title = ""
            if not page.is_closed():
                page_title = page.title() or ""

            final_candidates = api_clean_urls if api_clean_urls else stream_fallback_urls
            if not final_candidates:
                ctx.close()
                if on_embed_closed:
                    on_embed_closed()
                raise RuntimeError("内嵌视窗关闭前未提取到无水印视频源（如遇滑块验证，请先在右侧内嵌窗口完成滑块并等待视频画面出现）")

            raw_title = extracted_titles[0] if extracted_titles else (page_title or "无水印短视频")
            clean_title = sanitize_filename(re.sub(r"[-_|].*?(抖音|快手|小红书).*", "", raw_title))
            save_path = unique_filepath(self.video_dir, clean_title, ".mp4")

            cookies = ctx.cookies()
            cookie_header = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
            headers = {
                "User-Agent": DESKTOP_UA,
                "Referer": page.url if not page.is_closed() else url,
                "Cookie": cookie_header
            }

            downloaded = False
            last_err = None
            for cand_url in final_candidates[:4]:
                try:
                    with requests.get(cand_url, headers=headers, stream=True, timeout=30) as r:
                        r.raise_for_status()
                        with open(save_path, "wb") as f:
                            for chunk in r.iter_content(chunk_size=65536):
                                if chunk:
                                    f.write(chunk)
                    if os.path.exists(save_path) and os.path.getsize(save_path) > 50000:
                        downloaded = True
                        break
                except Exception as e:
                    last_err = e

            ctx.close()
            if on_embed_closed:
                on_embed_closed()

            if not downloaded:
                raise RuntimeError(f"视频流下载受阻：{last_err}")

        return {
            "title": clean_title,
            "file_path": save_path
        }

    def sniff_and_download_music(self, raw_text: str, host_info_fn=None, on_embed_ready=None, on_embed_closed=None) -> dict:
        url = extract_url(raw_text)
        if not url:
            raise ValueError("未识别到有效音乐链接")

        audio_urls = []
        song_title = ""
        lyrics_text = ""

        with sync_playwright() as p:
            w, h = (920, 620)
            hwnd = 0
            if host_info_fn:
                hwnd, w, h = host_info_fn()

            ctx = self._launch_desktop_context(p, width=w, height=h)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            if on_embed_ready:
                on_embed_ready()
            embed_chromium_into_widget("", hwnd, w, h)

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
                if on_embed_closed:
                    on_embed_closed()
                raise RuntimeError("未嗅探到音频播放流（请直接在右侧内嵌窗口中登录账号并点击网页播放键，再重新提取）")

            target_audio = audio_urls[-1]
            ext = ".flac" if ".flac" in target_audio.lower() else (".mp3" if ".mp3" in target_audio.lower() else ".m4a")
            safe_name = sanitize_filename(song_title)
            save_path = unique_filepath(self.music_dir, safe_name, ext)

            cookies = ctx.cookies()
            cookie_header = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
            headers = {
                "User-Agent": DESKTOP_UA,
                "Referer": url,
                "Cookie": cookie_header
            }
            with requests.get(target_audio, headers=headers, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(save_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)

            ctx.close()
            if on_embed_closed:
                on_embed_closed()

        return {
            "song_name": safe_name,
            "file_path": save_path,
            "lyrics_preview": lyrics_text.strip()
        }
