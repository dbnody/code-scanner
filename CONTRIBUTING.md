# 参与贡献

感谢提交 Issue 或 Pull Request。

## 本地开发

1. 运行 `install_windows.bat` 安装依赖。
2. 使用 `run_windows.bat` 启动程序。
3. 提交前运行：

   ```powershell
   .venv\Scripts\python.exe -m unittest discover -s tests -v
   .venv\Scripts\python.exe -m compileall -q .
   ```

请保持离线识别逻辑，不在扫码流程中上传图片或识别结果。
