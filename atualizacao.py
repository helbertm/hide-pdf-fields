"""Consulta e prepara atualizações de releases oficiais; não acessa PDFs."""
from __future__ import annotations
import hashlib
import json
import re
import tempfile
import urllib.request
from pathlib import Path

VERSAO = '1.3.0'
API = 'https://api.github.com/repos/helbertm/hide-pdf-fields/releases/latest'
ARQUIVOS = {'hide-pdf-fields-windows.zip': 10_485_760, 'install.ps1': 1_048_576}
HEADERS = {'User-Agent': 'hide-pdf-fields-updater', 'Accept': 'application/vnd.github+json'}


def consultar():
    request=urllib.request.Request(API,headers=HEADERS)
    with urllib.request.urlopen(request,timeout=12) as response:
        data=json.loads(response.read(1_000_001))
    version=data.get('tag_name','')
    if data.get('draft') or data.get('prerelease') or not re.fullmatch(r'v\d+\.\d+\.\d+',version):
        raise ValueError('Release inválida')
    if tuple(map(int,version[1:].split('.'))) <= tuple(map(int,VERSAO.split('.'))):return None
    assets={}
    for name,limit in ARQUIVOS.items():
        found=[a for a in data.get('assets',[]) if a.get('name')==name and a.get('state')=='uploaded']
        if len(found)!=1:raise ValueError('Pacote de atualização incompleto')
        asset=found[0]; digest=asset.get('digest',''); size=asset.get('size')
        expected=f'https://github.com/helbertm/hide-pdf-fields/releases/download/{version}/{name}'
        if asset.get('browser_download_url')!=expected or not re.fullmatch(r'sha256:[a-f0-9]{64}',digest) or not isinstance(size,int) or not 0<size<=limit:
            raise ValueError('Metadados de atualização inválidos')
        assets[name]={'url':expected,'sha256':digest[7:],'size':size}
    return {'version':version,'assets':assets}


def baixar(release, progresso):
    folder=Path(tempfile.mkdtemp(prefix='ocultar-dados-update-'))
    total=sum(a['size'] for a in release['assets'].values()); done=0
    try:
        for name,asset in release['assets'].items():
            h=hashlib.sha256(); count=0
            request=urllib.request.Request(asset['url'],headers={'User-Agent':HEADERS['User-Agent']})
            with urllib.request.urlopen(request,timeout=30) as response, (folder/name).open('xb') as out:
                while chunk:=response.read(65536):
                    count+=len(chunk)
                    if count>asset['size']:raise ValueError('Download excedeu o tamanho esperado')
                    out.write(chunk);h.update(chunk);progresso(done+count,total)
            if count!=asset['size'] or h.hexdigest()!=asset['sha256']:raise ValueError('Integridade da atualização não confirmada')
            done+=count
        return folder
    except BaseException:
        import shutil
        shutil.rmtree(folder,ignore_errors=True)
        raise
