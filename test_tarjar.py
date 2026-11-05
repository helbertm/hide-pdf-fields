"""Testes com documentos sintéticos; não contêm dados dos PDFs reais."""
import tempfile
import unittest
from pathlib import Path
import pymupdf as pdf
from tarjar import PEDIDO, NOTA, Recusado, plan, redact, pixel_box


def fixture(path, kind='pedido', observation=True):
    d = pdf.open()
    p = d.new_page(width=595, height=842)
    font = pdf.Font('helv')
    def text(x,y,s,size=8):
        p.insert_text((x,y+font.ascender*size), s, fontsize=size)
    for label, count, x, y in PEDIDO if kind == 'pedido' else NOTA:
        for i in range(count):
            text(x,y+i*56.7,label)
    if kind == 'pedido':
        text(272.8,296.1,'PAGAMENTO')
        text(357.3,511.3,'VALOR TOTAL DO PEDIDO:')
        text(36.9,528.5,'Faturamento na entrega?')
        text(470,30,'SEGREDO',6)
        text(100,88,'NOME CONFIDENCIAL',6)
        if observation:
            text(28,550,'OBSERVACAO PRIVADA LINHA 1')
            text(28,570,'OBSERVACAO PRIVADA LINHA 2')
    else:
        pix = pdf.Pixmap(pdf.csRGB, pdf.IRect(0,0,50,50), False)
        pix.clear_with(0)
        p.insert_image(pdf.Rect(503,89,574,160), pixmap=pix)
        text(100,250,'CLIENTE CONFIDENCIAL')
    d.set_metadata({'author':'AUTOR PRIVADO'})
    d.embfile_add('segredo.txt', b'ANEXO PRIVADO')
    d.save(path)
    d.close()


class TarjasTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.src, self.out = self.root/'in.pdf', self.root/'out.pdf'

    def mutate(self, action):
        with pdf.open(self.src) as d:
            action(d)
            data = d.tobytes()
        self.src.write_bytes(data)

    def test_pedido_observacao_multilinha_e_pixels_externos(self):
        fixture(self.src)
        original = self.src.read_bytes()
        with pdf.open(self.src) as d:
            _, masks, _ = plan(d)
            before = d[0].get_pixmap(dpi=200, colorspace=pdf.csRGB, alpha=False)
        result = redact(self.src, self.out, dpi=200)
        self.assertIn('observacoes_finais', result['regioes'])
        self.assertEqual(original,self.src.read_bytes())
        with pdf.open(self.out) as d:
            self.assertFalse(d[0].get_text())
            self.assertEqual(d.embfile_count(),0)
            after = pdf.Pixmap(d,d[0].get_images()[0][0])
            # Faixa financeira fora das máscaras deve permanecer byte a byte igual.
            y0,y1 = int(290*200/72),int(525*200/72)
            self.assertEqual(before.samples[y0*before.stride:y1*before.stride],
                             after.samples[y0*after.stride:y1*after.stride])
            for y in (550,570):
                self.assertEqual(after.pixel(int(40*200/72),int(y*200/72)),(0,0,0))

    def test_pedido_sem_observacao(self):
        fixture(self.src,observation=False)
        self.assertNotIn('observacoes_finais',redact(self.src,self.out)['regioes'])

    def test_nota(self):
        fixture(self.src,'nota')
        self.assertEqual(redact(self.src,self.out)['tipo'],'nota')

    def test_nao_sobrescreve(self):
        fixture(self.src)
        self.out.write_bytes(b'EXISTENTE')
        with self.assertRaises(Recusado): redact(self.src,self.out)
        self.assertEqual(self.out.read_bytes(),b'EXISTENTE')
        with self.assertRaises(Recusado): redact(self.src,self.src)

    def test_pagina_extra(self):
        fixture(self.src)
        self.mutate(lambda d:d.new_page())
        with self.assertRaises(Recusado): redact(self.src,self.out)
        self.assertFalse(self.out.exists())

    def test_rotacao(self):
        fixture(self.src)
        self.mutate(lambda d:d[0].set_rotation(90))
        with self.assertRaises(Recusado): redact(self.src,self.out)

    def test_ancora_duplicada(self):
        fixture(self.src)
        self.mutate(lambda d:d[0].insert_text((100,700),'GESTORA:'))
        with self.assertRaises(Recusado): redact(self.src,self.out)

    def test_ancora_ausente(self):
        fixture(self.src)
        def remove(d):
            p=d[0]
            p.add_redact_annot(p.search_for('GESTORA:')[0])
            p.apply_redactions()
        self.mutate(remove)
        with self.assertRaises(Recusado): redact(self.src,self.out)

    def test_layout_deslocado(self):
        fixture(self.src)
        def move(d):
            p=d[0]
            p.add_redact_annot(p.search_for('GESTORA:')[0]);p.apply_redactions()
            p.insert_text((427,80),'GESTORA:')
        self.mutate(move)
        with self.assertRaises(Recusado): redact(self.src,self.out)

    def test_sem_texto(self):
        with pdf.open() as d:
            d.new_page(width=595,height=842);d.save(self.src)
        with self.assertRaises(Recusado): redact(self.src,self.out)

    def test_tipo_incorreto(self):
        fixture(self.src)
        with self.assertRaises(Recusado): redact(self.src,self.out,'nota')

    def test_anotacao(self):
        fixture(self.src)
        self.mutate(lambda d:d[0].add_text_annot((50,50),'PRIVADO'))
        with self.assertRaises(Recusado): redact(self.src,self.out)


if __name__ == '__main__':
    unittest.main()
