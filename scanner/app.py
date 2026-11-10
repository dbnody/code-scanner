"""离线扫码桌面界面。"""

from __future__ import annotations

import csv
import os
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .decoder import DecodeResult, backend_status, decode_image, decode_image_file
from .stitcher import list_fragments, stitch_fragments as stitch_folder


class ScannerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("离线扫码 · 多码识别")
        self.geometry("1120x720")
        self.minsize(900, 580)
        self.configure(bg="#fff8f2")
        self.camera = None
        self.camera_running = False
        self.preview_image = None
        self.last_frame = None
        self.results: list[dict[str, str]] = []
        self._build_style()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

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
        style.configure("Soft.TButton", padding=(12, 7), font=("Microsoft YaHei UI", 10))

    def _build_ui(self) -> None:
        header = ttk.Frame(self, style="Card.TFrame", padding=(22, 18, 22, 14))
        header.pack(fill="x", padx=18, pady=(18, 10))
        ttk.Label(header, text="✨ 离线扫码", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="完全离线 · 一次识别多种二维码和条形码 · 不上传图片", style="Sub.TLabel").pack(anchor="w", pady=(4, 0))

        toolbar = ttk.Frame(self, style="Card.TFrame", padding=12)
        toolbar.pack(fill="x", padx=18, pady=(0, 10))
        ttk.Button(toolbar, text="打开图片", style="Accent.TButton", command=self.open_image).pack(side="left", padx=(0, 8))
        ttk.Button(toolbar, text="批量识别图片", style="Soft.TButton", command=self.batch_decode).pack(side="left", padx=(0, 8))
        self.camera_button = ttk.Button(toolbar, text="启动摄像头", style="Soft.TButton", command=self.toggle_camera)
        self.camera_button.pack(side="left", padx=4)
        ttk.Button(toolbar, text="拼接碎片二维码", style="Soft.TButton", command=self.stitch_fragments).pack(side="left", padx=4)
        ttk.Button(toolbar, text="复制全部结果", style="Soft.TButton", command=self.copy_all).pack(side="left", padx=4)
        ttk.Button(toolbar, text="导出 CSV", style="Soft.TButton", command=self.export_csv).pack(side="left", padx=4)
        ttk.Button(toolbar, text="清空记录", style="Soft.TButton", command=self.clear_results).pack(side="right")

        content = ttk.Panedwindow(self, orient="horizontal")
        content.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        left = ttk.Frame(content, style="Card.TFrame", padding=12)
        right = ttk.Frame(content, style="Card.TFrame", padding=12)
        content.add(left, weight=3)
        content.add(right, weight=2)

        self.preview = tk.Label(left, text="打开图片或启动摄像头\n识别过程完全在本机完成", bg="#fff2ed", fg="#a98f88", font=("Microsoft YaHei UI", 14), justify="center")
        self.preview.pack(fill="both", expand=True)
        self.status_var = tk.StringVar(value=f"识别引擎：{backend_status()}")
        ttk.Label(left, textvariable=self.status_var, style="Sub.TLabel").pack(anchor="w", pady=(9, 0))

        ttk.Label(right, text="识别结果", font=("Microsoft YaHei UI", 14, "bold"), foreground="#402a2a").pack(anchor="w", pady=(0, 8))
        columns = ("time", "source", "format", "text")
        self.table = ttk.Treeview(right, columns=columns, show="headings", selectmode="extended")
        self.table.heading("time", text="时间")
        self.table.heading("source", text="来源")
        self.table.heading("format", text="类型")
        self.table.heading("text", text="内容")
        self.table.column("time", width=72, anchor="center")
        self.table.column("source", width=110, anchor="w")
        self.table.column("format", width=88, anchor="center")
        self.table.column("text", width=260, anchor="w")
        scroll = ttk.Scrollbar(right, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def open_image(self) -> None:
        path = filedialog.askopenfilename(title="选择要识别的图片", filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.webp"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            import cv2  # type: ignore

            image = cv2.imread(path)
            if image is None:
                raise ValueError("图片格式不受支持或文件已损坏")
            self._show_frame(image)
            self._decode_async(image)
        except ImportError:
            messagebox.showerror("缺少依赖", "请先运行 install_windows.bat 安装识别依赖。")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("打开失败", str(exc))

    def toggle_camera(self) -> None:
        if self.camera_running:
            self._stop_camera()
            return
        try:
            import cv2  # type: ignore

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
            self._show_frame(frame)
            self._decode_async(frame)
        self.after(120, self._camera_tick)

    def _decode_async(self, frame: object) -> None:
        # 摄像头线程中不要阻塞 Tk 主循环；识别结果回到 UI 线程更新。
        snapshot = frame.copy() if hasattr(frame, "copy") else frame

        def worker() -> None:
            try:
                decoded = decode_image(snapshot)
                if decoded:
                    self.after(0, lambda: self._add_results(decoded))
            except Exception as exc:  # noqa: BLE001
                error_text = str(exc)
                self.after(0, lambda error=error_text: self.status_var.set(f"识别失败：{error}"))

        threading.Thread(target=worker, daemon=True).start()

    def _show_frame(self, frame: object) -> None:
        try:
            import cv2  # type: ignore
            from PIL import Image, ImageTk  # type: ignore

            image = frame.copy()
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            pil = Image.fromarray(rgb)
            pil.thumbnail((760, 530), Image.Resampling.LANCZOS)
            self.preview_image = ImageTk.PhotoImage(pil)
            self.preview.configure(image=self.preview_image, text="")
        except ImportError:
            self.preview.configure(text="缺少 Pillow/OpenCV，请先安装依赖", image="")

    def _add_results(self, decoded: list[DecodeResult], source: str = "", dedupe: bool = True) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        for item in decoded:
            if dedupe and any(row["text"] == item.text and row["format"] == item.format_name for row in self.results):
                continue
            row = {"time": now, "source": source, "format": item.format_name, "text": item.text}
            self.results.append(row)
            self.table.insert("", "end", values=(row["time"], row["source"], row["format"], row["text"]))
        self.status_var.set(f"识别引擎：{backend_status()}  ·  已识别 {len(self.results)} 条")

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
            writer = csv.DictWriter(file, fieldnames=("time", "source", "format", "text"))
            writer.writeheader()
            writer.writerows(self.results)
        self.status_var.set(f"已导出：{os.path.basename(path)}")

    def clear_results(self) -> None:
        self.results.clear()
        for item in self.table.get_children():
            self.table.delete(item)
        self.status_var.set(f"识别引擎：{backend_status()}  ·  已识别 0 条")

    def batch_decode(self) -> None:
        paths = filedialog.askopenfilenames(
            title="选择要识别的图片（可多选，按选择顺序展示结果）",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.webp"), ("所有文件", "*.*")],
        )
        if not paths:
            return
        self.status_var.set(f"正在识别 {len(paths)} 张图片…")
        threading.Thread(target=self._batch_worker, args=(list(paths),), daemon=True).start()

    def _batch_worker(self, paths: list[str]) -> None:
        items: list[tuple[str, object, list[DecodeResult]]] = []
        failed = 0
        for path in paths:
            try:
                image, decoded = decode_image_file(path)
            except Exception:  # noqa: BLE001 - 单张图片损坏不影响其余图片
                failed += 1
                continue
            items.append((os.path.basename(path), image, decoded))
        self.after(0, lambda: self._show_batch(items, failed))

    def _show_batch(self, items: list[tuple[str, object, list[DecodeResult]]], failed: int) -> None:
        total = sum(len(decoded) for _, _, decoded in items)
        for source, _, decoded in items:
            self._add_results(decoded, source=source, dedupe=False)
        if items:
            self._show_frame(items[-1][1])
        message = f"批量识别完成：{len(items)} 张图片，共 {total} 条结果"
        if failed:
            message += f"，{failed} 张读取失败"
        self.status_var.set(message)

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
            self.after(0, lambda: self._stitch_failed(error_text))
            return
        self.after(0, lambda: self._show_stitch(result))

    def _stitch_failed(self, message: str) -> None:
        self.status_var.set("拼接失败")
        messagebox.showerror("拼接失败", message)

    def _show_stitch(self, result: object) -> None:
        self._show_frame(result.image)
        if result.decoded:
            self._add_results(result.decoded, source="碎片拼接")
            self.status_var.set(f"拼接成功：{result.rows}×{result.cols}，识别到 {len(result.decoded)} 条结果")
        else:
            self.status_var.set(
                f"已按 {result.rows}×{result.cols} 拼接，但没能识别出二维码；请确认碎片完整、方向一致。"
            )

    def _stop_camera(self) -> None:
        self.camera_running = False
        self.camera_button.configure(text="启动摄像头")
        if self.camera is not None:
            self.camera.release()
            self.camera = None

    def _on_close(self) -> None:
        self._stop_camera()
        self.destroy()


def run() -> None:
    app = ScannerApp()
    app.mainloop()
