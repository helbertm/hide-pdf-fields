from datetime import datetime
from pathlib import Path
import tempfile
import unittest
import pymupdf as pdf
from test_tarjar import fixture
from tarjar import (AREA_AVISO, Recusado, texto_aviso, validar_destinatario,
                    redact, pixel_box, plan, inserir_aviso)


class AvisoTest(unittest.TestCase):
    def test_texto_e_data(self):
        self.assertEqual(texto_aviso('João e Márcia',datetime(2026,11,5,8,9)),
                         'Dados sigilosos ocultados intencionalmente. Documento gerado em 05/11/26 08:09.\nUso exclusivo de João e Márcia, gentileza não compartilhar com terceiros.')

    def test_destinatario(self):
        self.assertEqual(validar_destinatario('  João   e Márcia  '),'João e Márcia')
        self.assertEqual(len(validar_destinatario('A'*120)),120)
        for value in ['', '  ', 'A'*121, 'Nome\nNome', 'Nome\tNome', 'A\u200bB', '😀']:
            with self.assertRaises(Recusado):validar_destinatario(value)

    def test_texto_longo_cabe_e_cinza(self):
        with pdf.open() as d:
            page=d.new_page(width=595,height=842)
            pix=page.get_pixmap(dpi=300,colorspace=pdf.csRGB,alpha=False)
            inserir_aviso(pix,page.rect,'Á'*120,300,datetime(2026,11,5,8,9))
            box=pixel_box(AREA_AVISO,300,pix.width,pix.height)
            seen=[]
            for y in range(box.y0,box.y1):
                row=pix.samples_mv[y*pix.stride+box.x0*3:y*pix.stride+box.x1*3]
                seen.append(min(row))
            self.assertGreater(min(seen),100)
            self.assertLess(min(seen),150)

    def test_area_ocupada_recusa_sem_publicar(self):
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/'in.pdf';out=Path(tmp)/'out.pdf';fixture(src)
            with pdf.open(src) as d:
                d[0].insert_text((40,790),'CONTEUDO QUE NAO PODE SER APAGADO')
                data=d.tobytes()
            src.write_bytes(data)
            with self.assertRaises(Recusado):redact(src,out,destinatario='Equipe',campos=['gestora'])
            self.assertFalse(out.exists())

    def test_pdf_final_preserva_tarjas_e_area_externa(self):
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/'in.pdf';out=Path(tmp)/'out.pdf';plain=Path(tmp)/'plain.pdf'
            fixture(src)
            redact(src,plain)
            redact(src,out,destinatario='João e Márcia')
            with pdf.open(plain) as a,pdf.open(out) as b:
                before=pdf.Pixmap(a,a[0].get_images()[0][0]);after=pdf.Pixmap(b,b[0].get_images()[0][0])
                box=pixel_box(AREA_AVISO,300,before.width,before.height)
                self.assertEqual(before.samples[:box.y0*before.stride],after.samples[:box.y0*after.stride])
                self.assertEqual(before.samples[box.y1*before.stride:],after.samples[box.y1*after.stride:])
                self.assertNotEqual(before.samples,after.samples)
                self.assertFalse(b[0].get_text());self.assertFalse(b.embfile_count())
                self.assertFalse(b[0].get_fonts())


if __name__=='__main__':unittest.main()
