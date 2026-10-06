# 第三方元件授權聲明

BlurSorter 本身以 GPL-3.0-or-later 授權釋出（見 [LICENSE](LICENSE)）。
本專案使用或隨附下列第三方元件，各自依其原始授權條款提供：

| 元件 | 用途 | 授權 |
|---|---|---|
| [YuNet 人臉偵測模型](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)（`models/face_detection_yunet_2023mar.onnx`） | 偵測照片中的人臉與五官位置 | MIT License |
| [OpenCV](https://opencv.org/)（opencv-python-headless） | 影像讀取與清晰度計算 | Apache License 2.0 |
| [NumPy](https://numpy.org/) | 數值運算 | BSD 3-Clause License |
| [Pillow](https://python-pillow.org/) | 影像讀取、EXIF、預覽 | MIT-CMU (HPND) License |
| [PyInstaller](https://pyinstaller.org/)（僅打包時使用） | 打包成 exe | GPL-2.0 with bootloader exception |

## YuNet 模型 MIT 授權全文

```
MIT License

Copyright (c) 2020 Shiqi Yu <shiqi.yu@gmail.com>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## 程式圖示

`icon.png` / `icon.ico` 為作者 Dorigo 的個人形象圖，著作權屬於作者，**不包含在 GPL 授權範圍內**。
如果你要修改並重新發布本程式，請換成你自己的圖示（替換 `icon.png` 後重新打包即可）。

## 說明文件截圖

`docs/` 內截圖使用的範例照片，是由作者 Dorigo 的個人形象插圖加工而成（清楚、失焦、手震等版本），
著作權屬於作者，與程式圖示相同，**不包含在 GPL 授權範圍內**。
