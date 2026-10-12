# 妙妙扫码（MiaoMiao Scanner）

一个运行在 Windows 电脑上的离线扫码桌面程序，不是微信小程序。图片和摄像头帧只在本机处理，不上传网络。

![平台](https://img.shields.io/badge/platform-Windows-0078D4)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB)
![License](https://img.shields.io/badge/license-MIT-green)

## 功能

- 打开 PNG/JPG/BMP/WEBP 图片，一次识别图片中的多个码
- 调用电脑摄像头实时扫描
- 基于 ZXing-C++ 离线识别 QR Code、Data Matrix、Aztec、PDF417、MaxiCode、Code 128、EAN/UPC 等常见码制
- 识别历史去重、复制全部结果、导出 UTF-8 BOM CSV
- 提供 Python 源码、运行脚本和 Windows EXE 封装脚本

## 直接使用程序

仓库中的 [`dist/MiaoMiaoScanner.exe`](dist/MiaoMiaoScanner.exe) 是已经封装好的 Windows 程序，下载后双击即可运行，不需要安装 Python。

## 从源码运行

1. 安装 Python 3.10 或更新版本。
2. 双击 `install_windows.bat`，等待依赖安装完成。
3. 双击 `run_windows.bat` 启动源码版。

首次安装需要联网下载依赖；安装完成后，识别功能本身完全离线。

## 重新封装 EXE

双击 `build_windows.bat`，生成 `dist\MiaoMiaoScanner.exe`。GitHub Actions 也会在推送 `v*` 标签时自动构建并上传 EXE Artifact。

## 开发者启动

```powershell
.venv\Scripts\activate
python main.py
python -m unittest discover -s tests -v
```

核心识别适配在 `scanner/decoder.py`，界面在 `scanner/app.py`。如果没有安装 `zxing-cpp`，程序会自动回退到 OpenCV 的 QR/一维码识别器，但建议按 requirements 安装完整离线多码引擎。

## 项目结构

```text
scanner/                 界面和识别核心
tests/                   单元测试
dist/MiaoMiaoScanner.exe 已封装程序
main.py                  Python 入口
install_windows.bat      安装依赖
run_windows.bat          源码运行
build_windows.bat        PyInstaller 封装
```
