"""Visualizador manual de PDFs: etapa inicial somente de leitura."""
from pathlib import Path
from concurrent.futures.process import BrokenProcessPool
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from manual_pdf import ESCALA_100, ManualPdfErro, inspecionar, renderizar
from tarjar import CORES


class VisualizadorManual:
    """A interface vive no processo principal; inspeção/renderização usam o executor compartilhado."""

    def __init__(self, parent, executor, ocupado=lambda: False, ao_fechar=lambda: None, executor_quebrado=lambda: None):
        self.parent = parent
        self.executor = executor
        self.ocupado = ocupado
        self.ao_fechar = ao_fechar
        self.executor_quebrado = executor_quebrado
        self.closed = False
        self.document = None
        self.path = None
        self.page = 0
        self.excluded_pages = set()
        # Retângulos em pontos relativos à origem visível da página; IDs não mudam na sessão.
        self.marks = {}
        self.selected_mark_id = None
        self.next_mark_id = 1
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
        self.window.title('Modo manual — visualização')
        self.window.geometry('960x720')
        self.window.minsize(600, 450)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(3, weight=1)

        header = ttk.Frame(self.window, padding=(12, 12, 12, 6))
        header.grid(row=0, column=0, sticky='ew')
        header.columnconfigure(1, weight=1)
        self.open_button = ttk.Button(header, text='Abrir PDF…', command=self.choose)
        self.open_button.grid(row=0, column=0, sticky='w')
        self.filename = tk.StringVar(value='Nenhum PDF aberto')
        self.filename_entry = ttk.Entry(header, textvariable=self.filename, state='readonly')
        self.filename_entry.grid(row=0, column=1, sticky='ew', padx=12)
        ttk.Label(header, text='Visualização: 100%').grid(row=0, column=2, sticky='e')

        navigation = ttk.Frame(self.window, padding=(12, 0, 12, 6))
        navigation.grid(row=1, column=0, sticky='ew')
        self.prev_button = ttk.Button(navigation, text='Anterior', command=lambda: self.go(-1))
        self.prev_button.pack(side='left')
        self.page_label = tk.StringVar(value='Nenhuma página aberta')
        ttk.Label(navigation, textvariable=self.page_label).pack(side='left', padx=12)
        self.next_button = ttk.Button(navigation, text='Próxima', command=lambda: self.go(1))
        self.next_button.pack(side='left')

        tools = ttk.Frame(self.window, padding=(12, 0, 12, 6))
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
        ttk.Label(tools, text='Cor da nova tarja:').grid(row=1, column=0, sticky='w', pady=(4,0))
        self.mark_color = tk.StringVar(value=CORES['preto'][0])
        self.color_combo = ttk.Combobox(tools, textvariable=self.mark_color,
                                        values=[name for name, _ in CORES.values()],
                                        state='readonly', width=16)
        self.color_combo.grid(row=1, column=1, sticky='w', columnspan=2, pady=(4,0))
        self.tool.trace_add('write', self._tool_changed)
        self.mark_color.trace_add('write', self._color_changed)
        self.preview_warning = ttk.Label(tools, text='Prévia: as tarjas ainda não ocultam dados.', wraplength=520)
        self.preview_warning.grid(row=2, column=0, columnspan=2, sticky='w', pady=(4,0))
        self.selection_status = tk.StringVar(value='Nenhuma tarja selecionada.')
        self.selection_label = ttk.Label(tools, textvariable=self.selection_status, anchor='e')
        self.selection_label.grid(row=2, column=2, sticky='e', padx=(8,0), pady=(4,0))

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

        page_options = ttk.Frame(self.window, padding=(12, 6, 12, 0))
        page_options.grid(row=4, column=0, sticky='ew')
        page_options.columnconfigure(1, weight=1)
        self.exclude_button = ttk.Button(page_options, text='Excluir página', command=self.toggle_exclusion)
        self.exclude_button.grid(row=0, column=0, sticky='nw')
        self.exclusion_status = tk.StringVar(value='')
        self.exclusion_label = ttk.Label(page_options, textvariable=self.exclusion_status, wraplength=400, justify='left')
        self.exclusion_label.grid(row=0, column=1, sticky='ew', padx=(12,0))

        self.status = tk.StringVar(value='Abra um PDF para visualizar. Nesta etapa, nenhum arquivo será alterado ou exportado.')
        self.status_label = ttk.Label(self.window, textvariable=self.status, wraplength=570, padding=(12, 8, 12, 12))
        self.status_label.grid(row=5, column=0, sticky='ew')
        self.window.bind('<Configure>', self._resize_status)
        self._controls()
        self.window.after_idle(self.open_button.focus_set)
        self.window.after(80, self.poll)

    def _resize_status(self, event):
        if event.widget == self.window:
            self.status_label.configure(wraplength=max(120, event.width-32))
            self.exclusion_label.configure(wraplength=max(120, event.width-200))

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

    def _controls(self):
        busy = bool(self.ocupado())
        opening = self.inspect_future is not None
        self.open_button.configure(state='disabled' if busy or opening else 'normal')
        usable = self.document is not None and not busy and not opening
        self.prev_button.configure(state='normal' if usable and self.page > 0 else 'disabled')
        self.next_button.configure(state='normal' if usable and self.page + 1 < self.document['total_paginas'] else 'disabled')
        editing = (usable and self.image is not None and self.render_future is None
                   and self.render_request is None and self.page not in self.excluded_pages)
        self.draw_button.configure(state='normal' if editing else 'disabled')
        self.select_button.configure(state='normal' if editing else 'disabled')
        self.color_combo.configure(state='readonly' if editing else 'disabled')
        self.delete_button.configure(state='normal' if editing and self.selected_mark_id is not None else 'disabled')
        self.selection_status.set('Tarja selecionada.' if self.selected_mark_id is not None
                                  else 'Nenhuma tarja selecionada.')
        cursor = 'crosshair' if editing and self.tool.get() == 'desenhar' else ''
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
        if (self.closed or self.ocupado() or self.inspect_future is not None or not self.document
                or self.image is None or self.render_future is not None or self.render_request is not None):
            return
        if self.page in self.excluded_pages:
            self.excluded_pages.remove(self.page)
        elif self.document['total_paginas'] - len(self.excluded_pages) > 1:
            self.excluded_pages.add(self.page)
        self.selected_mark_id = None
        self._redraw_marks()
        self._controls()

    def _can_edit(self):
        return bool(not self.closed and not self.ocupado() and self.inspect_future is None
                    and self.document is not None and self.image is not None
                    and self.render_future is None and self.render_request is None
                    and self.page not in self.excluded_pages and self.page_image_id is not None)

    def _tool_changed(self, *_):
        self._cancel_drag()
        if self.tool.get() == 'desenhar':
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
        return bool(self.drag and self._can_edit() and self.tool.get() == 'desenhar'
                    and self.drag['session'] == self.session_id
                    and self.drag['page'] == self.page
                    and self.drag['token'] == self.render_token
                    and self.drag['sha256'] == self.document['sha256']
                    and self.drag['cor'] in CORES
                    and self.mark_color.get() == CORES[self.drag['cor']][0])

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
        if self.tool.get() != 'desenhar':
            return 'break'
        color = next((key for key, (label, _) in CORES.items() if label == self.mark_color.get()), None)
        if color is None:
            return 'break'
        self.selected_mark_id = None
        self._redraw_marks()
        self.drag = {'session': self.session_id, 'page': self.page, 'token': self.render_token,
                     'sha256': self.document['sha256'], 'start': point, 'cor': color}
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
                                     outline='#003b70', width=2, dash=(4, 2), tags=('draft',))
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
        color = self.drag['cor']
        self._cancel_drag()
        if rect[2] > rect[0] and rect[3] > rect[1]:
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

    def choose(self):
        if self.closed or self.ocupado() or self.inspect_future is not None:
            return
        path = filedialog.askopenfilename(parent=self.window, title='Abrir PDF',
                                          filetypes=[('Arquivos PDF', '*.pdf')])
        if path:
            self.open_path(path)

    def open_path(self, path):
        """Solicita inspeção sem descartar o documento anterior em caso de recusa."""
        if self.closed or self.ocupado() or self.inspect_future is not None:
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
        if self.closed or self.ocupado() or self.inspect_future is not None or not self.document:
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
        self.render_request = (self.render_token, self.path, self.document['sha256'], index)
        self.image = None
        self.canvas.delete('all')
        self.canvas.configure(scrollregion=(0, 0, 0, 0))
        self.page_label.set(f"Carregando página {index+1} de {self.document['total_paginas']}…")
        self.status.set('Carregando página…')
        self._controls()
        self._start_render()

    def _start_render(self):
        if self.closed or self.ocupado() or self.render_future is not None or self.render_request is None:
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
                    self.status.set('Visualização somente; o PDF original permanece inalterado.')
            elif not future.cancelled():
                try:
                    future.result()
                except BrokenProcessPool:
                    self.executor_quebrado()
                except Exception:
                    pass
        self._controls()
        self._start_render()
        self.window.after(80, self.poll)

    def close(self):
        if self.closed:
            return
        self._cancel_drag()
        self.closed = True
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
        # Variáveis Tcl devem ser liberadas na mesma thread que criou o Tk;
        # executores de processos podem disparar GC em suas próprias threads.
        self.filename = None
        self.page_label = None
        self.exclusion_status = None
        self.selection_status = None
        self.tool = None
        self.mark_color = None
        self.status = None
        self.ao_fechar()
