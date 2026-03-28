"""Build standalone executable using PyInstaller."""

import PyInstaller.__main__
import sys

PyInstaller.__main__.run([
    "pos_transform.py",
    "--onefile",
    "--windowed",
    "--name=DJITerraPOSTransformation",
    "--noconfirm",
    "--clean",
])
