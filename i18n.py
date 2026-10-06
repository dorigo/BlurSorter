# BlurSorter — 失焦照片分類器
# Copyright (C) 2026 Dorigo <https://dorigo-image.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""
介面文字（中文 / English）

新增語言：在 STRINGS 加一組新的語言代碼（例如 "ja"），把 "en" 的每個 key 翻譯過去，
再把語言名稱加進 LANG_NAMES 即可。缺少的 key 會自動退回英文。
"""

from __future__ import annotations

import locale
import sys

LANG_NAMES = {"zh": "中文", "en": "English"}

STRINGS = {
    # ------------------------------------------------------------------ 中文
    "zh": {
        "app_name": "失焦照片分類器",
        "sharp_dir": "清楚",
        "blur_dir": "模糊",
        "log_file": "_分類紀錄.csv",

        # 標題列
        "language": "語言",
        "tagline": "覺得好用的話，歡迎請我喝杯咖啡 ☕",
        "sponsor": "♥ 贊助開發者",
        "author_site": "作者網站 ↗",

        # 資料夾
        "folder_frame": "資料夾",
        "photo_folder": "照片資料夾",
        "browse": "瀏覽…",
        "include_sub": "包含子資料夾",
        "result_label": "分類結果",
        "result_desc": "複製到照片資料夾內的「{sharp}」與「{blur}」資料夾，原始照片完全不會移動或修改",
        "pick_folder_title": "選擇照片資料夾",

        # 門檻
        "th_frame": "判斷門檻（調整後立即重新判定，不需重新分析）",
        "th_relative": "相對門檻（建議）",
        "th_relative_desc": "分數低於本批較清楚照片的 X%\n就判定為模糊",
        "th_absolute": "絕對門檻",
        "th_face": "有人臉的照片",
        "th_tile": "無人臉的照片",
        "th_rel_info": "{pct:.0f}%  → 分數門檻 {th:.1f}（{n} 張）",
        "th_abs_info": "分數 < {th:.1f} 判定模糊（{n} 張）",

        # 操作列
        "start": "① 開始分析",
        "stop": "停止",
        "sidecar": "連同同名 RAW / XMP 檔",
        "copy_btn": "② 複製到「{sharp}」「{blur}」",
        "undo_btn": "刪除上次複製的檔案",
        "export_csv": "匯出 CSV",
        "open_folder": "開啟照片資料夾",

        # 清單
        "show": "顯示",
        "f_all": "全部", "f_blur": "模糊", "f_sharp": "清楚", "f_done": "已複製", "f_err": "錯誤",
        "toggle_hint": "雙擊或按空白鍵：手動切換 模糊 / 清楚",
        "col_name": "檔名", "col_score": "清晰度", "col_method": "判斷方式",
        "col_faces": "人臉", "col_verdict": "判定",
        "m_face": "人臉／眼部", "m_tile": "分區",
        "v_blur": "模糊", "v_sharp": "清楚", "v_manual": "（手動）",
        "v_done": "已複製→{folder}", "v_read_fail": "讀取失敗", "v_error": "錯誤",

        # 預覽
        "zoom": "顯示比例",
        "zoom_fit": "符合視窗",
        "zoom_now": "目前 {pct:.0f}%",
        "zoom_now_fit": "（符合視窗）",
        "preview_hint": ("選擇左側照片即可預覽。綠框＝清楚的臉，紅框＝模糊的臉，灰框＝次要人臉。\n"
                         "拖曳移動畫面；Ctrl＋滾輪縮放；雙擊在「符合視窗」與 100% 間切換。"),
        "file_missing": "檔案不存在",
        "preview_fail": "預覽失敗：{e}",
        "pv_score": "清晰度 {score:.1f}　門檻 {th:.1f}　→　{verdict}",
        "pv_how_face": "人臉 {n} 張（取主要人臉中最清楚的一張）",
        "pv_how_tile": "未偵測到人臉，使用分區判斷（取最清楚的區塊）",

        # 狀態列
        "status_ready": "請選擇照片資料夾，然後按「開始分析」。",
        "status_stopping": "正在停止…",
        "st_running": "分析中 {n}/{total}",
        "st_total": "共 {n} 張",
        "st_counts": "清楚 {sharp} 張　｜　模糊 {blur} 張",
        "st_done": "已複製 {n} 張",
        "st_err": "讀取失敗 {n} 張",
        "st_manual": "手動修正 {n} 張",
        "st_sep": "　｜　",

        # 訊息
        "no_model": "找不到人臉模型檔，將只使用分區判斷。\n{path}",
        "need_folder": "請先選擇有效的照片資料夾。",
        "no_photos": "這個資料夾裡沒有找到照片（JPG / PNG / TIF / WEBP）。",
        "nothing_to_copy": "沒有需要複製的照片（可能都已經複製過了）。",
        "confirm_copy": ("將複製到照片資料夾內：\n\n"
                         "　「{sharp}」　{n_sharp} 張\n　「{blur}」　{n_blur} 張\n\n"
                         "原始照片不會移動或修改。確定執行？"),
        "copy_done": "完成！已複製 {n} 個檔案。",
        "copy_skipped": "\n（{n} 個檔案已存在，略過）",
        "copy_errors": "\n\n有 {n} 個檔案失敗：\n",
        "error_log_at": "\n\n詳細紀錄：{path}",
        "confirm_undo": ("要刪除上次複製出來的 {n} 個檔案嗎？\n"
                         "（只刪除「{sharp}」「{blur}」裡的複本，原始照片不受影響）"),
        "undo_done": "已刪除上次複製的檔案。",
        "undo_errors": "\n\n有 {n} 個刪除失敗，可自行到資料夾刪除：\n",
        "analyze_first": "請先分析照片。",
        "export_title": "匯出分析結果",
        "export_file": "清晰度分析.csv",
        "exported": "已匯出。",
        "browser_fail": "無法自動開啟瀏覽器，網址已複製到剪貼簿：\n{url}",

        # CSV
        "csv_headers": ["檔案", "清晰度", "判斷方式", "人臉數", "判定", "手動修正", "已複製到", "錯誤"],
        "csv_face": "人臉", "csv_tile": "分區", "csv_yes": "是",
        "log_headers": ["動作", "原始位置", "新位置"],
        "log_copy": "複製",

        # 錯誤說明
        "err_decode": "無法讀取圖片",
        "err_unknown_app": "未知程式",
        "err_this_app": "{name}（本程式）",
        "err_pid": "{name}（PID {pid}）",
        "err_locked_by": "檔案正被以下程式使用：{names}。原檔保留未動",
        "err_list_sep": "、",
        "err_denied": ("存取被拒。\n"
                       "　可能是 Windows「受控資料夾存取」擋住了本程式（桌面、文件、圖片等資料夾受保護）。\n"
                       "　解決方式：Windows 安全性 → 病毒與威脅防護 → 管理勒索軟體防護 → "
                       "允許應用程式通過受控資料夾存取 → 加入 BlurSorter.exe；"
                       "或把照片放在受保護資料夾以外的位置（例如 D:\\照片）"),
        "err_in_use": "檔案被其他程式使用中。原檔保留未動，請關閉後再試一次",
        "err_not_found": "找不到檔案（可能已被移走）",
        "colon": "：",
    },

    # ------------------------------------------------------------------ English
    "en": {
        "app_name": "BlurSorter",
        "sharp_dir": "Sharp",
        "blur_dir": "Blurry",
        "log_file": "_sort_log.csv",

        "language": "Language",
        "tagline": "Find it useful? Buy me a coffee ☕",
        "sponsor": "♥ Sponsor",
        "author_site": "Author's site ↗",

        "folder_frame": "Folder",
        "photo_folder": "Photo folder",
        "browse": "Browse…",
        "include_sub": "Include subfolders",
        "result_label": "Output",
        "result_desc": "Photos are copied into \"{sharp}\" and \"{blur}\" folders inside the photo folder. Originals are never moved or modified.",
        "pick_folder_title": "Choose photo folder",

        "th_frame": "Threshold (changes apply instantly, no re-analysis needed)",
        "th_relative": "Relative (recommended)",
        "th_relative_desc": "Blurry if score is below X% of\nthe sharper photos in this batch",
        "th_absolute": "Absolute",
        "th_face": "Photos with faces",
        "th_tile": "Photos without faces",
        "th_rel_info": "{pct:.0f}%  → score threshold {th:.1f} ({n} photos)",
        "th_abs_info": "Score < {th:.1f} = blurry ({n} photos)",

        "start": "① Analyze",
        "stop": "Stop",
        "sidecar": "Include RAW / XMP with same name",
        "copy_btn": "② Copy to \"{sharp}\" / \"{blur}\"",
        "undo_btn": "Delete last copied files",
        "export_csv": "Export CSV",
        "open_folder": "Open photo folder",

        "show": "Show",
        "f_all": "All", "f_blur": "Blurry", "f_sharp": "Sharp", "f_done": "Copied", "f_err": "Errors",
        "toggle_hint": "Double-click or press Space to toggle Blurry / Sharp",
        "col_name": "File", "col_score": "Sharpness", "col_method": "Method",
        "col_faces": "Faces", "col_verdict": "Result",
        "m_face": "Face / eyes", "m_tile": "Regions",
        "v_blur": "Blurry", "v_sharp": "Sharp", "v_manual": " (manual)",
        "v_done": "Copied → {folder}", "v_read_fail": "Read failed", "v_error": "Error",

        "zoom": "Zoom",
        "zoom_fit": "Fit",
        "zoom_now": "Now {pct:.0f}%",
        "zoom_now_fit": " (fit)",
        "preview_hint": ("Select a photo on the left to preview. Green = sharp face, red = blurry face, gray = minor face.\n"
                         "Drag to pan; Ctrl + wheel to zoom; double-click to toggle Fit / 100%."),
        "file_missing": "File not found",
        "preview_fail": "Preview failed: {e}",
        "pv_score": "Sharpness {score:.1f}   Threshold {th:.1f}   →   {verdict}",
        "pv_how_face": "{n} face(s) — uses the sharpest main face",
        "pv_how_tile": "No face detected — uses the sharpest regions",

        "status_ready": "Choose a photo folder, then click \"Analyze\".",
        "status_stopping": "Stopping…",
        "st_running": "Analyzing {n}/{total}",
        "st_total": "{n} photos",
        "st_counts": "Sharp {sharp}  |  Blurry {blur}",
        "st_done": "Copied {n}",
        "st_err": "Read failed {n}",
        "st_manual": "Manual {n}",
        "st_sep": "  |  ",

        "no_model": "Face model not found. Only region-based detection will be used.\n{path}",
        "need_folder": "Please choose a valid photo folder first.",
        "no_photos": "No photos (JPG / PNG / TIF / WEBP) found in this folder.",
        "nothing_to_copy": "Nothing to copy (everything may have been copied already).",
        "confirm_copy": ("Copy into the photo folder:\n\n"
                         "   \"{sharp}\"   {n_sharp} photos\n   \"{blur}\"   {n_blur} photos\n\n"
                         "Originals will not be moved or modified. Continue?"),
        "copy_done": "Done! Copied {n} file(s).",
        "copy_skipped": "\n({n} file(s) already existed and were skipped)",
        "copy_errors": "\n\n{n} file(s) failed:\n",
        "error_log_at": "\n\nDetails: {path}",
        "confirm_undo": ("Delete the {n} file(s) copied last time?\n"
                         "(Only the copies in \"{sharp}\" / \"{blur}\" are deleted. Originals are not affected.)"),
        "undo_done": "Last copied files deleted.",
        "undo_errors": "\n\n{n} file(s) could not be deleted. You can delete them manually:\n",
        "analyze_first": "Please analyze photos first.",
        "export_title": "Export results",
        "export_file": "sharpness_report.csv",
        "exported": "Exported.",
        "browser_fail": "Could not open the browser. The link has been copied to the clipboard:\n{url}",

        "csv_headers": ["File", "Sharpness", "Method", "Faces", "Result", "Manual", "Copied to", "Error"],
        "csv_face": "Face", "csv_tile": "Regions", "csv_yes": "Yes",
        "log_headers": ["Action", "Source", "Destination"],
        "log_copy": "copy",

        "err_decode": "Cannot read image",
        "err_unknown_app": "Unknown program",
        "err_this_app": "{name} (this program)",
        "err_pid": "{name} (PID {pid})",
        "err_locked_by": "File is in use by: {names}. Original left untouched",
        "err_list_sep": ", ",
        "err_denied": ("Access denied.\n"
                       "   Windows \"Controlled folder access\" may be blocking this program (Desktop, Documents, Pictures are protected).\n"
                       "   Fix: Windows Security → Virus & threat protection → Manage ransomware protection → "
                       "Allow an app through Controlled folder access → add BlurSorter.exe; "
                       "or keep photos outside protected folders (e.g. D:\\Photos)"),
        "err_in_use": "File is in use by another program. Original left untouched; close it and try again",
        "err_not_found": "File not found (it may have been moved)",
        "colon": ": ",
    },
}

_lang = "zh"


def detect_default_lang() -> str:
    """依作業系統介面語言決定預設語言：中文系統用中文，其他用英文"""
    try:
        if sys.platform == "win32":
            import ctypes
            langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return "zh" if (langid & 0x3FF) == 0x04 else "en"   # 0x04 = LANG_CHINESE
        loc = (locale.getlocale()[0] or "").lower()
        return "zh" if loc.startswith("zh") or "chinese" in loc else "en"
    except Exception:
        return "en"


def set_lang(lang: str):
    global _lang
    _lang = lang if lang in STRINGS else "en"


def get_lang() -> str:
    return _lang


def T(key: str, **kw):
    """取得目前語言的文字；有參數時代入 {name} 佔位符"""
    s = STRINGS.get(_lang, {}).get(key)
    if s is None:
        s = STRINGS["en"].get(key, key)
    return s.format(**kw) if kw and isinstance(s, str) else s


def all_values(key: str) -> set:
    """某個 key 在所有語言的文字（例如兩種語言的資料夾名稱，掃描時都要略過）"""
    return {d[key] for d in STRINGS.values() if key in d}
