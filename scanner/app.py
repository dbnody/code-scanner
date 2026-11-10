"""离线扫码桌面界面。

支持拖拽 / 粘贴 / 截图扫码，批量与文件夹识别，预览标注与图像预处理。
"""

from __future__ import annotations

import csv
import os
import queue
import threading
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:  # 拖拽依赖，缺失时自动降级
    from tkinterdnd2 import DND_FILES, TkinterDnD

    _DND = True
    _Base = TkinterDnD.Tk
except Exception:  # noqa: BLE001
    DND_FILES = ""
    _DND = False
    _Base = tk.Tk

from .annotate import annotate
from .batch import is_image, read_image, relative_source, scan_folder
from .decoder import DecodeResult, backend_status, decode_image
from .preprocess import OPTION_KEYS, OPTION_LABELS, decode_with_options
from .stitcher import list_fragments, stitch_fragments as stitch_folder

IMAGE_TYPES = [("图片", "*.png *.jpg *.jpeg *.bmp *.webp"), ("所有文件", "*.*")]
PREVIEW_LIMIT = 12


class RegionSelector(tk.Toplevel):
    """全屏半透明遮罩，拖出矩形后回调 (x1, y1, x2, y2)；取消时回调 None。"""

    def __init__(self, master: tk.Misc, callback: Any) -> None:
        super().__init__(master)
        self.callback = callback
        self.start: tuple[int, int] | None = None
        self.rect: int | None = None
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.3)
        try:
            self.attributes("-fullscreen", True)
        except tk.TclError:
            self.geometry("1600x900+0+0")
        self.configure(bg="black")
        self.canvas = tk.Canvas(self, cursor="cross", bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.bind("<Escape>", lambda _event: self._cancel())
        self.focus_force()

    def _press(self, event: tk.Event) -> None:
        self.start = (event.x_root, event.y_root)
        self.rect = self.canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="#ff5c52", width=3)

    def _drag(self, event: tk.Event) -> None:
        if self.start is None or self.rect is None:
            return
        x0, y0 = self.start
        self.canvas.coords(self.rect, x0, y0, event.x_root, event.y_root)
        self.canvas.configure(cursor="cross")

    def _release(self, event: tk.Event) -> None:
        if self.start is None:
            self._cancel()
            return
        x0, y0 = self.start
        x1, y1 = event.x_root, event.y_root
        self.destroy()
        if abs(x1 - x0) < 8 or abs(y1 - y0) < 8:
            self.callback(None)
        else:
            self.callback((min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))

    def _cancel(self) -> None:
        self.destroy()
        self.callback(None)


class ScannerApp(_Base):
    def __init__(self) -> None:
        super().__init__()
        self.title("离线扫码 · 多码识别")
        self.geometry("1180x760")
        self.minsize(960, 620)
        self.configure(bg="#fff8f2")
        self.camera = None
        self.camera_running = False
        self.camera_results: list[DecodeResult] = []
        self.preview_image = None
        self.last_frame = None
        self.results: list[dict[str, Any]] = []
        self.previews: dict[str, Any] = {}
        self.failed: list[tuple[str, str, str]] = []
        self.cancel_event: threading.Event | None = None
        self.batch_generation = 0
        self.batch_total = 0
        self.last_batch_view: tuple[Any, Any, list[DecodeResult]] | None = None
        self.current_image = None
        self.current_decoded: list[DecodeResult] = []
        self.current_highlight: Any = None
        self.original_image = None
        self.processed_image = None
        self.option_vars = {key: tk.BooleanVar(value=False) for key in OPTION_KEYS}
        self.strategy_var = tk.StringVar(value="普通")
        self.sort_var = tk.StringVar(value="文件名")
        self.compare_var = tk.BooleanVar(value=False)
        self._ui_queue: queue.Queue[Any] = queue.Queue()
        self._closed = False
        self._build_style()
        self._build_ui()
        self._setup_dnd()
        self.bind_all("<Control-v>", lambda _event: self.paste_clipboard())
        self.bind_all("<Control-V>", lambda _event: self.paste_clipboard())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(60, self._drain_queue)

    def _post(self, callback: Any) -> None:
        """把界面更新丢回主线程执行；后台线程不直接碰 Tk 控件。"""
        self._ui_queue.put(callback)

    def _drain_queue(self) -> None:
        if self._closed:
            return
        while True:
            try:
                callback = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception:  # noqa: BLE001 - 单个界面回调失败不打断轮询
                pass
        self.after(60, self._drain_queue)

    def _build_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", background="#fff8f2", foreground="#402a2a", font=("Microsoft YaHei UI", 20, "bold"))
        style.configure("Sub.TLabel", background="#fff8f2", foreground="#806c6c", font=("Microsoft YaHei UI", 10))
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("Accent.TButton", background="#ff7b72", foreground="#ffffff", padding=(14, 8), font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#ef665e")])
        style.configure("Soft.TButton", padding=(10, 6), font=("Microsoft YaHei UI", 9))

    def _build_ui(self) -> None:
        header = ttk.Frame(self, style="Card.TFrame", padding=(22, 16, 22, 12))
        header.pack(fill="x", padx=18, pady=(18, 8))
        ttk.Label(header, text="✨ 离线扫码", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="拖拽 / 粘贴 / 截图 · 批量与文件夹识别 · 完全离线，不上传图片", style="Sub.TLabel").pack(anchor="w", pady=(4, 0))

        toolbar = ttk.Frame(self, style="Card.TFrame", padding=(12, 10))
        toolbar.pack(fill="x", padx=18, pady=(0, 6))
        ttk.Button(toolbar, text="打开图片", style="Accent.TButton", command=self.open_image).pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="批量识别图片", style="Soft.TButton", command=self.batch_decode).pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="扫描文件夹", style="Soft.TButton", command=self.scan_folder_dialog).pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="截图扫码", style="Soft.TButton", command=self.screenshot).pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="粘贴图片", style="Soft.TButton", command=self.paste_clipboard).pack(side="left", padx=(0, 6))
        self.camera_button = ttk.Button(toolbar, text="启动摄像头", style="Soft.TButton", command=self.toggle_camera)
        self.camera_button.pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="拼接碎片二维码", style="Soft.TButton", command=self.stitch_fragments).pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="复制全部结果", style="Soft.TButton", command=self.copy_all).pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="导出 CSV", style="Soft.TButton", command=self.export_csv).pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="清空记录", style="Soft.TButton", command=self.clear_results).pack(side="right")

        options = ttk.Frame(self, style="Card.TFrame", padding=(12, 8))
        options.pack(fill="x", padx=18, pady=(0, 8))
        ttk.Label(options, text="预处理：", style="Sub.TLabel").pack(side="left")
        for key in OPTION_KEYS:
            ttk.Checkbutton(options, text=OPTION_LABELS[key], variable=self.option_vars[key], command=self._rerender).pack(side="left", padx=1)
        ttk.Label(options, text="  策略：", style="Sub.TLabel").pack(side="left")
        ttk.Combobox(options, textvariable=self.strategy_var, values=("普通", "困难"), width=5, state="readonly").pack(side="left", padx=(2, 8))
        ttk.Checkbutton(options, text="前后对比", variable=self.compare_var, command=self._rerender).pack(side="left", padx=(0, 10))
        self.retry_button = ttk.Button(options, text="重试失败 (0)", style="Soft.TButton", command=self.retry_failed, state="disabled")
        self.retry_button.pack(side="left")
        ttk.Combobox(options, textvariable=self.sort_var, values=("文件名", "修改时间"), width=7, state="readonly").pack(side="right")
        ttk.Label(options, text="排序：", style="Sub.TLabel").pack(side="right")

        content = ttk.Panedwindow(self, orient="horizontal")
        content.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        left = ttk.Frame(content, style="Card.TFrame", padding=12)
        right = ttk.Frame(content, style="Card.TFrame", padding=12)
        content.add(left, weight=3)
        content.add(right, weight=2)

        self.preview = tk.Label(
            left,
            text="把图片拖到这里，或按 Ctrl+V 粘贴截图\n识别过程完全在本机完成",
            bg="#fff2ed",
            fg="#a98f88",
            font=("Microsoft YaHei UI", 14),
            justify="center",
        )
        self.preview.pack(fill="both", expand=True)
        self.status_var = tk.StringVar(value=f"识别引擎：{backend_status()}")
        ttk.Label(left, textvariable=self.status_var, style="Sub.TLabel").pack(anchor="w", pady=(9, 0))
        bar_row = ttk.Frame(left, style="Card.TFrame")
        bar_row.pack(fill="x", pady=(6, 0))
        self.progress = ttk.Progressbar(bar_row, mode="determinate", maximum=1, value=0)
        self.progress.pack(side="left", fill="x", expand=True)
        self.cancel_button = ttk.Button(bar_row, text="取消", style="Soft.TButton", command=self.cancel_batch, state="disabled")
        self.cancel_button.pack(side="left", padx=(8, 0))

        ttk.Label(right, text="识别结果", font=("Microsoft YaHei UI", 14, "bold"), foreground="#402a2a").pack(anchor="w", pady=(0, 8))
        columns = ("time", "source", "format", "text")
        self.table = ttk.Treeview(right, columns=columns, show="headings", selectmode="extended")
        self.table.heading("time", text="时间")
        self.table.heading("source", text="来源")
        self.table.heading("format", text="类型")
        self.table.heading("text", text="内容")
        self.table.column("time", width=72, anchor="center")
        self.table.column("source", width=118, anchor="w")
        self.table.column("format", width=86, anchor="center")
        self.table.column("text", width=252, anchor="w")
        scroll = ttk.Scrollbar(right, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.table.bind("<<TreeviewSelect>>", self._on_row_select)

    # ---------- 拖拽 / 粘贴 / 截图 ----------

    def _setup_dnd(self) -> None:
        if not _DND:
            self.status_var.set(f"识别引擎：{backend_status()}  ·  未安装 tkinterdnd2，拖拽不可用（可用按钮或 Ctrl+V）")
            return
        try:
            for widget in (self, self.preview):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)
        except tk.TclError:
            pass

    def _on_drop(self, event: Any) -> None:
        paths = [Path(item) for item in self.tk.splitlist(event.data)]
        images = [path for path in paths if is_image(path)]
        if not images:
            self.status_var.set("拖入的文件里没有支持的图片")
            return
        if len(images) == 1:
            self.decode_path(str(images[0]))
        else:
            self._start_batch([(path, path.name) for path in images])

    def paste_clipboard(self) -> None:
        try:
            from PIL import ImageGrab
        except ImportError:
            messagebox.showerror("缺少依赖", "请先运行 install_windows.bat 安装识别依赖。")
            return
        try:
            data = ImageGrab.grabclipboard()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("粘贴失败", str(exc))
            return
        if isinstance(data, list):
            images = [Path(item) for item in data if is_image(Path(item))]
            if images:
                self._start_batch([(path, path.name) for path in images])
            else:
                self.status_var.set("剪贴板里没有图片文件")
            return
        if data is None:
            self.status_var.set("剪贴板里没有图片或图片文件")
            return
        try:
            import numpy as np

            image = np.array(data.convert("RGB"))[:, :, ::-1].copy()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("粘贴失败", str(exc))
            return
        self._show_frame(image)
        self._decode_image_async(image, "剪贴板")

    def screenshot(self) -> None:
        self.withdraw()
        self.after(250, self._open_selector)

    def _open_selector(self) -> None:
        self._selector = RegionSelector(self, self._on_region_selected)

    def _on_region_selected(self, bbox: Any) -> None:
        if bbox is None:
            self.deiconify()
            self.status_var.set("已取消截图")
            return
        # 主窗口仍然隐藏，遮罩刚销毁，稍等一帧再抓屏，避免把界面本身截进来
        self.after(120, lambda: self._grab_region(bbox))

    def _grab_region(self, bbox: Any) -> None:
        try:
            from PIL import ImageGrab
            import numpy as np

            image = np.array(ImageGrab.grab(bbox=bbox).convert("RGB"))[:, :, ::-1].copy()
        except Exception as exc:  # noqa: BLE001
            self.deiconify()
            messagebox.showerror("截图失败", str(exc))
            return
        self.deiconify()
        self._show_frame(image)
        self._decode_image_async(image, "截图")

    # ---------- 单张识别 ----------

    def open_image(self) -> None:
        path = filedialog.askopenfilename(title="选择要识别的图片", filetypes=IMAGE_TYPES)
        if path:
            self.decode_path(path)

    def decode_path(self, path: str, source: str | None = None) -> None:
        try:
            image = read_image(path)
        except ImportError:
            messagebox.showerror("缺少依赖", "请先运行 install_windows.bat 安装识别依赖。")
            return
        if image is None:
            messagebox.showerror("打开失败", f"无法读取图片：{path}")
            return
        self._show_frame(image)
        self._decode_image_async(image, source or os.path.basename(path))

    def _decode_image_async(self, image: Any, source: str) -> None:
        options = self._active_options()
        hard = self._hard_mode()
        self.status_var.set(f"正在识别：{source}…")

        def worker() -> None:
            try:
                decoded, processed, note = decode_with_options(image, options, hard)
            except Exception as exc:  # noqa: BLE001
                error_text = str(exc)
                self._post(lambda: self.status_var.set(f"识别失败：{error_text}"))
                return
            self._post(lambda: self._show_decoded(image, processed, decoded, note, source))

        threading.Thread(target=worker, daemon=True).start()

    def _show_decoded(self, image: Any, processed: Any, decoded: list[DecodeResult], note: str, source: str) -> None:
        self.original_image = image
        self.processed_image = processed
        self.previews[source] = processed
        self._trim_previews()
        self._add_results(decoded, source=source, dedupe=False)
        self._show_frame(processed, results=decoded)
        suffix = f"（预处理：{note}）" if note else ""
        if decoded:
            self.status_var.set(f"{source}：识别到 {len(decoded)} 条{suffix}")
        else:
            self.status_var.set(f"{source}：没有识别到码{suffix}")

    # ---------- 批量 / 文件夹 ----------

    def batch_decode(self) -> None:
        paths = filedialog.askopenfilenames(title="选择要识别的图片（可多选，按选择顺序展示结果）", filetypes=IMAGE_TYPES)
        if paths:
            self._start_batch([(Path(path), os.path.basename(path)) for path in paths])

    def scan_folder_dialog(self) -> None:
        folder = filedialog.askdirectory(title="选择要递归扫描的文件夹")
        if not folder:
            return
        try:
            paths = scan_folder(folder, recursive=True, sort_by="mtime" if self.sort_var.get() == "修改时间" else "name")
        except OSError as exc:
            messagebox.showerror("扫描失败", str(exc))
            return
        if not paths:
            messagebox.showinfo("没有图片", "该文件夹里没有 PNG/JPG/BMP/WEBP 图片。")
            return
        self._start_batch([(path, relative_source(path, folder)) for path in paths])

    def _start_batch(self, items: list[tuple[Path, str]]) -> None:
        if self.cancel_event is not None:
            messagebox.showinfo("任务进行中", "请等待当前任务完成，或先点击「取消」。")
            return
        options = self._active_options()
        hard = self._hard_mode()
        self.cancel_event = threading.Event()
        self.batch_generation += 1
        generation = self.batch_generation
        cancel_event = self.cancel_event
        self.progress.configure(maximum=max(1, len(items)), value=0)
        self.cancel_button.configure(state="normal")
        self.status_var.set(f"开始识别 {len(items)} 张图片…")
        self.batch_total = len(items)

        def worker() -> None:
            failures: list[tuple[str, str, str]] = []
            found = 0
            done = 0
            for path, source in items:
                if cancel_event.is_set():
                    break
                try:
                    image = read_image(path)
                    if image is None:
                        raise ValueError("无法读取图片")
                    decoded, processed, _note = decode_with_options(image, options, hard)
                except Exception as exc:  # noqa: BLE001
                    failures.append((str(path), source, str(exc)))
                    processed, decoded = None, []
                done += 1
                found += len(decoded)
                self._post(partial(self._on_batch_item, source, image, processed, decoded, done))
            cancelled = cancel_event.is_set()
            self._post(lambda: self._finish_batch(failures, cancelled, generation, done, found))

        threading.Thread(target=worker, daemon=True).start()

    def _on_batch_item(self, source: str, original: Any, processed: Any, decoded: list[DecodeResult], done: int) -> None:
        if processed is not None:
            self.previews[source] = processed
            self._trim_previews()
            self.last_batch_view = (original, processed, decoded)
        self._add_results(decoded, source=source, dedupe=False)
        self.progress.configure(value=done)
        self.status_var.set(f"识别中 {done}/{self.batch_total}：{source}")

    def _finish_batch(self, failures: list[tuple[str, str, str]], cancelled: bool, generation: int, done: int, found: int) -> None:
        if generation != self.batch_generation:
            return
        if self.last_batch_view is not None:
            original, processed, decoded = self.last_batch_view
            self.original_image, self.processed_image = original, processed
            self._show_frame(processed, results=decoded)
        self.failed = failures
        self.retry_button.configure(text=f"重试失败 ({len(failures)})", state="normal" if failures else "disabled")
        self.cancel_button.configure(state="disabled")
        self.cancel_event = None
        if cancelled:
            self.status_var.set(f"已取消：完成 {done} 张，失败 {len(failures)} 张")
            return
        message = f"完成 {done} 张，共 {found} 条结果"
        if failures:
            message += f"，失败 {len(failures)} 张（可点「重试失败」）"
        self.status_var.set(message)

    def cancel_batch(self) -> None:
        if self.cancel_event is not None:
            self.cancel_event.set()
            self.cancel_button.configure(state="disabled")
            self.status_var.set("正在取消…")

    def retry_failed(self) -> None:
        if not self.failed:
            messagebox.showinfo("没有失败项", "当前没有识别失败的图片。")
            return
        items = [(Path(abs_path), source) for abs_path, source, _reason in self.failed]
        self.failed = []
        self.retry_button.configure(text="重试失败 (0)", state="disabled")
        self._start_batch(items)

    # ---------- 预览与结果 ----------

    def _render(self, image: Any, decoded: list[DecodeResult]) -> Any:
        import cv2
        from PIL import Image

        pil = annotate(image, decoded, self.current_highlight) if decoded else Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        if self.compare_var.get() and image is self.processed_image and self.original_image is not None and image is not self.original_image:
            import numpy as np

            original = cv2.cvtColor(self.original_image, cv2.COLOR_BGR2RGB)
            processed = np.array(pil)
            height = min(original.shape[0], processed.shape[0])
            original = cv2.resize(original, (max(1, int(original.shape[1] * height / original.shape[0])), height))
            processed = cv2.resize(processed, (max(1, int(processed.shape[1] * height / processed.shape[0])), height))
            pil = Image.fromarray(np.hstack([original, processed]))
        return pil

    def _show_frame(self, image: Any, results: list[DecodeResult] | None = None, highlight: Any = None) -> None:
        self.current_image = image
        self.current_decoded = list(results or [])
        self.current_highlight = highlight
        try:
            from PIL import Image, ImageTk
        except ImportError:
            self.preview.configure(text="缺少 Pillow/OpenCV，请先安装依赖", image="")
            return
        pil = self._render(image, self.current_decoded)
        pil.thumbnail((760, 560), Image.Resampling.LANCZOS)
        self.preview_image = ImageTk.PhotoImage(pil)
        self.preview.configure(image=self.preview_image, text="")

    def _rerender(self) -> None:
        if self.current_image is not None:
            self._show_frame(self.current_image, self.current_decoded, self.current_highlight)

    def _on_row_select(self, _event: Any = None) -> None:
        selection = self.table.selection()
        if not selection:
            return
        index = self.table.index(selection[0])
        if index >= len(self.results):
            return
        row = self.results[index]
        image = self.previews.get(row["source"])
        if image is None:
            return
        same_source = [
            DecodeResult(other["text"], other["format"], other["position"])
            for other in self.results
            if other["source"] == row["source"] and other["position"]
        ]
        self._show_frame(image, results=same_source, highlight=row["position"])

    def _add_results(self, decoded: list[DecodeResult], source: str = "", dedupe: bool = True) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        for item in decoded:
            if dedupe and any(row["text"] == item.text and row["format"] == item.format_name for row in self.results):
                continue
            row = {"time": now, "source": source, "format": item.format_name, "text": item.text, "position": item.position}
            self.results.append(row)
            self.table.insert("", "end", values=(row["time"], row["source"], row["format"], row["text"]))
        self.status_var.set(f"识别引擎：{backend_status()}  ·  已识别 {len(self.results)} 条")

    def _trim_previews(self) -> None:
        while len(self.previews) > PREVIEW_LIMIT:
            self.previews.pop(next(iter(self.previews)))

    # ---------- 摄像头 ----------

    def toggle_camera(self) -> None:
        if self.camera_running:
            self._stop_camera()
            return
        try:
            import cv2

            self.camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            if not self.camera.isOpened():
                self.camera.release()
                self.camera = cv2.VideoCapture(0)
            if not self.camera.isOpened():
                raise RuntimeError("没有找到可用摄像头")
            self.camera_running = True
            self.camera_button.configure(text="停止摄像头")
            self._camera_tick()
        except ImportError:
            messagebox.showerror("缺少依赖", "请先运行 install_windows.bat 安装识别依赖。")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("摄像头启动失败", str(exc))

    def _camera_tick(self) -> None:
        if not self.camera_running or self.camera is None:
            return
        ok, frame = self.camera.read()
        if ok:
            self.last_frame = frame
            self._show_frame(frame, results=self.camera_results)
            self._decode_frame_async(frame)
        self.after(120, self._camera_tick)

    def _decode_frame_async(self, frame: Any) -> None:
        snapshot = frame.copy()

        def worker() -> None:
            try:
                decoded = decode_image(snapshot)
            except Exception as exc:  # noqa: BLE001
                error_text = str(exc)
                self._post(lambda: self.status_var.set(f"识别失败：{error_text}"))
                return
            if decoded:
                self._post(lambda: self._on_camera_results(decoded))

        threading.Thread(target=worker, daemon=True).start()

    def _on_camera_results(self, decoded: list[DecodeResult]) -> None:
        self.camera_results = decoded
        self._add_results(decoded, source="摄像头", dedupe=True)
        if self.last_frame is not None:
            self._show_frame(self.last_frame, results=decoded)

    def _stop_camera(self) -> None:
        self.camera_running = False
        self.camera_results = []
        self.camera_button.configure(text="启动摄像头")
        if self.camera is not None:
            self.camera.release()
            self.camera = None

    # ---------- 碎片拼接 ----------

    def stitch_fragments(self) -> None:
        folder = filedialog.askdirectory(title="选择存放碎片图片的文件夹")
        if not folder:
            return
        try:
            paths = list_fragments(folder)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("无法读取碎片", str(exc))
            return
        if len(paths) < 4:
            messagebox.showwarning("碎片不足", "文件夹里至少要有 4 张碎片图片。")
            return
        self.status_var.set(f"正在拼接 {len(paths)} 块碎片…")
        threading.Thread(target=self._stitch_worker, args=(paths,), daemon=True).start()

    def _stitch_worker(self, paths: list[Path]) -> None:
        try:
            result = stitch_folder(paths)
        except Exception as exc:  # noqa: BLE001
            error_text = str(exc)
            self._post(lambda: self._stitch_failed(error_text))
            return
        self._post(lambda: self._show_stitch(result))

    def _stitch_failed(self, message: str) -> None:
        self.status_var.set("拼接失败")
        messagebox.showerror("拼接失败", message)

    def _show_stitch(self, result: Any) -> None:
        self.previews["碎片拼接"] = result.image
        self._trim_previews()
        self._add_results(result.decoded, source="碎片拼接")
        self._show_frame(result.image, results=result.decoded)
        if result.decoded:
            self.status_var.set(f"拼接成功：{result.rows}×{result.cols}，识别到 {len(result.decoded)} 条结果")
        else:
            self.status_var.set(f"已按 {result.rows}×{result.cols} 拼接，但没能识别出二维码；请确认碎片完整、方向一致。")

    # ---------- 设置与导出 ----------

    def _active_options(self) -> list[str]:
        return [key for key in OPTION_KEYS if self.option_vars[key].get()]

    def _hard_mode(self) -> bool:
        return self.strategy_var.get() == "困难"

    def copy_all(self) -> None:
        if not self.results:
            messagebox.showinfo("复制结果", "当前没有识别结果。")
            return
        text = "\n".join("\t".join(part for part in (row["source"], row["format"], row["text"]) if part) for row in self.results)
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        self.status_var.set("已复制全部结果到剪贴板")

    def export_csv(self) -> None:
        if not self.results:
            messagebox.showinfo("导出结果", "当前没有识别结果。")
            return
        path = filedialog.asksaveasfilename(title="导出识别结果", defaultextension=".csv", filetypes=[("CSV 文件", "*.csv")], initialfile="扫码结果.csv")
        if not path:
            return
        with open(path, "w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=("time", "source", "format", "text"), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self.results)
        self.status_var.set(f"已导出：{os.path.basename(path)}")

    def clear_results(self) -> None:
        self.results.clear()
        self.previews.clear()
        self.failed.clear()
        for item in self.table.get_children():
            self.table.delete(item)
        self.retry_button.configure(text="重试失败 (0)", state="disabled")
        self.current_image = None
        self.current_decoded = []
        self.original_image = None
        self.processed_image = None
        self.preview.configure(image="", text="把图片拖到这里，或按 Ctrl+V 粘贴截图\n识别过程完全在本机完成")
        self.preview_image = None
        self.status_var.set(f"识别引擎：{backend_status()}  ·  已识别 0 条")

    def _on_close(self) -> None:
        self._closed = True
        self._stop_camera()
        self.destroy()


def run() -> None:
    app = ScannerApp()
    app.mainloop()
