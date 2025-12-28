@echo off
setlocal
python -m pip install -r requirements.txt
pyinstaller build\xyza.spec
