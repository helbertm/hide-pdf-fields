"""Regressões de páginas e aviso sobre observação usando apenas dados sintéticos."""
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
import pymupdf as pdf
from test_tarjar import fixture
from tarjar import redact, Recusado, AREA_AVISO, CORES, pixel_box
from lote import processar_arquivo, comparar

class PaginasTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.src=self.folder/'pedido.pdf'
        fixture(self.src)
        with pdf.open(self.src) as doc:
            doc[0].insert_text((40,800),'SEGREDO NA ULTIMA LINHA')
            doc.new_page().insert_text((40,50),'CONTEUDO DE OUTRA PAGINA')
            data=doc.tobytes()
        self.src.write_bytes(data)

    def test_multiplas_paginas_cores_e_aviso(self):
        original=self.src.read_bytes()
        for color,(_,rgb) in CORES.items():
            with self.subTest(color=color):
                out=self.folder/(color+'.pdf')
                info=redact(self.src,out,dpi=200,destinatario='Equipe',cor=color,gerado_em=datetime(2026,11,5))
                self.assertEqual(info['paginas_descartadas'],1)
                with pdf.open(out) as doc:
                    self.assertEqual(len(doc),1)
                    page=doc[0]
                    self.assertFalse(page.get_text());self.assertFalse(page.get_fonts());self.assertFalse(doc.embfile_count())
                    pix=pdf.Pixmap(doc,page.get_images()[0][0]);scale=200/72
                    self.assertEqual(pix.pixel(int(40*scale),int(700*scale)),rgb)
                    self.assertEqual(pix.pixel(int(40*scale),pix.height-2),rgb)
                    box=pixel_box(AREA_AVISO,200,pix.width,pix.height)
                    samples=[pix.pixel(x,y) for y in range(box.y0,box.y1) for x in range(box.x0,box.x1)]
                    self.assertTrue(any(v!=rgb for v in samples),'aviso ausente')
        self.assertEqual(original,self.src.read_bytes())

    def test_multipagina_sem_observacao_selecionada_recusa(self):
        out=self.folder/'out.pdf'
        with self.assertRaises(Recusado):redact(self.src,out,campos=['gestora'],destinatario='Equipe')
        self.assertFalse(out.exists())

    def test_sem_fechamento_na_primeira_recusa(self):
        with pdf.open(self.src) as d:
            p=d[0]
            for label in ('VALOR TOTAL DO PEDIDO:','Faturamento na entrega?'):
                p.add_redact_annot(p.search_for(label)[0])
            p.apply_redactions();data=d.tobytes()
        self.src.write_bytes(data)
        with self.assertRaises(Recusado):redact(self.src,self.folder/'out.pdf')

    def test_sem_campos_e_ignorado(self):
        result=processar_arquivo(self.src,self.folder,destinatario='Equipe',campos=[])
        self.assertEqual(result.status,'ignorado')

    def test_um_marcador_de_fechamento_e_suficiente(self):
        for removed in ('VALOR TOTAL DO PEDIDO:','Faturamento na entrega?'):
            with self.subTest(removed=removed), pdf.open(self.src) as d:
                page=d[0];page.add_redact_annot(page.search_for(removed)[0]);page.apply_redactions()
                src=self.folder/('sem_total.pdf' if removed.startswith('VALOR') else 'sem_faturamento.pdf')
                src.write_bytes(d.tobytes())
                out=src.with_name('out_'+src.name)
                self.assertEqual(redact(src,out,destinatario='Equipe')['paginas_descartadas'],1)

    def test_primeira_pagina_sem_tinta_apos_fechamento(self):
        fixture(self.src,observation=False)
        with pdf.open(self.src) as d:
            d.new_page().insert_text((40,50),'CONTINUACAO PRIVADA')
            data=d.tobytes()
        self.src.write_bytes(data)
        info=redact(self.src,self.folder/'out.pdf',destinatario='Equipe')
        self.assertIn('observacoes_finais',info['regioes'])

    def test_aviso_se_ajusta_a_observacao_no_rodape(self):
        fixture(self.src,observation=False)
        with pdf.open(self.src) as d:
            page=d[0]
            for label in ('VALOR TOTAL DO PEDIDO:','Faturamento na entrega?'):
                page.add_redact_annot(page.search_for(label)[0])
            page.apply_redactions()
            page.insert_text((357.3,767),'VALOR TOTAL DO PEDIDO:',fontsize=8)
            page.insert_text((40,806),'SEGREDO AO FINAL',fontsize=8)
            d.new_page().insert_text((40,50),'CONTINUACAO')
            data=d.tobytes()
        self.src.write_bytes(data)
        self.assertEqual(redact(self.src,self.folder/'out.pdf',destinatario='Equipe')['paginas_descartadas'],1)

    def test_nota_multipagina_recusada(self):
        fixture(self.src,'nota')
        with pdf.open(self.src) as d:
            d.new_page(); data=d.tobytes()
        self.src.write_bytes(data)
        with self.assertRaises(Recusado):redact(self.src,self.folder/'out.pdf')

    def test_status_e_preview_explicitam_primeira_pagina(self):
        result=processar_arquivo(self.src,self.folder,destinatario='Equipe')
        self.assertEqual(result.status,'concluido')
        self.assertIn('1 página(s) descartada(s)',result.mensagem)
        preview=comparar(result)
        self.assertEqual(preview['paginas_origem'],2)
        self.assertTrue(preview['antes']);self.assertTrue(preview['depois'])
