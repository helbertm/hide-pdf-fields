"""Testes nativos opcionais: TARJA_GUI_TESTS=1 python -m unittest test_interface -v."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from test_tarjar import fixture


@unittest.skipUnless(os.environ.get('TARJA_GUI_TESTS')=='1','Requer sessão gráfica e TARJA_GUI_TESTS=1')
class InterfaceTest(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from interface import Aplicativo
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)/'in';self.folder.mkdir()
        fixture(self.folder/'A.pdf');fixture(self.folder/'B.pdf','nota')
        self.root=tk.Tk();self.app=Aplicativo(self.root)
        self.app.source.set(str(self.folder));self.app.target.set(str(Path(self.tmp.name)/'out'))
        self.app.recipient.set('Equipe de teste')
        self.app.load()
        self.pump(lambda:bool(self.app.jobs[0].tipo) and self.app.preview_future is None and self.app.preview_request is None)

    def tearDown(self):
        self.app.closing=True;self.app.preview_request=None
        self.app.pool.shutdown(wait=True,cancel_futures=True)
        try:self.root.destroy()
        except Exception:pass

    def pump(self,condition,timeout=30):
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            self.root.update()
            if condition():return
            time.sleep(.02)
        self.fail('Interface não atingiu o estado esperado dentro do prazo.')

    def test_selecoes_preservam_widgets_e_independencia(self):
        before=self.app.fields_frame.winfo_children()
        self.app.field_vars['gestora'].set(False);self.app._fields_changed()
        self.assertEqual(before,self.app.fields_frame.winfo_children())
        self.app.tree.selection_set('1');self.app.selection()
        self.pump(lambda:bool(self.app.jobs[1].tipo))
        self.assertTrue(all(v.get() for v in self.app.field_vars.values()))
        self.app.tree.selection_set('0');self.app.selection()
        self.assertFalse(self.app.field_vars['gestora'].get())

    def test_saida_padrao_e_escolha_manual(self):
        self.app.target.set('')
        self.app.source.set(str(self.folder/'primeira'))
        self.assertEqual(self.app.target.get(),self.app.source.get())
        self.app.source.set(str(self.folder/'segunda'))
        self.assertEqual(self.app.target.get(),self.app.source.get())
        custom=str(self.folder/'personalizada')
        self.app.target.set(custom)
        self.app.source.set(str(self.folder/'terceira'))
        self.assertEqual(self.app.target.get(),custom)
        self.app.target.set(self.app.source.get())
        self.app.source.set(str(self.folder/'quarta'))
        self.assertEqual(self.app.target.get(),self.app.source.get())

    def test_detalhe_recusado_vermelho_e_reset(self):
        self.app.jobs[0].status='recusado'
        self.app.jobs[0].mensagem='Saída já existe.'
        self.app.selection()
        self.assertEqual(str(self.app.detail_label.cget('foreground')),'#d32f2f')
        self.assertIn('Recusado',self.app.detail.get())
        self.app.tree.selection_set('1');self.app.selection()
        self.assertEqual(str(self.app.detail_label.cget('foreground')),'')

    def test_nenhum_campo_desabilita_execucao(self):
        self.app._set_fields([])
        self.app.tree.selection_set('1');self.app.selection()
        self.pump(lambda:bool(self.app.jobs[1].tipo))
        self.app._set_fields([])
        self.assertIn('disabled',self.app.run_button.state())
        self.assertIn('pelo menos',self.app.summary.get())

    def test_lote_previews_resize_e_ampliacao(self):
        self.assertEqual(self.root.title(),'Ocultar Dados - Pedido Interno e NFe')
        self.assertEqual(self.app.run_button.cget('text'),'Processar')
        self.assertEqual(self.app.stop_button.cget('text'),'Interromper')
        self.assertEqual(self.app.color.get(),'Preto')
        self.app.color.set('Branco')
        self.app.start()
        self.assertEqual(self.app.batch_color,'branco')
        self.assertIn('disabled',self.app.color_combo.state())
        self.assertEqual(self.app.batch_recipient,'Equipe de teste')
        self.assertIn('disabled',self.app.recipient_entry.state())
        self.pump(lambda:not self.app.running)
        self.assertEqual([j.status for j in self.app.jobs],['concluido','concluido'])
        self.assertIn('Processamento concluído',self.app.summary.get())
        self.assertEqual(self.app.summary_label.cget('background'),'#dff3e5')
        self.pump(lambda:self.app.preview_future is None and self.app.preview_request is None)
        self.assertEqual(set(self.app.photos),{'antes','depois'})
        self.root.geometry('900x650')
        self.pump(lambda:self.app.resize_after is None and self.app.preview_future is None and self.app.preview_request is None)
        for side,photo in self.app.photos.items():
            self.assertLessEqual(photo.width(),self.app.canvases[side].winfo_width())
            self.assertLessEqual(photo.height(),self.app.canvases[side].winfo_height())
        self.app.selection(zoom=True)
        self.pump(lambda:any(w.winfo_class()=='Toplevel' for w in self.root.winfo_children()))


if __name__=='__main__':unittest.main()
