"""Verificações de interface nativa, somente com PDFs sintéticos."""
import concurrent.futures
from concurrent.futures.process import BrokenProcessPool
from datetime import datetime, timezone
import hashlib
import gc
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pymupdf as pdf


@unittest.skipUnless(os.environ.get('TARJA_GUI_TESTS') == '1', 'Requer sessão gráfica e TARJA_GUI_TESTS=1')
class ManualInterfaceTest(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from interface import Aplicativo
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.source = self.folder / 'teste.pdf'
        with pdf.open() as doc:
            for width, height in ((200, 300), (300, 200), (220, 280)):
                page = doc.new_page(width=width, height=height)
                page.insert_text((30, 40), 'PAGINA SINTETICA')
            doc.save(self.source)
        self.root = tk.Tk()
        self.app = Aplicativo(self.root)
        self.app.open_manual()
        self.viewer = self.app.manual_viewer
        self.root.update()

    def tearDown(self):
        self.app.closing = True
        self.app.preview_request = None
        if self.app.manual_viewer is not None:
            self.app.manual_viewer.close()
        self.app.pool.shutdown(wait=True, cancel_futures=True)
        try:
            self.root.destroy()
        except Exception:
            pass
        self.app._release_tk_resources()
        # Cada caso cria um interpretador Tk próprio. Faça a coleta de ciclos
        # na thread Tk antes que o executor do teste seguinte possa iniciar.
        self.viewer = None
        self.app = None
        self.root = None
        gc.collect()

    def pump(self, condition, timeout=30):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.root.update()
            if condition():
                return
            time.sleep(.02)
        self.fail('A interface não atingiu o estado esperado no prazo.')

    def test_abrir_navegar_escala_fixa_sem_gravar(self):
        source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.viewer.open_path(self.source)
        self.pump(lambda: self.viewer.image is not None)
        self.assertEqual(self.viewer.page_label.get(), 'Página 1 de 3')
        self.assertEqual(self.viewer.image.width(), 267)
        self.assertEqual(self.viewer.image.height(), 400)
        self.viewer.window.geometry('640x480');self.root.update()
        self.assertEqual((self.viewer.image.width(),self.viewer.image.height()),(267,400))
        self.assertIn('disabled', self.viewer.prev_button.state())
        self.viewer.go(1)
        self.pump(lambda: self.viewer.image is not None and self.viewer.page == 1)
        self.assertEqual(self.viewer.page_label.get(), 'Página 2 de 3')
        self.assertEqual(self.viewer.image.width(), 400)
        self.assertEqual(self.viewer.image.height(), 267)
        self.viewer.go(1)
        self.pump(lambda: self.viewer.image is not None and self.viewer.page == 2)
        self.assertEqual(self.viewer.page_label.get(), 'Página 3 de 3')
        self.assertIn('disabled', self.viewer.next_button.state())
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), source_hash)
        self.assertEqual(list(self.folder.iterdir()), [self.source])

    def mouse(self, sequence, x, y):
        self.viewer.canvas.event_generate(sequence, x=int(x), y=int(y))
        self.root.update()

    def draw(self, x0, y0, x1, y1):
        self.mouse('<ButtonPress-1>',x0,y0)
        self.mouse('<B1-Motion>',x1,y1)
        self.mouse('<ButtonRelease-1>',x1,y1)

    def test_quatro_cores_selecao_e_apagar_sobreposicao(self):
        source_hash=hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.viewer.open_path(self.source)
        self.pump(lambda:self.viewer.image is not None)
        self.assertIn('ainda não ocultam dados',self.viewer.preview_warning.cget('text'))
        for label in ('Preto','Vermelho escuro','Cinza escuro','Branco'):
            self.viewer.mark_color.set(label)
            self.draw(20,20,100,100)
        marks=self.viewer.marks[0]
        self.assertEqual([mark['cor'] for mark in marks],['preto','vermelho_escuro','cinza_escuro','branco'])
        self.assertEqual(len({mark['id'] for mark in marks}),4)
        self.assertEqual(len(self.viewer.canvas.find_withtag('mark')),8)
        # The white region has both white and black outlines and remains visible.
        last_ids=self.viewer.canvas.find_withtag('mark')[-2:]
        self.assertEqual(self.viewer.canvas.itemcget(last_ids[0],'outline'),'#ffffff')
        self.assertEqual(self.viewer.canvas.itemcget(last_ids[1],'outline'),'#000000')
        self.viewer.tool.set('selecionar')
        self.mouse('<ButtonPress-1>',40,40)
        self.mouse('<ButtonRelease-1>',40,40)
        self.assertEqual(self.viewer.selected_mark_id,marks[-1]['id'])
        self.assertIn('selecionada',self.viewer.selection_status.get())
        selected_outline=self.viewer.canvas.find_withtag('mark')[-1]
        self.assertEqual(self.viewer.canvas.itemcget(selected_outline,'dash'),'5 3')
        self.assertEqual(float(self.viewer.canvas.itemcget(selected_outline,'width')),3.0)
        self.assertNotIn('disabled',self.viewer.delete_button.state())
        self.viewer.delete_button.invoke()
        self.assertEqual([mark['cor'] for mark in self.viewer.marks[0]],['preto','vermelho_escuro','cinza_escuro'])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),source_hash)
        self.assertEqual(list(self.folder.iterdir()),[self.source])

    def test_arrasto_inverso_vazio_fora_e_limitado_a_pagina(self):
        self.viewer.open_path(self.source)
        self.pump(lambda:self.viewer.image is not None)
        self.draw(400,20,420,50)  # início fora da página não deve criar tarja
        self.assertEqual(self.viewer.marks,{})
        self.draw(30,30,30,30)
        self.assertEqual(self.viewer.marks,{})
        self.draw(200,200,20,20)
        r=self.viewer.marks[0][0]['rect']
        self.assertLess(r[0],r[2]);self.assertLess(r[1],r[3])
        self.draw(15,15,800,800)
        r=self.viewer.marks[0][1]['rect']
        self.assertAlmostEqual(r[2],200,places=5)
        self.assertAlmostEqual(r[3],300,places=5)

    def test_coordenadas_com_rolagem_xy_e_bloqueio_durante_arrasto(self):
        from manual_pdf import ESCALA_100
        wide=self.folder/'largo_marcacao.pdf'
        with pdf.open() as d:
            d.new_page(width=1000,height=1400);d.save(wide)
        self.viewer.window.geometry('640x480')
        self.viewer.open_path(wide)
        self.pump(lambda:self.viewer.image is not None)
        canvas=self.viewer.canvas
        canvas.xview_moveto(.25);canvas.yview_moveto(.3);self.root.update()
        origin=canvas.coords(self.viewer.page_image_id)
        expected_x=(canvas.canvasx(35)-origin[0])/ESCALA_100
        expected_y=(canvas.canvasy(45)-origin[1])/ESCALA_100
        before_x,before_y=canvas.xview(),canvas.yview()
        self.mouse('<ButtonPress-1>',35,45)
        self.assertIsNotNone(self.viewer.drag)
        self.viewer._scroll('x',4);self.viewer._scroll('y',4)
        self.viewer._viewport('x','scroll',4,'units');self.viewer._viewport('y','scroll',4,'units')
        self.assertEqual(canvas.xview(),before_x);self.assertEqual(canvas.yview(),before_y)
        self.mouse('<B1-Motion>',95,105)
        self.mouse('<ButtonRelease-1>',95,105)
        rect=self.viewer.marks[0][0]['rect']
        self.assertAlmostEqual(rect[0],expected_x,places=5)
        self.assertAlmostEqual(rect[1],expected_y,places=5)
        self.assertAlmostEqual(rect[2]-rect[0],60/ESCALA_100,places=5)
        self.assertAlmostEqual(rect[3]-rect[1],60/ESCALA_100,places=5)

    def test_cropbox_coordenadas_relativas_a_pagina_visivel(self):
        from manual_pdf import ESCALA_100
        src=self.folder/'recorte.pdf'
        with pdf.open() as d:
            page=d.new_page(width=500,height=600)
            page.set_cropbox(pdf.Rect(50,60,450,560))
            d.save(src)
        self.viewer.open_path(src)
        self.pump(lambda:self.viewer.image is not None)
        self.assertEqual(self.viewer.document['paginas'][0]['cropbox'][:2],[50.0,60.0])
        canvas=self.viewer.canvas;origin=canvas.coords(self.viewer.page_image_id)
        expected_x=(canvas.canvasx(40)-origin[0])/ESCALA_100
        expected_y=(canvas.canvasy(50)-origin[1])/ESCALA_100
        self.draw(40,50,100,110)
        rect=self.viewer.marks[0][0]['rect']
        self.assertAlmostEqual(rect[0],expected_x,places=5)
        self.assertAlmostEqual(rect[1],expected_y,places=5)
        self.assertLess(rect[0],50)
        self.assertLess(rect[1],60)

    def test_cancelar_por_cor_modo_escape_ou_navegacao(self):
        self.viewer.open_path(self.source)
        self.pump(lambda:self.viewer.image is not None)
        self.mouse('<ButtonPress-1>',20,20)
        self.assertIsNotNone(self.viewer.drag)
        self.viewer.mark_color.set('Branco')
        self.assertIsNone(self.viewer.drag)
        self.mouse('<ButtonRelease-1>',100,100)
        self.assertEqual(self.viewer.marks,{})
        self.mouse('<ButtonPress-1>',20,20)
        self.viewer.tool.set('selecionar')
        self.assertIsNone(self.viewer.drag)
        self.viewer.tool.set('desenhar')
        self.mouse('<ButtonPress-1>',20,20)
        self.viewer._cancel_drag()
        self.mouse('<ButtonRelease-1>',100,100)
        self.assertEqual(self.viewer.marks,{})
        self.mouse('<ButtonPress-1>',20,20)
        self.viewer.go(1)
        self.assertIsNone(self.viewer.drag)
        self.pump(lambda:self.viewer.image is not None and self.viewer.page==1)
        self.mouse('<ButtonRelease-1>',100,100)
        self.assertEqual(self.viewer.marks,{})

    def test_delete_apaga_somente_com_foco_no_canvas(self):
        self.viewer.open_path(self.source)
        self.pump(lambda:self.viewer.image is not None)
        self.draw(20,20,100,100)
        self.viewer.tool.set('selecionar')
        self.mouse('<ButtonPress-1>',40,40)
        self.mouse('<ButtonRelease-1>',40,40)
        self.viewer.canvas.focus_force()
        self.root.update()
        if self.root.focus_get() is not self.viewer.canvas:
            self.skipTest('Ambiente gráfico não concedeu foco ao canvas.')
        self.viewer.canvas.event_generate('<Delete>')
        self.root.update()
        self.assertEqual(self.viewer.marks,{})

    def test_escape_real_cancela_arrasto_e_ocupacao_tambem(self):
        self.viewer.open_path(self.source)
        self.pump(lambda:self.viewer.image is not None)
        self.mouse('<ButtonPress-1>',20,20)
        self.viewer.canvas.focus_force()
        self.root.update()
        if self.root.focus_get() is self.viewer.canvas:
            self.viewer.canvas.event_generate('<Escape>')
            self.root.update()
            self.assertIsNone(self.viewer.drag)
        else:
            self.viewer._cancel_drag()
        self.mouse('<ButtonRelease-1>',100,100)
        self.assertEqual(self.viewer.marks,{})
        self.mouse('<ButtonPress-1>',20,20)
        self.app.running=True
        self.viewer._controls()
        self.assertIsNone(self.viewer.drag)
        self.app.running=False
        self.mouse('<ButtonRelease-1>',100,100)
        self.assertEqual(self.viewer.marks,{})

    def test_troca_durante_arrasto_invalido_preserva_valido_descarta(self):
        self.viewer.open_path(self.source)
        self.pump(lambda:self.viewer.image is not None)
        self.draw(20,20,90,90)
        saved=list(self.viewer.marks[0])
        invalid=self.folder/'rotacionado_durante_arrasto.pdf'
        with pdf.open() as d:
            d.new_page().set_rotation(90);d.save(invalid)
        self.mouse('<ButtonPress-1>',120,120)
        self.assertIsNotNone(self.viewer.drag)
        with patch('manual_interface.messagebox.showerror'):
            self.viewer.open_path(invalid)
            self.assertIsNone(self.viewer.drag)
            self.mouse('<ButtonRelease-1>',160,160)
            self.pump(lambda:self.viewer.inspect_future is None)
        self.assertEqual(self.viewer.marks[0],saved)
        self.mouse('<ButtonPress-1>',120,120)
        self.assertIsNotNone(self.viewer.drag)
        valid=self.folder/'outro_durante_arrasto.pdf'
        with pdf.open() as d:
            d.new_page(width=200,height=300);d.save(valid)
        self.viewer.open_path(valid)
        self.assertIsNone(self.viewer.drag)
        self.mouse('<ButtonRelease-1>',160,160)
        self.pump(lambda:self.viewer.path==str(valid) and self.viewer.image is not None)
        self.assertEqual(self.viewer.marks,{})
        self.assertEqual(self.viewer.next_mark_id,1)

    def test_excluir_pagina_bloqueia_edicao_mas_mantem_tarjas(self):
        self.viewer.open_path(self.source)
        self.pump(lambda:self.viewer.image is not None)
        self.draw(20,20,100,100)
        saved=list(self.viewer.marks[0])
        self.viewer.toggle_exclusion()
        self.assertIn('disabled',self.viewer.draw_button.state())
        self.draw(120,120,160,160)
        self.assertEqual(self.viewer.marks[0],saved)
        self.viewer.toggle_exclusion()
        self.assertNotIn('disabled',self.viewer.draw_button.state())
        self.assertEqual(self.viewer.marks[0],saved)
        self.viewer.go(1)
        self.pump(lambda:self.viewer.image is not None and self.viewer.page==1)
        self.draw(20,20,80,80)
        self.viewer.go(-1)
        self.pump(lambda:self.viewer.image is not None and self.viewer.page==0)
        self.assertEqual(self.viewer.marks[0],saved)
        self.assertEqual(len(self.viewer.marks[1]),1)
        self.app.running=True
        self.viewer._controls()
        self.draw(120,120,160,160)
        self.assertEqual(self.viewer.marks[0],saved)
        self.app.running=False

    def test_aviso_no_tamanho_minimo_com_atualizacao(self):
        self.root.geometry('900x650')
        self.app.update_queue.put(('checked',{'version':'v9.0.0','assets':{}}))
        self.app.poll_update()
        self.viewer.window.geometry('600x450')
        self.viewer.open_path(self.source)
        self.pump(lambda:self.viewer.image is not None)
        self.viewer.recipient.set('Equipe')
        self.viewer.tool.set('aviso')
        self.draw(10,10,250,190)
        self.pump(lambda:self.viewer.notice_image is not None)
        self.viewer.excluded_pages.update({1,2})
        self.viewer._controls()
        self.root.update()
        self.assertTrue(self.app.update_button.winfo_ismapped())
        self.assertIn('Prévia:',self.viewer.notice_status.get())
        self.assertIn('horário real',self.viewer.notice_status.get())
        window=self.viewer.window
        x0,y0=window.winfo_rootx(),window.winfo_rooty()
        x1,y1=x0+window.winfo_width(),y0+window.winfo_height()
        for widget in (self.viewer.draw_button,self.viewer.select_button,self.viewer.delete_button,
                       self.viewer.color_combo,self.viewer.recipient_entry,self.viewer.preview_warning,
                       self.viewer.selection_label,self.viewer.notice_button,self.viewer.notice_remove_button,
                       self.viewer.notice_status_label,self.viewer.notice_warning,self.viewer.canvas,
                       self.viewer.exclude_button,self.viewer.exclusion_label,self.viewer.status_label):
            self.assertTrue(widget.winfo_ismapped(),str(widget))
            left,top=widget.winfo_rootx(),widget.winfo_rooty()
            right,bottom=left+widget.winfo_width(),top+widget.winfo_height()
            self.assertGreaterEqual(left,x0,str(widget));self.assertGreaterEqual(top,y0,str(widget))
            self.assertLessEqual(right,x1,str(widget));self.assertLessEqual(bottom,y1,str(widget))
            if widget is not self.viewer.canvas:
                self.assertGreaterEqual(widget.winfo_width(),widget.winfo_reqwidth(),str(widget))
                self.assertGreaterEqual(widget.winfo_height(),widget.winfo_reqheight(),str(widget))
        self.assertGreaterEqual(self.viewer.canvas.winfo_height(),120)
        # A long validation error must also fit instead of clipping the controls.
        self.viewer.recipient.set('😀')
        self.pump(lambda:'não suportados' in self.viewer.notice_status.get())
        self.root.update()
        self.assertGreaterEqual(self.viewer.notice_status_label.winfo_height(),self.viewer.notice_status_label.winfo_reqheight())
        self.assertGreaterEqual(self.viewer.canvas.winfo_height(),120)

    def prepare_notice(self, recipient='Equipe', coords=(10,10,250,190)):
        self.viewer.recipient.set(recipient)
        self.viewer.tool.set('aviso')
        self.draw(*coords)
        self.assertIsNotNone(self.viewer.notice_area)

    def test_geracao_e_conferencia_preservam_editor_e_verificam_arquivo(self):
        self.viewer.open_path(self.source)
        self.pump(lambda:self.viewer.image is not None)
        self.draw(15,15,80,80)
        self.prepare_notice()
        original_hash=hashlib.sha256(self.source.read_bytes()).hexdigest()
        original_marks=repr(self.viewer.marks)
        original_notice=dict(self.viewer.notice_area)
        output=self.folder/'resultado.pdf'
        before_dialog=datetime(2026,1,1,12,0,tzinfo=timezone.utc)
        after_confirmation=datetime(2026,1,1,12,7,tzinfo=timezone.utc)
        with patch('manual_interface.filedialog.asksaveasfilename',return_value=str(output)), \
             patch('manual_interface.messagebox.askyesno',return_value=True), \
             patch('manual_interface.datetime') as clock:
            clock.now.side_effect=[before_dialog,after_confirmation]
            self.viewer.generate()
            self.assertTrue(self.viewer.exporting)
            self.assertEqual(self.viewer.export_snapshot['instante'],after_confirmation.astimezone().isoformat())
        with patch('manual_interface.messagebox.showerror'):
            self.pump(lambda:self.viewer.result_viewer is not None,timeout=60)
        result=self.viewer.result_viewer
        self.pump(lambda:result.image is not None,timeout=60)
        result.window.geometry('600x450')
        self.root.update()
        def check_bounds():
            window=result.window
            left,top=window.winfo_rootx(),window.winfo_rooty()
            right,bottom=left+window.winfo_width(),top+window.winfo_height()
            for widget in (result.prev,result.next,result.status_label,result.return_button,result.canvas):
                self.assertTrue(widget.winfo_ismapped())
                self.assertGreaterEqual(widget.winfo_rootx(),left)
                self.assertGreaterEqual(widget.winfo_rooty(),top)
                self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),right)
                self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),bottom)
                if widget is not result.canvas:
                    self.assertGreaterEqual(widget.winfo_width(),widget.winfo_reqwidth())
                    self.assertGreaterEqual(widget.winfo_height(),widget.winfo_reqheight())
        check_bounds()
        self.assertTrue(output.exists())
        self.assertEqual(result.label.get(),'Resultado 1 de 3 · original 1')
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),original_hash)
        self.assertEqual(repr(self.viewer.marks),original_marks)
        self.assertEqual(self.viewer.notice_area,original_notice)
        self.assertEqual(self.viewer.recipient.get(),'Equipe')
        saved_result=dict(result.resultado,limpeza_pendente=True)
        result.close()
        self.viewer._finish_export(resultado=saved_result)
        result=self.viewer.result_viewer
        self.pump(lambda:result.image is not None,timeout=60)
        self.assertIn('PDF salvo',self.viewer.status.get())
        self.assertIn('temporário adicional',result.status.get())
        result.window.geometry('600x450');self.root.update();check_bounds()
        result.go(1)
        self.pump(lambda:result.image is not None and result.page==1)
        self.assertEqual(result.label.get(),'Resultado 2 de 3 · original 2')
        output.write_bytes(output.read_bytes()+b'alterado')
        result.go(1)
        self.pump(lambda:'Não foi possível conferir' in result.status.get())
        self.assertEqual(result.label.get(),'Resultado 3 de 3 · original 3')
        self.root.update()
        check_bounds()
        self.assertIsNone(result.image)
        result.close()
        self.assertEqual(repr(self.viewer.marks),original_marks)

    def test_cancelamento_e_destino_existente_preservam_escolhas(self):
        self.viewer.open_path(self.source)
        self.pump(lambda:self.viewer.image is not None)
        self.prepare_notice()
        notice=dict(self.viewer.notice_area)
        with patch('manual_interface.filedialog.asksaveasfilename',return_value=''):
            self.viewer.generate()
        self.assertEqual(self.viewer.notice_area,notice)
        with patch('manual_interface.filedialog.asksaveasfilename',return_value=str(self.source)), \
             patch('manual_interface.messagebox.showerror') as error:
            self.viewer.generate()
        error.assert_called_once()
        self.assertFalse(self.viewer.exporting)
        self.assertEqual(self.viewer.notice_area,notice)

    def test_aviso_sobre_texto_e_tarja_preserva_marcacao_e_dados(self):
        original=hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.viewer.open_path(self.source)
        self.pump(lambda:self.viewer.image is not None)
        self.draw(10,10,250,190)
        mark=dict(self.viewer.marks[0][0])
        self.prepare_notice('João e Márcia')
        self.pump(lambda:self.viewer.notice_image is not None)
        self.assertEqual(self.viewer.notice_area['pagina'],0)
        self.assertEqual(self.viewer.marks[0],[mark])
        self.assertIn('João e Márcia',self.viewer.notice_text)
        self.assertIn('Prévia:',self.viewer.notice_status.get())
        self.assertIn('horário real',self.viewer.notice_status.get())
        self.assertIn('O aviso pode cobrir conteúdo do documento.',self.viewer.notice_warning.cget('text'))
        # White notice image is above marked rectangles in the canvas stack.
        all_items=list(self.viewer.canvas.find_all())
        notice_images=[item for item in self.viewer.canvas.find_withtag('notice') if self.viewer.canvas.type(item)=='image']
        self.assertEqual(len(notice_images),1)
        self.assertGreater(all_items.index(notice_images[0]),max(all_items.index(item) for item in self.viewer.canvas.find_withtag('mark')))
        # Underlying mark remains selectable/deletable even underneath the notice.
        self.viewer.tool.set('selecionar')
        self.mouse('<ButtonPress-1>',40,40);self.mouse('<ButtonRelease-1>',40,40)
        self.assertEqual(self.viewer.selected_mark_id,mark['id'])
        self.viewer.delete_button.invoke()
        self.assertEqual(self.viewer.marks,{})
        self.assertIsNotNone(self.viewer.notice_area)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),original)
        self.assertEqual(list(self.folder.iterdir()),[self.source])

    def test_aviso_sobre_imagem_e_branco_sem_verificacao_do_fundo(self):
        source=self.folder/'imagem.pdf'
        with pdf.open() as d:
            page=d.new_page(width=200,height=300)
            pix=pdf.Pixmap(pdf.csRGB,pdf.IRect(0,0,25,25),False);pix.clear_with(0)
            page.insert_image(pdf.Rect(15,15,150,100),pixmap=pix)
            d.save(source)
        before=source.read_bytes()
        self.viewer.open_path(source);self.pump(lambda:self.viewer.image is not None)
        self.prepare_notice('Equipe')
        self.pump(lambda:self.viewer.notice_image is not None)
        self.assertIsNotNone(self.viewer.notice_area)
        self.viewer.notice_remove_button.invoke()
        self.assertIsNone(self.viewer.notice_area)
        self.viewer.tool.set('aviso')
        # lower part of page is blank; acceptance is independent of content
        self.draw(10,150,250,350)
        self.pump(lambda:self.viewer.notice_image is not None)
        self.assertEqual(source.read_bytes(),before)
        self.assertEqual(set(self.folder.iterdir()),{self.source,source})

    def test_aviso_destinatario_invalido_e_120_caracteres(self):
        self.viewer.open_path(self.source);self.pump(lambda:self.viewer.image is not None)
        self.prepare_notice('')
        self.assertIn('informe o destinatário',self.viewer.notice_status.get())
        for bad in ('A'*121,'😀'):
            self.viewer.recipient.set(bad)
            self.pump(lambda:('120 caracteres' in self.viewer.notice_status.get() or 'não suportados' in self.viewer.notice_status.get()))
            self.assertIsNone(self.viewer.notice_image)
            self.assertIsNone(self.viewer.notice_text)
        self.viewer.recipient.set('Á'*120)
        self.pump(lambda:self.viewer.notice_image is not None)
        self.assertIn('Á'*120,self.viewer.notice_text)
        self.assertIsNotNone(self.viewer.notice_area)

    def test_aviso_area_insuficiente_remover_e_refazer(self):
        self.viewer.open_path(self.source);self.pump(lambda:self.viewer.image is not None)
        self.prepare_notice('Equipe',coords=(10,10,60,30))
        self.pump(lambda:('dimensões inválidas' in self.viewer.notice_status.get() or 'não cabe' in self.viewer.notice_status.get()))
        self.assertIsNone(self.viewer.notice_image)
        self.assertIsNone(self.viewer.notice_text)
        self.assertIsNotNone(self.viewer.notice_area)
        self.assertIn('disabled',self.viewer.notice_button.state())
        self.viewer.notice_remove_button.invoke()
        self.assertIsNone(self.viewer.notice_area)
        self.assertNotIn('disabled',self.viewer.notice_button.state())
        self.prepare_notice('Equipe')
        self.pump(lambda:self.viewer.notice_image is not None)
        self.assertIn('Equipe',self.viewer.notice_text)

    def test_aviso_navegar_excluir_restaurar_remover(self):
        self.viewer.open_path(self.source);self.pump(lambda:self.viewer.image is not None)
        self.prepare_notice('Equipe')
        self.pump(lambda:self.viewer.notice_image is not None)
        area=dict(self.viewer.notice_area)
        self.viewer.go(1)
        self.pump(lambda:self.viewer.image is not None and self.viewer.page==1)
        self.assertEqual(self.viewer.notice_area,area)
        self.assertEqual(self.viewer.canvas.find_withtag('notice'),())
        self.viewer.go(-1)
        self.pump(lambda:self.viewer.image is not None and self.viewer.page==0 and self.viewer.notice_image is not None)
        self.viewer.toggle_exclusion()
        self.assertEqual(self.viewer.notice_area,area)
        self.assertIn('inativo',self.viewer.notice_status.get())
        self.assertIsNone(self.viewer.notice_image)
        self.assertNotIn('disabled',self.viewer.notice_remove_button.state())
        self.viewer.toggle_exclusion()
        self.pump(lambda:self.viewer.notice_image is not None)
        self.viewer.toggle_exclusion()
        self.viewer.notice_remove_button.invoke()
        self.assertIsNone(self.viewer.notice_area)
        self.assertIn('disabled',self.viewer.notice_button.state())
        self.viewer.toggle_exclusion()
        self.assertNotIn('disabled',self.viewer.notice_button.state())

    def test_aviso_cropbox_rolagem_arrasto_inverso_e_limites(self):
        from manual_pdf import ESCALA_100
        source=self.folder/'recorte_aviso.pdf'
        with pdf.open() as d:
            page=d.new_page(width=1100,height=1500)
            page.set_cropbox(pdf.Rect(50,60,1050,1460));d.save(source)
        self.viewer.window.geometry('640x480')
        self.viewer.open_path(source);self.pump(lambda:self.viewer.image is not None)
        canvas=self.viewer.canvas
        canvas.xview_moveto(.25);canvas.yview_moveto(.30);self.root.update()
        origin=canvas.coords(self.viewer.page_image_id)
        expected=((canvas.canvasx(35)-origin[0])/ESCALA_100,(canvas.canvasy(45)-origin[1])/ESCALA_100)
        self.viewer.recipient.set('Equipe');self.viewer.tool.set('aviso')
        self.draw(95,105,35,45)
        rect=self.viewer.notice_area['rect']
        self.assertAlmostEqual(rect[0],expected[0],places=5)
        self.assertAlmostEqual(rect[1],expected[1],places=5)
        self.assertAlmostEqual(rect[2]-rect[0],60/ESCALA_100,places=5)
        self.assertAlmostEqual(rect[3]-rect[1],60/ESCALA_100,places=5)
        self.assertEqual(self.viewer.notice_area['pagina'],0)

    def test_aviso_resposta_atrasada_destinatario_e_remocao(self):
        from manual_pdf import visualizar_aviso
        class ControlledExecutor:
            def __init__(self):self.tasks=[]
            def submit(self,func,*args):
                future=concurrent.futures.Future();self.tasks.append((func.__name__,args,future));return future
        self.viewer.open_path(self.source);self.pump(lambda:self.viewer.image is not None)
        executor=ControlledExecutor();self.viewer.executor=lambda:executor
        self.prepare_notice('Nome antigo')
        self.pump(lambda:len(executor.tasks)==1)
        task=executor.tasks[0]
        self.assertEqual(task[0],'visualizar_aviso')
        self.viewer.recipient.set('Nome novo')
        task[2].set_result(visualizar_aviso(*task[1]))
        self.viewer.poll()
        self.assertIsNone(self.viewer.notice_image)
        self.assertIsNone(self.viewer.notice_text)
        self.pump(lambda:len(executor.tasks)==2)
        task2=executor.tasks[1]
        task2[2].set_result(visualizar_aviso(*task2[1]))
        self.viewer.poll()
        self.assertIn('Nome novo',self.viewer.notice_text)
        self.assertNotIn('Nome antigo',self.viewer.notice_text)
        self.viewer.recipient.set('Resposta que será descartada')
        self.pump(lambda:len(executor.tasks)==3)
        task3=executor.tasks[2]
        self.viewer.remove_notice()
        task3[2].set_result(visualizar_aviso(*task3[1]))
        self.viewer.poll()
        self.assertIsNone(self.viewer.notice_area)
        self.assertIsNone(self.viewer.notice_image)
        self.assertIsNone(self.viewer.notice_text)

    def test_aviso_resposta_atrasada_de_pagina_anterior(self):
        from manual_pdf import visualizar_aviso
        class ControlledExecutor:
            def __init__(self):self.tasks=[]
            def submit(self,func,*args):
                future=concurrent.futures.Future();self.tasks.append((func.__name__,args,future));return future
        self.viewer.open_path(self.source);self.pump(lambda:self.viewer.image is not None)
        executor=ControlledExecutor();self.viewer.executor=lambda:executor
        self.prepare_notice('Equipe')
        self.pump(lambda:len(executor.tasks)==1)
        old=executor.tasks[0]
        self.viewer.go(1)
        self.assertEqual(executor.tasks[1][0],'renderizar')
        old[2].set_result(visualizar_aviso(*old[1]))
        self.viewer.poll()
        self.assertIsNone(self.viewer.notice_image)
        self.assertIsNone(self.viewer.notice_text)
        pix=pdf.Pixmap(pdf.csRGB,pdf.IRect(0,0,400,267),False);pix.clear_with(255)
        executor.tasks[1][2].set_result(pix.tobytes('png'))
        self.viewer.poll()
        self.assertEqual(self.viewer.page,1)
        self.assertEqual(self.viewer.canvas.find_withtag('notice'),())
        self.assertEqual(self.viewer.notice_area['pagina'],0)

    def test_area_aviso_substituicao_recusada_preserva_valida_limpa(self):
        self.viewer.open_path(self.source);self.pump(lambda:self.viewer.image is not None)
        self.prepare_notice('Equipe');self.pump(lambda:self.viewer.notice_image is not None)
        area=dict(self.viewer.notice_area);texto=self.viewer.notice_text
        invalid=self.folder/'aviso_rotacionado.pdf'
        with pdf.open() as d:
            d.new_page().set_rotation(90);d.save(invalid)
        with patch('manual_interface.messagebox.showerror'):
            self.viewer.open_path(invalid);self.pump(lambda:self.viewer.inspect_future is None)
        self.assertEqual(self.viewer.notice_area,area)
        self.assertEqual(self.viewer.notice_text,texto)
        replacement=self.folder/'aviso_novo.pdf'
        with pdf.open() as d:
            d.new_page(width=200,height=300);d.save(replacement)
        self.viewer.open_path(replacement)
        self.pump(lambda:self.viewer.path==str(replacement) and self.viewer.image is not None)
        self.assertIsNone(self.viewer.notice_area)
        self.assertIsNone(self.viewer.notice_image)
        self.assertIsNone(self.viewer.notice_text)

    def test_area_aviso_limpa_ao_invalidar_original(self):
        self.viewer.open_path(self.source);self.pump(lambda:self.viewer.image is not None)
        self.prepare_notice('Equipe');self.pump(lambda:self.viewer.notice_image is not None)
        with pdf.open(self.source) as d:
            d.new_page();data=d.tobytes()
        self.source.write_bytes(data)
        with patch('manual_interface.messagebox.showerror'):
            self.viewer.go(1);self.pump(lambda:self.viewer.document is None)
        self.assertIsNone(self.viewer.notice_area)
        self.assertIsNone(self.viewer.notice_image)
        self.assertIsNone(self.viewer.notice_text)

    def test_cursor_reflete_modo_e_possibilidade_de_editar(self):
        self.assertNotEqual(self.viewer.canvas.cget('cursor'),'crosshair')
        self.viewer.open_path(self.source)
        self.pump(lambda:self.viewer.image is not None)
        self.assertEqual(self.viewer.canvas.cget('cursor'),'crosshair')
        self.viewer.tool.set('selecionar')
        self.assertNotEqual(self.viewer.canvas.cget('cursor'),'crosshair')
        self.viewer.tool.set('desenhar')
        self.assertEqual(self.viewer.canvas.cget('cursor'),'crosshair')
        self.viewer.toggle_exclusion()
        self.assertNotEqual(self.viewer.canvas.cget('cursor'),'crosshair')
        self.viewer.toggle_exclusion()
        self.assertEqual(self.viewer.canvas.cget('cursor'),'crosshair')
        self.app.running=True;self.viewer._controls()
        self.assertNotEqual(self.viewer.canvas.cget('cursor'),'crosshair')
        self.app.running=False;self.viewer._controls()
        self.assertEqual(self.viewer.canvas.cget('cursor'),'crosshair')

    def test_barra_e_canvas_no_tamanho_minimo_com_atualizacao_e_tarja(self):
        self.root.geometry('900x650')
        self.app.update_queue.put(('checked',{'version':'v9.0.0','assets':{}}))
        self.app.poll_update()
        self.viewer.window.geometry('600x450')
        self.viewer.open_path(self.source)
        self.pump(lambda:self.viewer.image is not None)
        self.draw(20,20,100,100)
        self.viewer.tool.set('selecionar')
        self.mouse('<ButtonPress-1>',40,40)
        self.mouse('<ButtonRelease-1>',40,40)
        self.root.update()
        self.assertTrue(self.app.update_button.winfo_ismapped())
        self.assertIsNotNone(self.viewer.selected_mark_id)
        window=self.viewer.window
        x0,y0=window.winfo_rootx(),window.winfo_rooty()
        x1,y1=x0+window.winfo_width(),y0+window.winfo_height()
        for widget in (self.viewer.draw_button,self.viewer.select_button,self.viewer.delete_button,
                       self.viewer.color_combo,self.viewer.preview_warning,self.viewer.selection_label,
                       self.viewer.canvas,self.viewer.exclude_button,self.viewer.exclusion_label,
                       self.viewer.status_label):
            self.assertTrue(widget.winfo_ismapped(),str(widget))
            left,top=widget.winfo_rootx(),widget.winfo_rooty()
            right,bottom=left+widget.winfo_width(),top+widget.winfo_height()
            self.assertGreaterEqual(left,x0,str(widget));self.assertGreaterEqual(top,y0,str(widget))
            self.assertLessEqual(right,x1,str(widget));self.assertLessEqual(bottom,y1,str(widget))
            if widget is not self.viewer.canvas:
                self.assertGreaterEqual(widget.winfo_width(),widget.winfo_reqwidth(),str(widget))
                self.assertGreaterEqual(widget.winfo_height(),widget.winfo_reqheight(),str(widget))
        self.assertGreaterEqual(self.viewer.canvas.winfo_height(),80)

    def test_rolagem_horizontal_vertical_e_teclado(self):
        wide = self.folder / 'largo.pdf'
        with pdf.open() as doc:
            doc.new_page(width=1000,height=1400)
            doc.save(wide)
        self.viewer.window.geometry('640x480')
        self.viewer.open_path(wide)
        self.pump(lambda: self.viewer.image is not None)
        self.root.update()
        self.assertEqual(self.viewer.canvas.xview()[0],0.0)
        self.assertEqual(self.viewer.canvas.yview()[0],0.0)
        self.viewer._scroll('x',3)
        self.viewer._scroll('y',3)
        self.assertGreater(self.viewer.canvas.xview()[0],0.0)
        self.assertGreater(self.viewer.canvas.yview()[0],0.0)
        # Exercise the actual Tk binding, not only the helper. Some headless
        # window systems decline keyboard focus, so skip only that condition.
        self.viewer.canvas.focus_force()
        self.root.update()
        if self.root.focus_get() is self.viewer.canvas:
            before=self.viewer.canvas.yview()[0]
            self.viewer.canvas.event_generate('<Down>')
            self.root.update()
            self.assertGreater(self.viewer.canvas.yview()[0],before)

    def test_excluir_restaurar_paginas_mantem_ordem_e_original(self):
        source_hash=hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.viewer.open_path(self.source)
        self.pump(lambda:self.viewer.image is not None)
        self.assertEqual(self.viewer.excluded_pages,set())
        self.assertIn('Resultado previsto: 3 páginas · 0 excluídas',self.viewer.exclusion_status.get())
        self.viewer.exclude_button.focus_force();self.root.update()
        focused=self.root.focus_get() is self.viewer.exclude_button
        self.viewer.exclude_button.invoke();self.root.update()
        self.assertEqual(self.viewer.excluded_pages,{0})
        self.assertEqual(self.viewer.exclude_button.cget('text'),'Restaurar página')
        self.assertIn('Excluída do resultado',self.viewer.exclusion_status.get())
        if focused:self.assertIs(self.root.focus_get(),self.viewer.exclude_button)
        self.viewer.go(1)
        self.assertIn('disabled',self.viewer.exclude_button.state())
        self.viewer.toggle_exclusion()
        self.assertEqual(self.viewer.excluded_pages,{0})
        self.pump(lambda:self.viewer.image is not None and self.viewer.page==1)
        self.viewer.toggle_exclusion()
        self.assertEqual(self.viewer.excluded_pages,{0,1})
        self.viewer.go(1)
        self.pump(lambda:self.viewer.image is not None and self.viewer.page==2)
        self.assertIn('disabled',self.viewer.exclude_button.state())
        self.assertIn('O resultado precisa manter pelo menos uma página.',self.viewer.exclusion_status.get())
        self.viewer.toggle_exclusion()
        self.assertEqual(self.viewer.excluded_pages,{0,1})
        self.viewer.go(-1)
        self.pump(lambda:self.viewer.image is not None and self.viewer.page==1)
        self.assertIn('Excluída do resultado',self.viewer.exclusion_status.get())
        self.viewer.toggle_exclusion()
        self.assertEqual(self.viewer.excluded_pages,{0})
        self.assertIn('Resultado previsto: 2 páginas · 1 excluídas',self.viewer.exclusion_status.get())
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),source_hash)
        self.assertEqual(list(self.folder.iterdir()),[self.source])

    def test_arquivo_com_uma_pagina_nao_pode_ser_excluido(self):
        single=self.folder/'unica.pdf'
        with pdf.open() as d:
            d.new_page();d.save(single)
        self.viewer.open_path(single)
        self.pump(lambda:self.viewer.image is not None)
        self.assertIn('disabled',self.viewer.exclude_button.state())
        self.assertIn('O resultado precisa manter pelo menos uma página.',self.viewer.exclusion_status.get())
        self.viewer.toggle_exclusion()
        self.assertEqual(self.viewer.excluded_pages,set())

    def test_substituicao_recusada_preserva_marcacoes_e_sucesso_limpa(self):
        self.viewer.open_path(self.source)
        self.pump(lambda:self.viewer.image is not None)
        self.viewer.toggle_exclusion()
        self.assertEqual(self.viewer.excluded_pages,{0})
        # Restore, add a mark, then exclude again before attempting replacement.
        self.viewer.toggle_exclusion()
        self.draw(20,20,100,100)
        saved_marks=list(self.viewer.marks[0])
        self.viewer.toggle_exclusion()
        invalid=self.folder/'nao_suportado.pdf'
        with pdf.open() as d:
            d.new_page().set_rotation(90);d.save(invalid)
        with patch('manual_interface.messagebox.showerror') as error:
            self.viewer.open_path(invalid)
            self.pump(lambda:self.viewer.inspect_future is None)
        self.assertTrue(error.called)
        self.assertEqual(self.viewer.path,str(self.source))
        self.assertEqual(self.viewer.excluded_pages,{0})
        self.assertEqual(self.viewer.marks[0],saved_marks)
        self.assertIn('Excluída do resultado',self.viewer.exclusion_status.get())
        replacement=self.folder/'outro.pdf'
        with pdf.open() as d:
            d.new_page();d.new_page();d.save(replacement)
        self.viewer.open_path(replacement)
        self.pump(lambda:self.viewer.path==str(replacement) and self.viewer.image is not None)
        self.assertEqual(self.viewer.excluded_pages,set())
        self.assertEqual(self.viewer.marks,{})
        self.assertEqual(self.viewer.next_mark_id,1)
        self.assertIn('Resultado previsto: 2 páginas · 0 excluídas',self.viewer.exclusion_status.get())

    def test_ocupado_impede_alteracao_da_exclusao(self):
        self.viewer.open_path(self.source)
        self.pump(lambda:self.viewer.image is not None)
        self.app.running=True
        self.viewer._controls()
        self.assertIn('disabled',self.viewer.exclude_button.state())
        self.viewer.toggle_exclusion()
        self.assertEqual(self.viewer.excluded_pages,set())
        self.app.running=False
        self.viewer._controls()
        self.viewer.toggle_exclusion()
        self.assertEqual(self.viewer.excluded_pages,{0})

    def test_abertura_recusada_preserva_visualizacao_anterior(self):
        self.viewer.open_path(self.source)
        self.pump(lambda: self.viewer.image is not None)
        invalid = self.folder / 'rotacionado.pdf'
        with pdf.open() as doc:
            doc.new_page(width=200, height=300)
            doc.new_page(width=200, height=300).set_rotation(90)
            doc.save(invalid)
        with patch('manual_interface.messagebox.showerror') as error:
            self.viewer.open_path(invalid)
            self.pump(lambda: self.viewer.inspect_future is None)
        self.assertTrue(error.called)
        self.assertFalse(self.app.pool_broken)
        self.assertEqual(self.viewer.path, str(self.source))
        self.assertEqual(self.viewer.page_label.get(), 'Página 1 de 3')
        self.assertIsNotNone(self.viewer.image)

    def test_alteracao_do_original_invalida_sessao(self):
        self.viewer.open_path(self.source)
        self.pump(lambda: self.viewer.image is not None)
        self.draw(20,20,100,100)
        self.viewer.toggle_exclusion()
        self.assertEqual(self.viewer.excluded_pages,{0})
        self.assertIn(0,self.viewer.marks)
        with pdf.open(self.source) as doc:
            doc.new_page()
            changed = doc.tobytes()
        self.source.write_bytes(changed)
        with patch('manual_interface.messagebox.showerror') as error:
            self.viewer.go(1)
            self.pump(lambda: self.viewer.document is None)
        self.assertTrue(error.called)
        self.assertIsNone(self.viewer.image)
        self.assertEqual(self.viewer.excluded_pages,set())
        self.assertEqual(self.viewer.marks,{})
        self.assertIn('alterado', self.viewer.status.get().lower())

    def test_renderizacao_atrasada_nao_substitui_pagina_solicitada(self):
        class ControlledExecutor:
            def __init__(self):
                self.tasks = []
            def submit(self, func, *args):
                future = concurrent.futures.Future()
                self.tasks.append((func.__name__, args, future))
                return future
        executor = ControlledExecutor()
        self.viewer.executor = lambda: executor
        self.viewer.open_path(self.source)
        metadata = {'sha256': 'a' * 64, 'total_paginas': 3, 'paginas': []}
        executor.tasks[0][2].set_result(metadata)
        self.viewer.poll()
        self.assertEqual(executor.tasks[1][1][-1], 0)
        pix = pdf.Pixmap(pdf.csRGB, pdf.IRect(0, 0, 20, 20), False)
        pix.clear_with(255)
        png = pix.tobytes('png')
        executor.tasks[1][2].set_result(png)
        self.viewer.poll()
        self.viewer.toggle_exclusion()
        self.assertEqual(self.viewer.excluded_pages,{0})
        self.viewer.go(1)
        self.assertEqual(executor.tasks[2][1][-1],1)
        self.viewer.go(1)
        self.assertIn('3 de 3',self.viewer.page_label.get())
        executor.tasks[2][2].set_result(png)
        self.viewer.poll()
        self.assertIsNone(self.viewer.image)
        self.assertEqual(self.viewer.excluded_pages,{0})
        self.assertEqual(executor.tasks[3][1][-1],2)
        executor.tasks[3][2].set_result(png)
        self.viewer.poll()
        self.assertEqual(self.viewer.page_label.get(),'Página 3 de 3')
        self.assertIsNotNone(self.viewer.image)
        self.assertEqual(self.viewer.excluded_pages,{0})

    def test_rodape_adapta_e_nome_longo_pode_ser_percorrido(self):
        self.viewer.window.geometry('600x450')
        self.root.update()
        self.assertLessEqual(int(self.viewer.status_label.cget('wraplength')),self.viewer.window.winfo_width()-20)
        name = 'documento_' + 'a'*95 + '.pdf'
        self.viewer.filename.set(name)
        self.root.update()
        self.assertEqual(str(self.viewer.filename_entry.cget('state')),'readonly')
        self.viewer.filename_entry.xview_moveto(1.0)
        self.root.update()
        self.assertGreater(self.viewer.filename_entry.xview()[0],0.0)
        self.assertEqual(self.viewer.filename_entry.get(),name)

    def test_falha_do_executor_e_recuperacao_na_proxima_abertura(self):
        future=concurrent.futures.Future()
        future.set_exception(BrokenProcessPool('terminated'))
        broken=MagicMock()
        broken.submit.return_value=future
        self.viewer.executor=lambda:broken
        with patch('manual_interface.messagebox.showerror') as error:
            self.viewer.open_path(self.source)
            self.viewer.poll()
        self.assertTrue(error.called)
        self.assertTrue(self.app.pool_broken)
        self.assertIn('novamente',error.call_args.args[1])
        old_pool=self.app.pool
        replacement=MagicMock()
        replacement.submit.return_value=concurrent.futures.Future()
        self.viewer.executor=self.app._manual_executor
        try:
            with patch('interface.ProcessPoolExecutor',return_value=replacement), patch.object(old_pool,'shutdown') as shutdown:
                self.viewer.open_path(self.source)
                shutdown.assert_called_once_with(wait=False,cancel_futures=True)
                self.assertFalse(self.app.pool_broken)
                replacement.submit.assert_called_once()
        finally:
            self.app.pool=old_pool

    def test_falha_do_executor_durante_renderizacao_invalida_sessao(self):
        future=concurrent.futures.Future()
        future.set_exception(BrokenProcessPool('terminated'))
        broken=MagicMock()
        broken.submit.return_value=future
        self.viewer.executor=lambda:broken
        self.viewer.document={'sha256':'a'*64,'total_paginas':1,'paginas':[]}
        self.viewer.path=str(self.source)
        self.viewer.request_page(0)
        with patch('manual_interface.messagebox.showerror'):
            self.viewer.poll()
        self.assertTrue(self.app.pool_broken)
        self.assertIsNone(self.viewer.document)
        self.assertIn('novamente',self.viewer.status.get())

    def test_fechar_durante_render_pendente_libera_variaveis_no_thread_tk(self):
        import tkinter as tk
        future=concurrent.futures.Future()
        future.set_running_or_notify_cancel()
        busy_executor=MagicMock()
        busy_executor.submit.return_value=future
        self.viewer.executor=lambda:busy_executor
        self.viewer.document={'sha256':'a'*64,'total_paginas':1,'paginas':[]}
        self.viewer.path=str(self.source)
        self.viewer.request_page(0)
        self.assertIsNotNone(self.viewer.render_future)
        tracked={id(self.viewer.filename),id(self.viewer.page_label),id(self.viewer.status),id(self.viewer.exclusion_status),id(self.viewer.selection_status),id(self.viewer.notice_status),id(self.viewer.recipient),id(self.viewer.tool),id(self.viewer.mark_color)}
        destroyed=[]
        original_del=tk.Variable.__del__
        def check_thread(variable):
            if id(variable) in tracked:
                destroyed.append((id(variable),threading.get_ident()))
            original_del(variable)
        with patch.object(tk.Variable,'__del__',check_thread):
            self.viewer.close()
        self.assertEqual({item[0] for item in destroyed},tracked)
        self.assertTrue(all(item[1]==threading.get_ident() for item in destroyed))
        self.assertIsNone(self.app.manual_viewer)
        self.assertFalse(future.cancelled())
        busy_executor.shutdown.assert_not_called()
        future.set_result(b'descartado')
        self.root.update()
        self.assertTrue(self.viewer.closed)

    def test_fechar_aplicativo_com_renderizacao_manual_pendente(self):
        future=concurrent.futures.Future()
        future.set_running_or_notify_cancel()
        busy_executor=MagicMock()
        busy_executor.submit.return_value=future
        self.viewer.executor=lambda:busy_executor
        self.viewer.document={'sha256':'a'*64,'total_paginas':1,'paginas':[]}
        self.viewer.path=str(self.source)
        self.viewer.request_page(0)
        self.app.close()
        self.assertTrue(self.viewer.closed)
        self.pump(lambda:self.app.source is None)
        self.assertIsNone(self.app.summary)
        self.assertIsNone(self.app.manual_viewer)
        self.assertFalse(future.cancelled())
        future.set_result(b'descartado')

    def test_abrir_e_fechar_visualizador_repetidamente_no_mesmo_aplicativo(self):
        original=hashlib.sha256(self.source.read_bytes()).hexdigest()
        for _ in range(12):
            if self.app.manual_viewer is None:
                self.app.open_manual()
            self.viewer=self.app.manual_viewer
            self.viewer.open_path(self.source)
            self.pump(lambda:self.viewer.image is not None)
            self.viewer.close()
            self.assertIsNone(self.app.manual_viewer)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),original)
        self.assertEqual(list(self.folder.iterdir()),[self.source])

    def test_fechar_com_inspecoes_pendentes_repetidamente_no_mesmo_aplicativo(self):
        for _ in range(12):
            if self.app.manual_viewer is None:
                self.app.open_manual()
            self.viewer=self.app.manual_viewer
            self.viewer.open_path(self.source)
            self.assertIsNotNone(self.viewer.inspect_future)
            self.viewer.close()
            self.assertIsNone(self.app.manual_viewer)
            self.root.update()
        self.app.open_manual()
        self.viewer=self.app.manual_viewer
        self.viewer.open_path(self.source)
        self.pump(lambda:self.viewer.image is not None)
        self.assertEqual(self.viewer.page_label.get(),'Página 1 de 3')
        self.assertEqual(list(self.folder.iterdir()),[self.source])

    def test_instancia_unica_e_operacoes_bloqueadas_em_lote(self):
        self.app.open_manual()
        self.assertIs(self.app.manual_viewer, self.viewer)
        self.app.running = True
        self.viewer._controls()
        self.assertIn('disabled', self.viewer.open_button.state())
        self.viewer.open_path(self.source)
        self.assertIsNone(self.viewer.inspect_future)
        self.app.running = False
        self.viewer._controls()
        self.assertNotIn('disabled', self.viewer.open_button.state())


if __name__ == '__main__':
    unittest.main()
