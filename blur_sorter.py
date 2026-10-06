# BlurSorter — 失焦照片分類器
# Copyright (C) 2026 Dorigo <https://dorigo-image.com>
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later version.
# This program is distributed WITHOUT ANY WARRANTY. See the LICENSE file for details.

"""
失焦照片分類器 BlurSorter
- 針對淺景深人像（個人 / 團體）：以臉部、眼部清晰度判斷
- 先分析、可調門檻、可手動修正，再一次搬移或複製
"""

from __future__ import annotations

import csv
import io
import json
import os
import queue
import shutil
import stat
import errno
import time
import sys
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageOps, ImageTk, ImageDraw

import focus_analyzer as fa
from i18n import T, set_lang, get_lang, all_values, detect_default_lang, LANG_NAMES

APP_VER = "2.5"
SPONSOR_URL = "https://www.paypal.com/ncp/payment/ATJ3PTJAC8RC6"
AUTHOR_URL = "https://dorigo-image.com"
SETTINGS_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "BlurSorter")
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")

DEFAULTS = {
    "src": "", "recursive": False,
    "mode": "relative", "face_rel": 40, "tile_rel": 40, "face_abs": 25.0, "tile_abs": 5.0,
    "sidecar": True, "geometry": "1280x800", "zoom": "fit", "lang": "",
}

FILTER_KEYS = ["f_all", "f_blur", "f_sharp", "f_done", "f_err"]

ZOOM_FIT = "fit"          # 設定檔內部用的值；畫面上顯示 T("zoom_fit")
ZOOM_PCTS = ["25%", "50%", "75%", "100%", "150%", "200%", "300%"]
ZOOM_STEPS = [5, 10, 15, 25, 33, 50, 67, 75, 100, 150, 200, 300, 400, 600, 800]
ZOOM_MIN, ZOOM_MAX = 5, 800

LEGACY_DIRS = ("失焦照片",)   # 舊版建立的資料夾，掃描時一併略過


def app_name() -> str:
    return T("app_name")


def output_dir_names() -> set:
    """所有語言的「清楚 / 模糊」資料夾名稱（掃描時都要略過）"""
    return all_values("sharp_dir") | all_values("blur_dir") | set(LEGACY_DIRS)


def error_text(err: str) -> str:
    return T("err_decode") if err == "decode_failed" else err


def load_settings() -> dict:
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            s.update(json.load(f))
    except Exception:
        pass
    if s.get("zoom") in all_values("zoom_fit"):   # 舊版存的是「符合視窗」
        s["zoom"] = ZOOM_FIT
    if s.get("lang") not in LANG_NAMES:
        s["lang"] = detect_default_lang()
    return s


def save_settings(s: dict):
    try:
        os.makedirs(SETTINGS_DIR, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def unique_path(path: str) -> str:
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 1
    while os.path.exists(f"{base}_{i}{ext}"):
        i += 1
    return f"{base}_{i}{ext}"


def _clear_readonly(path: str):
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


def _remove_file(path: str):
    try:
        os.remove(path)
    except PermissionError:
        _clear_readonly(path)   # 唯讀檔在 Windows 刪除會出現「存取被拒」
        os.remove(path)


def _retry(fn, tries: int = 10, delay: float = 0.5):
    """檔案被防毒、縮圖索引、雲端同步短暫鎖住時，稍等再試"""
    for i in range(tries):
        try:
            return fn()
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(delay)


def safe_move(src: str, dst: str):
    """
    移動檔案：
    - 同一顆磁碟：直接改名（瞬間完成、不會產生複本）
    - 不同磁碟：先複製再刪除原檔；若原檔刪不掉，會把剛複製的檔案刪掉，
      保證不會出現「兩邊都有」的情況
    """
    try:
        _retry(lambda: os.rename(src, dst))
        return
    except PermissionError:
        _clear_readonly(src)
        try:
            _retry(lambda: os.rename(src, dst))
            return
        except OSError as e:
            if getattr(e, "winerror", None) != 17 and getattr(e, "errno", None) != errno.EXDEV:
                raise
    except OSError as e:
        # 17 = ERROR_NOT_SAME_DEVICE；EXDEV = 跨磁碟
        if getattr(e, "winerror", None) != 17 and getattr(e, "errno", None) != errno.EXDEV:
            raise
    shutil.copy2(src, dst)
    try:
        _retry(lambda: _remove_file(src))
    except Exception:
        try:
            os.remove(dst)
        except OSError:
            pass
        raise


def who_locks(path: str) -> list:
    """
    用 Windows Restart Manager 查出目前是哪些程式開著這個檔案。
    回傳 [(pid, 程式名稱)]；非 Windows 或查詢失敗時回傳空清單。
    """
    if sys.platform != "win32":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        class RM_UNIQUE_PROCESS(ctypes.Structure):
            _fields_ = [("dwProcessId", wintypes.DWORD),
                        ("ProcessStartTime", wintypes.FILETIME)]

        class RM_PROCESS_INFO(ctypes.Structure):
            _fields_ = [("Process", RM_UNIQUE_PROCESS),
                        ("strAppName", wintypes.WCHAR * 256),
                        ("strServiceShortName", wintypes.WCHAR * 64),
                        ("ApplicationType", ctypes.c_int),
                        ("AppStatus", wintypes.ULONG),
                        ("TSSessionId", wintypes.DWORD),
                        ("bRestartable", wintypes.BOOL)]

        rm = ctypes.WinDLL("rstrtmgr")
        session = wintypes.DWORD(0)
        key = ctypes.create_unicode_buffer(33)
        if rm.RmStartSession(ctypes.byref(session), 0, key) != 0:
            return []
        try:
            files = (wintypes.LPCWSTR * 1)(os.path.abspath(path))
            if rm.RmRegisterResources(session, 1, files, 0, None, 0, None) != 0:
                return []
            needed, count, reasons = wintypes.UINT(0), wintypes.UINT(0), wintypes.DWORD(0)
            rc = rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), None, ctypes.byref(reasons))
            if rc not in (0, 234) or needed.value == 0:      # 234 = ERROR_MORE_DATA
                return []
            arr = (RM_PROCESS_INFO * needed.value)()
            count = wintypes.UINT(needed.value)
            if rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), arr, ctypes.byref(reasons)) != 0:
                return []
            return [(int(arr[i].Process.dwProcessId), arr[i].strAppName or T("err_unknown_app"))
                    for i in range(count.value)]
        finally:
            rm.RmEndSession(session)
    except Exception:
        return []


def copy_file(src: str, dst: str):
    """複製檔案內容；修改時間等屬性盡力保留，就算被系統擋下也不影響複製結果"""
    shutil.copyfile(src, dst)
    try:
        shutil.copystat(src, dst)
    except OSError:
        pass


def explain_error(e: Exception, path: str = "") -> str:
    code = getattr(e, "winerror", None)
    tag = f"[WinError {code}] " if code else ""
    if isinstance(e, PermissionError):
        holders = who_locks(path) if path else []
        if holders:
            names = [T("err_this_app", name=name) if pid == os.getpid() else T("err_pid", name=name, pid=pid)
                     for pid, name in holders]
            return tag + T("err_locked_by", names=T("err_list_sep").join(names))
        if code == 5:
            return tag + T("err_denied")
        return tag + T("err_in_use")
    if isinstance(e, FileNotFoundError):
        return tag + T("err_not_found")
    return f"{tag}{e}"


def log_error(context: str, path: str, e: Exception):
    """把完整錯誤寫進 %LOCALAPPDATA%\\BlurSorter\\error.log，方便回報"""
    try:
        import traceback, datetime
        os.makedirs(SETTINGS_DIR, exist_ok=True)
        with open(os.path.join(SETTINGS_DIR, "error.log"), "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] v{APP_VER} {context}: {path}\n")
            f.write(f"holders={who_locks(path)}\n")
            f.write("".join(traceback.format_exception(type(e), e, e.__traceback__)))
    except Exception:
        pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.cfg = load_settings()
        set_lang(self.cfg["lang"])
        self.title(f"{app_name()} v{APP_VER}")
        self.geometry(self.cfg.get("geometry", "1280x800"))
        self.minsize(1000, 640)
        self._setup_style()
        self._set_window_icon()

        self.results: dict[str, fa.AnalysisResult] = {}   # path -> result
        self.order: list[str] = []
        self.override: dict[str, bool] = {}                # path -> 手動判定（True=失焦）
        self.done_paths: dict[str, str] = {}               # 已複製：path -> "清楚" / "模糊"
        self.last_log: list[tuple] = []                    # [(op, src, dst)]
        self.q: queue.Queue = queue.Queue()
        self.stop_flag = threading.Event()
        self.worker: threading.Thread | None = None
        self.total = 0
        self.face_th = 0.0
        self.tile_th = 0.0
        self._preview_img = None
        self._preview_path = None
        self._pv_res = None
        self._pv_cache = None
        self._pv_s = None
        self._pv_focus = None
        self._filter_key = "f_all"
        self._building = False

        self._build_ui()
        self._recalc()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll)

        if not os.path.exists(fa.MODEL_PATH):
            messagebox.showwarning(app_name(), T("no_model", path=fa.MODEL_PATH))

    # ------------------------------------------------------------ 介面
    def _set_window_icon(self):
        """視窗左上角與工作列的圖示（與 exe 圖示相同）"""
        ico = fa.resource_path("icon.ico")
        png = fa.resource_path("icon.png")
        try:
            if sys.platform == "win32" and os.path.exists(ico):
                self.iconbitmap(default=ico)
                return
            src = png if os.path.exists(png) else (ico if os.path.exists(ico) else None)
            if src:
                with Image.open(src) as im:
                    im = im.convert("RGBA").resize((64, 64), Image.LANCZOS)
                self._icon_img = ImageTk.PhotoImage(im)
                self.iconphoto(True, self._icon_img)
        except Exception:
            pass

    def _setup_style(self):
        st = ttk.Style(self)
        if "vista" in st.theme_names():
            st.theme_use("vista")
        import tkinter.font as tkfont
        fams = set(tkfont.families(self))
        fam = next((f for f in ("Microsoft JhengHei UI", "Microsoft JhengHei", "PingFang TC",
                                "Noto Sans CJK TC", "Noto Sans TC") if f in fams), None)
        if fam:
            for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
                try:
                    tkfont.nametofont(name).configure(family=fam, size=10)
                except tk.TclError:
                    pass
        st.configure("Treeview", rowheight=24)
        st.configure("Big.TButton", padding=(14, 6))

    def _build_ui(self):
        self._building = True
        pad = dict(padx=6, pady=4)

        # --- 標題列（右上角：語言、贊助、作者網站）
        header = ttk.Frame(self)
        header.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Label(header, text=f"{app_name()}  v{APP_VER}", font=("Microsoft JhengHei UI", 12, "bold")).pack(side="left")
        # side="right" 先放的會在最右邊：作者網站 → 贊助 → 標語 → 語言
        self.btn_author = self._link_button(header, T("author_site"), AUTHOR_URL, "#455a64", "#263238")
        self.btn_author.pack(side="right")
        self.btn_sponsor = self._link_button(header, T("sponsor"), SPONSOR_URL, "#e91e63", "#c2185b")
        self.btn_sponsor.pack(side="right", padx=(0, 6))
        ttk.Label(header, text=T("tagline"), foreground="#888").pack(side="right", padx=8)
        self.v_lang = tk.StringVar(value=LANG_NAMES[get_lang()])
        cb_lang = ttk.Combobox(header, textvariable=self.v_lang, values=list(LANG_NAMES.values()),
                               width=8, state="readonly")
        cb_lang.pack(side="right", padx=(4, 12))
        cb_lang.bind("<<ComboboxSelected>>", lambda e: self._lang_selected())
        ttk.Label(header, text=T("language")).pack(side="right")

        # --- 資料夾
        top = ttk.LabelFrame(self, text=T("folder_frame"))
        top.pack(fill="x", padx=8, pady=(6, 4))
        top.columnconfigure(1, weight=1)

        self.v_src = tk.StringVar(value=self.cfg["src"])
        self.v_rec = tk.BooleanVar(value=self.cfg["recursive"])

        ttk.Label(top, text=T("photo_folder")).grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(top, textvariable=self.v_src).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(top, text=T("browse"), command=self._pick_src).grid(row=0, column=2, **pad)
        ttk.Checkbutton(top, text=T("include_sub"), variable=self.v_rec).grid(row=0, column=3, **pad)

        ttk.Label(top, text=T("result_label")).grid(row=1, column=0, sticky="w", **pad)
        ttk.Label(top, text=T("result_desc", sharp=T("sharp_dir"), blur=T("blur_dir")),
                  foreground="#555").grid(row=1, column=1, columnspan=3, sticky="w", **pad)

        # --- 門檻
        th = ttk.LabelFrame(self, text=T("th_frame"))
        th.pack(fill="x", padx=8, pady=4)

        self.v_mode = tk.StringVar(value=self.cfg["mode"])
        mf = ttk.Frame(th)
        mf.grid(row=0, column=0, rowspan=2, sticky="nw", padx=6, pady=4)
        ttk.Radiobutton(mf, text=T("th_relative"), value="relative", variable=self.v_mode,
                        command=self._mode_changed).pack(anchor="w")
        ttk.Label(mf, text=T("th_relative_desc"), foreground="#777").pack(anchor="w", padx=(20, 0))
        ttk.Radiobutton(mf, text=T("th_absolute"), value="absolute", variable=self.v_mode,
                        command=self._mode_changed).pack(anchor="w", pady=(6, 0))

        self.v_face = tk.DoubleVar()
        self.v_tile = tk.DoubleVar()
        self.lbl_face = ttk.Label(th, width=40)
        self.lbl_tile = ttk.Label(th, width=40)

        ttk.Label(th, text=T("th_face")).grid(row=0, column=1, sticky="w", padx=6)
        self.sc_face = ttk.Scale(th, variable=self.v_face, command=lambda e: self._slider_moved())
        self.sc_face.grid(row=0, column=2, sticky="ew", padx=6)
        self.sp_face = ttk.Spinbox(th, textvariable=self.v_face, width=7, command=self._recalc)
        self.sp_face.grid(row=0, column=3, padx=4)
        self.lbl_face.grid(row=0, column=4, sticky="w", padx=6)

        ttk.Label(th, text=T("th_tile")).grid(row=1, column=1, sticky="w", padx=6)
        self.sc_tile = ttk.Scale(th, variable=self.v_tile, command=lambda e: self._slider_moved())
        self.sc_tile.grid(row=1, column=2, sticky="ew", padx=6)
        self.sp_tile = ttk.Spinbox(th, textvariable=self.v_tile, width=7, command=self._recalc)
        self.sp_tile.grid(row=1, column=3, padx=4)
        self.lbl_tile.grid(row=1, column=4, sticky="w", padx=6)
        th.columnconfigure(2, weight=1)
        for sp in (self.sp_face, self.sp_tile):
            sp.bind("<Return>", lambda e: self._recalc())
            sp.bind("<FocusOut>", lambda e: self._recalc())
        self._mode_changed(init=True)

        # --- 操作列
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=4)
        self.btn_start = ttk.Button(bar, text=T("start"), style="Big.TButton", command=self._start)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(bar, text=T("stop"), command=self._stop, state="disabled")
        self.btn_stop.pack(side="left", padx=4)

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=10)
        self.v_side = tk.BooleanVar(value=self.cfg["sidecar"])
        ttk.Checkbutton(bar, text=T("sidecar"), variable=self.v_side).pack(side="left")
        self.btn_move = ttk.Button(bar, text=T("copy_btn", sharp=T("sharp_dir"), blur=T("blur_dir")),
                                   style="Big.TButton", command=self._do_copy)
        self.btn_move.pack(side="left", padx=6)
        self.btn_undo = ttk.Button(bar, text=T("undo_btn"), command=self._undo, state="disabled")
        self.btn_undo.pack(side="left", padx=4)

        ttk.Button(bar, text=T("export_csv"), command=self._export_csv).pack(side="right")
        ttk.Button(bar, text=T("open_folder"), command=self._open_dst).pack(side="right", padx=4)

        # --- 主區：清單 + 預覽
        pw = ttk.PanedWindow(self, orient="horizontal")
        pw.pack(fill="both", expand=True, padx=8, pady=4)

        left = ttk.Frame(pw)
        fl = ttk.Frame(left)
        fl.pack(fill="x", pady=(0, 4))
        ttk.Label(fl, text=T("show")).pack(side="left")
        self.v_filter = tk.StringVar(value=T(self._filter_key))
        cb = ttk.Combobox(fl, textvariable=self.v_filter, values=[T(k) for k in FILTER_KEYS],
                          width=10, state="readonly")
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self._filter_selected())
        ttk.Label(fl, text=T("toggle_hint"), foreground="#777").pack(side="left", padx=10)

        cols = ("name", "score", "method", "faces", "verdict")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="extended")
        heads = {"name": ("col_name", 300, "w"), "score": ("col_score", 80, "e"),
                 "method": ("col_method", 95, "center"), "faces": ("col_faces", 50, "center"),
                 "verdict": ("col_verdict", 135, "center")}
        for c, (k, w, a) in heads.items():
            self.tree.heading(c, text=T(k), command=lambda c=c: self._sort_by(c))
            self.tree.column(c, width=w, anchor=a, stretch=(c == "name"))
        self.tree.tag_configure("blur", foreground="#c62828")
        self.tree.tag_configure("manual", background="#fff8e1")
        self.tree.tag_configure("done", foreground="#9e9e9e")
        self.tree.tag_configure("err", foreground="#9e9e9e", background="#f5f5f5")
        vs = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="left", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._show_preview())
        self.tree.bind("<Double-1>", lambda e: self._toggle_selected())
        self.tree.bind("<space>", lambda e: self._toggle_selected())
        pw.add(left, weight=3)

        right = ttk.Frame(pw)
        zb = ttk.Frame(right)
        zb.pack(fill="x", pady=(0, 4))
        ttk.Label(zb, text=T("zoom")).pack(side="left")
        ttk.Button(zb, text="－", width=3, command=lambda: self._zoom_step(-1)).pack(side="left", padx=(6, 0))
        self.v_zoom = tk.StringVar(value=self._zoom_label(self.cfg.get("zoom", ZOOM_FIT)))
        self.cb_zoom = ttk.Combobox(zb, textvariable=self.v_zoom, values=[T("zoom_fit")] + ZOOM_PCTS, width=9)
        self.cb_zoom.pack(side="left", padx=2)
        self.cb_zoom.bind("<<ComboboxSelected>>", lambda e: self._zoom_changed())
        self.cb_zoom.bind("<Return>", lambda e: self._zoom_changed())
        self.cb_zoom.bind("<FocusOut>", lambda e: self._zoom_changed())
        ttk.Button(zb, text="＋", width=3, command=lambda: self._zoom_step(1)).pack(side="left")
        ttk.Button(zb, text=T("zoom_fit"), command=lambda: self._set_zoom(ZOOM_FIT)).pack(side="left", padx=(6, 0))
        ttk.Button(zb, text="100%", command=lambda: self._set_zoom("100%")).pack(side="left", padx=2)
        self.lbl_zoom = ttk.Label(zb, foreground="#777")
        self.lbl_zoom.pack(side="left", padx=8)

        cf = ttk.Frame(right)
        cf.pack(fill="both", expand=True)
        cf.rowconfigure(0, weight=1); cf.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(cf, background="#222", highlightthickness=0,
                                xscrollincrement=40, yscrollincrement=40)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.pv_vs = ttk.Scrollbar(cf, orient="vertical", command=lambda *a: self._pv_scroll("y", *a))
        self.pv_hs = ttk.Scrollbar(cf, orient="horizontal", command=lambda *a: self._pv_scroll("x", *a))
        self.pv_vs.grid(row=0, column=1, sticky="ns")
        self.pv_hs.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(xscrollcommand=self.pv_hs.set, yscrollcommand=self.pv_vs.set)
        self.canvas.bind("<Configure>", lambda e: self._pv_relayout())
        self.canvas.bind("<ButtonPress-1>", self._pv_press)
        self.canvas.bind("<B1-Motion>", self._pv_drag)
        self.canvas.bind("<Double-Button-1>", self._pv_double)
        self.canvas.bind("<MouseWheel>", self._pv_wheel)                     # Windows
        self.canvas.bind("<Button-4>", lambda e: self._pv_wheel(e, 120))    # Linux
        self.canvas.bind("<Button-5>", lambda e: self._pv_wheel(e, -120))
        self.lbl_info = ttk.Label(right, text=T("preview_hint"), wraplength=460, justify="left")
        self.lbl_info.pack(fill="x", pady=4)
        pw.add(right, weight=2)

        # --- 狀態列
        sb = ttk.Frame(self)
        sb.pack(fill="x", padx=8, pady=(0, 8))
        self.pb = ttk.Progressbar(sb, mode="determinate", length=260)
        self.pb.pack(side="left")
        self.lbl_status = ttk.Label(sb, text=T("status_ready"))
        self.lbl_status.pack(side="left", padx=10)
        self._building = False

    # ------------------------------------------------------------ 語言
    def _lang_selected(self):
        name = self.v_lang.get()
        lang = next((k for k, v in LANG_NAMES.items() if v == name), "en")
        if lang != get_lang():
            self._switch_lang(lang)

    def _switch_lang(self, lang: str):
        """立即切換語言：記下目前狀態 → 重建整個介面 → 還原狀態（分析結果不會遺失）"""
        self._sync_cfg()
        sel = list(self.tree.selection())
        pv_path = self._preview_path
        pb_max, pb_val = self.pb.cget("maximum"), self.pb.cget("value")
        self.cfg["lang"] = lang
        set_lang(lang)
        self.title(f"{app_name()} v{APP_VER}")
        self._release_preview()
        for w in self.winfo_children():
            w.destroy()
        self._build_ui()
        # 還原狀態
        self.pb.configure(maximum=pb_max, value=pb_val)
        running = self.worker is not None and self.worker.is_alive()
        if running:
            self.btn_start.configure(state="disabled"); self.btn_stop.configure(state="normal")
            self.btn_move.configure(state="disabled")
        self.btn_undo.configure(state="normal" if self.last_log else "disabled")
        self._recalc()
        keep = [p for p in sel if self.tree.exists(p)]
        if keep:
            self.tree.selection_set(keep)
            self.tree.see(keep[0])
            if pv_path in keep:
                self.after(50, lambda: self._show_preview(force=True))
        elif not self.order:
            self.lbl_status.configure(text=T("status_ready"))

    def _sync_cfg(self):
        self.cfg.update(src=self.v_src.get(), recursive=self.v_rec.get(),
                        mode=self.v_mode.get(), sidecar=self.v_side.get())

    def _filter_selected(self):
        label = self.v_filter.get()
        self._filter_key = next((k for k in FILTER_KEYS if T(k) == label), "f_all")
        self._refresh_tree()

    # ------------------------------------------------------------ 資料夾
    def _pick_src(self):
        d = filedialog.askdirectory(title=T("pick_folder_title"), initialdir=self.v_src.get() or None)
        if d:
            self.v_src.set(os.path.normpath(d))

    def _link_button(self, parent, text, url, bg, bg_hover):
        b = tk.Button(parent, text=text, command=lambda: self._open_url(url),
                      bg=bg, fg="white", activebackground=bg_hover, activeforeground="white",
                      relief="flat", bd=0, padx=14, pady=4, cursor="hand2",
                      font=("Microsoft JhengHei UI", 10, "bold"))
        b.bind("<Enter>", lambda e: b.configure(bg=bg_hover))
        b.bind("<Leave>", lambda e: b.configure(bg=bg))
        return b

    def _open_url(self, url):
        try:
            webbrowser.open(url, new=2)
        except Exception:
            # 開不了瀏覽器時，把網址複製到剪貼簿
            self.clipboard_clear(); self.clipboard_append(url)
            messagebox.showinfo(app_name(), T("browser_fail", url=url))

    def _out_dirs(self) -> list:
        src = self.v_src.get().strip()
        return [os.path.join(src, d) for d in output_dir_names()] if src else []

    def _open_dst(self):
        d = self.v_src.get().strip()
        if d and os.path.isdir(d) and hasattr(os, "startfile"):
            os.startfile(d)

    # ------------------------------------------------------------ 門檻
    def _mode_changed(self, init=False):
        rel = self.v_mode.get() == "relative"
        if not init:
            self._store_threshold_values()
        if rel:
            self.sc_face.configure(from_=5, to=95)
            self.sc_tile.configure(from_=5, to=95)
            for sp in (self.sp_face, self.sp_tile):
                sp.configure(from_=5, to=95, increment=1)
            self.v_face.set(self.cfg["face_rel"])
            self.v_tile.set(self.cfg["tile_rel"])
        else:
            self.sc_face.configure(from_=1, to=150)
            self.sc_tile.configure(from_=0.5, to=40)
            self.sp_face.configure(from_=1, to=150, increment=1)
            self.sp_tile.configure(from_=0.5, to=40, increment=0.5)
            self.v_face.set(self.cfg["face_abs"])
            self.v_tile.set(self.cfg["tile_abs"])
        self._recalc()

    def _store_threshold_values(self):
        # 存的是「切換前」那個模式的數值
        prev = "absolute" if self.v_mode.get() == "relative" else "relative"
        try:
            f, t = float(self.v_face.get()), float(self.v_tile.get())
        except (tk.TclError, ValueError):
            return
        if prev == "relative":
            self.cfg["face_rel"], self.cfg["tile_rel"] = round(f), round(t)
        else:
            self.cfg["face_abs"], self.cfg["tile_abs"] = round(f, 1), round(t, 1)

    def _slider_moved(self):
        rel = self.v_mode.get() == "relative"
        self.v_face.set(round(self.v_face.get()) if rel else round(self.v_face.get(), 1))
        self.v_tile.set(round(self.v_tile.get()) if rel else round(self.v_tile.get(), 1))
        if not getattr(self, "_recalc_pending", False):
            self._recalc_pending = True
            self.after(120, self._recalc)

    def _recalc(self):
        self._recalc_pending = False
        try:
            fv, tv = float(self.v_face.get()), float(self.v_tile.get())
        except (tk.TclError, ValueError):
            return
        mode = self.v_mode.get()
        if mode == "relative":
            self.cfg["face_rel"], self.cfg["tile_rel"] = round(fv), round(tv)
        else:
            self.cfg["face_abs"], self.cfg["tile_abs"] = round(fv, 1), round(tv, 1)
        res = [self.results[p] for p in self.order]
        self.face_th, self.tile_th = fa.compute_thresholds(res, mode, fv, tv)
        nf = sum(1 for r in res if r.ok and r.method == "face")
        nt = sum(1 for r in res if r.ok and r.method == "tile")
        if mode == "relative":
            self.lbl_face.configure(text=T("th_rel_info", pct=fv, th=self.face_th, n=nf))
            self.lbl_tile.configure(text=T("th_rel_info", pct=tv, th=self.tile_th, n=nt))
        else:
            self.lbl_face.configure(text=T("th_abs_info", th=fv, n=nf))
            self.lbl_tile.configure(text=T("th_abs_info", th=tv, n=nt))
        if not self._building and hasattr(self, "tree"):
            self._refresh_tree()
            self._pv_info()

    def _verdict(self, path: str) -> bool | None:
        r = self.results.get(path)
        if r is None or not r.ok:
            return None
        if path in self.override:
            return self.override[path]
        return fa.is_blurry(r, self.face_th, self.tile_th)

    # ------------------------------------------------------------ 分析
    def _start(self):
        src = self.v_src.get().strip()
        if not src or not os.path.isdir(src):
            messagebox.showwarning(app_name(), T("need_folder"))
            return
        files = fa.list_images(src, self.v_rec.get(), skip_dirs=self._out_dirs())
        if not files:
            messagebox.showinfo(app_name(), T("no_photos"))
            return
        self.results.clear(); self.order.clear(); self.override.clear(); self.done_paths.clear()
        self.tree.delete(*self.tree.get_children())
        self._release_preview()
        self.total = len(files)
        self.pb.configure(maximum=self.total, value=0)
        self.stop_flag.clear()
        self.btn_start.configure(state="disabled"); self.btn_stop.configure(state="normal")
        self.btn_move.configure(state="disabled")
        self.worker = threading.Thread(target=self._work, args=(files,), daemon=True)
        self.worker.start()

    def _work(self, files):
        local = threading.local()

        def job(p):
            if self.stop_flag.is_set():
                return None
            if not hasattr(local, "an"):
                local.an = fa.FocusAnalyzer()
            return local.an.analyze(p)

        n = max(1, min(8, (os.cpu_count() or 2) - 1))
        with ThreadPoolExecutor(max_workers=n) as ex:
            for r in ex.map(job, files):
                if r is not None:
                    self.q.put(("result", r))
        self.q.put(("done", None))

    def _stop(self):
        self.stop_flag.set()
        self.btn_stop.configure(state="disabled")
        self.lbl_status.configure(text=T("status_stopping"))

    def _poll(self):
        changed = False
        try:
            for _ in range(500):
                kind, r = self.q.get_nowait()
                if kind == "result":
                    self.results[r.path] = r
                    self.order.append(r.path)
                    changed = True
                elif kind == "done":
                    self.worker = None
                    self._last_refresh = 0
                    self.btn_start.configure(state="normal"); self.btn_stop.configure(state="disabled")
                    self.btn_move.configure(state="normal")
                    changed = True
        except queue.Empty:
            pass
        import time
        if changed:
            self._dirty = True
        if getattr(self, "_dirty", False) and time.time() - getattr(self, "_last_refresh", 0) > 0.6:
            self._dirty = False
            self._last_refresh = time.time()
            self.pb.configure(value=len(self.order))
            self._recalc()   # 相對門檻依目前結果更新，並重繪清單
        self.after(150, self._poll)

    # ------------------------------------------------------------ 清單
    def _row_values(self, p):
        r = self.results[p]
        name = os.path.relpath(p, self.v_src.get()) if self.v_rec.get() else os.path.basename(p)
        if not r.ok:
            return (name, "-", T("v_read_fail"), "-", T("v_error")), ("err",)
        v = self._verdict(p)
        method = T("m_face") if r.method == "face" else T("m_tile")
        faces = str(len(r.faces)) if r.faces else "-"
        if p in self.done_paths:
            verdict, tags = T("v_done", folder=self.done_paths[p]), ("done",)
        else:
            verdict = T("v_blur") if v else T("v_sharp")
            tags = ("blur",) if v else ()
            if p in self.override:
                verdict += T("v_manual")
                tags = tags + ("manual",)
        return (name, f"{r.score:.1f}", method, faces, verdict), tags

    def _match_filter(self, p, flt):
        r = self.results[p]
        if flt == "f_all":
            return True
        if flt == "f_err":
            return not r.ok
        if flt == "f_done":
            return p in self.done_paths
        if not r.ok or p in self.done_paths:
            return False
        v = self._verdict(p)
        return v if flt == "f_blur" else not v

    def _refresh_tree(self):
        flt = self._filter_key
        sel = set(self.tree.selection())
        want = [p for p in self.order if self._match_filter(p, flt)]
        existing = set(self.tree.get_children())
        for iid in existing - set(want):
            self.tree.delete(iid)
        for i, p in enumerate(want):
            vals, tags = self._row_values(p)
            if p in existing:
                self.tree.item(p, values=vals, tags=tags)
            else:
                self.tree.insert("", i, iid=p, values=vals, tags=tags)
        keep = [s for s in sel if self.tree.exists(s)]
        if keep:
            self.tree.selection_set(keep)
        self._update_status()

    def _sort_by(self, col):
        key = {
            "name": lambda p: os.path.basename(p).lower(),
            "score": lambda p: self.results[p].score,
            "method": lambda p: self.results[p].method,
            "faces": lambda p: len(self.results[p].faces),
            "verdict": lambda p: (self._verdict(p) is not True, self.results[p].score),
        }[col]
        rev = getattr(self, "_sort_state", None) == (col, False)
        self.order.sort(key=key, reverse=rev)
        self._sort_state = (col, rev)
        self.tree.delete(*self.tree.get_children())
        self._refresh_tree()

    def _toggle_selected(self):
        for p in self.tree.selection():
            v = self._verdict(p)
            if v is None or p in self.done_paths:
                continue
            auto = fa.is_blurry(self.results[p], self.face_th, self.tile_th)
            new = not v
            if new == auto:
                self.override.pop(p, None)
            else:
                self.override[p] = new
        self._refresh_tree()
        self._pv_info()
        return "break"

    def _update_status(self):
        n = len(self.order)
        blur = sum(1 for p in self.order if self._verdict(p))
        sharp = sum(1 for p in self.order if self._verdict(p) is False)
        err = sum(1 for p in self.order if not self.results[p].ok)
        running = self.worker is not None and self.worker.is_alive()
        if not n and not running:
            self.lbl_status.configure(text=T("status_ready"))
            return
        parts = [T("st_running", n=n, total=self.total) if running else T("st_total", n=n),
                 T("st_counts", sharp=sharp, blur=blur)]
        if self.done_paths:
            parts.append(T("st_done", n=len(self.done_paths)))
        if err:
            parts.append(T("st_err", n=err))
        if self.override:
            parts.append(T("st_manual", n=len(self.override)))
        self.lbl_status.configure(text=T("st_sep").join(parts))

    # ------------------------------------------------------------ 預覽
    # 座標說明：
    #   「原圖座標」＝原始解析度（轉正後）的像素位置，人臉框也是用這個座標
    #   「畫布座標」＝原圖座標 × 顯示比例 s，圖片左上角在 (0, 0)
    #   畫面只算出「目前看得到的那一塊」，所以 300% 放大大圖也不會吃光記憶體

    @staticmethod
    def _zoom_label(value: str) -> str:
        """設定值 → 畫面顯示文字"""
        return T("zoom_fit") if value == ZOOM_FIT else value

    @staticmethod
    def _is_fit(v: str) -> bool:
        return (not v) or v == ZOOM_FIT or v in all_values("zoom_fit")

    def _zoom_percent(self):
        """回傳使用者設定的比例（%），符合視窗時回傳 None"""
        v = self.v_zoom.get().strip().replace("％", "%")
        if self._is_fit(v):
            return None
        try:
            return max(ZOOM_MIN, min(ZOOM_MAX, float(v.rstrip("%").strip())))
        except ValueError:
            return None

    def _pv_fit_scale(self):
        r = self._pv_res
        cw, ch = max(50, self.canvas.winfo_width()), max(50, self.canvas.winfo_height())
        return min(cw / r.width, ch / r.height)

    def _pv_target_scale(self):
        z = self._zoom_percent()
        return self._pv_fit_scale() if z is None else z / 100.0

    def _show_preview(self, force=False):
        sel = self.tree.selection()
        if not sel:
            return
        p = sel[0]
        if p == self._preview_path and not force:
            return
        r = self.results.get(p)
        self.canvas.delete("all")
        self._preview_path = p
        self._pv_res = None
        self._pv_cache = None
        if r is None or not r.ok or not os.path.exists(p):
            self.lbl_info.configure(text=(error_text(r.error) if r and not r.ok else T("file_missing")))
            return
        self._pv_res = r
        # 放大檢視時，畫面中心對準最清楚的主要人臉，方便直接看對焦
        mains = [f for f in r.faces if f.main]
        if mains:
            b = max(mains, key=lambda f: f.score).box
            focus = (b[0] + b[2] / 2, b[1] + b[3] * 0.4)   # 約在雙眼的高度
        else:
            focus = (r.width / 2, r.height / 2)
        self._pv_focus = focus
        self._pv_layout(anchor=focus, screen=None)
        self._pv_info()

    def _pv_info(self):
        """預覽下方的說明文字（判定改變時也會呼叫）"""
        p, r = self._preview_path, self._pv_res
        if r is None or p is None:
            return
        v = self._verdict(p)
        th = self.face_th if r.method == "face" else self.tile_th
        how = T("pv_how_face", n=len(r.faces)) if r.method == "face" else T("pv_how_tile")
        verdict = (T("v_blur") if v else T("v_sharp")) + (T("v_manual") if p in self.override else "")
        self.lbl_info.configure(text=(
            f"{os.path.basename(p)}   {r.width}×{r.height}\n"
            + T("pv_score", score=r.score, th=th, verdict=verdict) + f"\n{how}"))

    def _pv_source(self, need_full: bool):
        """取得解碼後的圖；需要時才解碼原始解析度，並快取同一張圖"""
        p, r = self._preview_path, self._pv_res
        c = self._pv_cache
        if c and c[0] == p and (c[1] or not need_full):
            return c[2]
        cw, ch = max(50, self.canvas.winfo_width()), max(50, self.canvas.winfo_height())
        # 讀進記憶體後立即關檔，不會鎖住照片
        with Image.open(io.BytesIO(fa.read_bytes(p))) as src_im:
            if not need_full and src_im.format == "JPEG":
                src_im.draft("RGB", (cw * 2, ch * 2))   # 符合視窗時用快速縮小解碼
            im = ImageOps.exif_transpose(src_im).convert("RGB")
            im.load()
        self._pv_cache = (p, need_full or im.width >= r.width, im)
        return im

    def _pv_layout(self, anchor=None, screen=None):
        """
        依目前比例重新排版。
        anchor：要對準的原圖座標；screen：要對準到的畫布視窗位置（預設為中央）
        """
        r = self._pv_res
        if r is None:
            return
        cw, ch = max(50, self.canvas.winfo_width()), max(50, self.canvas.winfo_height())
        s = self._pv_target_scale()
        self._pv_s = s
        VW, VH = r.width * s, r.height * s
        # 圖比視窗小時置中：讓捲動範圍比圖大，圖自然位於中間
        rx0 = min(0.0, -(cw - VW) / 2); ry0 = min(0.0, -(ch - VH) / 2)
        rx1 = max(VW, VW + (cw - VW) / 2); ry1 = max(VH, VH + (ch - VH) / 2)
        self._pv_region = (rx0, ry0, rx1, ry1)
        self.canvas.configure(scrollregion=(rx0, ry0, rx1, ry1))

        if anchor is not None:
            sx, sy = screen if screen else (cw / 2, ch / 2)
            ax, ay = anchor[0] * s, anchor[1] * s
            if rx1 - rx0 > cw:
                self.canvas.xview_moveto(max(0.0, (ax - sx - rx0) / (rx1 - rx0)))
            else:
                self.canvas.xview_moveto(0)
            if ry1 - ry0 > ch:
                self.canvas.yview_moveto(max(0.0, (ay - sy - ry0) / (ry1 - ry0)))
            else:
                self.canvas.yview_moveto(0)

        # 人臉框（畫布物件，捲動時自動跟著移動）
        self.canvas.delete("face")
        fsize = 11 if s < 0.5 else 13
        for f in r.faces:
            x, y, w, h = (v * s for v in f.box)
            color = "#9e9e9e" if not f.main else ("#e53935" if f.score < self.face_th else "#43a047")
            self.canvas.create_rectangle(x, y, x + w, y + h, outline=color, width=2, tags="face")
            if f.main:
                self.canvas.create_text(x + 2, y - 2, text=f"{f.score:.0f}", fill=color, anchor="sw",
                                        font=("Arial", fsize, "bold"), tags="face")

        z = self._zoom_percent()
        self.lbl_zoom.configure(text=T("zoom_now", pct=s * 100) + (T("zoom_now_fit") if z is None else ""))
        self._pv_render()

    def _pv_render(self):
        """只把目前看得到的區域畫出來"""
        self._pv_render_pending = False
        r = self._pv_res
        if r is None:
            return
        s = self._pv_s
        cw, ch = max(50, self.canvas.winfo_width()), max(50, self.canvas.winfo_height())
        x0, y0 = self.canvas.canvasx(0), self.canvas.canvasy(0)
        VW, VH = r.width * s, r.height * s
        ix0, iy0 = max(0.0, x0), max(0.0, y0)
        ix1, iy1 = min(VW, x0 + cw), min(VH, y0 + ch)
        self.canvas.delete("img")
        if ix1 - ix0 < 1 or iy1 - iy0 < 1:
            return
        try:
            need_full = s > (self._pv_fit_scale() * 1.5)
            im = self._pv_source(need_full)
        except Exception as e:
            self.lbl_info.configure(text=T("preview_fail", e=e))
            return
        k = im.width / float(r.width)          # 載入的圖 相對 原圖 的比例
        box = (ix0 / s * k, iy0 / s * k, ix1 / s * k, iy1 / s * k)
        out_w, out_h = max(1, int(round(ix1 - ix0))), max(1, int(round(iy1 - iy0)))
        src_w = box[2] - box[0]
        if out_w >= src_w * 2:
            resample = Image.NEAREST         # 大幅放大：看得到每個像素，判斷對焦最準
        elif out_w >= src_w:
            resample = Image.BICUBIC
        else:
            resample = Image.LANCZOS
        tile = im.resize((out_w, out_h), resample, box=box)
        self._preview_img = ImageTk.PhotoImage(tile)
        self.canvas.create_image(ix0, iy0, image=self._preview_img, anchor="nw", tags="img")
        self.canvas.tag_lower("img")

    def _pv_schedule(self):
        if not getattr(self, "_pv_render_pending", False):
            self._pv_render_pending = True
            self.after_idle(self._pv_render)

    def _pv_view_center(self):
        """目前畫面中央對應的原圖座標"""
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        s = self._pv_s
        return (self.canvas.canvasx(cw / 2) / s, self.canvas.canvasy(ch / 2) / s)

    def _pv_relayout(self):
        if self._pv_res is not None and getattr(self, "_pv_s", None):
            self._pv_layout(anchor=self._pv_view_center())

    def _pv_scroll(self, axis, *args):
        (self.canvas.xview if axis == "x" else self.canvas.yview)(*args)
        self._pv_schedule()

    def _pv_press(self, e):
        self.canvas.scan_mark(e.x, e.y)

    def _pv_drag(self, e):
        self.canvas.scan_dragto(e.x, e.y, gain=1)
        self._pv_schedule()

    def _pv_wheel(self, e, delta=None):
        if self._pv_res is None:
            return
        d = delta if delta is not None else e.delta
        if e.state & 0x0004:                     # Ctrl＋滾輪：以游標位置為中心縮放
            self._zoom_step(1 if d > 0 else -1, at=(e.x, e.y))
        elif e.state & 0x0001:                   # Shift＋滾輪：左右捲動
            self.canvas.xview_scroll(-1 if d > 0 else 1, "units"); self._pv_schedule()
        else:
            self.canvas.yview_scroll(-1 if d > 0 else 1, "units"); self._pv_schedule()

    def _pv_double(self, e):
        if self._pv_res is None:
            return
        if self._zoom_percent() is None:
            self._set_zoom("100%", at=(e.x, e.y))
        else:
            self._set_zoom(ZOOM_FIT)

    def _set_zoom(self, value: str, at=None):
        if self._pv_res is None or not getattr(self, "_pv_s", None):
            self.v_zoom.set(self._zoom_label(value))
            self._zoom_changed()
            return
        if at is None:
            at = (self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2)
            # 從「符合視窗」放大時，直接對準最清楚的臉（雙眼位置）
            if self._zoom_percent() is None and value != ZOOM_FIT:
                self.v_zoom.set(self._zoom_label(value))
                self.cfg["zoom"] = value
                self._pv_layout(anchor=self._pv_focus, screen=at)
                return
        s = self._pv_s
        anchor = (self.canvas.canvasx(at[0]) / s, self.canvas.canvasy(at[1]) / s)
        self.v_zoom.set(self._zoom_label(value))
        self.cfg["zoom"] = value
        self._pv_layout(anchor=anchor, screen=at)

    def _zoom_step(self, direction: int, at=None):
        cur = (self._pv_s if getattr(self, "_pv_s", None) and self._pv_res else
               (self._zoom_percent() or 100) / 100.0) * 100
        if direction > 0:
            nxt = next((z for z in ZOOM_STEPS if z > cur + 0.5), ZOOM_MAX)
        else:
            nxt = next((z for z in reversed(ZOOM_STEPS) if z < cur - 0.5), ZOOM_MIN)
        self._set_zoom(f"{nxt}%", at=at)

    def _zoom_changed(self):
        was_fit = self.cfg.get("zoom", ZOOM_FIT) == ZOOM_FIT
        v = self.v_zoom.get().strip()
        z = self._zoom_percent()
        if z is None and not self._is_fit(v):
            self.v_zoom.set(self._zoom_label(self.cfg.get("zoom", ZOOM_FIT)))   # 輸入格式不對就還原
            return
        val = ZOOM_FIT if z is None else f"{z:g}%"
        self.v_zoom.set(self._zoom_label(val))
        self.cfg["zoom"] = val
        if self._pv_res is not None and getattr(self, "_pv_s", None):
            anchor = self._pv_focus if (was_fit and z is not None) else self._pv_view_center()
            self._pv_layout(anchor=anchor)

    def _release_preview(self):
        """清掉預覽圖與快取，確保程式本身沒有握住任何照片資料"""
        self.canvas.delete("all")
        self._preview_img = None
        self._preview_path = None
        self._pv_res = None
        self._pv_cache = None
        import gc
        gc.collect()

    def _label_font(self):
        if getattr(self, "_font", None) is None:
            from PIL import ImageFont
            self._font = None
            for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
                try:
                    self._font = ImageFont.truetype(name, 16)
                    break
                except OSError:
                    pass
            if self._font is None:
                self._font = ImageFont.load_default()
        return self._font

    # ------------------------------------------------------------ 搬移
    def _sidecars(self, path: str) -> list:
        d, fn = os.path.split(path)
        stem = os.path.splitext(fn)[0].lower()
        out = []
        try:
            for f in os.listdir(d):
                full = os.path.join(d, f)
                if f == fn or not os.path.isfile(full):
                    continue
                s, e = os.path.splitext(f)
                # IMG_001.CR3、IMG_001.xmp、IMG_001.CR3.xmp 都算
                if s.lower() == stem or f.lower().startswith(stem + "."):
                    out.append(full)
        except OSError:
            pass
        return out

    def _do_copy(self):
        src_root = self.v_src.get().strip()
        targets = [p for p in self.order if p not in self.done_paths and self._verdict(p) is not None]
        if not targets:
            messagebox.showinfo(app_name(), T("nothing_to_copy"))
            return
        n_blur = sum(1 for p in targets if self._verdict(p))
        n_sharp = len(targets) - n_blur
        sharp_dir, blur_dir = T("sharp_dir"), T("blur_dir")
        if not messagebox.askyesno(app_name(), T("confirm_copy", sharp=sharp_dir, blur=blur_dir,
                                                 n_sharp=n_sharp, n_blur=n_blur)):
            return
        self._release_preview()
        log, errors, skipped = [], [], 0
        for p in targets:
            folder = blur_dir if self._verdict(p) else sharp_dir
            dst_root = os.path.join(src_root, folder)
            files = [p] + (self._sidecars(p) if self.v_side.get() else [])
            main_ok = False
            for f in files:
                try:
                    rel = os.path.relpath(os.path.dirname(f), src_root)
                    ddir = dst_root if rel in (".", "") else os.path.join(dst_root, rel)
                    os.makedirs(ddir, exist_ok=True)
                    dst = os.path.join(ddir, os.path.basename(f))
                    if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(f):
                        skipped += 1          # 已經有相同的檔案，不重複複製
                    else:
                        dst = unique_path(dst)
                        copy_file(f, dst)
                        log.append((T("log_copy"), f, dst))
                    if f == p:
                        main_ok = True
                except Exception as e:
                    log_error("copy", f, e)
                    errors.append(os.path.basename(f) + T("colon") + explain_error(e, f))
                    if f == p:
                        break
            if main_ok:
                self.done_paths[p] = folder
        self.last_log = log
        self.btn_undo.configure(state="normal" if log else "disabled")
        self._write_log(src_root, log)
        self._preview_path = None
        self._refresh_tree()
        msg = T("copy_done", n=len(log))
        if skipped:
            msg += T("copy_skipped", n=skipped)
        if errors:
            msg += T("copy_errors", n=len(errors)) + "\n".join(errors[:10])
            msg += T("error_log_at", path=os.path.join(SETTINGS_DIR, "error.log"))
        messagebox.showinfo(app_name(), msg)

    def _write_log(self, dst_root, log):
        if not log:
            return
        try:
            path = os.path.join(dst_root, T("log_file"))
            new = not os.path.exists(path)
            with open(path, "a", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(T("log_headers"))
                w.writerows(log)
        except Exception:
            pass

    def _undo(self):
        if not self.last_log:
            return
        if not messagebox.askyesno(app_name(), T("confirm_undo", n=len(self.last_log),
                                                 sharp=T("sharp_dir"), blur=T("blur_dir"))):
            return
        self._release_preview()
        errors, restored = [], set()
        for op, src, dst in reversed(self.last_log):
            try:
                _retry(lambda: _remove_file(dst))
                restored.add(src)
            except FileNotFoundError:
                restored.add(src)
            except Exception as e:
                log_error("undo", dst, e)
                errors.append(os.path.basename(dst) + T("colon") + explain_error(e, dst))
        for p in list(self.done_paths):
            if p in restored:
                del self.done_paths[p]
        self.last_log = []
        self.btn_undo.configure(state="disabled")
        self._preview_path = None
        self._refresh_tree()
        msg = T("undo_done")
        if errors:
            msg += T("undo_errors", n=len(errors)) + "\n".join(errors[:10])
        messagebox.showinfo(app_name(), msg)

    # ------------------------------------------------------------ 其他
    def _export_csv(self):
        if not self.order:
            messagebox.showinfo(app_name(), T("analyze_first"))
            return
        path = filedialog.asksaveasfilename(title=T("export_title"), defaultextension=".csv",
                                            initialfile=T("export_file"), filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(T("csv_headers"))
            for p in self.order:
                r = self.results[p]
                v = self._verdict(p)
                w.writerow([p, r.score if r.ok else "", T("csv_face") if r.method == "face" else T("csv_tile"),
                            len(r.faces), "" if v is None else (T("v_blur") if v else T("v_sharp")),
                            T("csv_yes") if p in self.override else "", self.done_paths.get(p, ""),
                            error_text(r.error)])
        messagebox.showinfo(app_name(), T("exported"))

    def _on_close(self):
        self.stop_flag.set()
        self._sync_cfg()
        self.cfg["geometry"] = self.geometry()
        save_settings(self.cfg)
        self.destroy()


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Dorigo.BlurSorter")
        except Exception:
            pass
    App().mainloop()


if __name__ == "__main__":
    main()
