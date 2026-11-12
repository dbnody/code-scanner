"""界面主题：配色、字体、ttk 样式与图标。"""

from __future__ import annotations

import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk

BG = "#faf3ee"
CARD = "#ffffff"
CARD_ALT = "#fff8f4"
BORDER = "#f0ded4"
TEXT = "#33241f"
MUTED = "#9b8076"
ACCENT = "#f0604f"
ACCENT_DARK = "#cf4436"
ACCENT_SOFT = "#ffe8e3"
OK = "#2f9e68"
ROW_ALT = "#fffaf7"
FONT = "Microsoft YaHei UI"


def asset(name: str) -> Path:
    """图标等资源路径，兼容源码运行与 PyInstaller 单文件模式。"""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "assets" / name


def card(master: tk.Misc, padx: int = 12, pady: int = 10) -> tk.Frame:
    """白底细边框卡片。"""
    return tk.Frame(master, bg=CARD, highlightthickness=1, highlightbackground=BORDER, bd=0, padx=padx, pady=pady)


def chip(master: tk.Misc, text: str) -> tk.Label:
    return tk.Label(master, text=text, bg=ACCENT_SOFT, fg=ACCENT_DARK, font=(FONT, 9), padx=10, pady=4)


def logo(master: tk.Misc, size: int = 52) -> tk.PhotoImage | None:
    path = asset("icon.png")
    if not path.exists():
        return None
    try:
        photo = tk.PhotoImage(file=str(path))
    except tk.TclError:
        return None
    factor = max(1, round(photo.width() / size))
    return photo.subsample(factor, factor) if factor > 1 else photo


def apply(root: tk.Misc) -> None:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    root.configure(bg=BG)
    style.configure(".", background=CARD, foreground=TEXT, font=(FONT, 10), focuscolor=ACCENT, borderwidth=0)
    style.configure("TFrame", background=CARD)
    style.configure("Card.TFrame", background=CARD)
    style.configure("TLabel", background=CARD, foreground=TEXT)
    style.configure("Title.TLabel", background=CARD, foreground=TEXT, font=(FONT, 21, "bold"))
    style.configure("Sub.TLabel", background=CARD, foreground=MUTED, font=(FONT, 9))
    style.configure("Section.TLabel", background=CARD, foreground=ACCENT_DARK, font=(FONT, 9, "bold"))
    style.configure("Head.TLabel", background=CARD, foreground=TEXT, font=(FONT, 13, "bold"))

    style.configure("TButton", background=CARD_ALT, foreground=TEXT, bordercolor=BORDER, lightcolor=CARD_ALT,
                    darkcolor=CARD_ALT, padding=(11, 6), font=(FONT, 9))
    style.map("TButton", background=[("active", ACCENT_SOFT)], bordercolor=[("active", ACCENT)])
    style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff", bordercolor=ACCENT,
                    lightcolor=ACCENT, darkcolor=ACCENT, padding=(15, 7), font=(FONT, 9, "bold"))
    style.map("Accent.TButton", background=[("active", ACCENT_DARK), ("disabled", "#f0b5ad")],
              foreground=[("disabled", "#fff5f3")], bordercolor=[("active", ACCENT_DARK)])
    style.configure("Soft.TButton", background=CARD, foreground=TEXT, bordercolor=BORDER, lightcolor=CARD,
                    darkcolor=CARD, padding=(10, 5), font=(FONT, 9))
    style.map("Soft.TButton", background=[("active", CARD_ALT)], bordercolor=[("active", ACCENT)])

    style.configure("TCheckbutton", background=CARD, foreground=TEXT, focuscolor=CARD, font=(FONT, 9),
                    indicatorcolor=CARD, indicatorrelief="flat")
    style.map("TCheckbutton", background=[("active", CARD)], foreground=[("active", ACCENT_DARK)])
    style.configure("TCombobox", fieldbackground=CARD_ALT, background=CARD_ALT, foreground=TEXT,
                    bordercolor=BORDER, arrowcolor=ACCENT_DARK, padding=(6, 4), font=(FONT, 9))
    style.map("TCombobox", fieldbackground=[("readonly", CARD_ALT)], bordercolor=[("active", ACCENT)])
    style.configure("TSpinbox", fieldbackground=CARD_ALT, background=CARD_ALT, bordercolor=BORDER,
                    arrowcolor=ACCENT_DARK, padding=(4, 3), font=(FONT, 9))

    style.configure("TProgressbar", background=ACCENT, troughcolor=CARD_ALT, bordercolor=CARD_ALT,
                    lightcolor=ACCENT, darkcolor=ACCENT, thickness=8)
    style.configure("TSeparator", background=BORDER)

    style.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT, bordercolor=BORDER,
                    rowheight=30, font=(FONT, 9))
    style.configure("Treeview.Heading", background=CARD_ALT, foreground=MUTED, font=(FONT, 9, "bold"),
                    relief="flat", bordercolor=BORDER, padding=(6, 7))
    style.map("Treeview.Heading", background=[("active", ACCENT_SOFT)])
    style.map("Treeview", background=[("selected", ACCENT_SOFT)], foreground=[("selected", TEXT)])
    style.configure("Detail.Treeview", rowheight=26, font=(FONT, 9))


def set_window_icon(root: tk.Misc) -> None:
    ico = asset("icon.ico")
    try:
        if ico.exists():
            root.iconbitmap(default=str(ico))
    except tk.TclError:
        pass
    photo = logo(root, 64)
    if photo is not None:
        root._icon_photo = photo  # 保持引用，避免被回收
        try:
            root.iconphoto(True, photo)
        except tk.TclError:
            pass
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("dbnody.code-scanner")
        except Exception:  # noqa: BLE001 - 老系统没有该 API，不影响使用
            pass
