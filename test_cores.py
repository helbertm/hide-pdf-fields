import tempfile
import unittest
from pathlib import Path
import pymupdf as pdf
from tarjar import CORES, Recusado, pixel_box, redact
from test_tarjar import fixture

class CoresTest(unittest.TestCase):
    def test_cores_opacas_inclusive_branco(self):
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/'entrada.pdf';fixture(src)
            with pdf.open(src) as d:
                original=d[0].get_pixmap(dpi=200,alpha=False)
            box=pixel_box(pdf.Rect(465,28.4,566.8,40.3),200,original.width,original.height)
            self.assertTrue(any(v!=255 for y in range(box.y0,box.y1) for v in original.samples_mv[y*original.stride+box.x0*3:y*original.stride+box.x1*3]))
            for cor,(_,rgb) in CORES.items():
                out=Path(tmp)/(cor+'.pdf')
                redact(src,out,campos=['gestora'],cor=cor,dpi=200)
                with pdf.open(out) as d:
                    self.assertFalse(d[0].get_text());self.assertFalse(d[0].get_fonts())
                    imgs=d[0].get_images();self.assertEqual(len(imgs),1);self.assertEqual(imgs[0][1],0)
                    pix=pdf.Pixmap(d,imgs[0][0])
                    for y in range(box.y0,box.y1):
                        self.assertEqual(pix.samples_mv[y*pix.stride+box.x0*3:y*pix.stride+box.x1*3],bytes(rgb)*(box.x1-box.x0))
                    y=int(85*200/72)
                    self.assertEqual(pix.samples_mv[y*pix.stride:(y+1)*pix.stride],original.samples_mv[y*original.stride:(y+1)*original.stride])
    def test_cor_invalida_sem_saida(self):
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/'entrada.pdf';out=Path(tmp)/'out.pdf';fixture(src)
            for cor in ['azul',[],None]:
                with self.assertRaises(Recusado):redact(src,out,cor=cor)
                self.assertFalse(out.exists())
