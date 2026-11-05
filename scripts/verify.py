"""Stable local/CI verification command; test fixtures contain synthetic data."""
from pathlib import Path
import subprocess
import sys
root=Path(__file__).resolve().parents[1]
subprocess.run([sys.executable,'-m','unittest','discover','-s',str(root),'-v'],cwd=root,check=True)
for path in root.rglob('*'):
    if not path.is_file() or any(p in {'.git','.venv','__pycache__','dist','build'} for p in path.parts):continue
    if path.suffix.lower() in {'.pdf','.png','.ico','.jpg','.jpeg','.zip'} and path.relative_to(root).as_posix() not in {'assets/icon.png','assets/icon.ico'}:
        raise SystemExit('Unexpected document or binary in source: '+str(path.relative_to(root)))
    if path.suffix in {'.py','.md','.ps1','.yml','.txt','.lock'}:
        data=path.read_text(encoding='utf-8-sig')
        if any(token in data for token in ('/'+'Users/', '/'+'home/')):
            raise SystemExit('Machine-local path found in '+str(path.relative_to(root)))
print('Source surface: OK')
