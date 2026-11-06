"""Testes de geração manual com dados inteiramente sintéticos."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf as pdf

from manual_export import ManualExportErro, exportar
from manual_pdf import inspecionar


class ManualExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.source = self.folder/'original.pdf'
        self.output = self.folder/'resultado.pdf'
        with pdf.open() as d:
            for n in range(3):
                p=d.new_page(width=400+n*20,height=500+n*20)
                p.insert_text((45,75),f'PRIVADO PAGINA {n+1}')
                p.insert_text((45,170),f'VISIVEL PAGINA {n+1}')
            annotation=d[0].add_rect_annot(pdf.Rect(300,180,340,210))
            annotation.set_colors(stroke=(1,0,0));annotation.set_border(width=2);annotation.update()
            d[2].set_cropbox(pdf.Rect(20,30,400,500))
            d.set_metadata({'title':'Título sintético','author':'Autor sintético'})
            d.embfile_add('anexo.txt',b'ANEXO SINTETICO PRIVADO')
            d.save(self.source)
        self.original=self.source.read_bytes()
        self.info=inspecionar(self.source)
        self.snapshot={'origem':str(self.source),'sha256_origem':self.info['sha256'],
                       'destino':str(self.output),'excluidas':[1],
                       'marcas':{0:[{'rect':(42,55,190,85),'cor':'preto'}],
                                 2:[{'rect':(25,25,160,58),'cor':'vermelho_escuro'}]},
                       'aviso':{'pagina':0,'rect':(20,300,380,360)},
                       'destinatario':'Equipe de teste','instante':'2026-11-06T10:30:00-03:00','dpi':200}

    def test_multiplas_paginas_excluidas_e_corte(self):
        result=exportar(self.snapshot)
        self.assertEqual(result['paginas_originais'],[0,2])
        self.assertEqual(result['sha256_saida'],hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertEqual(self.source.read_bytes(),self.original)
        self.assertEqual({p.name for p in self.folder.iterdir()},{self.source.name,self.output.name})
        with pdf.open(self.output) as d, pdf.open(self.source) as original:
            self.assertEqual(len(d),2)
            self.assertEqual(d.embfile_count(),0)
            for i,page in enumerate(d):
                self.assertFalse(page.get_text());self.assertFalse(page.get_fonts());self.assertFalse(page.get_links())
                self.assertEqual(len(page.get_images()),1)
                self.assertAlmostEqual(page.rect.width,self.info['paginas'][[0,2][i]]['largura'],places=2)
                self.assertAlmostEqual(page.rect.height,self.info['paginas'][[0,2][i]]['altura'],places=2)
            pix=pdf.Pixmap(d,d[0].get_images()[0][0]);scale=200/72
            self.assertEqual(pix.pixel(int(70*scale),int(70*scale)),(0,0,0))
            antes=original[0].get_pixmap(dpi=200,colorspace=pdf.csRGB,alpha=False)
            y0,y1=int(155*scale),int(215*scale)
            self.assertEqual(antes.samples[y0*antes.stride:y1*antes.stride],pix.samples[y0*pix.stride:y1*pix.stride])
            pix2=pdf.Pixmap(d,d[1].get_images()[0][0])
            self.assertEqual(pix2.pixel(int(50*scale),int(40*scale)),(128,0,0))

    def test_cores_sobreposicoes_e_aviso_sobre_tarjas(self):
        self.snapshot['excluidas']=[1,2]
        self.snapshot['marcas']={0:[
            {'rect':(40,45,320,130),'cor':'preto'},
            {'rect':(50,55,310,120),'cor':'vermelho_escuro'},
            {'rect':(60,65,300,110),'cor':'cinza_escuro'},
            {'rect':(70,75,290,100),'cor':'branco'},
            {'rect':(20,300,380,375),'cor':'preto'}]}
        self.snapshot['aviso']={'pagina':0,'rect':(20,300,380,360)}
        exportar(self.snapshot)
        with pdf.open(self.output) as d:
            pix=pdf.Pixmap(d,d[0].get_images()[0][0]);s=200/72
            for x,y,rgb in [(45,50,(0,0,0)),(55,60,(128,0,0)),(65,70,(64,64,64)),(80,80,(255,255,255))]:
                self.assertEqual(pix.pixel(int(x*s),int(y*s)),rgb)
            self.assertEqual(pix.pixel(int(40*s),int(370*s)),(0,0,0))
            self.assertEqual(pix.pixel(int(25*s),int(302*s)),(255,255,255))

    def test_aviso_em_area_ocupada_sem_exigir_tarjas(self):
        self.snapshot['excluidas']=[1,2];self.snapshot['marcas']={}
        self.snapshot['aviso']={'pagina':0,'rect':(20,130,380,200)}
        exportar(self.snapshot)
        with pdf.open(self.output) as d:
            pix=pdf.Pixmap(d,d[0].get_images()[0][0]);s=200/72
            self.assertEqual(pix.pixel(int(45*s),int(170*s)),(255,255,255))

    def test_aviso_em_pagina_cortada_com_coordenadas_fracionarias(self):
        self.snapshot['excluidas']=[0,1]
        self.snapshot['marcas']={2:[{'rect':(20.2,250.3,360.1,340.7),'cor':'preto'}]}
        self.snapshot['aviso']={'pagina':2,'rect':(25.2,260.3,350.1,330.7)}
        self.snapshot['dpi']=300
        result=exportar(self.snapshot)
        self.assertEqual(result['paginas_originais'],[2])
        with pdf.open(self.output) as d:
            pix=pdf.Pixmap(d,d[0].get_images()[0][0]);s=300/72
            self.assertEqual(pix.pixel(int(22*s),int(255*s)),(0,0,0))
            self.assertEqual(pix.pixel(int(30*s),int(265*s)),(255,255,255))

    def test_mesma_selecao_gera_duas_copias_distintas(self):
        import copy
        anterior=copy.deepcopy(self.snapshot)
        primeiro=exportar(self.snapshot)
        self.assertEqual(self.snapshot,anterior)
        outra=dict(self.snapshot);outra['destino']=str(self.folder/'segunda.pdf')
        segundo=exportar(outra)
        self.assertEqual(primeiro['paginas_originais'],segundo['paginas_originais'])
        self.assertTrue(self.output.exists());self.assertTrue(Path(segundo['destino']).exists())
        self.assertEqual(self.source.read_bytes(),self.original)

    def test_colisao_e_original_nunca_sobrescritos(self):
        self.output.write_bytes(b'existente')
        with self.assertRaises(ManualExportErro):exportar(self.snapshot)
        self.assertEqual(self.output.read_bytes(),b'existente')
        self.snapshot['destino']=str(self.source)
        with self.assertRaises(ManualExportErro):exportar(self.snapshot)
        self.assertEqual(self.source.read_bytes(),self.original)

    def test_link_dangling_e_recusado(self):
        self.output.symlink_to(self.folder/'ausente.pdf')
        with self.assertRaises(ManualExportErro):exportar(self.snapshot)
        self.assertTrue(self.output.is_symlink())

    def test_fonte_alterada_antes_e_durante_geracao(self):
        self.source.write_bytes(self.original+b' ')
        with self.assertRaises(ManualExportErro):exportar(self.snapshot)
        self.assertFalse(self.output.exists())
        self.source.write_bytes(self.original)
        with patch('manual_export._ler',side_effect=[self.original,self.original+b' ']):
            with self.assertRaises(ManualExportErro):exportar(self.snapshot)
        self.assertFalse(self.output.exists())
        self.assertEqual({p.name for p in self.folder.iterdir()},{self.source.name})

    def test_erro_de_verificacao_nao_publica_temporario(self):
        with patch('manual_export._verificar_saida',side_effect=ManualExportErro('falha')):
            with self.assertRaises(ManualExportErro):exportar(self.snapshot)
        self.assertFalse(self.output.exists())
        self.assertEqual({p.name for p in self.folder.iterdir()},{self.source.name})

    def test_falha_limpeza_apos_publicacao_mantem_sucesso(self):
        with patch('manual_export.os.unlink',side_effect=PermissionError('bloqueado')):
            resultado=exportar(self.snapshot)
        self.assertTrue(resultado['limpeza_pendente'])
        self.assertTrue(self.output.exists())
        temporarios=list(self.folder.glob('.ocultar-*.pdf'))
        self.assertEqual(len(temporarios),1)
        self.assertEqual(temporarios[0].read_bytes(),self.output.read_bytes())
        with pdf.open(temporarios[0]) as documento:
            self.assertEqual(documento.embfile_count(),0)
            for pagina in documento:
                self.assertFalse(pagina.get_text())
                self.assertFalse(pagina.get_fonts())
        self.assertNotIn(b'ANEXO SINTETICO PRIVADO',temporarios[0].read_bytes())

    def test_falha_limpeza_nao_mascara_erro_anterior(self):
        with patch('manual_export._verificar_saida',side_effect=ManualExportErro('falha original')):
            with patch('manual_export.os.unlink',side_effect=PermissionError('bloqueado')):
                with self.assertRaisesRegex(ManualExportErro,'falha original'):
                    exportar(self.snapshot)
        self.assertFalse(self.output.exists())

    def test_arquivo_alterado_antes_verificacao_e_recusado(self):
        from manual_export import _verificar_saida
        def contaminar(caminho, esperadas):
            with pdf.open(caminho) as d:
                d[0].insert_text((30,250),'TEXTO INESPERADO')
                d.saveIncr()
            _verificar_saida(caminho,esperadas)
        with patch('manual_export._verificar_saida',side_effect=contaminar):
            with self.assertRaises(ManualExportErro):exportar(self.snapshot)
        self.assertFalse(self.output.exists())
        self.assertEqual({p.name for p in self.folder.iterdir()},{self.source.name})

    def test_colisao_na_publicacao_preserva_existente(self):
        def colidir(origem,destino):
            Path(destino).write_bytes(b'OUTRO PROCESSO')
            raise FileExistsError
        with patch('manual_export.os.link',side_effect=colidir):
            with self.assertRaises(ManualExportErro):exportar(self.snapshot)
        self.assertEqual(self.output.read_bytes(),b'OUTRO PROCESSO')
        self.assertEqual({p.name for p in self.folder.iterdir()},{self.source.name,self.output.name})

    def test_snapshot_invalido_recusado(self):
        cases=[('excluidas',[0,1,2]),('excluidas',[1,1]),('excluidas',[True]),
               ('marcas',{0:[{'rect':(0,0,float('nan'),3),'cor':'preto'}]}),
               ('marcas',{0:[{'rect':(-1,0,10,10),'cor':'preto'}]}),
               ('marcas',{0:[{'rect':(0,0,10,10),'cor':'outro'}]}),
               ('aviso',{'pagina':1,'rect':(20,300,380,360)}),
               ('aviso',{'pagina':0,'rect':(20,300,25,305)}),
               ('destinatario',''),('dpi',True)]
        for key,value in cases:
            with self.subTest(key=key,value=value):
                altered=dict(self.snapshot);altered[key]=value
                with self.assertRaises(ManualExportErro):exportar(altered)
                self.assertFalse(self.output.exists())

    def test_aviso_que_nao_cabe_nao_publica(self):
        self.snapshot['aviso']={'pagina':0,'rect':(20,300,100,320)}
        with self.assertRaises(ManualExportErro):exportar(self.snapshot)
        self.assertFalse(self.output.exists())


if __name__=='__main__':unittest.main()
