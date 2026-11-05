import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import atualizacao as a

class Response(io.BytesIO):
    def __enter__(self):return self
    def __exit__(self,*_):self.close()

def fixture():
    contents={'install.ps1':b'script', 'hide-pdf-fields-windows.zip':b'zip'}
    assets=[]
    for name,data in contents.items():
        assets.append({'name':name,'state':'uploaded','digest':'sha256:'+hashlib.sha256(data).hexdigest(),'size':len(data),'browser_download_url':f'https://github.com/helbertm/hide-pdf-fields/releases/download/v9.0.0/{name}'})
    return {'tag_name':'v9.0.0','assets':assets},contents

class UpdateTest(unittest.TestCase):
    def test_valida_metadados_e_rejeita_duplicatas(self):
        data,_=fixture()
        with patch.object(a.urllib.request,'urlopen',side_effect=lambda *x,**y:Response(json.dumps(data).encode())):
            self.assertEqual(a.consultar()['version'],'v9.0.0')
            data['assets'].append(data['assets'][0])
            with self.assertRaises(ValueError):a.consultar()

    def test_baixa_e_confere_ambos_arquivos(self):
        data,contents=fixture()
        def open_url(request,**_):
            if request.full_url==a.API:return Response(json.dumps(data).encode())
            return Response(contents[request.full_url.rsplit('/',1)[1]])
        with tempfile.TemporaryDirectory() as tmp, patch.object(a.tempfile,'tempdir',tmp), patch.object(a.urllib.request,'urlopen',side_effect=open_url):
            release=a.consultar(); progress=[]
            folder=a.baixar(release,lambda x,y:progress.append((x,y)))
            self.assertEqual((folder/'install.ps1').read_bytes(),b'script')
            self.assertEqual(progress[-1][0],progress[-1][1])
            contents['install.ps1']=b'other!'
            with self.assertRaises(ValueError):a.baixar(release,lambda *_:None)
            self.assertEqual(len(list(Path(tmp).iterdir())),1)
