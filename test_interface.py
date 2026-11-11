"""Testes nativos opcionais: TARJA_GUI_TESTS=1 python -m unittest test_interface -v."""
import os
import gc
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
        self.app._release_tk_resources()
        # Não deixar o interpretador de um teste para o GC da thread do próximo executor.
        self.app = None
        self.root = None
        gc.collect()

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

    def test_controles_visuais_e_ajuda_contextual(self):
        from unittest.mock import patch
        self.assertIn('original e resultado', self.app.zoom_button.cget('text').lower())
        for button in (self.app.load_button, self.app.run_button, self.app.stop_button,
                       self.app.manual_button, self.app.zoom_button, self.app.path_widgets[1]):
            self.assertTrue(button.cget('image'))
            self.assertEqual(str(button.cget('compound')), 'left')
            self.assertTrue(button.cget('text'))
        for label, color in [('Preto','#000000'),('Branco','#ffffff'),
                             ('Vermelho escuro','#800000'),('Cinza escuro','#404040')]:
            self.app.color.set(label)
            self.assertEqual(self.app.color_selector.swatch.itemcget(
                self.app.color_selector._rectangle, 'fill'), color)
        for button, context in ((self.app.config_help, 'Pastas e destinatário'),
                                (self.app.fields_help, 'Campos a ocultar')):
            self.assertEqual(button.cget('text'), '?')
            self.assertFalse(button.cget('image'))
            self.assertIn(context, button._ui_tooltip.text)
            self.assertEqual(str(button.cget('takefocus')), '1')
        with patch('ui_components.messagebox.showinfo') as help_dialog:
            self.app.config_help.invoke()
            self.app.fields_help.invoke()
            self.assertEqual(help_dialog.call_count, 2)
        self.assertTrue(hasattr(self.app.run_button, '_ui_tooltip'))

    def test_botoes_principais_cabem_na_janela_minima(self):
        self.root.geometry('900x650')
        self.root.update()
        for widget in (self.app.load_button, self.app.run_button, self.app.stop_button,
                       self.app.manual_button, self.app.zoom_button, self.app.config_help,
                       self.app.fields_help, self.app.color_combo):
            self.assertTrue(widget.winfo_ismapped())
            self.assertGreater(widget.winfo_width(), 1)
            self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                                 self.root.winfo_rootx() + self.root.winfo_width())
            self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                                 self.root.winfo_rooty() + self.root.winfo_height())

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

    def test_atualizacao_indisponivel_durante_lote_e_confirmacao(self):
        from unittest.mock import patch
        self.app.update_info={'version':'v9.0.0','assets':{}}
        self.app.update_queue.put(('checked',self.app.update_info))
        self.app.poll_update()
        self.root.update_idletasks()
        self.assertIn('v9.0.0',self.app.update_button.cget('text'))
        from atualizacao import VERSAO
        self.assertEqual(self.app.version_label.cget('text'),f'Versão {VERSAO}')
        self.assertTrue(self.app.version_label.winfo_ismapped())
        self.assertTrue(self.app.update_button.winfo_ismapped())
        self.root.geometry('900x650');self.root.update()
        self.assertLessEqual(self.app.update_button.winfo_x()+self.app.update_button.winfo_width(),self.app.version_label.winfo_x())
        self.assertLessEqual(self.app.version_label.winfo_x()+self.app.version_label.winfo_width(),self.app.version_label.master.winfo_width())
        self.app.running=True
        with patch('interface.messagebox.askyesno') as confirm:
            self.app.begin_update()
            confirm.assert_not_called()
        self.app.running=False
        with patch('interface.messagebox.askyesno',return_value=False):self.app.begin_update()
        self.assertFalse(self.app.updating)

    def test_exportacao_manual_bloqueia_e_restaura_acoes(self):
        from unittest.mock import patch
        self.app.run_button.configure(state='normal')
        self.app.load_button.configure(state='disabled')
        self.app.update_info={'version':'v9.0.0','assets':{}}
        self.app.update_button.configure(state='normal')
        self.app._manual_export_started()
        self.assertTrue(self.app.manual_exporting)
        for widget in (self.app.run_button,self.app.load_button,self.app.manual_button,
                       self.app.color_combo,self.app.zoom_button,self.app.update_button,
                       *self.app.path_widgets):
            self.assertIn('disabled',widget.state())
        self.assertIn('disabled',self.app.tree.state())
        self.app.selection()
        self.assertIn('disabled',self.app.zoom_button.state())
        self.app.update_queue.put(('checked',self.app.update_info))
        self.app.poll_update()
        self.assertIn('disabled',self.app.update_button.state())
        with patch('interface.messagebox.askyesno') as confirm, patch('interface.messagebox.showinfo') as notice:
            self.app.start()
            self.app.begin_update()
            self.app.close()
            confirm.assert_not_called()
            notice.assert_called_once()
        self.assertFalse(self.app.running)
        self.assertFalse(self.app.updating)
        self.assertFalse(self.app.closing)
        self.app._manual_export_finished()
        self.assertFalse(self.app.manual_exporting)
        self.assertNotIn('disabled',self.app.run_button.state())
        self.assertIn('disabled',self.app.load_button.state())
        self.assertNotIn('disabled',self.app.manual_button.state())
        self.assertNotIn('disabled',self.app.tree.state())
        self.assertNotIn('disabled',self.app.update_button.state())

    def test_atualizacao_congela_versao_durante_download(self):
        from unittest.mock import patch
        release={'version':'v2.0.0','assets':{'hide-pdf-fields-windows.zip':{'sha256':'a'*64}}}
        newer={'version':'v3.0.0','assets':{'hide-pdf-fields-windows.zip':{'sha256':'b'*64}}}
        self.app.update_info=release
        with patch('interface.messagebox.askyesno',return_value=True), patch('interface.threading.Thread'):
            self.app.begin_update()
        self.app.update_queue.put(('checked',newer))
        self.app.update_queue.put(('downloaded',Path(self.tmp.name)))
        with patch('interface.messagebox.showinfo'), patch('interface.subprocess.CREATE_NEW_CONSOLE',0,create=True), patch('interface.subprocess.Popen') as launch, patch.object(self.app,'close'):
            self.app.poll_update()
        args=launch.call_args.args[0]
        self.assertIn('v2.0.0',args)
        self.assertIn('a'*64,args)
        self.assertNotIn('v3.0.0',args)

    def test_pedido_multipagina_mostra_descarte_antes_de_processar(self):
        import pymupdf as pdf
        src=self.folder/'A.pdf'
        with pdf.open(src) as d:
            d.new_page(); data=d.tobytes()
        src.write_bytes(data)
        self.app.load()
        self.pump(lambda:self.app.page_counts.get(0)==2)
        self.assertIn('página 1 de 2',self.app.original_title.get())
        labels=[w.cget('text') for w in self.app.fields_frame.winfo_children() if w.winfo_class()=='TCheckbutton']
        self.assertTrue(any('serão descartadas' in label for label in labels))

    def test_lote_previews_resize_e_ampliacao(self):
        self.assertEqual(self.root.title(),'Ocultar Dados - Pedido Interno e NFe')
        self.assertIsNotNone(self.app.window_icon)
        self.assertEqual(self.app.window_icon.width(),512)
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
