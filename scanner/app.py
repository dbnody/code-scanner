"""离线扫码桌面界面。

支持拖拽 / 粘贴 / 截图扫码，批量与文件夹识别，预览标注与图像预处理。
"""

from __future__ import annotations

import csv
import json
import os
import queue
import threading
import time
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

try:  # 拖拽依赖，缺失时自动降级
    from tkinterdnd2 import DND_FILES, TkinterDnD

    _DND = True
    _Base = TkinterDnD.Tk
except Exception:  # noqa: BLE001
    DND_FILES = ""
    _DND = False
    _Base = tk.Tk

from . import theme
from .annotate import annotate
from .batch import is_image, read_image, relative_source, scan_folder
from .camera import CameraGate, offset_results, roi_crop
from .content import TEMPLATES, classify, extract_fields, render_copy, type_label
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


class ExportDialog(tk.Toplevel):
    """选择要导出的字段和格式。"""

    FIELDS = (("time", "时间"), ("source", "来源"), ("type", "类型"), ("format", "码制"), ("text", "内容"))

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self.title("导出识别结果")
        self.configure(bg=theme.CARD)
        theme.set_window_icon(self)
        self.transient(master)
        self.resizable(False, False)
        self.choice: tuple[list[str], str] | None = None
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="导出字段", style="Head.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.vars: dict[str, tk.BooleanVar] = {}
        for index, (key, label) in enumerate(self.FIELDS, start=1):
            variable = tk.BooleanVar(value=True)
            self.vars[key] = variable
            ttk.Checkbutton(frame, text=label, variable=variable).grid(row=index, column=0, sticky="w")
        ttk.Label(frame, text="导出格式", style="Head.TLabel").grid(row=0, column=1, sticky="w", padx=(28, 0), pady=(0, 6))
        self.format_var = tk.StringVar(value="CSV")
        ttk.Combobox(frame, textvariable=self.format_var, values=("CSV", "TSV", "JSON"), width=8, state="readonly").grid(row=1, column=1, sticky="w", padx=(28, 0))
        buttons = ttk.Frame(frame)
        buttons.grid(row=len(self.FIELDS) + 1, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="导出", style="Accent.TButton", command=self._ok).pack(side="right", padx=(0, 8))
        self.grab_set()
        self.wait_window()

    def _ok(self) -> None:
        fields = [key for key, _label in self.FIELDS if self.vars[key].get()]
        if not fields:
            messagebox.showinfo("导出", "至少选择一个字段。", parent=self)
            return
        self.choice = (fields, self.format_var.get())
        self.destroy()


class ScannerApp(_Base):
    def __init__(self) -> None:
        super().__init__()
        self.title("离线扫码 · 多码识别")
        self.geometry("1240x812")
        self.minsize(1000, 640)
        self.configure(bg=theme.BG)
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
        self.copy_template = tk.StringVar(value="仅内容")
        self.custom_template = "{text}"
        self.roi_var = tk.BooleanVar(value=True)
        self.cooldown_var = tk.IntVar(value=3)
        self.votes_var = tk.IntVar(value=2)
        self.sound_var = tk.BooleanVar(value=True)
        self.gate = CameraGate(cooldown=3, votes=2)
        self._feedback_job: str | None = None
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
        theme.apply(self)

    def _build_ui(self) -> None:
        theme.set_window_icon(self)
        page = tk.Frame(self, bg=theme.BG)
        page.pack(fill="both", expand=True)

        header = theme.card(page, padx=16, pady=11)
        header.pack(fill="x", padx=14, pady=(12, 8))
        picture = theme.logo(header, 46)
        if picture is not None:
            logo_label = tk.Label(header, image=picture, bg=theme.CARD)
            logo_label.image = picture
            logo_label.pack(side="left", padx=(0, 14))
        titles = tk.Frame(header, bg=theme.CARD)
        titles.pack(side="left")
        tk.Label(titles, text="离线扫码", bg=theme.CARD, fg=theme.TEXT, font=(theme.FONT, 20, "bold")).pack(anchor="w")
        tk.Label(
            titles,
            text="拖拽 / 粘贴 / 截图 · 批量与文件夹识别 · 图片只在本机处理",
            bg=theme.CARD,
            fg=theme.MUTED,
            font=(theme.FONT, 9),
        ).pack(anchor="w", pady=(3, 0))
        chips = tk.Frame(header, bg=theme.CARD)
        chips.pack(side="right")
        theme.chip(chips, "● 完全离线").pack(side="left", padx=(0, 6))
        theme.chip(chips, f"引擎 {backend_status()}").pack(side="left")

        toolbar = theme.card(page, padx=9, pady=7)
        toolbar.pack(fill="x", padx=14, pady=(0, 7))
        ttk.Button(toolbar, text="打开图片", style="Accent.TButton", command=self.open_image).pack(side="left", padx=(0, 6))
        for text, command in (
            ("批量识别图片", self.batch_decode),
            ("扫描文件夹", self.scan_folder_dialog),
            ("截图扫码", self.screenshot),
            ("粘贴图片", self.paste_clipboard),
        ):
            ttk.Button(toolbar, text=text, style="Soft.TButton", command=command).pack(side="left", padx=(0, 6))
        self.camera_button = ttk.Button(toolbar, text="启动摄像头", style="Soft.TButton", command=self.toggle_camera)
        self.camera_button.pack(side="left", padx=(0, 6))
        for text, command in (("拼接碎片", self.stitch_fragments), ("复制全部", self.copy_all), ("导出结果", self.export_csv)):
            ttk.Button(toolbar, text=text, style="Soft.TButton", command=command).pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="清空记录", style="Soft.TButton", command=self.clear_results).pack(side="right")

        options = theme.card(page, padx=11, pady=6)
        options.pack(fill="x", padx=14, pady=(0, 5))
        tk.Label(options, text="预处理", bg=theme.CARD, fg=theme.ACCENT_DARK, font=(theme.FONT, 9, "bold")).pack(side="left", padx=(0, 8))
        for key in OPTION_KEYS:
            ttk.Checkbutton(options, text=OPTION_LABELS[key], variable=self.option_vars[key], command=self._rerender).pack(side="left", padx=1)
        ttk.Separator(options, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Label(options, text="策略", style="Sub.TLabel").pack(side="left")
        ttk.Combobox(options, textvariable=self.strategy_var, values=("普通", "困难"), width=5, state="readonly").pack(side="left", padx=(4, 10))
        ttk.Checkbutton(options, text="前后对比", variable=self.compare_var, command=self._rerender).pack(side="left", padx=(0, 10))
        self.retry_button = ttk.Button(options, text="重试失败 (0)", style="Soft.TButton", command=self.retry_failed, state="disabled")
        self.retry_button.pack(side="left")
        ttk.Combobox(options, textvariable=self.sort_var, values=("文件名", "修改时间"), width=7, state="readonly").pack(side="right")
        ttk.Label(options, text="排序", style="Sub.TLabel").pack(side="right", padx=(0, 4))

        camera_row = theme.card(page, padx=11, pady=6)
        camera_row.pack(fill="x", padx=14, pady=(0, 8))
        tk.Label(camera_row, text="摄像头", bg=theme.CARD, fg=theme.ACCENT_DARK, font=(theme.FONT, 9, "bold")).pack(side="left", padx=(0, 8))
        ttk.Checkbutton(camera_row, text="仅扫中间区域", variable=self.roi_var).pack(side="left", padx=(0, 8))
        ttk.Label(camera_row, text="冷却", style="Sub.TLabel").pack(side="left")
        ttk.Spinbox(camera_row, from_=0, to=60, width=3, textvariable=self.cooldown_var).pack(side="left", padx=(4, 3))
        ttk.Label(camera_row, text="秒", style="Sub.TLabel").pack(side="left", padx=(0, 8))
        ttk.Label(camera_row, text="连续", style="Sub.TLabel").pack(side="left")
        ttk.Spinbox(camera_row, from_=1, to=10, width=3, textvariable=self.votes_var).pack(side="left", padx=(4, 3))
        ttk.Label(camera_row, text="帧确认", style="Sub.TLabel").pack(side="left", padx=(0, 8))
        ttk.Checkbutton(camera_row, text="提示音", variable=self.sound_var).pack(side="left")
        self.save_frame_button = ttk.Button(camera_row, text="保存当前帧", style="Soft.TButton", command=self.save_current_frame, state="disabled")
        self.save_frame_button.pack(side="left", padx=(8, 0))
        ttk.Separator(camera_row, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Label(camera_row, text="复制模板", style="Sub.TLabel").pack(side="left", padx=(0, 4))
        ttk.Combobox(camera_row, textvariable=self.copy_template, values=tuple(TEMPLATES) + ("自定义",), width=9, state="readonly").pack(side="left", padx=(0, 6))
        ttk.Button(camera_row, text="复制选中", style="Soft.TButton", command=self.copy_selected).pack(side="left", padx=(0, 6))
        ttk.Button(camera_row, text="自定义模板…", style="Soft.TButton", command=self.edit_template).pack(side="left")

        content = ttk.Panedwindow(page, orient="horizontal")
        content.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        left = theme.card(content, padx=8, pady=8)
        right = theme.card(content, padx=10, pady=8)
        content.add(left, weight=5)
        content.add(right, weight=3)

        self.preview = tk.Label(
            left,
            text="把图片拖到这里，或按 Ctrl+V 粘贴截图\n\n识别全程在本机完成，不上传任何图片",
            bg=theme.CARD_ALT,
            fg=theme.MUTED,
            font=(theme.FONT, 11),
            justify="center",
        )
        self.preview.pack(fill="both", expand=True)
        self.status_var = tk.StringVar(value="就绪 · 拖入图片、粘贴截图或点「打开图片」开始")
        tk.Label(left, textvariable=self.status_var, bg=theme.CARD, fg=theme.MUTED, anchor="w", font=(theme.FONT, 9)).pack(fill="x", pady=(9, 0))
        bar_row = tk.Frame(left, bg=theme.CARD)
        bar_row.pack(fill="x", pady=(6, 0))
        self.progress = ttk.Progressbar(bar_row, mode="determinate", maximum=1, value=0)
        self.progress.pack(side="left", fill="x", expand=True)
        self.cancel_button = ttk.Button(bar_row, text="取消", style="Soft.TButton", command=self.cancel_batch, state="disabled")
        self.cancel_button.pack(side="left", padx=(8, 0))

        tk.Label(right, text="识别结果", bg=theme.CARD, fg=theme.TEXT, font=(theme.FONT, 13, "bold")).pack(anchor="w", pady=(0, 8))
        table_frame = tk.Frame(right, bg=theme.CARD)
        table_frame.pack(fill="both", expand=True)
        columns = ("time", "source", "type", "format", "text")
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")
        self.table.tag_configure("odd", background=theme.CARD)
        self.table.tag_configure("even", background=theme.ROW_ALT)
        self.table.heading("time", text="时间")
        self.table.heading("source", text="来源")
        self.table.heading("type", text="类型")
        self.table.heading("format", text="码制")
        self.table.heading("text", text="内容")
        self.table.column("time", width=64, minwidth=60, anchor="center", stretch=False)
        self.table.column("source", width=82, minwidth=70, anchor="w")
        self.table.column("type", width=58, minwidth=52, anchor="center", stretch=False)
        self.table.column("format", width=58, minwidth=52, anchor="center", stretch=False)
        self.table.column("text", width=190, minwidth=120, anchor="w")
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.table.bind("<<TreeviewSelect>>", self._on_row_select)

        tk.Label(right, text="字段详情 · 双击值复制", bg=theme.CARD, fg=theme.MUTED, font=(theme.FONT, 9)).pack(anchor="w", pady=(10, 4))
        self.detail = ttk.Treeview(right, columns=("field", "value"), show="headings", height=4, style="Detail.Treeview")
        self.detail.heading("field", text="字段")
        self.detail.heading("value", text="值")
        self.detail.column("field", width=96, anchor="w")
        self.detail.column("value", width=300, anchor="w")
        self.detail.pack(fill="x")
        self.detail.bind("<Double-1>", self._copy_detail_field)

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
        self._fill_detail(row)
        image = self.previews.get(row["source"])
        if image is None:
            return
        same_source = [
            DecodeResult(other["text"], other["format"], other["position"])
            for other in self.results
            if other["source"] == row["source"] and other["position"]
        ]
        self._show_frame(image, results=same_source, highlight=row["position"])

    @staticmethod
    def _one_line(text: Any) -> str:
        """表格一行显示：把换行压成 ⏎，避免多行文字压到邻行。"""
        parts = [part.strip() for part in str(text).replace("\r", "\n").split("\n")]
        return " ⏎ ".join(part for part in parts if part)

    def _fill_detail(self, row: dict[str, Any]) -> None:
        for item in self.detail.get_children():
            self.detail.delete(item)
        self.detail.insert("", "end", values=("类型", row.get("type", "")))
        for name, value in [("内容", row.get("text", ""))] + list(row.get("fields") or []):
            self.detail.insert("", "end", values=(name, self._one_line(value)))

    def _add_results(self, decoded: list[DecodeResult], source: str = "", dedupe: bool = True) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        for item in decoded:
            if dedupe and any(row["text"] == item.text and row["format"] == item.format_name for row in self.results):
                continue
            row = {
                "time": now,
                "source": source,
                "type": type_label(classify(item.text)),
                "format": item.format_name,
                "text": item.text,
                "fields": extract_fields(item.text),
                "position": item.position,
            }
            self.results.append(row)
            tag = "even" if len(self.results) % 2 == 0 else "odd"
            self.table.insert(
                "",
                "end",
                values=(row["time"], row["source"], row["type"], row["format"], self._one_line(row["text"])),
                tags=(tag,),
            )
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
            self.gate = CameraGate(cooldown=self.cooldown_var.get(), votes=self.votes_var.get())
            self.camera_button.configure(text="停止摄像头")
            self.save_frame_button.configure(state="normal")
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
            if self.roi_var.get():
                region, (dx, dy) = roi_crop(frame)
            else:
                region, (dx, dy) = frame, (0, 0)
            self._decode_frame_async(region, dx, dy)
        self.after(120, self._camera_tick)

    def _decode_frame_async(self, frame: Any, dx: int = 0, dy: int = 0) -> None:
        snapshot = frame.copy()

        def worker() -> None:
            try:
                decoded = decode_image(snapshot)
            except Exception as exc:  # noqa: BLE001
                error_text = str(exc)
                self._post(lambda: self.status_var.set(f"识别失败：{error_text}"))
                return
            if decoded:
                self._post(lambda: self._on_camera_results(offset_results(decoded, dx, dy)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_camera_results(self, decoded: list[DecodeResult]) -> None:
        self.camera_results = decoded
        confirmed = self.gate.observe(decoded, time.monotonic())
        if confirmed:
            self._add_results(confirmed, source="摄像头", dedupe=False)
            self._feedback()
        if self.last_frame is not None:
            self._show_frame(self.last_frame, results=decoded)

    def _feedback(self) -> None:
        if self.sound_var.get():
            try:
                import winsound

                winsound.MessageBeep(winsound.MB_OK)
            except Exception:  # noqa: BLE001 - 没有声音设备不影响扫码
                pass
        self.preview.configure(bg="#d9f5e4")
        if self._feedback_job is not None:
            self.after_cancel(self._feedback_job)
        self._feedback_job = self.after(180, lambda: self.preview.configure(bg=theme.CARD_ALT))

    def save_current_frame(self) -> None:
        if self.last_frame is None:
            messagebox.showinfo("保存当前帧", "还没有摄像头画面，先启动摄像头。")
            return
        path = filedialog.asksaveasfilename(
            title="保存当前帧",
            defaultextension=".png",
            filetypes=[("PNG 图片", "*.png"), ("JPEG 图片", "*.jpg")],
            initialfile=f"frame-{datetime.now().strftime('%H%M%S')}.png",
        )
        if not path:
            return
        try:
            import cv2

            ok, buffer = cv2.imencode(Path(path).suffix or ".png", self.last_frame)
            if not ok:
                raise ValueError("编码失败")
            buffer.tofile(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("保存失败", str(exc))
            return
        self.status_var.set(f"已保存当前帧：{os.path.basename(path)}")

    def _stop_camera(self) -> None:
        self.camera_running = False
        self.camera_results = []
        self.gate.reset()
        self.camera_button.configure(text="启动摄像头")
        self.save_frame_button.configure(state="disabled")
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
        self._copy_text(self._render_copy(self.results), "已复制全部结果到剪贴板")

    def copy_selected(self) -> None:
        selection = self.table.selection()
        if not selection:
            messagebox.showinfo("复制结果", "请先选中一行或多行结果。")
            return
        rows = [self.results[self.table.index(item)] for item in selection if self.table.index(item) < len(self.results)]
        self._copy_text(self._render_copy(rows), f"已复制 {len(rows)} 行结果")

    def _copy_detail_field(self, _event: Any = None) -> None:
        selection = self.detail.selection()
        if not selection:
            return
        values = self.detail.item(selection[0], "values")
        self._copy_text(str(values[1]), f"已复制字段：{values[0]}")

    def edit_template(self) -> None:
        template = simpledialog.askstring(
            "自定义模板",
            "可用占位符：{text} {source} {type} {format} {time} {fields}，也可直接写字段名，如 {名称}",
            initialvalue=self.custom_template,
            parent=self,
        )
        if template is None:
            return
        self.custom_template = template
        self.copy_template.set("自定义")
        self.status_var.set("自定义模板已更新")

    def _render_copy(self, rows: list[dict[str, Any]]) -> str:
        return render_copy(rows, self.copy_template.get(), self.custom_template)

    def _copy_text(self, text: str, message: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        self.status_var.set(message)

    def export_csv(self) -> None:
        if not self.results:
            messagebox.showinfo("导出结果", "当前没有识别结果。")
            return
        dialog = ExportDialog(self)
        if dialog.choice is None:
            return
        fields, fmt = dialog.choice
        extension = ".json" if fmt == "JSON" else ".csv" if fmt == "CSV" else ".tsv"
        path = filedialog.asksaveasfilename(
            title="导出识别结果",
            defaultextension=extension,
            filetypes=[(f"{fmt} 文件", f"*{extension}")],
            initialfile=f"扫码结果{extension}",
        )
        if not path:
            return
        self._write_export(path, fields, fmt)
        self.status_var.set(f"已导出：{os.path.basename(path)}")

    def _write_export(self, path: str, fields: list[str], fmt: str) -> None:
        labels = {"time": "时间", "source": "来源", "type": "类型", "format": "码制", "text": "内容"}
        if fmt == "JSON":
            payload = [{key: row.get(key, "") for key in fields} for row in self.results]
            with open(path, "w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
            return
        delimiter = "\t" if fmt == "TSV" else ","
        with open(path, "w", encoding="utf-8-sig", newline="") as file:
            writer = csv.writer(file, delimiter=delimiter)
            writer.writerow([labels[key] for key in fields])
            for row in self.results:
                writer.writerow([row.get(key, "") for key in fields])

    def clear_results(self) -> None:
        self.results.clear()
        self.previews.clear()
        self.failed.clear()
        for item in self.table.get_children():
            self.table.delete(item)
        for item in self.detail.get_children():
            self.detail.delete(item)
        self.retry_button.configure(text="重试失败 (0)", state="disabled")
        self.current_image = None
        self.current_decoded = []
        self.original_image = None
        self.processed_image = None
        self.preview.configure(
            bg=theme.CARD_ALT,
            fg=theme.MUTED,
            image="",
            text="把图片拖到这里，或按 Ctrl+V 粘贴截图\n\n识别全程在本机完成，不上传任何图片",
        )
        self.preview_image = None
        self.status_var.set(f"识别引擎：{backend_status()}  ·  已识别 0 条")

    def _on_close(self) -> None:
        self._closed = True
        self._stop_camera()
        self.destroy()


def run() -> None:
    app = ScannerApp()
    app.mainloop()
