"""Build an allowlisted release archive and SHA-256 manifest."""
from pathlib import Path
import hashlib
import zipfile
root=Path(__file__).resolve().parents[1]
files=['assets/icon.png','assets/icon.ico','interface.py','manual_pdf.py','manual_interface.py','manual_export.py','atualizacao.py','tarjar.py','lote.py','requirements-win.lock','README.md','USO.md','THIRD_PARTY.md','scripts/smoke.py']
out=root/'dist';out.mkdir(exist_ok=True)
archive=out/'hide-pdf-fields-windows.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for name in files:
        info=zipfile.ZipInfo(name,date_time=(2026,1,1,0,0,0))
        info.external_attr=0o100644<<16
        info.compress_type=zipfile.ZIP_DEFLATED
        z.writestr(info,(root/name).read_bytes())
(out/'SHA256SUMS.txt').write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n')
print(archive.name)
