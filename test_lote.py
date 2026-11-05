import tempfile
from functools import partial
from datetime import datetime
import unittest
from pathlib import Path
import pymupdf as pdf
from test_tarjar import fixture
from tarjar import redact, Recusado, SemTarjas
from lote import descobrir, processar_arquivo, processar_lote, comparar, Resultado, nome_saida
processar_arquivo = partial(processar_arquivo,destinatario='Equipe')
processar_lote = partial(processar_lote,destinatario='Equipe')


class LoteTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.input=self.root/'entrada';self.input.mkdir()
        self.output=self.root/'saida'

    def test_somente_pdf_sem_subpastas(self):
        fixture(self.input/'A.PDF');fixture(self.input/'b.pdf','nota')
        for name in ['x.png','x.jpg','x.docx','x.zip','x.txt']:(self.input/name).write_bytes(b'nada')
        sub=self.input/'sub';sub.mkdir();fixture(sub/'c.pdf')
        files,_=descobrir(self.input,self.output)
        self.assertEqual([p.name for p in files],['A.PDF','b.pdf'])

    def test_pasta_vazia(self):
        with self.assertRaises(Recusado):descobrir(self.input,self.output)

    def test_mesma_pasta_e_alias(self):
        fixture(self.input/'a.pdf')
        self.assertEqual(descobrir(self.input,self.input)[1],self.input.resolve())
        alias=self.root/'alias'
        try:alias.symlink_to(self.input,target_is_directory=True)
        except OSError:self.skipTest('Sistema sem suporte a symlink')
        self.assertEqual(descobrir(self.input,alias)[1],self.input.resolve())

    def test_lote_misto_preserva_sucessos(self):
        fixture(self.input/'a.pdf');(self.input/'b.pdf').write_bytes(b'pdf invalido')
        fixture(self.input/'c.PDF','nota')
        files,out=descobrir(self.input,self.output)
        results=list(processar_lote(files,out))
        self.assertEqual([r.status for r in results],['concluido','falhou','concluido'])
        self.assertEqual(len([p for p in out.iterdir() if p.suffix.lower()=='.pdf']),2)

    def test_destino_existente_nao_e_preview_depois(self):
        fixture(self.input/'a.pdf')
        first=processar_arquivo(self.input/'a.pdf',self.output)
        self.assertEqual(first.status,'concluido')
        second=processar_arquivo(self.input/'a.pdf',self.output)
        self.assertEqual(second.status,'recusado')
        self.assertIsNone(comparar(second)['depois'])

    def test_cancelamento_entre_arquivos(self):
        fixture(self.input/'a.pdf');fixture(self.input/'b.pdf')
        files,out=descobrir(self.input,self.output)
        stopped=False
        iterator=processar_lote(files,out,interromper=lambda:stopped)
        self.assertEqual(next(iterator).status,'concluido');stopped=True
        self.assertEqual(next(iterator).status,'cancelado')
        self.assertEqual(len(list(out.glob('*.pdf'))),1)

    def test_selecao_independente_e_pixels_mantidos(self):
        for name in ['a.pdf','b.pdf']:fixture(self.input/name)
        a=processar_arquivo(self.input/'a.pdf',self.output,campos=['gestora'])
        b=processar_arquivo(self.input/'b.pdf',self.output,campos=['matriz_razao_social'])
        self.assertEqual(a.status,'concluido');self.assertEqual(b.status,'concluido')
        with pdf.open(self.input/'a.pdf') as d:
            original=d[0].get_pixmap(dpi=300,colorspace=pdf.csRGB,alpha=False)
        for result,hidden,kept in [(a,(465,28.4,566.8,40.3),(98,85,488,96.4)),
                                   (b,(98,85,488,96.4),(465,28.4,566.8,40.3))]:
            with pdf.open(result.destino) as d:
                pix=pdf.Pixmap(d,d[0].get_images()[0][0])
                from tarjar import pixel_box
                box=pixel_box(pdf.Rect(kept),300,pix.width,pix.height)
                for y in range(box.y0,box.y1):
                    i=y*pix.stride+box.x0*3;j=y*pix.stride+box.x1*3
                    self.assertEqual(pix.samples_mv[i:j],original.samples_mv[i:j])
                box=pixel_box(pdf.Rect(hidden),300,pix.width,pix.height)
                self.assertEqual(pix.pixel(box.x0+2,box.y0+2),(0,0,0))

    def test_vazio_e_observacao_ausente_nao_geram_pdf(self):
        src=self.input/'a.pdf';fixture(src,observation=False)
        for campos in [[],['observacoes_finais']]:
            r=processar_arquivo(src,self.output,campos=campos)
            self.assertEqual(r.status,'ignorado');self.assertFalse(r.destino)
        self.assertFalse(self.output.exists())

    def test_ids_invalidos(self):
        src=self.input/'a.pdf';fixture(src)
        for campos in [['inventado'],['qr_code'],'gestora',[123]]:
            with self.assertRaises(Recusado):redact(src,self.output/'x.pdf',campos=campos)

    def test_imagem_renomeada_para_pdf_e_rejeitada(self):
        pix=pdf.Pixmap(pdf.csRGB,pdf.IRect(0,0,20,20),False);pix.clear_with(255)
        (self.input/'imagem.pdf').write_bytes(pix.tobytes('png'))
        r=processar_arquivo(self.input/'imagem.pdf',self.output)
        self.assertNotEqual(r.status,'concluido');self.assertFalse(self.output.exists())
        self.assertIsNone(comparar(r)['antes'])

    def test_extensoes_nao_pdf_recusadas_mesmo_com_conteudo_pdf(self):
        original=self.input/'a.pdf';fixture(original)
        for suffix in ['.png','.zip','.docx','.jpg']:
            path=self.input/('entrada'+suffix);path.write_bytes(original.read_bytes())
            self.assertEqual(processar_arquivo(path,self.output).status,'recusado')
            with self.assertRaises(Recusado):redact(path,self.output/'out.pdf')

    def test_nome_limpo_e_data(self):
        instante=datetime(2026,11,5,10,30)
        self.assertEqual(nome_saida('Nota 123.pdf','João da Silva',instante),'Joao_da_Silva-051126-Nota_123.pdf')
        self.assertEqual(nome_saida('a.pdf','../José / & Cia!',instante),'Jose___Cia-051126-a.pdf')
        self.assertEqual(nome_saida('Nota Açúcar nº 42.PDF','José & Cia',instante),'Jose__Cia-051126-Nota_Acucar_no_42.pdf')
        with self.assertRaises(Recusado):nome_saida('!!!.pdf','Equipe',instante)
        for nome in ['!!!','///']:
            with self.assertRaises(Recusado):nome_saida('a.pdf',nome,instante)

    def test_mesma_pasta_snapshot_e_colisao(self):
        src=self.input/'a.pdf';fixture(src);original=src.read_bytes()
        files,out=descobrir(self.input)
        results=list(processar_lote(files,out,destinatario='João da Silva'))
        self.assertEqual(len(results),1);self.assertEqual(results[0].status,'concluido')
        output=Path(results[0].destino);self.assertEqual(output.parent.resolve(),self.input.resolve())
        self.assertEqual(src.read_bytes(),original)
        before=output.read_bytes()
        self.assertEqual(processar_arquivo(src,out,destinatario='Joao da Silva').status,'recusado')
        self.assertEqual(output.read_bytes(),before)
        self.assertEqual(len(list(self.input.glob('*.pdf'))),2)

    def test_preview_detecta_arquivo_modificado(self):
        src=self.input/'a.pdf';fixture(src)
        result=processar_arquivo(src,self.output)
        self.assertTrue(comparar(result)['depois'].startswith(b'\x89PNG'))
        Path(result.destino).write_bytes(b'modificado')
        preview=comparar(result)
        self.assertIsNone(preview['depois']);self.assertIn('alterado',preview['depois_erro'])


if __name__=='__main__':unittest.main()
