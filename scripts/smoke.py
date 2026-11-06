"""Check the installed interpreter, PDF library and native Tk runtime."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pymupdf
import tkinter
import manual_pdf
import manual_interface
import interface
import lote
import tarjar
root = tkinter.Tk()
root.withdraw()
root.update()
root.destroy()
print('PDF and Tk runtime: OK')
