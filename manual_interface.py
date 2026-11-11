"""Visualizador manual de PDFs: etapa inicial somente de leitura."""
from pathlib import Path
import copy
import re
import unicodedata
from datetime import datetime
from concurrent.futures.process import BrokenProcessPool
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from manual_pdf import ESCALA_100, ManualPdfErro, inspecionar, renderizar, visualizar_aviso
from tarjar import CORES
from manual_export import ManualExportErro, exportar
from ui_components import ColorSelector, add_tooltip, help_button, icon


def _nome_seguro(texto):
    texto = unicodedata.normalize('NFKD', texto).encode('ascii','ignore').decode('ascii')
    return re.sub(r'[^A-Za-z0-9_]', '', re.sub(r'\s+', '_', texto)).strip('_')


class ConferenciaManual:
    """Navega exclusivamente no PDF efetivamente salvo e vinculado ao hash."""
    def __init__(self, parent, executor, resultado, ao_fechar=lambda: None, executor_quebrado=lambda: None):
        self.executor=executor
        self.executor_quebrado=executor_quebrado
        self.resultado=copy.deepcopy(resultado)
        self.ao_fechar=ao_fechar
        self.closed=False
        self.page=0
        self.token=0
        self.future=None
        self.request=None
        self.image=None
        self.window=tk.Toplevel(parent)
        self.window.title('Conferência — resultado salvo')
        self.window.geometry('900x700');self.window.minsize(600,450)
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        self.window.columnconfigure(0,weight=1);self.window.rowconfigure(2,weight=1)
        self.icons = []
        header=ttk.Frame(self.window,padding=(12,10));header.grid(row=0,column=0,sticky='ew')
        ttk.Label(header,text='Resultado salvo:').pack(side='left')
        self.filename=tk.StringVar(value=Path(resultado['destino']).name)
        ttk.Entry(header,textvariable=self.filename,state='readonly').pack(side='left',fill='x',expand=True,padx=8)
        nav=ttk.Frame(self.window,padding=(12,0,12,5));nav.grid(row=1,column=0,sticky='ew')
        self.prev=ttk.Button(nav,text='Anterior',command=lambda:self.go(-1));self.prev.pack(side='left')
        self.label=tk.StringVar(value='Carregando resultado…')
        ttk.Label(nav,textvariable=self.label).pack(side='left',padx=10)
        self.next=ttk.Button(nav,text='Próxima',command=lambda:self.go(1));self.next.pack(side='left')
        for button, name, hint in ((self.prev, 'previous', 'Ver a página anterior do resultado.'),
                                   (self.next, 'next', 'Ver a próxima página do resultado.')):
            picture = icon(button, name); self.icons.append(picture)
            button.configure(image=picture, compound='left')
            add_tooltip(button, hint)
        self.help_button = help_button(nav, 'Ajuda — conferência',
            'Esta visualização mostra o PDF salvo. Confira todas as páginas e use as barras de rolagem para ver os detalhes. '
            'Volte ao editor para alterar as marcações e gerar outra cópia.')
        self.help_button.configure(text='Ajuda da conferência')
        self.help_button.pack(side='right')
        box=ttk.Frame(self.window,padding=(12,0));box.grid(row=2,column=0,sticky='nsew')
        box.columnconfigure(0,weight=1);box.rowconfigure(0,weight=1)
        self.canvas=tk.Canvas(box,background='#e9ecef',takefocus=True)
        self.canvas.grid(row=0,column=0,sticky='nsew')
        sy=ttk.Scrollbar(box,orient='vertical',command=self.canvas.yview);sy.grid(row=0,column=1,sticky='ns')
        sx=ttk.Scrollbar(box,orient='horizontal',command=self.canvas.xview);sx.grid(row=1,column=0,sticky='ew')
        self.canvas.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        self.canvas.bind('<MouseWheel>',self._wheel)
        self.canvas.bind('<Shift-MouseWheel>',self._wheel_x)
        self.canvas.bind('<Button-4>',lambda e:self._scroll('y',-3))
        self.canvas.bind('<Button-5>',lambda e:self._scroll('y',3))
        for key,axis,amount in [('<Up>','y',-1),('<Down>','y',1),('<Left>','x',-1),('<Right>','x',1)]:
            self.canvas.bind(key,lambda event,a=axis,n=amount:self._scroll(a,n))
        self.canvas.bind('<Button-1>',lambda e:self.canvas.focus_set())
        foot=ttk.Frame(self.window,padding=(12,8));foot.grid(row=3,column=0,sticky='ew')
        self.return_button=ttk.Button(foot,text='Voltar ao editor',command=self.close)
        self.return_button.pack(side='right')
        add_tooltip(self.return_button, 'Voltar às marcações preservadas no editor.')
        ttk.Label(foot,text='Confira todas as páginas antes de compartilhar.',wraplength=450).pack(side='left')
        self.status=tk.StringVar(value=('PDF salvo. Um arquivo temporário adicional pode permanecer na pasta de destino.'
                                        if resultado.get('limpeza_pendente') else ''))
        self.status_label=ttk.Label(self.window,textvariable=self.status,justify='left',padding=(12,0,12,8))
        self.status_label.grid(row=4,column=0,sticky='ew')
        self.window.bind('<Configure>',self._resize_status)
        self.request_page(0);self.window.after(80,self.poll)

    def _resize_status(self,event):
        if event.widget is self.window:
            self.status_label.configure(wraplength=max(120,self.window.winfo_width()-32))

    def _scroll(self,axis,amount):
        getattr(self.canvas,axis+'view_scroll')(amount,'units');return 'break'

    def _wheel(self,event):
        return self._scroll('y', -1 if event.delta>0 else 1)

    def _wheel_x(self,event):
        return self._scroll('x', -1 if event.delta>0 else 1)

    def go(self,offset):
        index=self.page+offset
        if 0<=index<len(self.resultado['paginas_originais']):self.request_page(index)

    def request_page(self,index):
        self.page=index;self.token+=1
        self.request=(self.token,index);self.image=None
        self.canvas.delete('all');self.canvas.configure(scrollregion=(0,0,0,0))
        self.label.set(f"Carregando resultado {index+1} de {len(self.resultado['paginas_originais'])}…")
        self.prev.configure(state='normal' if index>0 else 'disabled')
        self.next.configure(state='normal' if index+1<len(self.resultado['paginas_originais']) else 'disabled')
        self._start()

    def _start(self):
        if self.closed or self.future is not None or self.request is None:return
        request=self.request;self.request=None
        try:
            future=self.executor().submit(renderizar,self.resultado['destino'],self.resultado['sha256_saida'],request[1])
        except Exception as error:
            if isinstance(error,BrokenProcessPool):self.executor_quebrado()
            self._invalidar();return
        self.future=(request,future)

    def _invalidar(self):
        self.token+=1;self.request=None;self.image=None
        self.canvas.delete('all');self.canvas.configure(scrollregion=(0,0,0,0))
        self.label.set(f"Resultado {self.page+1} de {len(self.resultado['paginas_originais'])} · original {self.resultado['paginas_originais'][self.page]+1}")
        aviso='Não foi possível conferir o arquivo salvo. Volte ao editor e verifique o destino.'
        if self.resultado.get('limpeza_pendente'):
            aviso+=' Um arquivo temporário adicional pode permanecer na pasta de destino.'
        self.status.set(aviso)
        self.prev.configure(state='disabled');self.next.configure(state='disabled')

    def poll(self):
        if self.closed:return
        if self.future is not None and self.future[1].done():
            request,future=self.future;self.future=None
            if request[0]==self.token:
                try:self.image=tk.PhotoImage(master=self.window,data=future.result())
                except Exception as error:
                    if isinstance(error,BrokenProcessPool):self.executor_quebrado()
                    self._invalidar()
                else:
                    self.canvas.delete('all');self.canvas.create_image(0,0,anchor='nw',image=self.image)
                    self.canvas.configure(scrollregion=(0,0,self.image.width(),self.image.height()))
                    self.canvas.xview_moveto(0);self.canvas.yview_moveto(0)
                    original=self.resultado['paginas_originais'][self.page]+1
                    self.label.set(f"Resultado {self.page+1} de {len(self.resultado['paginas_originais'])} · original {original}")
        self._start();self.window.after(80,self.poll)

    def close(self):
        if self.closed:return
        self.closed=True;self.token+=1;self.request=None
        if self.future is not None:self.future[1].cancel()
        self.image=None
        self.window.destroy()
        self.icons.clear()
        self.filename=None;self.label=None;self.status=None
        self.ao_fechar()


class VisualizadorManual:
    """A interface vive no processo principal; inspeção/renderização usam o executor compartilhado."""

    def __init__(self, parent, executor, ocupado=lambda: False, ao_fechar=lambda: None, executor_quebrado=lambda: None, ao_iniciar_exportacao=lambda: None, ao_encerrar_exportacao=lambda: None):
        self.parent = parent
        self.executor = executor
        self.ocupado = ocupado
        self.ao_fechar = ao_fechar
        self.executor_quebrado = executor_quebrado
        self.ao_iniciar_exportacao = ao_iniciar_exportacao
        self.ao_encerrar_exportacao = ao_encerrar_exportacao
        self.exporting = False
        self.export_future = None
        self.result_viewer = None
        self.closed = False
        self.document = None
        self.path = None
        self.page = 0
        self.excluded_pages = set()
        # Retângulos em pontos relativos à origem visível da página; IDs não mudam na sessão.
        self.marks = {}
        self.selected_mark_id = None
        self.next_mark_id = 1
        self.notice_area = None
        self.notice_image = None
        self.notice_text = None
        self.notice_token = 0
        self.notice_request = None
        self.notice_future = None
        self.notice_after = None
        self.session_id = 0
        self.drag = None
        self.page_image_id = None
        self.image = None
        self.inspect_future = None
        self.inspect_path = None
        self.render_future = None
        self.render_token = 0
        self.render_request = None

        self.window = tk.Toplevel(parent)
        self.window.title('Modo manual — edição')
        self.icons = []
        self.window.geometry('960x720')
        self.window.minsize(600, 450)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(3, weight=1)

        header = ttk.Frame(self.window, padding=(12, 6, 12, 3))
        header.grid(row=0, column=0, sticky='ew')
        header.columnconfigure(1, weight=1)
        self.open_button = ttk.Button(header, text='Abrir PDF…', command=self.choose)
        self.open_button.grid(row=0, column=0, sticky='w')
        self.filename = tk.StringVar(value='Nenhum PDF aberto')
        self.filename_entry = ttk.Entry(header, textvariable=self.filename, state='readonly')
        self.filename_entry.grid(row=0, column=1, sticky='ew', padx=12)
        ttk.Label(header, text='Visualização: 100%').grid(row=0, column=2, sticky='e')
        add_tooltip(self.open_button, 'Escolher um arquivo PDF para editar.')
        add_tooltip(self.filename_entry, 'Arquivo aberto; use as setas para percorrer nomes longos.')
        picture = icon(self.open_button, 'open'); self.icons.append(picture)
        self.open_button.configure(image=picture, compound='left')

        navigation = ttk.Frame(self.window, padding=(12, 0, 12, 2))
        navigation.grid(row=1, column=0, sticky='ew')
        self.prev_button = ttk.Button(navigation, text='Anterior', command=lambda: self.go(-1))
        self.prev_button.pack(side='left')
        self.page_label = tk.StringVar(value='Nenhuma página aberta')
        ttk.Label(navigation, textvariable=self.page_label).pack(side='left', padx=12)
        self.next_button = ttk.Button(navigation, text='Próxima', command=lambda: self.go(1))
        self.next_button.pack(side='left')
        for button, name, hint in ((self.prev_button, 'previous', 'Ir para a página anterior.'),
                                   (self.next_button, 'next', 'Ir para a próxima página.')):
            picture = icon(button, name); self.icons.append(picture)
            button.configure(image=picture, compound='left')
            add_tooltip(button, hint)
        self.help_button = help_button(navigation, 'Ajuda — modo manual',
            'Abra um PDF e navegue pelas páginas. Escolha Desenhar tarja e arraste sobre cada área que deseja ocultar. '
            'Para refazer uma tarja, escolha Selecionar, clique nela e apague. Informe o destinatário, escolha Definir área do aviso e arraste no documento. '
            'Você pode excluir páginas e restaurá-las antes de gerar. As marcações só são aplicadas ao gerar o PDF; confira o resultado salvo antes de compartilhar.')
        self.help_button.configure(text='Ajuda do editor')
        self.help_button.pack(side='right')

        tools = ttk.Frame(self.window, padding=(12, 0, 12, 2))
        tools.grid(row=2, column=0, sticky='ew')
        self.tool = tk.StringVar(value='desenhar')
        self.draw_button = ttk.Radiobutton(tools, text='Desenhar tarja', variable=self.tool,
                                           value='desenhar', command=self._tool_changed)
        self.draw_button.grid(row=0, column=0, sticky='w')
        self.select_button = ttk.Radiobutton(tools, text='Selecionar', variable=self.tool,
                                             value='selecionar', command=self._tool_changed)
        self.select_button.grid(row=0, column=1, sticky='w', padx=(8,0))
        self.delete_button = ttk.Button(tools, text='Apagar tarja selecionada', command=self.delete_selected)
        self.delete_button.grid(row=0, column=2, sticky='w', padx=(8,0))
        ttk.Label(tools, text='Cor da nova tarja:').grid(row=1, column=0, sticky='w', pady=(1,0))
        self.mark_color = tk.StringVar(value=CORES['preto'][0])
        self.color_selector = ColorSelector(tools, textvariable=self.mark_color, colors=CORES, width=13)
        self.color_combo = self.color_selector.combo
        self.color_selector.grid(row=1, column=1, sticky='w', pady=(1,0))
        add_tooltip(self.color_combo, 'Cor aplicada às próximas tarjas desenhadas.')
        recipient_box=ttk.Frame(tools)
        recipient_box.grid(row=1, column=2, sticky='ew', padx=(8,0), pady=(1,0))
        ttk.Label(recipient_box,text='Destinatário:').pack(side='left')
        self.recipient=tk.StringVar(value='')
        self.recipient_entry=ttk.Entry(recipient_box,textvariable=self.recipient,width=16)
        self.recipient_entry.pack(side='left',fill='x',expand=True,padx=(5,0))
        add_tooltip(self.recipient_entry, 'Nome de quem receberá a cópia; será incluído no aviso.')
        add_tooltip(self.draw_button, 'Arraste sobre o conteúdo que deseja ocultar.')
        add_tooltip(self.select_button, 'Clique em uma tarja para selecioná-la e apagá-la.')
        add_tooltip(self.delete_button, 'Apagar a tarja selecionada; depois você pode desenhá-la novamente.')
        self.tool.trace_add('write', self._tool_changed)
        self.mark_color.trace_add('write', self._color_changed)
        self.preview_warning = ttk.Label(tools, text='As marcações ainda não ocultam dados. O aviso pode cobrir conteúdo do documento.', wraplength=280)
        self.preview_warning.grid(row=2, column=0, columnspan=3, sticky='w', pady=(1,0))
        self.selection_status = tk.StringVar(value='Sem seleção.')
        self.selection_label = ttk.Label(tools, textvariable=self.selection_status, anchor='e')
        self.selection_label.grid(row=3, column=2, sticky='e', padx=(8,0), pady=(1,0))
        self.notice_button=ttk.Radiobutton(tools,text='Definir área do aviso',variable=self.tool,
                                           value='aviso',command=self._tool_changed)
        self.notice_button.grid(row=3,column=0,sticky='w',pady=(1,0))
        self.notice_remove_button=ttk.Button(tools,text='Remover área do aviso',command=self.remove_notice)
        self.notice_remove_button.grid(row=3,column=1,sticky='w',padx=(8,0),pady=(1,0))
        add_tooltip(self.notice_button, 'Arraste para escolher onde inserir o aviso de destinatário.')
        add_tooltip(self.notice_remove_button, 'Remover a área escolhida para posicionar o aviso novamente.')
        self.notice_status=tk.StringVar(value='Nenhuma área de aviso definida.')
        self.notice_status_label=ttk.Label(tools,textvariable=self.notice_status,wraplength=560,justify='left')
        self.notice_status_label.grid(row=4,column=0,columnspan=3,sticky='w',pady=(1,0))
        self.notice_warning=self.preview_warning
        self.recipient.trace_add('write',self._recipient_changed)

        viewer = ttk.Frame(self.window, padding=(12, 0, 12, 0))
        viewer.grid(row=3, column=0, sticky='nsew')
        viewer.columnconfigure(0, weight=1)
        viewer.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(viewer, background='#e9ecef', highlightthickness=1,
                                highlightbackground='#b9bec4', takefocus=True)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        vertical = ttk.Scrollbar(viewer, orient='vertical', command=lambda *args:self._viewport('y', *args))
        horizontal = ttk.Scrollbar(viewer, orient='horizontal', command=lambda *args:self._viewport('x', *args))
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        self.canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.canvas.bind('<MouseWheel>', self._wheel_vertical)
        self.canvas.bind('<Shift-MouseWheel>', self._wheel_horizontal)
        self.canvas.bind('<Button-4>', lambda _: self._scroll('y', -3))
        self.canvas.bind('<Button-5>', lambda _: self._scroll('y', 3))
        for key, axis, amount in [('<Up>', 'y', -1), ('<Down>', 'y', 1),
                                  ('<Left>', 'x', -1), ('<Right>', 'x', 1),
                                  ('<Prior>', 'y', -12), ('<Next>', 'y', 12)]:
            self.canvas.bind(key, lambda event, a=axis, n=amount: self._scroll(a, n))
        self.canvas.bind('<ButtonPress-1>', self._pointer_down)
        self.canvas.bind('<B1-Motion>', self._pointer_move)
        self.canvas.bind('<ButtonRelease-1>', self._pointer_up)
        self.canvas.bind('<Escape>', self._cancel_drag)
        self.canvas.bind('<Delete>', self._delete_key)
        self.canvas.bind('<BackSpace>', self._delete_key)

        page_options = ttk.Frame(self.window, padding=(12, 2, 12, 0))
        page_options.grid(row=4, column=0, sticky='ew')
        page_options.columnconfigure(1, weight=1)
        self.exclude_button = ttk.Button(page_options, text='Excluir página', command=self.toggle_exclusion)
        self.exclude_button.grid(row=0, column=0, sticky='nw')
        add_tooltip(self.exclude_button, 'Excluir ou restaurar a página atual na cópia gerada.')
        self.exclusion_status = tk.StringVar(value='')
        self.exclusion_label = ttk.Label(page_options, textvariable=self.exclusion_status, wraplength=400, justify='left')
        self.exclusion_label.grid(row=0, column=1, sticky='ew', padx=(12,0))

        self.export_button = ttk.Button(page_options,text='Gerar PDF…',command=self.generate)
        self.export_button.grid(row=0,column=2,sticky='ne',padx=(8,0))
        picture = icon(self.export_button, 'export'); self.icons.append(picture)
        self.export_button.configure(image=picture, compound='left')
        add_tooltip(self.export_button, 'Salvar uma nova cópia com as páginas e marcações escolhidas.')
        self.export_progress = ttk.Progressbar(self.window,mode='indeterminate',length=120)
        self.status = tk.StringVar(value='Abra um PDF para visualizar e marcar áreas. O original não será alterado.')
        self.status_label = ttk.Label(self.window, textvariable=self.status, wraplength=570, padding=(12, 3, 12, 3))
        self.status_label.grid(row=5, column=0, sticky='ew')
        self.window.bind('<Configure>', self._resize_status)
        self._controls()
        self.window.after_idle(self.open_button.focus_set)
        self.window.after(80, self.poll)

    def _resize_status(self, event):
        if event.widget == self.window:
            width = self.window.winfo_width()
            if width <= 1:
                return
            self.status_label.configure(wraplength=max(120, width-32))
            self.exclusion_label.configure(wraplength=max(120, width-300))
            self.notice_status_label.configure(wraplength=max(120,width-32))
            self.notice_warning.configure(wraplength=max(120,width-32))

    def _viewport(self, axis, *args):
        if self.drag is None:
            getattr(self.canvas, axis + 'view')(*args)

    def _scroll(self, axis, amount):
        if self.drag is None:
            getattr(self.canvas, axis + 'view_scroll')(amount, 'units')
        return 'break'

    @staticmethod
    def _wheel_amount(event):
        delta = event.delta
        if not delta:
            return 0
        # Windows often uses multiples of 120; macOS may send small deltas.
        return -int(delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)

    def _wheel_vertical(self, event):
        return self._scroll('y', self._wheel_amount(event))

    def _wheel_horizontal(self, event):
        return self._scroll('x', self._wheel_amount(event))

    def _busy(self):
        return self.exporting or bool(self.ocupado())

    def _controls(self):
        busy = bool(self._busy())
        opening = self.inspect_future is not None
        self.open_button.configure(state='disabled' if busy or opening else 'normal')
        self.export_button.configure(state='normal' if self.document is not None and not busy and not opening and self.image is not None and self.render_future is None and self.render_request is None else 'disabled')
        usable = self.document is not None and not busy and not opening
        self.prev_button.configure(state='normal' if usable and self.page > 0 else 'disabled')
        self.next_button.configure(state='normal' if usable and self.page + 1 < self.document['total_paginas'] else 'disabled')
        editing = (usable and self.image is not None and self.render_future is None
                   and self.render_request is None and self.page not in self.excluded_pages)
        self.draw_button.configure(state='normal' if editing else 'disabled')
        self.select_button.configure(state='normal' if editing else 'disabled')
        self.notice_button.configure(state='normal' if editing and self.notice_area is None else 'disabled')
        removable = usable and self.image is not None and self.render_future is None and self.render_request is None and self.notice_area is not None
        self.notice_remove_button.configure(state='normal' if removable else 'disabled')
        self.recipient_entry.configure(state='normal' if not busy and not opening else 'disabled')
        self.color_combo.configure(state='readonly' if editing else 'disabled')
        self.delete_button.configure(state='normal' if editing and self.selected_mark_id is not None else 'disabled')
        self.selection_status.set('Tarja selecionada.' if self.selected_mark_id is not None
                                  else 'Sem seleção.')
        cursor = 'crosshair' if editing and self.tool.get() in ('desenhar','aviso') else ''
        if self.canvas.cget('cursor') != cursor:
            self.canvas.configure(cursor=cursor)
        if not editing and self.drag is not None:
            self._cancel_drag()
        if not self.document:
            self.exclude_button.configure(text='Excluir página', state='disabled')
            self.exclusion_status.set('')
            return
        total = self.document['total_paginas']
        excluded = self.page in self.excluded_pages
        remaining = total - len(self.excluded_pages)
        last_retained = not excluded and remaining <= 1
        ready = usable and self.image is not None and self.render_future is None and self.render_request is None
        self.exclude_button.configure(text='Restaurar página' if excluded else 'Excluir página',
                                      state='normal' if ready and not last_retained else 'disabled')
        page_state = 'Excluída do resultado' if excluded else 'Página mantida no resultado'
        summary = f'Resultado previsto: {remaining} páginas · {len(self.excluded_pages)} excluídas'
        reason = '\nO resultado precisa manter pelo menos uma página.' if last_retained else ''
        self.exclusion_status.set(f'{page_state} · {summary}{reason}')

    def toggle_exclusion(self):
        if (self.closed or self._busy() or self.inspect_future is not None or not self.document
                or self.image is None or self.render_future is not None or self.render_request is not None):
            return
        if self.page in self.excluded_pages:
            self.excluded_pages.remove(self.page)
        elif self.document['total_paginas'] - len(self.excluded_pages) > 1:
            self.excluded_pages.add(self.page)
        self.selected_mark_id = None
        self._refresh_notice()
        self._redraw_marks()
        self._controls()

    def _can_edit(self):
        return bool(not self.closed and not self._busy() and self.inspect_future is None
                    and self.document is not None and self.image is not None
                    and self.render_future is None and self.render_request is None
                    and self.page not in self.excluded_pages and self.page_image_id is not None)

    def _tool_changed(self, *_):
        self._cancel_drag()
        if self.tool.get() in ('desenhar','aviso'):
            self.selected_mark_id = None
        self._redraw_marks()
        self._controls()

    def _color_changed(self, *_):
        self._cancel_drag()

    def _page_point(self, event, clamp=False):
        if not self.document or self.page_image_id is None:
            return None
        origin = self.canvas.coords(self.page_image_id)
        if len(origin) != 2:
            return None
        geometry = self.document['paginas'][self.page]
        x = (self.canvas.canvasx(event.x) - origin[0]) / ESCALA_100
        y = (self.canvas.canvasy(event.y) - origin[1]) / ESCALA_100
        width, height = geometry['largura'], geometry['altura']
        if not clamp and not (0 <= x <= width and 0 <= y <= height):
            return None
        return max(0.0, min(width, x)), max(0.0, min(height, y))

    def _gesture_valid(self):
        return bool(self.drag and self._can_edit() and self.tool.get() == self.drag['mode']
                    and self.drag['session'] == self.session_id
                    and self.drag['page'] == self.page
                    and self.drag['token'] == self.render_token
                    and self.drag['sha256'] == self.document['sha256']
                    and (self.drag['mode']=='aviso' or (self.drag['cor'] in CORES
                         and self.mark_color.get() == CORES[self.drag['cor']][0])))

    def _pointer_down(self, event):
        self.canvas.focus_set()
        if not self._can_edit():
            return 'break'
        self._cancel_drag()
        point = self._page_point(event)
        if point is None:
            self.selected_mark_id = None
            self._redraw_marks()
            self._controls()
            return 'break'
        if self.tool.get() == 'selecionar':
            x, y = point
            match = next((mark for mark in reversed(self.marks.get(self.page, []))
                          if mark['rect'][0] <= x <= mark['rect'][2]
                          and mark['rect'][1] <= y <= mark['rect'][3]), None)
            self.selected_mark_id = match['id'] if match else None
            self._redraw_marks()
            self._controls()
            return 'break'
        mode = self.tool.get()
        if mode not in ('desenhar','aviso') or (mode=='aviso' and self.notice_area is not None):
            return 'break'
        color = next((key for key, (label, _) in CORES.items() if label == self.mark_color.get()), None) if mode=='desenhar' else None
        if mode=='desenhar' and color is None:
            return 'break'
        self.selected_mark_id = None
        self._redraw_marks()
        self.drag = {'session': self.session_id, 'page': self.page, 'token': self.render_token,
                     'sha256': self.document['sha256'], 'start': point, 'cor': color, 'mode': mode}
        self._controls()
        return 'break'

    def _pointer_move(self, event):
        if self.drag is None:
            return 'break'
        if not self._gesture_valid():
            self._cancel_drag()
            return 'break'
        point = self._page_point(event, clamp=True)
        if point is None:
            self._cancel_drag()
            return 'break'
        self.canvas.delete('draft')
        x0, y0 = self.drag['start']
        x1, y1 = point
        origin = self.canvas.coords(self.page_image_id)
        self.canvas.create_rectangle(origin[0] + x0*ESCALA_100, origin[1] + y0*ESCALA_100,
                                     origin[0] + x1*ESCALA_100, origin[1] + y1*ESCALA_100,
                                     outline='#ffffff', width=5, tags=('draft',))
        self.canvas.create_rectangle(origin[0] + x0*ESCALA_100, origin[1] + y0*ESCALA_100,
                                     origin[0] + x1*ESCALA_100, origin[1] + y1*ESCALA_100,
                                     outline='#7b168d' if self.drag['mode']=='aviso' else '#003b70',
                                     width=2, dash=(4, 2), tags=('draft',))
        return 'break'

    def _pointer_up(self, event):
        if self.drag is None:
            return 'break'
        if not self._gesture_valid():
            self._cancel_drag()
            return 'break'
        point = self._page_point(event, clamp=True)
        if point is None:
            self._cancel_drag()
            return 'break'
        x0, y0 = self.drag['start']
        x1, y1 = point
        rect = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        color,mode = self.drag['cor'],self.drag['mode']
        self._cancel_drag()
        if rect[2] > rect[0] and rect[3] > rect[1]:
            if mode == 'aviso':
                self.notice_area = {'pagina': self.page, 'rect': rect}
                self.tool.set('selecionar')
                self._refresh_notice()
            else:
                mark = {'id': self.next_mark_id, 'rect': rect, 'cor': color}
                self.next_mark_id += 1
                self.marks.setdefault(self.page, []).append(mark)
        self._redraw_marks()
        self._controls()
        return 'break'

    def _cancel_drag(self, *_):
        self.drag = None
        if hasattr(self, 'canvas'):
            self.canvas.delete('draft')
        return 'break'

    def _redraw_marks(self):
        if not hasattr(self, 'canvas'):
            return
        self.canvas.delete('mark')
        self.canvas.delete('notice')
        if self.image is None or self.page_image_id is None:
            return
        origin = self.canvas.coords(self.page_image_id)
        if len(origin) != 2:
            return
        for mark in self.marks.get(self.page, []):
            x0,y0,x1,y1 = mark['rect']
            coords = (origin[0]+x0*ESCALA_100, origin[1]+y0*ESCALA_100,
                      origin[0]+x1*ESCALA_100, origin[1]+y1*ESCALA_100)
            color = '#%02x%02x%02x' % CORES[mark['cor']][1]
            self.canvas.create_rectangle(*coords, fill=color, stipple='gray50',
                                         outline='#ffffff', width=5, tags=('mark',))
            selected = mark['id'] == self.selected_mark_id
            self.canvas.create_rectangle(*coords, outline='#005fcc' if selected else '#000000',
                                         width=3 if selected else 2, dash=(5,3) if selected else (), tags=('mark',))
        if self.notice_area is not None and self.notice_area['pagina'] == self.page:
            x0,y0,x1,y1 = self.notice_area['rect']
            coords = (origin[0]+x0*ESCALA_100, origin[1]+y0*ESCALA_100,
                      origin[0]+x1*ESCALA_100, origin[1]+y1*ESCALA_100)
            if self.notice_image is not None and self.page not in self.excluded_pages:
                self.canvas.create_image(coords[0],coords[1],anchor='nw',image=self.notice_image,tags=('notice',))
            self.canvas.create_rectangle(*coords,outline='#ffffff',width=5,tags=('notice',))
            self.canvas.create_rectangle(*coords,outline='#7b168d',width=2,dash=(2,3),tags=('notice',))

    def delete_selected(self):
        if not self._can_edit() or self.tool.get() != 'selecionar' or self.selected_mark_id is None:
            return
        marks = self.marks.get(self.page, [])
        self.marks[self.page] = [mark for mark in marks if mark['id'] != self.selected_mark_id]
        if not self.marks[self.page]:
            self.marks.pop(self.page, None)
        self.selected_mark_id = None
        self._redraw_marks()
        self._controls()

    def _delete_key(self, _event):
        self.delete_selected()
        return 'break'

    def _recipient_changed(self, *_):
        self._cancel_drag()
        self._refresh_notice()

    def _cancel_notice_timer(self):
        if self.notice_after is not None:
            self.window.after_cancel(self.notice_after)
            self.notice_after = None

    def _refresh_notice(self):
        """Invalida resultados antigos e agenda apenas a prévia mais recente."""
        self.notice_token += 1
        self._cancel_notice_timer()
        self.notice_request = None
        self.notice_image = None
        self.notice_text = None
        area = self.notice_area
        if area is None or self.document is None:
            self.notice_status.set('Nenhuma área de aviso definida.')
        elif area['pagina'] in self.excluded_pages:
            self.notice_status.set(f"Aviso na página {area['pagina']+1} inativo: página excluída. Restaure-a ou remova a área.")
        elif not self.recipient.get().strip():
            self.notice_status.set(f"Aviso na página {area['pagina']+1}: informe o destinatário para visualizar.")
        else:
            instante = datetime.now().astimezone().replace(second=0,microsecond=0)
            request = {'token':self.notice_token,'session':self.session_id,'render_token':self.render_token,
                       'pagina_atual':self.page,'sha256':self.document['sha256'],
                       'area':(area['pagina'],tuple(area['rect'])), 'destinatario':self.recipient.get(),
                       'instante':instante.isoformat(), 'data':instante.strftime('%d/%m/%y %H:%M')}
            self.notice_status.set(f"Preparando prévia do aviso na página {area['pagina']+1}…")
            self.notice_after = self.window.after(180,lambda req=request:self._queue_notice(req))
        self._redraw_marks()

    def _queue_notice(self, request):
        self.notice_after = None
        if self.closed or request['token'] != self.notice_token:
            return
        self.notice_request = request
        self._start_notice()

    def _start_notice(self):
        if self.closed or self._busy() or self.notice_future is not None or self.notice_request is None:
            return
        request = self.notice_request
        self.notice_request = None
        rect = request['area'][1]
        try:
            future = self.executor().submit(visualizar_aviso, request['destinatario'],
                                            rect[2]-rect[0], rect[3]-rect[1], request['instante'])
        except Exception as error:
            self.notice_status.set(self._message(error))
            return
        self.notice_future = (request, future)

    def _notice_current(self, request):
        return bool(self.document and self.notice_area and request['token']==self.notice_token
                    and request['session']==self.session_id and request['render_token']==self.render_token
                    and request['pagina_atual']==self.page and request['sha256']==self.document['sha256']
                    and request['area']==(self.notice_area['pagina'],tuple(self.notice_area['rect']))
                    and request['destinatario']==self.recipient.get()
                    and self.notice_area['pagina'] not in self.excluded_pages)

    def remove_notice(self):
        if (self.closed or self._busy() or self.inspect_future is not None or self.document is None
                or self.image is None or self.render_future is not None or self.render_request is not None
                or self.notice_area is None):
            return
        self._cancel_drag()
        self.notice_area = None
        self._refresh_notice()
        self._controls()

    def generate(self):
        """Solicita consentimento e congela as escolhas antes de usar o trabalhador."""
        if (self.closed or self._busy() or self.inspect_future is not None or not self.document
                or self.image is None or self.render_future is not None or self.render_request is not None):
            return
        if self.notice_area is None:
            messagebox.showerror('Aviso necessário','Defina a área do aviso antes de gerar o PDF.',parent=self.window);return
        if self.notice_area['pagina'] in self.excluded_pages:
            messagebox.showerror('Aviso em página excluída','Restaure a página do aviso ou remova e redefina sua área.',parent=self.window);return
        nome=self.recipient.get().strip()
        if not nome:
            messagebox.showerror('Destinatário necessário','Informe o destinatário do documento.',parent=self.window);self.recipient_entry.focus_set();return
        instante=datetime.now().astimezone()
        nome_destino=_nome_seguro(nome)
        nome_arquivo=_nome_seguro(Path(self.path).stem)
        if not nome_destino or not nome_arquivo:
            messagebox.showerror('Nome inválido','O destinatário e o nome original precisam conter letras ou números.',parent=self.window);return
        suggested=f"{nome_destino}-{instante:%d%m%y}-{nome_arquivo}.pdf"
        destino=filedialog.asksaveasfilename(parent=self.window,title='Salvar PDF processado',
                    initialdir=str(Path(self.path).parent),initialfile=suggested,defaultextension='.pdf',
                    filetypes=[('Arquivos PDF','*.pdf')])
        if not destino:return
        path=Path(destino)
        try:
            if path.suffix.lower()!='.pdf' or path.resolve()==Path(self.path).resolve() or path.exists():
                raise ValueError
        except (ValueError,OSError):
            messagebox.showerror('Destino inválido','Escolha um novo arquivo PDF que não exista e seja diferente do original.',parent=self.window);return
        recursos=self.document.get('recursos',[])
        detalhes=('\n\nRecursos detectados: '+', '.join(recursos)+'.') if recursos else ''
        message=('A cópia será convertida em imagem. Texto selecionável, links, formulários, anexos e recursos de acessibilidade não serão preservados. '
                 'Assinaturas digitais do original não serão válidas na cópia. O arquivo original permanece inalterado.'
                 +detalhes+'\n\nDeseja gerar o PDF?')
        if not messagebox.askyesno('Gerar cópia em PDF?',message,parent=self.window):return
        instante=datetime.now().astimezone()
        snapshot={'origem':str(self.path),'sha256_origem':self.document['sha256'],'destino':str(path),
                  'excluidas':sorted(self.excluded_pages),
                  'marcas':{int(k):[{'rect':list(m['rect']),'cor':m['cor']} for m in marks] for k,marks in self.marks.items()},
                  'aviso':{'pagina':self.notice_area['pagina'],'rect':list(self.notice_area['rect'])},
                  'destinatario':nome,'instante':instante.isoformat(),'dpi':300}
        self._cancel_drag()
        self.exporting=True
        self.export_snapshot=copy.deepcopy(snapshot)
        self.ao_iniciar_exportacao()
        self.status.set('Gerando e verificando o PDF. Aguarde…')
        self.export_progress.grid(row=6,column=0,sticky='ew',padx=12,pady=(0,6));self.export_progress.start(12)
        self._controls()
        try:self.export_future=self.executor().submit(exportar,copy.deepcopy(snapshot))
        except Exception as error:
            self.export_future=None
            self._finish_export(error=error)

    def _finish_export(self,resultado=None,error=None):
        self.export_progress.stop();self.export_progress.grid_remove()
        self.exporting=False
        self.ao_encerrar_exportacao()
        self._controls()
        if error is not None:
            if isinstance(error,BrokenProcessPool):self.executor_quebrado()
            texto=str(error) if isinstance(error,ManualExportErro) else 'Não foi possível gerar o PDF. Confira o arquivo e o destino.'
            self.status.set('Não foi possível gerar o PDF. As escolhas continuam no editor.')
            messagebox.showerror('Geração não concluída',texto,parent=self.window)
            return
        if resultado.get('limpeza_pendente'):
            self.status.set('PDF salvo. Um arquivo temporário adicional pode permanecer na pasta de destino.')
        else:
            self.status.set('PDF gerado. Alterações no editor não modificam a cópia salva.')
        if self.result_viewer is not None and not self.result_viewer.closed:self.result_viewer.close()
        def closed():
            self.result_viewer=None
            if not self.closed:self.window.lift()
        try:self.result_viewer=ConferenciaManual(self.window,self.executor,resultado,closed,self.executor_quebrado)
        except Exception:
            self.result_viewer=None
            messagebox.showerror('Conferência indisponível','O PDF foi gerado, mas não foi possível abrir a conferência. Verifique o arquivo salvo.',parent=self.window)

    def choose(self):
        if self.closed or self._busy() or self.inspect_future is not None:
            return
        path = filedialog.askopenfilename(parent=self.window, title='Abrir PDF',
                                          filetypes=[('Arquivos PDF', '*.pdf')])
        if path:
            self.open_path(path)

    def open_path(self, path):
        """Solicita inspeção sem descartar o documento anterior em caso de recusa."""
        if self.closed or self._busy() or self.inspect_future is not None:
            return
        self._cancel_drag()
        self.inspect_path = str(Path(path))
        try:
            self.inspect_future = self.executor().submit(inspecionar, self.inspect_path)
        except Exception as error:
            self.inspect_path = None
            messagebox.showerror('Não foi possível abrir', self._message(error), parent=self.window)
            return
        self.status.set('Verificando o PDF…')
        self._controls()

    def go(self, offset):
        if self.closed or self._busy() or self.inspect_future is not None or not self.document:
            return
        index = self.page + offset
        if 0 <= index < self.document['total_paginas']:
            self.request_page(index)

    def request_page(self, index):
        self._cancel_drag()
        self.selected_mark_id = None
        self.page_image_id = None
        self.page = index
        self.render_token += 1
        self._refresh_notice()
        self.render_request = (self.render_token, self.path, self.document['sha256'], index)
        self.image = None
        self.canvas.delete('all')
        self.canvas.configure(scrollregion=(0, 0, 0, 0))
        self.page_label.set(f"Carregando página {index+1} de {self.document['total_paginas']}…")
        self.status.set('Carregando página…')
        self._controls()
        self._start_render()

    def _start_render(self):
        if self.closed or self._busy() or self.render_future is not None or self.render_request is None:
            return
        request = self.render_request
        self.render_request = None
        try:
            self.render_future = (request, self.executor().submit(renderizar, request[1], request[2], request[3]))
        except Exception as error:
            self._invalidate(self._message(error))

    def _invalidate(self, message):
        self._cancel_drag()
        self.session_id += 1
        self.marks.clear()
        self.selected_mark_id = None
        self.next_mark_id = 1
        self.notice_area = None
        self._refresh_notice()
        self.page_image_id = None
        self.render_token += 1
        self.render_request = None
        self.document = None
        self.path = None
        self.page = 0
        self.excluded_pages.clear()
        self.image = None
        self.canvas.delete('all')
        self.canvas.configure(scrollregion=(0, 0, 0, 0))
        self.filename.set('Nenhum PDF aberto')
        self.page_label.set('Nenhuma página aberta')
        self.status.set(message)
        self._controls()
        messagebox.showerror('Visualização indisponível', message, parent=self.window)

    def _message(self, error):
        if isinstance(error, BrokenProcessPool):
            self.executor_quebrado()
            return 'O processo de leitura foi encerrado. Abra o PDF novamente para tentar outra vez.'
        return str(error) if isinstance(error, ManualPdfErro) else 'Não foi possível ler o PDF. Confira o arquivo e tente novamente.'

    def poll(self):
        if self.closed:
            return
        if self.export_future is not None and self.export_future.done():
            future=self.export_future;self.export_future=None
            try:resultado=future.result()
            except Exception as error:self._finish_export(error=error)
            else:self._finish_export(resultado=resultado)
        if self.inspect_future is not None and self.inspect_future.done():
            future, candidate = self.inspect_future, self.inspect_path
            self.inspect_future = None
            self.inspect_path = None
            try:
                doc = future.result()
            except Exception as error:
                self.status.set('Não foi possível abrir o arquivo selecionado. A visualização anterior foi mantida.' if self.document else 'Nenhum PDF aberto.')
                messagebox.showerror('Não foi possível abrir o PDF', self._message(error), parent=self.window)
            else:
                self._cancel_drag()
                self.session_id += 1
                self.marks.clear()
                self.selected_mark_id = None
                self.next_mark_id = 1
                self.notice_area = None
                self._refresh_notice()
                self.document, self.path = doc, candidate
                self.excluded_pages.clear()
                self.filename.set(str(Path(candidate).name))
                self.request_page(0)
        if self.render_future is not None and self.render_future[1].done():
            request, future = self.render_future
            self.render_future = None
            if request[0] == self.render_token and self.document is not None:
                try:
                    data = future.result()
                    image = tk.PhotoImage(master=self.window, data=data)
                except Exception as error:
                    self._invalidate(self._message(error))
                else:
                    self.image = image
                    self.canvas.delete('all')
                    self.page_image_id = self.canvas.create_image(0, 0, anchor='nw', image=image)
                    self._redraw_marks()
                    self.canvas.configure(scrollregion=(0, 0, image.width(), image.height()))
                    self.canvas.xview_moveto(0)
                    self.canvas.yview_moveto(0)
                    self.page_label.set(f"Página {self.page+1} de {self.document['total_paginas']}")
                    self.status.set('As marcações não alteram o original. Gere e confira o PDF antes de compartilhar.')
            elif not future.cancelled():
                try:
                    future.result()
                except BrokenProcessPool:
                    self.executor_quebrado()
                except Exception:
                    pass
        if self.notice_future is not None and self.notice_future[1].done():
            request, future = self.notice_future
            self.notice_future = None
            if self._notice_current(request):
                try:
                    result=future.result()
                    self.notice_image=tk.PhotoImage(master=self.window,data=result['png'])
                    self.notice_text=result['texto']
                except Exception as error:
                    self.notice_image=None
                    self.notice_text=None
                    self.notice_status.set(f"Aviso na página {request['area'][0]+1}: {self._message(error)}")
                else:
                    self.notice_status.set(f"Aviso na página {request['area'][0]+1}. Prévia: {request['data']}; na geração será usado o horário real.")
                self._redraw_marks()
            elif not future.cancelled():
                try:
                    future.result()
                except BrokenProcessPool:
                    self.executor_quebrado()
                except Exception:
                    pass
        self._controls()
        self._start_render()
        self._start_notice()
        self.window.after(80, self.poll)

    def close(self):
        if self.closed:
            return
        if self.exporting:
            messagebox.showinfo('Geração em andamento','Aguarde a conclusão antes de fechar.',parent=self.window);return
        if self.result_viewer is not None and not self.result_viewer.closed:self.result_viewer.close()
        self._cancel_drag()
        self._cancel_notice_timer()
        self.closed = True
        self.notice_token += 1
        self.notice_request = None
        if self.notice_future is not None:
            self.notice_future[1].cancel()
        self.notice_area = None
        self.notice_image = None
        self.notice_text = None
        self.session_id += 1
        self.marks.clear()
        self.selected_mark_id = None
        self.render_token += 1
        self.render_request = None
        if self.inspect_future is not None:
            self.inspect_future.cancel()
        if self.render_future is not None:
            self.render_future[1].cancel()
        self.image = None
        self.excluded_pages.clear()
        self.window.destroy()
        self.icons.clear()
        # Variáveis Tcl devem ser liberadas na mesma thread que criou o Tk;
        # executores de processos podem disparar GC em suas próprias threads.
        self.filename = None
        self.page_label = None
        self.exclusion_status = None
        self.selection_status = None
        self.notice_status = None
        self.recipient = None
        self.tool = None
        self.mark_color = None
        self.status = None
        self.ao_fechar()
