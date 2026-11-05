"""Testes com documentos sintéticos; não contêm dados dos PDFs reais."""
import tempfile
import unittest
from pathlib import Path
import pymupdf as pdf
from tarjar import PEDIDO, NOTA, Recusado, plan, redact, pixel_box


def fixture(path, kind='pedido', observation=True, auth_offset=0, note_shift=(0,0)):
    d = pdf.open()
    p = d.new_page(width=595, height=842)
    font = pdf.Font('helv')
    def text(x,y,s,size=8):
        p.insert_text((x,y+font.ascender*size), s, fontsize=size)
    for label, count, x, y in PEDIDO if kind == 'pedido' else NOTA:
        for i in range(count):
            text(x+(auth_offset if label == 'Cód. de Autenticidade' else 0)+(note_shift[0] if kind == 'nota' else 0),y+i*56.7+(note_shift[1] if kind == 'nota' else 0),label,size=5.2 if label == 'Cód. de Autenticidade' else 8)
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
        text(415.4,132.8,'CODIGOSIGILOSO',6)
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

    def test_nota_rotulo_autenticidade_variacao_pequena(self):
        fixture(self.src,'nota',auth_offset=0.35)
        self.assertEqual(redact(self.src,self.out,dpi=200)['tipo'],'nota')
        with pdf.open(self.out) as d:
            pix=pdf.Pixmap(d,d[0].get_images()[0][0])
            self.assertEqual(pix.pixel(int(420*200/72),int(137*200/72)),(0,0,0))

    def test_nota_rotulo_autenticidade_deslocamento_excessivo(self):
        fixture(self.src,'nota',auth_offset=0.8)
        with self.assertRaises(Recusado):redact(self.src,self.out)
        self.assertFalse(self.out.exists())

    def test_nota_ancoras_aceitam_variacao_subponto(self):
        for n,shift in enumerate(((0.4,0.4),(-0.4,-0.4))):
            with self.subTest(shift=shift):
                fixture(self.src,'nota',note_shift=shift)
                self.assertEqual(redact(self.src,self.root/f'out_{n}.pdf',dpi=200)['tipo'],'nota')

    def test_nota_ancoras_rejeitam_variacao_maior(self):
        fixture(self.src,'nota',note_shift=(0.8,0.0))
        with self.assertRaises(Recusado):redact(self.src,self.out)
        self.assertFalse(self.out.exists())

    def test_nota_tomador_extrapolando_tarja_recusado(self):
        fixture(self.src,'nota')
        self.mutate(lambda d:d[0].insert_text((575,290),'DADO',fontsize=7))
        with self.assertRaises(Recusado):redact(self.src,self.out)
        self.assertFalse(self.out.exists())

    def test_nota_autenticidade_fora_da_tarja_recusada(self):
        fixture(self.src,'nota',auth_offset=0.35)
        self.mutate(lambda d:d[0].insert_text((485,140),'VALORLONGO',fontsize=7))
        with self.assertRaises(Recusado):redact(self.src,self.out)
        self.assertFalse(self.out.exists())

    def test_nota_imagem_na_borda_da_tarja_recusada(self):
        fixture(self.src,'nota')
        def add(d):
            pix=pdf.Pixmap(pdf.csRGB,pdf.IRect(0,0,20,20),False);pix.clear_with(0)
            d[0].insert_image(pdf.Rect(393.6,134,410,140),pixmap=pix,keep_proportion=False)
        self.mutate(add)
        with self.assertRaises(Recusado):redact(self.src,self.out,cor='branco',dpi=400)
        self.assertFalse(self.out.exists())

    def test_nota_vetor_na_borda_da_tarja_recusado(self):
        fixture(self.src,'nota')
        self.mutate(lambda d:d[0].draw_rect(pdf.Rect(393.6,134,410,140),fill=(0,0,0)))
        with self.assertRaises(Recusado):redact(self.src,self.out,cor='branco',dpi=400)
        self.assertFalse(self.out.exists())

    def test_nota_traco_na_borda_da_tarja_recusado(self):
        fixture(self.src,'nota')
        self.mutate(lambda d:d[0].draw_line((393.5,137),(405,137),color=(0,0,0),width=0.5))
        with self.assertRaises(Recusado):redact(self.src,self.out,cor='branco',dpi=400)
        self.assertFalse(self.out.exists())

    def test_nota_texto_contornado_na_borda_recusado(self):
        fixture(self.src,'nota')
        self.mutate(lambda d:d[0].insert_text((394.1,140),'I',fontsize=6,render_mode=1,border_width=2,color=(0,0,0)))
        with self.assertRaises(Recusado):redact(self.src,self.out,cor='branco',dpi=400)
        self.assertFalse(self.out.exists())

    def test_nota_uniao_miter_na_borda_recusada(self):
        fixture(self.src,'nota')
        self.mutate(lambda d:d[0].draw_polyline([(394.4,137),(400,135.9),(400,138.1)],color=(0,0,0),width=0.4,closePath=True,lineJoin=0))
        with self.assertRaises(Recusado):redact(self.src,self.out,cor='branco',dpi=400)
        self.assertFalse(self.out.exists())

    def test_nao_sobrescreve(self):
        fixture(self.src)
        self.out.write_bytes(b'EXISTENTE')
        with self.assertRaises(Recusado): redact(self.src,self.out)
        self.assertEqual(self.out.read_bytes(),b'EXISTENTE')
        with self.assertRaises(Recusado): redact(self.src,self.src)

    def test_pagina_extra(self):
        fixture(self.src)
        self.mutate(lambda d:d.new_page())
        result = redact(self.src,self.out)
        self.assertEqual(result['paginas_descartadas'],1)
        with pdf.open(self.out) as out:self.assertEqual(len(out),1)

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
