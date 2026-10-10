#!/usr/bin/env python3
"""
Wallpics Desktop Software - Native Windows GUI with Progress Bar
Built with CustomTkinter for a sleek dark-mode desktop interface.
"""

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

# Import the core engine
import download_images

# Appearance configuration
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class WallpicsDesktopApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Wallpics PRO — Ultra-HD Image Downloader")
        self.geometry("900x750")
        self.minsize(800, 650)

        # State
        self.is_running = False
        self.cancel_flag = threading.Event()
        self.event_queue = queue.Queue()
        self.total_images = 0
        self.saved_count = 0
        self.skipped_count = 0
        self.total_bytes = 0
        self.start_time = None

        self._build_ui()
        self._check_system()
        self._poll_events()

    def _build_ui(self):
        # Main container with padding
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)  # log console expands

        # 1. Header Frame
        header_frame = ctk.CTkFrame(self, corner_radius=12, fg_color=("#1a1f2c", "#111625"))
        header_frame.grid(row=0, column=0, padx=16, pady=(16, 10), sticky="ew")
        header_frame.grid_columnconfigure(0, weight=1)

        title_label = ctk.CTkLabel(
            header_frame,
            text="WALLPICS PRO MAX",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color="#6366F1"
        )
        title_label.grid(row=0, column=0, padx=16, pady=(12, 2), sticky="w")

        sub_label = ctk.CTkLabel(
            header_frame,
            text="Native Desktop Ultra-HD Scraper & CDN Original Upscaler",
            font=ctk.CTkFont(size=12),
            text_color="#94A3B8"
        )
        sub_label.grid(row=1, column=0, padx=16, pady=(0, 12), sticky="w")

        self.lbl_system_status = ctk.CTkLabel(
            header_frame,
            text="● Engine Ready",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#10B981"
        )
        self.lbl_system_status.grid(row=0, column=1, rowspan=2, padx=16, pady=12, sticky="e")

        # 2. Source Configuration Frame
        config_frame = ctk.CTkFrame(self, corner_radius=12)
        config_frame.grid(row=1, column=0, padx=16, pady=6, sticky="ew")
        config_frame.grid_columnconfigure(1, weight=1)

        # URL Input
        lbl_url = ctk.CTkLabel(config_frame, text="Target URL:", font=ctk.CTkFont(size=13, weight="bold"))
        lbl_url.grid(row=0, column=0, padx=(16, 8), pady=(12, 4), sticky="w")

        self.entry_url = ctk.CTkEntry(
            config_frame,
            placeholder_text="https://example.com/gallery or wallpaper page...",
            font=ctk.CTkFont(size=13),
            height=36
        )
        self.entry_url.grid(row=0, column=1, padx=6, pady=(12, 4), sticky="ew")

        btn_paste = ctk.CTkButton(
            config_frame,
            text="Paste",
            width=65,
            height=36,
            fg_color="#334155",
            hover_color="#475569",
            command=self._paste_clipboard
        )
        btn_paste.grid(row=0, column=2, padx=(4, 16), pady=(12, 4))

        # Sample Presets Row
        presets_frame = ctk.CTkFrame(config_frame, fg_color="transparent")
        presets_frame.grid(row=1, column=1, columnspan=2, padx=6, pady=(0, 8), sticky="w")

        lbl_presets = ctk.CTkLabel(presets_frame, text="Presets:", font=ctk.CTkFont(size=11), text_color="#64748B")
        lbl_presets.pack(side="left", padx=(0, 6))

        for name, url in [
            ("Unsplash HD", "https://unsplash.com/wallpapers"),
            ("WallpaperCave", "https://wallpapercave.com/cool-wallpapers"),
            ("Wikipedia Aurora", "https://en.wikipedia.org/wiki/Aurora")
        ]:
            b = ctk.CTkButton(
                presets_frame,
                text=name,
                font=ctk.CTkFont(size=11),
                height=24,
                width=80,
                fg_color="#1E293B",
                hover_color="#334155",
                command=lambda u=url: self._set_url(u)
            )
            b.pack(side="left", padx=4)

        # Output Directory Row
        lbl_out = ctk.CTkLabel(config_frame, text="Save To:", font=ctk.CTkFont(size=13, weight="bold"))
        lbl_out.grid(row=2, column=0, padx=(16, 8), pady=8, sticky="w")

        default_out = os.path.abspath("downloaded_images")
        self.entry_output = ctk.CTkEntry(config_frame, height=34, font=ctk.CTkFont(size=12))
        self.entry_output.insert(0, default_out)
        self.entry_output.grid(row=2, column=1, padx=6, pady=8, sticky="ew")

        out_btns_frame = ctk.CTkFrame(config_frame, fg_color="transparent")
        out_btns_frame.grid(row=2, column=2, padx=(4, 16), pady=8)

        btn_browse = ctk.CTkButton(
            out_btns_frame,
            text="Browse...",
            width=75,
            height=34,
            fg_color="#334155",
            hover_color="#475569",
            command=self._browse_output
        )
        btn_browse.pack(side="left", padx=(0, 4))

        btn_open_folder = ctk.CTkButton(
            out_btns_frame,
            text="Open",
            width=55,
            height=34,
            fg_color="#1E293B",
            hover_color="#334155",
            command=self._open_output_folder
        )
        btn_open_folder.pack(side="left")

        # Options Row
        options_frame = ctk.CTkFrame(config_frame, fg_color="transparent")
        options_frame.grid(row=3, column=0, columnspan=3, padx=16, pady=(4, 14), sticky="ew")

        self.sw_render = ctk.CTkSwitch(options_frame, text="Render JavaScript (Playwright)", font=ctk.CTkFont(size=12))
        self.sw_render.pack(side="left", padx=(0, 16))

        self.sw_deep = ctk.CTkSwitch(options_frame, text="Deep Source Scan", font=ctk.CTkFont(size=12))
        self.sw_deep.select()
        self.sw_deep.pack(side="left", padx=16)

        self.sw_upgrade = ctk.CTkSwitch(options_frame, text="Max-Res CDN Rewriting", font=ctk.CTkFont(size=12))
        self.sw_upgrade.select()
        self.sw_upgrade.pack(side="left", padx=16)

        lbl_min = ctk.CTkLabel(options_frame, text="Min Size:", font=ctk.CTkFont(size=12))
        lbl_min.pack(side="left", padx=(16, 6))

        self.combo_min_dim = ctk.CTkComboBox(
            options_frame,
            values=["All Sizes", "300px+", "720px+ HD", "1080px+ FHD", "2160px+ 4K"],
            width=120,
            height=28,
            font=ctk.CTkFont(size=11)
        )
        self.combo_min_dim.set("All Sizes")
        self.combo_min_dim.pack(side="left")

        # 3. Progress Card (Prominent Progress Bar)
        progress_card = ctk.CTkFrame(self, corner_radius=12, fg_color=("#111827", "#0B0F19"), border_width=1, border_color="#374151")
        progress_card.grid(row=2, column=0, padx=16, pady=6, sticky="ew")
        progress_card.grid_columnconfigure(0, weight=1)

        # Progress Header
        prog_header = ctk.CTkFrame(progress_card, fg_color="transparent")
        prog_header.grid(row=0, column=0, padx=16, pady=(12, 4), sticky="ew")
        prog_header.grid_columnconfigure(0, weight=1)

        self.lbl_stage = ctk.CTkLabel(
            prog_header,
            text="IDLE",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#06B6D4"
        )
        self.lbl_stage.grid(row=0, column=0, sticky="w")

        self.lbl_status = ctk.CTkLabel(
            prog_header,
            text="Ready to extract images",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#F8FAFC"
        )
        self.lbl_status.grid(row=1, column=0, sticky="w", pady=(2, 0))

        self.lbl_percent = ctk.CTkLabel(
            prog_header,
            text="0%",
            font=ctk.CTkFont(size=28, weight="bold"),
            text_color="#6366F1"
        )
        self.lbl_percent.grid(row=0, column=1, rowspan=2, sticky="e")

        # Progress Bar Widget
        self.progress_bar = ctk.CTkProgressBar(
            progress_card,
            height=16,
            corner_radius=8,
            progress_color="#6366F1",
            fg_color="#1F2937"
        )
        self.progress_bar.set(0.0)
        self.progress_bar.grid(row=1, column=0, padx=16, pady=8, sticky="ew")

        # Metrics Row
        metrics_frame = ctk.CTkFrame(progress_card, fg_color="transparent")
        metrics_frame.grid(row=2, column=0, padx=16, pady=(2, 12), sticky="ew")

        self.lbl_m_found = ctk.CTkLabel(metrics_frame, text="Found: 0", font=ctk.CTkFont(size=12, weight="bold"), text_color="#94A3B8")
        self.lbl_m_found.pack(side="left", padx=(0, 20))

        self.lbl_m_processed = ctk.CTkLabel(metrics_frame, text="Processed: 0", font=ctk.CTkFont(size=12, weight="bold"), text_color="#94A3B8")
        self.lbl_m_processed.pack(side="left", padx=20)

        self.lbl_m_saved = ctk.CTkLabel(metrics_frame, text="Saved: 0", font=ctk.CTkFont(size=12, weight="bold"), text_color="#10B981")
        self.lbl_m_saved.pack(side="left", padx=20)

        self.lbl_m_skipped = ctk.CTkLabel(metrics_frame, text="Skipped: 0", font=ctk.CTkFont(size=12, weight="bold"), text_color="#F59E0B")
        self.lbl_m_skipped.pack(side="left", padx=20)

        self.lbl_m_size = ctk.CTkLabel(metrics_frame, text="Size: 0.0 MB", font=ctk.CTkFont(size=12, weight="bold"), text_color="#06B6D4")
        self.lbl_m_size.pack(side="left", padx=20)

        self.lbl_m_time = ctk.CTkLabel(metrics_frame, text="Elapsed: 0s", font=ctk.CTkFont(size=12), text_color="#64748B")
        self.lbl_m_time.pack(side="right")

        # 4. Action Buttons
        actions_frame = ctk.CTkFrame(self, fg_color="transparent")
        actions_frame.grid(row=3, column=0, padx=16, pady=6, sticky="ew")
        actions_frame.grid_columnconfigure(0, weight=1)

        self.btn_start = ctk.CTkButton(
            actions_frame,
            text="START EXTRACTION (MAX QUALITY)",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=44,
            fg_color="#6366F1",
            hover_color="#4F46E5",
            command=self._start_download
        )
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.btn_cancel = ctk.CTkButton(
            actions_frame,
            text="CANCEL",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=44,
            width=120,
            fg_color="#E11D48",
            hover_color="#BE123C",
            state="disabled",
            command=self._cancel_download
        )
        self.btn_cancel.pack(side="right")

        # 5. Live Activity Log Console
        console_frame = ctk.CTkFrame(self, corner_radius=12)
        console_frame.grid(row=4, column=0, padx=16, pady=(6, 16), sticky="nsew")
        console_frame.grid_columnconfigure(0, weight=1)
        console_frame.grid_rowconfigure(1, weight=1)

        console_bar = ctk.CTkFrame(console_frame, fg_color="transparent")
        console_bar.grid(row=0, column=0, padx=14, pady=(8, 4), sticky="ew")
        console_bar.grid_columnconfigure(0, weight=1)

        lbl_console = ctk.CTkLabel(console_bar, text="Console Activity & Download Feed:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#94A3B8")
        lbl_console.grid(row=0, column=0, sticky="w")

        btn_clear_log = ctk.CTkButton(
            console_bar,
            text="Clear",
            width=50,
            height=22,
            font=ctk.CTkFont(size=11),
            fg_color="#334155",
            hover_color="#475569",
            command=self._clear_logs
        )
        btn_clear_log.grid(row=0, column=1, sticky="e")

        self.txt_console = ctk.CTkTextbox(
            console_frame,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#090D16",
            text_color="#E2E8F0"
        )
        self.txt_console.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="nsew")
        self._append_log("Wallpics desktop software initialized. Ready for input.")

    def _check_system(self):
        pillow_ok = download_images.Image is not None
        status = ["Engine Ready"]
        if pillow_ok:
            status.append("Pillow Active")
        self.lbl_system_status.configure(text="● " + " • ".join(status))

    def _paste_clipboard(self):
        try:
            text = self.clipboard_get().strip()
            if text:
                self.entry_url.delete(0, tk.END)
                self.entry_url.insert(0, text)
        except Exception:
            pass

    def _set_url(self, url):
        self.entry_url.delete(0, tk.END)
        self.entry_url.insert(0, url)
        if "unsplash" in url or "wallpapercave" in url:
            self.sw_render.select()

    def _browse_output(self):
        folder = filedialog.askdirectory(initialdir=self.entry_output.get(), title="Select Output Folder")
        if folder:
            self.entry_output.delete(0, tk.END)
            self.entry_output.insert(0, folder)

    def _open_output_folder(self):
        folder = self.entry_output.get().strip() or os.path.abspath("downloaded_images")
        os.makedirs(folder, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(os.path.abspath(folder))
            else:
                subprocess.Popen(["xdg-open" if sys.platform != "darwin" else "open", folder])
        except Exception as e:
            messagebox.showerror("Error", f"Could not open directory: {e}")

    def _clear_logs(self):
        self.txt_console.delete("1.0", tk.END)

    def _append_log(self, text):
        t = time.strftime("%H:%M:%S")
        self.txt_console.insert(tk.END, f"[{t}] {text}\n")
        self.txt_console.see(tk.END)

    def _start_download(self):
        url = self.entry_url.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Please enter a target webpage URL.")
            self.entry_url.focus()
            return

        if not (url.startswith("http://") or url.startswith("https://")):
            url = "https://" + url
            self.entry_url.delete(0, tk.END)
            self.entry_url.insert(0, url)

        # Parse min dim
        min_map = {"All Sizes": 0, "300px+": 300, "720px+ HD": 720, "1080px+ FHD": 1080, "2160px+ 4K": 2160}
        min_dim = min_map.get(self.combo_min_dim.get(), 0)

        output_dir = self.entry_output.get().strip() or "downloaded_images"
        render = bool(self.sw_render.get())
        deep = bool(self.sw_deep.get())
        no_upgrade = not bool(self.sw_upgrade.get())

        # Reset counters
        self.is_running = True
        self.cancel_flag.clear()
        self.total_images = 0
        self.saved_count = 0
        self.skipped_count = 0
        self.total_bytes = 0
        self.start_time = time.time()

        self.progress_bar.set(0.0)
        self.lbl_percent.configure(text="0%")
        self.lbl_stage.configure(text="CONNECTING")
        self.lbl_status.configure(text=f"Connecting to {url}...")
        self.lbl_m_found.configure(text="Found: 0")
        self.lbl_m_processed.configure(text="Processed: 0")
        self.lbl_m_saved.configure(text="Saved: 0")
        self.lbl_m_skipped.configure(text="Skipped: 0")
        self.lbl_m_size.configure(text="Size: 0.0 MB")
        self.lbl_m_time.configure(text="Elapsed: 0s")

        self.btn_start.configure(state="disabled", text="DOWNLOADING...")
        self.btn_cancel.configure(state="normal")

        self._append_log(f"Starting extraction for: {url}")

        # Launch background thread
        threading.Thread(
            target=self._worker_thread,
            args=(url, output_dir, render, deep, no_upgrade, min_dim),
            daemon=True
        ).start()

    def _cancel_download(self):
        if self.is_running:
            self.cancel_flag.set()
            self.btn_cancel.configure(state="disabled", text="STOPPING...")
            self._append_log("Cancellation requested by user...")

    def _worker_thread(self, url, output_dir, render, deep, no_upgrade, min_dim):
        def cb(ev):
            self.event_queue.put(ev)

        try:
            download_images.download_images(
                url=url,
                output=output_dir,
                render=render,
                deep=deep,
                no_upgrade=no_upgrade,
                min_dim=min_dim,
                debug=True,
                progress_callback=cb,
                is_cancelled=self.cancel_flag.is_set
            )
        except Exception as e:
            self.event_queue.put({"type": "error", "message": str(e)})

    def _poll_events(self):
        while not self.event_queue.empty():
            try:
                ev = self.event_queue.get_nowait()
                self._handle_event(ev)
            except queue.Empty:
                break

        if self.is_running and self.start_time:
            elapsed = int(time.time() - self.start_time)
            self.lbl_m_time.configure(text=f"Elapsed: {elapsed}s")

        self.after(80, self._poll_events)

    def _handle_event(self, ev):
        t = ev.get("type")

        if t == "status":
            stage = ev.get("stage", "working").upper()
            msg = ev.get("message", "")
            self.lbl_stage.configure(text=stage)
            self.lbl_status.configure(text=msg)
            self._append_log(msg)

        elif t == "scraped":
            self.total_images = ev.get("total", 0)
            self.lbl_m_found.configure(text=f"Found: {self.total_images}")
            self.lbl_stage.configure(text="SCRAPED")
            self.lbl_status.configure(text=f"Found {self.total_images} logical images")
            self._append_log(f"Discovered {self.total_images} images on webpage.")

        elif t == "progress":
            pct = ev.get("percent", 0.0)
            self.progress_bar.set(pct / 100.0)
            self.lbl_percent.configure(text=f"{int(pct)}%")
            idx = ev.get("index", 0)
            tot = ev.get("total", 0)
            self.lbl_m_processed.configure(text=f"Processed: {idx}/{tot}")
            self.lbl_status.configure(text=ev.get("status", ""))

        elif t == "log":
            lvl = ev.get("level", "info")
            if lvl != "debug":
                self._append_log(ev.get("message", ""))

        elif t == "image_result":
            status = ev.get("status")
            if status == "saved":
                self.saved_count += 1
                f = ev.get("file", {})
                self.total_bytes += f.get("size_bytes", 0)
                mb = self.total_bytes / (1024 * 1024)
                self.lbl_m_saved.configure(text=f"Saved: {self.saved_count}")
                self.lbl_m_size.configure(text=f"Size: {mb:.1f} MB")
                self._append_log(f"✓ Saved: {f.get('filename')} ({f.get('dim_str')}, {f.get('size_kb')} KB)")
            elif status == "skipped":
                self.skipped_count += 1
                self.lbl_m_skipped.configure(text=f"Skipped: {self.skipped_count}")
                self._append_log(f"⚠ {ev.get('message', '')}")
            elif status == "failed":
                self._append_log(f"✕ {ev.get('message', '')}")

        elif t == "done":
            self._finish_job("COMPLETED", f"Completed: {ev.get('saved', self.saved_count)} saved to folder.", "#10B981")

        elif t == "cancelled":
            self._finish_job("CANCELLED", "Download cancelled by user.", "#F59E0B")

        elif t == "error":
            self._finish_job("ERROR", ev.get("message", "An error occurred."), "#EF4444")

    def _finish_job(self, stage, msg, color):
        self.is_running = False
        self.progress_bar.set(1.0 if stage == "COMPLETED" else self.progress_bar.get())
        if stage == "COMPLETED":
            self.lbl_percent.configure(text="100%")
        self.lbl_stage.configure(text=stage, text_color=color)
        self.lbl_status.configure(text=msg)
        self.btn_start.configure(state="normal", text="START EXTRACTION (MAX QUALITY)")
        self.btn_cancel.configure(state="disabled", text="CANCEL")
        self._append_log(f"--- {msg} ---")


if __name__ == "__main__":
    app = WallpicsDesktopApp()
    app.mainloop()
