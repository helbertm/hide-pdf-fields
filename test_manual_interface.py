"""Verificações de interface nativa, somente com PDFs sintéticos."""
import concurrent.futures
from concurrent.futures.process import BrokenProcessPool
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
        invalid=self.folder/'nao_suportado.pdf'
        with pdf.open() as d:
            d.new_page().set_rotation(90);d.save(invalid)
        with patch('manual_interface.messagebox.showerror') as error:
            self.viewer.open_path(invalid)
            self.pump(lambda:self.viewer.inspect_future is None)
        self.assertTrue(error.called)
        self.assertEqual(self.viewer.path,str(self.source))
        self.assertEqual(self.viewer.excluded_pages,{0})
        self.assertIn('Excluída do resultado',self.viewer.exclusion_status.get())
        replacement=self.folder/'outro.pdf'
        with pdf.open() as d:
            d.new_page();d.new_page();d.save(replacement)
        self.viewer.open_path(replacement)
        self.pump(lambda:self.viewer.path==str(replacement) and self.viewer.image is not None)
        self.assertEqual(self.viewer.excluded_pages,set())
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
        self.viewer.toggle_exclusion()
        self.assertEqual(self.viewer.excluded_pages,{0})
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
        tracked={id(self.viewer.filename),id(self.viewer.page_label),id(self.viewer.status),id(self.viewer.exclusion_status)}
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
