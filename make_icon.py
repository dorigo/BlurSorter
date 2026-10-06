# BlurSorter — 失焦照片分類器
# Copyright (C) 2026 Dorigo <https://dorigo-image.com>
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later version.
# This program is distributed WITHOUT ANY WARRANTY. See the LICENSE file for details.

"""
make_icon.py — 把 icon.png 轉成 Windows 用的 icon.ico（打包時由 build.bat 自動執行）

換圖示的方法：
  把你自己的圖片命名為 icon.png（建議 256×256 以上的正方形、可透明背景），
  放在這個資料夾裡覆蓋原本的檔案，再執行 build.bat 即可。
  如果你已經有現成的 icon.ico，也可以直接覆蓋 icon.ico，並刪掉 icon.png。
"""

import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
PNG = os.path.join(HERE, "icon.png")
ICO = os.path.join(HERE, "icon.ico")
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main():
    if not os.path.exists(PNG):
        if os.path.exists(ICO):
            print("使用現有的 icon.ico")
            return 0
        print("找不到 icon.png 或 icon.ico，將使用預設圖示")
        return 0

    # icon.ico 比 icon.png 新，代表已轉換過，不用重做
    if os.path.exists(ICO) and os.path.getmtime(ICO) >= os.path.getmtime(PNG):
        print("icon.ico 已是最新")
        return 0

    im = Image.open(PNG).convert("RGBA")
    # 非正方形的圖：置中補成正方形（透明背景），避免被拉長變形
    if im.width != im.height:
        side = max(im.size)
        sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        sq.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
        im = sq
    if im.width < 256:
        print(f"提醒：icon.png 只有 {im.width}×{im.height}，建議至少 256×256，放大後可能較模糊")
    im = im.resize((256, 256), Image.LANCZOS)
    im.save(ICO, format="ICO", sizes=SIZES)
    print("已產生 icon.ico")
    return 0


if __name__ == "__main__":
    sys.exit(main())
