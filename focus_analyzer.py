# BlurSorter — 失焦照片分類器
# Copyright (C) 2026 Dorigo <https://dorigo-image.com>
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later version.
# This program is distributed WITHOUT ANY WARRANTY. See the LICENSE file for details.

"""
focus_analyzer.py — 照片清晰度分析核心

判斷流程：
1. 讀取照片（支援中文路徑、依 EXIF 自動轉正）
2. 用 YuNet 偵測人臉
3. 有人臉：從「原始解析度」裁切每張臉，統一縮放到固定寬度，
   以「雙眼區域」的拉普拉斯變異數作為清晰度分數（眼睛是人像對焦的關鍵）
   → 照片分數 = 主要人臉（尺寸 >= 最大臉 40%）中最清楚的那一張
4. 無人臉：把照片切成格子，取最清楚的幾格平均（淺景深背景模糊不影響判斷）
"""

from __future__ import annotations

import io
import os
import sys
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image

cv2.setLogLevel(2) if hasattr(cv2, "setLogLevel") else None

FACE_NORM_WIDTH = 256      # 每張臉統一縮放到的寬度（讓不同照片的分數可比較）
DETECT_LONG_SIDE = 1280    # 人臉偵測用的縮圖長邊
TILE_LONG_SIDE = 1600      # 無人臉時分區分析用的長邊
TILE_GRID = 8              # 分區格數（8x8）
TILE_TOP_K = 3             # 取最清楚的幾格
MIN_FACE_PX = 40           # 原圖中小於此寬度的人臉忽略
FACE_SCORE_TH = 0.75       # 人臉偵測信心門檻
MAIN_FACE_RATIO = 0.4      # 尺寸 >= 最大臉此比例才算主要人臉
REF_PERCENTILE = 75        # 相對門檻的基準百分位

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def resource_path(rel: str) -> str:
    """取得資源路徑（相容 PyInstaller 打包後的路徑）"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


MODEL_PATH = resource_path(os.path.join("models", "face_detection_yunet_2023mar.onnx"))


@dataclass
class FaceInfo:
    box: tuple            # (x, y, w, h) 原圖座標
    score: float          # 清晰度分數
    main: bool = True     # 是否為主要人臉


@dataclass
class AnalysisResult:
    path: str
    ok: bool = True
    error: str = ""
    method: str = ""      # "face" 或 "tile"
    score: float = 0.0
    faces: list = field(default_factory=list)
    width: int = 0
    height: int = 0


# ---------------------------------------------------------------- 讀檔

def read_bytes(path: str) -> bytes:
    """
    一次把整個檔案讀進記憶體並立即關檔。
    之後所有解碼都從記憶體進行，程式不會在任何時候持續握住照片檔，
    避免 Windows 上「檔案使用中，無法移動 / 刪除」。
    """
    with open(path, "rb") as f:
        return f.read()


def _exif_orientation(data: bytes) -> int:
    try:
        with Image.open(io.BytesIO(data)) as im:
            return int(im.getexif().get(0x0112, 1))
    except Exception:
        return 1


def _apply_orientation(img: np.ndarray, ori: int) -> np.ndarray:
    if ori == 2:
        return cv2.flip(img, 1)
    if ori == 3:
        return cv2.rotate(img, cv2.ROTATE_180)
    if ori == 4:
        return cv2.flip(img, 0)
    if ori == 5:
        return cv2.flip(cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE), 1)
    if ori == 6:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if ori == 7:
        return cv2.flip(cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE), 1)
    if ori == 8:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img


def load_image(path: str) -> np.ndarray:
    """讀取為 BGR，支援 Windows 中文路徑，並依 EXIF 轉正"""
    data = read_bytes(path)
    flags = cv2.IMREAD_COLOR | getattr(cv2, "IMREAD_IGNORE_ORIENTATION", 128)
    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), flags)
    if img is None:
        raise ValueError("decode_failed")   # 介面會依語言顯示對應文字
    return _apply_orientation(img, _exif_orientation(data))


# ---------------------------------------------------------------- 清晰度

def sharpness(gray: np.ndarray) -> float:
    """拉普拉斯變異數；先輕微降噪，避免高 ISO 雜訊被誤當成細節"""
    if gray.size == 0:
        return 0.0
    g = cv2.GaussianBlur(gray, (3, 3), 0)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def _resize_to_width(img: np.ndarray, width: int) -> tuple[np.ndarray, float]:
    h, w = img.shape[:2]
    s = width / float(w)
    interp = cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC
    return cv2.resize(img, (width, max(1, int(round(h * s)))), interpolation=interp), s


# ---------------------------------------------------------------- 分析器

class FocusAnalyzer:
    """每個執行緒各自建立一個實例（YuNet 物件非執行緒安全）"""

    def __init__(self, model_path: str = MODEL_PATH):
        self.detector = None
        if os.path.exists(model_path):
            self.detector = cv2.FaceDetectorYN.create(
                model_path, "", (320, 320), FACE_SCORE_TH, 0.3, 5000)

    def detect_faces(self, bgr: np.ndarray) -> list:
        """回傳原圖座標的 [(x, y, w, h, lmk(5x2))]"""
        if self.detector is None:
            return []
        h, w = bgr.shape[:2]
        s = min(1.0, DETECT_LONG_SIDE / float(max(h, w)))
        small = cv2.resize(bgr, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else bgr
        sh, sw = small.shape[:2]
        self.detector.setInputSize((sw, sh))
        _, faces = self.detector.detect(small)
        out = []
        if faces is None:
            return out
        for f in faces:
            x, y, fw, fh = (f[:4] / s).tolist()
            lmk = (f[4:14].reshape(5, 2) / s)
            if fw >= MIN_FACE_PX:
                out.append((x, y, fw, fh, lmk))
        return out

    def face_sharpness(self, gray: np.ndarray, face) -> float:
        x, y, fw, fh, lmk = face
        H, W = gray.shape[:2]
        # 臉部稍微外擴後裁切
        pad = 0.1
        x0 = int(max(0, x - fw * pad)); y0 = int(max(0, y - fh * pad))
        x1 = int(min(W, x + fw * (1 + pad))); y1 = int(min(H, y + fh * (1 + pad)))
        crop = gray[y0:y1, x0:x1]
        if crop.size == 0:
            return 0.0
        norm, s = _resize_to_width(crop, FACE_NORM_WIDTH)

        # 雙眼區域（landmark 0、1 為右眼、左眼）
        eyes = (lmk[:2] - np.array([x0, y0])) * s
        d = float(np.linalg.norm(eyes[0] - eyes[1]))
        if d > 10:
            ex0 = int(max(0, eyes[:, 0].min() - d * 0.5))
            ex1 = int(min(norm.shape[1], eyes[:, 0].max() + d * 0.5))
            ey0 = int(max(0, eyes[:, 1].min() - d * 0.35))
            ey1 = int(min(norm.shape[0], eyes[:, 1].max() + d * 0.35))
            eye_region = norm[ey0:ey1, ex0:ex1]
            if eye_region.shape[0] > 8 and eye_region.shape[1] > 16:
                # 眼部為主，整張臉為輔（避免閉眼、眼鏡反光造成極端值）
                return 0.7 * sharpness(eye_region) + 0.3 * sharpness(norm)
        return sharpness(norm)

    def tile_sharpness(self, gray: np.ndarray) -> float:
        h, w = gray.shape[:2]
        s = min(1.0, TILE_LONG_SIDE / float(max(h, w)))
        g = cv2.resize(gray, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else gray
        h, w = g.shape[:2]
        th, tw = h // TILE_GRID, w // TILE_GRID
        vals = []
        for r in range(TILE_GRID):
            for c in range(TILE_GRID):
                t = g[r * th:(r + 1) * th, c * tw:(c + 1) * tw]
                # 忽略幾乎純色的格子（天空、牆面）
                if t.size and t.std() > 4:
                    vals.append(sharpness(t))
        if not vals:
            return sharpness(g)
        vals.sort(reverse=True)
        return float(np.mean(vals[:TILE_TOP_K]))

    def analyze(self, path: str) -> AnalysisResult:
        res = AnalysisResult(path=path)
        try:
            bgr = load_image(path)
            res.height, res.width = bgr.shape[:2]
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            faces = self.detect_faces(bgr)
            if faces:
                biggest = max(f[2] for f in faces)
                for f in faces:
                    main = f[2] >= biggest * MAIN_FACE_RATIO
                    sc = self.face_sharpness(gray, f) if main else 0.0
                    res.faces.append(FaceInfo(
                        box=tuple(int(v) for v in f[:4]), score=round(sc, 1), main=main))
                res.method = "face"
                res.score = max(fi.score for fi in res.faces if fi.main)
            else:
                res.method = "tile"
                res.score = self.tile_sharpness(gray)
            res.score = round(res.score, 1)
        except Exception as e:  # noqa
            res.ok = False
            res.error = str(e)
        return res


# ---------------------------------------------------------------- 門檻

def compute_thresholds(results, mode: str, face_val: float, tile_val: float):
    """
    mode = "relative"：門檻 = 本批同類照片「較清楚的前 25%」的分數（第 75 百分位）× 百分比
                       用第 75 百分位而不是平均，即使這批有很多失焦照片，基準也不會被拉低
    mode = "absolute"：門檻直接是分數
    回傳 (人臉門檻, 無人臉門檻)
    """
    if mode == "absolute":
        return face_val, tile_val

    def ref(method):
        v = [r.score for r in results if r.ok and r.method == method]
        return float(np.percentile(v, REF_PERCENTILE)) if v else 0.0

    return ref("face") * face_val / 100.0, ref("tile") * tile_val / 100.0


def is_blurry(r: AnalysisResult, face_th: float, tile_th: float) -> bool:
    if not r.ok:
        return False
    return r.score < (face_th if r.method == "face" else tile_th)


def list_images(folder: str, recursive: bool, skip_dirs=()) -> list:
    skip = {os.path.normcase(os.path.abspath(d)) for d in skip_dirs if d}
    out = []
    if recursive:
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs
                       if os.path.normcase(os.path.abspath(os.path.join(root, d))) not in skip]
            for f in files:
                if os.path.splitext(f)[1].lower() in IMAGE_EXTS:
                    out.append(os.path.join(root, f))
    else:
        for f in os.listdir(folder):
            p = os.path.join(folder, f)
            if os.path.isfile(p) and os.path.splitext(f)[1].lower() in IMAGE_EXTS:
                out.append(p)
    out.sort()
    return out
