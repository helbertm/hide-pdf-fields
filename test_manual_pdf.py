"""Testes sintéticos da inspeção e visualização manual, sem arquivos reais."""
import hashlib
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf as pdf

from manual_pdf import ESCALA_100, ManualPdfErro, inspecionar, renderizar, visualizar_aviso


class ManualPdfTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'arquivo.pdf'

    def criar(self):
        with pdf.open() as doc:
            doc.new_page(width=300, height=600).insert_text((30, 70), 'Conteúdo sintético')
            doc.new_page(width=400, height=300).insert_text((30, 70), 'Outra página')
            doc.save(self.path)

    def test_inspecao_e_renderizacao_por_pagina(self):
        self.criar()
        antes = self.path.read_bytes()
        info = inspecionar(self.path)
        self.assertEqual(info['total_paginas'], 2)
        self.assertEqual(info['sha256'], hashlib.sha256(antes).hexdigest())
        self.assertEqual(info['paginas'][0]['indice'], 0)
        self.assertEqual(info['paginas'][0]['largura'], 300)
        self.assertEqual(info['paginas'][1]['altura'], 300)
        for indice, (largura, altura) in enumerate(((300, 600), (400, 300))):
            imagem = renderizar(self.path, info['sha256'], indice)
            pix = pdf.Pixmap(imagem)
            self.assertEqual((pix.width, pix.height),
                             (math.ceil(largura * ESCALA_100), math.ceil(altura * ESCALA_100)))
        self.assertEqual(self.path.read_bytes(), antes)

    def test_inventario_de_recursos_sem_expor_valores(self):
        with pdf.open() as doc:
            page = doc.new_page()
            page.insert_text((30, 30), 'VALOR PRIVADO SINTETICO')
            page.insert_link({'kind': pdf.LINK_URI, 'from': pdf.Rect(30,40,100,60), 'uri': 'https://example.org'})
            page.add_text_annot((50,100), 'COMENTARIO SINTETICO')
            widget = pdf.Widget()
            widget.field_name = 'campo_sintetico'
            widget.field_type = pdf.PDF_WIDGET_TYPE_TEXT
            widget.rect = pdf.Rect(30,130,180,150)
            page.add_widget(widget)
            doc.embfile_add('anexo_sintetico.txt', b'dados')
            doc.set_toc([[1,'TITULO SINTETICO',1]])
            doc.save(self.path)
        before = self.path.read_bytes()
        info = inspecionar(self.path)
        self.assertEqual(set(info['recursos']), {'texto selecionável','links','formulários',
                                                  'anotações','anexos','marcadores'})
        self.assertNotIn('PRIVADO', repr(info))
        self.assertNotIn('example.org', repr(info))
        self.assertEqual(self.path.read_bytes(), before)

    def test_inventario_nao_inventa_recursos(self):
        with pdf.open() as doc:
            doc.new_page()
            doc.save(self.path)
        self.assertEqual(inspecionar(self.path)['recursos'], [])

    def test_inventario_reconhece_campo_de_assinatura(self):
        with pdf.open() as doc:
            page = doc.new_page()
            widget = pdf.Widget()
            widget.field_name = 'assinatura_sintetica'
            widget.field_type = pdf.PDF_WIDGET_TYPE_SIGNATURE
            widget.rect = pdf.Rect(30,30,180,50)
            page.add_widget(widget)
            doc.save(self.path)
        recursos = inspecionar(self.path)['recursos']
        self.assertIn('formulários', recursos)
        self.assertIn('assinaturas ou campos de assinatura', recursos)

    def test_rotacao_em_qualquer_pagina_recusada(self):
        self.criar()
        with pdf.open(self.path) as doc:
            doc[1].set_rotation(90)
            self.path.write_bytes(doc.tobytes())
        with self.assertRaisesRegex(ManualPdfErro, 'página 2'):
            inspecionar(self.path)

    def test_rotacao_herdada_recusada(self):
        self.criar()
        with pdf.open(self.path) as doc:
            page_xref = doc[1].xref
            parent = int(doc.xref_get_key(page_xref, 'Parent')[1].split()[0])
            doc.xref_set_key(parent, 'Rotate', '90')
            for page in doc:
                doc.xref_set_key(page.xref, 'Rotate', 'null')
            self.path.write_bytes(doc.tobytes())
        with self.assertRaisesRegex(ManualPdfErro, 'rotação'):
            inspecionar(self.path)

    def test_documento_que_exige_senha_recusado(self):
        with pdf.open() as doc:
            doc.new_page()
            doc.save(self.path, encryption=pdf.PDF_ENCRYPT_AES_256,
                     owner_pw='dono', user_pw='abrir')
        with self.assertRaisesRegex(ManualPdfErro, 'senha'):
            inspecionar(self.path)

    def test_pdf_criptografado_que_abre_sem_senha_e_aceito(self):
        with pdf.open() as doc:
            doc.new_page()
            doc.save(self.path, encryption=pdf.PDF_ENCRYPT_AES_256,
                     owner_pw='dono', user_pw='')
        self.assertEqual(inspecionar(self.path)['total_paginas'], 1)

    def test_recusa_nao_pdf_mesmo_com_extensao_pdf(self):
        pix = pdf.Pixmap(pdf.csRGB, pdf.IRect(0, 0, 10, 10), False)
        pix.clear_with(255)
        self.path.write_bytes(pix.tobytes('png'))
        with self.assertRaises(ManualPdfErro):
            inspecionar(self.path)

    def test_recusa_corrompido_e_extensao_errada(self):
        self.path.write_bytes(b'%PDF-1.7\nconteudo incompleto')
        with self.assertRaises(ManualPdfErro):
            inspecionar(self.path)
        self.criar()
        other = self.path.with_suffix('.zip')
        other.write_bytes(self.path.read_bytes())
        with self.assertRaises(ManualPdfErro):
            inspecionar(other)

    def test_pagina_muito_grande_recusada_antes_de_renderizar(self):
        with pdf.open() as doc:
            doc.new_page(width=16000, height=16000)
            doc.save(self.path)
        with self.assertRaisesRegex(ManualPdfErro, 'grande demais'):
            inspecionar(self.path)

    def test_recusa_pagina_e_hash_invalidos(self):
        self.criar()
        h = inspecionar(self.path)['sha256']
        for indice in (-1, 2, True, 0.5, '1'):
            with self.subTest(indice=indice), self.assertRaises(ManualPdfErro):
                renderizar(self.path, h, indice)
        for valor in ('', 'a'*63, None, 'g'*64):
            with self.subTest(hash=valor), self.assertRaises(ManualPdfErro):
                renderizar(self.path, valor, 0)

    def test_recusa_quando_original_muda_antes_da_renderizacao(self):
        self.criar()
        h = inspecionar(self.path)['sha256']
        self.path.write_bytes(self.path.read_bytes() + b' ')
        with self.assertRaisesRegex(ManualPdfErro, 'alterado'):
            renderizar(self.path, h, 0)

    def test_recusa_quando_original_muda_durante_a_renderizacao(self):
        self.criar()
        h = inspecionar(self.path)['sha256']
        dados = self.path.read_bytes()
        with patch('manual_pdf._ler', side_effect=[dados, dados + b' ']):
            with self.assertRaisesRegex(ManualPdfErro, 'alterado'):
                renderizar(self.path, h, 0)


class AvisoManualTest(unittest.TestCase):
    def test_aviso_completo_acentuado_e_em_memoria(self):
        result = visualizar_aviso('  João   e Márcia ', 535, 80, '2026-11-05T08:09:00-03:00')
        self.assertEqual(result['destinatario'], 'João e Márcia')
        self.assertEqual(result['texto'], 'Dados sigilosos ocultados intencionalmente. Documento gerado em 05/11/26 08:09.\nUso exclusivo de João e Márcia, gentileza não compartilhar com terceiros.')
        pix = pdf.Pixmap(result['png'])
        self.assertEqual((pix.width, pix.height),(math.ceil(535*ESCALA_100),math.ceil(80*ESCALA_100)))
        self.assertLess(min(pix.samples),200)

    def test_mesma_tipografia_e_pixels_do_aviso_existente(self):
        from datetime import datetime
        from tarjar import inserir_aviso, pixel_box
        area=pdf.Rect(30,750,565,798)
        with pdf.open() as d:
            page=d.new_page(width=595,height=842)
            original=page.get_pixmap(dpi=96,colorspace=pdf.csRGB,alpha=False)
            inserir_aviso(original,page.rect,'Equipe',96,datetime(2026,11,5,8,9),area=area)
            preview=pdf.Pixmap(visualizar_aviso('Equipe',area.width,area.height,'2026-11-05T08:09:00')['png'])
            box=pixel_box(area,96,original.width,original.height)
            self.assertEqual((preview.width,preview.height),(box.width,box.height))
            for y in range(preview.height):
                before=original.samples_mv[(box.y0+y)*original.stride+box.x0*3:(box.y0+y)*original.stride+box.x1*3]
                after=preview.samples_mv[y*preview.stride:(y+1)*preview.stride]
                self.assertEqual(before,after)

    def test_destinatario_120_e_validacoes(self):
        self.assertIn('Á'*120,visualizar_aviso('Á'*120,535,80,'2026-11-05T08:09:00')['texto'])
        for recipient in ('','A'*121,'x\ny','😀'):
            with self.subTest(recipient=recipient), self.assertRaises(ManualPdfErro):
                visualizar_aviso(recipient,535,80,'2026-11-05T08:09:00')

    def test_area_pequena_invalida_e_limites(self):
        for width,height in ((535,8),(8,20),(0,50),(-1,100),(float('nan'),100),(100000,100000)):
            with self.subTest(width=width,height=height), self.assertRaises(ManualPdfErro):
                visualizar_aviso('Equipe',width,height,'2026-11-05T08:09:00')
        with self.assertRaises(ManualPdfErro):
            visualizar_aviso('Equipe',535,80,'data inválida')


if __name__ == '__main__':
    unittest.main()
