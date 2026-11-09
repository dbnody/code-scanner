# 离线扫码（Code Scanner）

一个运行在 Windows 电脑上的离线扫码桌面程序，不是微信小程序。图片和摄像头帧只在本机处理，不上传网络。

## 功能

- 打开 PNG/JPG/BMP/WEBP 图片，一次识别图片中的多个码
- 调用电脑摄像头实时扫描
- 基于 ZXing-C++ 离线识别 QR Code、Data Matrix、Aztec、PDF417、MaxiCode、Code 128、EAN/UPC 等常见码制
- **碎片二维码拼接**：把被打乱的二维码碎片重新拼回整图并自动识别
- 识别历史去重、复制全部结果、导出 UTF-8 BOM CSV
- 提供 Python 源码、运行脚本和 Windows EXE 封装脚本

## 碎片二维码拼接

二维码被切成多块、顺序打乱后，点击工具栏的「拼接碎片二维码」，选择存放碎片的文件夹即可。

- 碎片需来自同一张图、尺寸一致、方向一致（不做旋转校正），能排成矩形网格
- 拼接按接缝像素连续性求解，并用「外圈应为白色静区」剪枝；拼好后自动解码，解码通过才算成功
- 支持 4～25 块（如 2×2、3×3、4×4、5×5）的常见切分，通常几秒内完成
- 若切分线恰好落在二维码模块边界上，接缝两侧像素不相等，可能拼不出唯一解；此时界面会显示误差最小的拼接图并提示检查碎片

## 使用

1. 安装 Python 3.10 或更新版本。
2. 双击 `install_windows.bat`，等待依赖安装完成。
3. 双击 `run_windows.bat` 启动源码版。
4. 需要封装程序时双击 `build_windows.bat`，生成 `dist\CodeScanner.exe`。

首次安装需要联网下载依赖；安装完成后，识别功能本身完全离线。若部署到无 Python 的电脑，只需复制 `dist\CodeScanner.exe`。

## 开发者启动

```powershell
.venv\Scripts\activate
python main.py
```

核心识别适配在 `scanner/decoder.py`，碎片拼接在 `scanner/stitcher.py`，界面在 `scanner/app.py`。如果没有安装 `zxing-cpp`，程序会自动回退到 OpenCV 的 QR/一维码识别器，但建议按 requirements 安装完整离线多码引擎。

## 测试

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`tests/test_stitcher.py` 会用 zxing-cpp 现场生成二维码、切成碎片、打乱顺序，再验证能拼回并识别出原文。
