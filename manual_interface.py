"""Visualizador manual de PDFs: etapa inicial somente de leitura."""
from pathlib import Path
from concurrent.futures.process import BrokenProcessPool
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from manual_pdf import ManualPdfErro, inspecionar, renderizar


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
        self.window.rowconfigure(2, weight=1)

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

        viewer = ttk.Frame(self.window, padding=(12, 0, 12, 0))
        viewer.grid(row=2, column=0, sticky='nsew')
        viewer.columnconfigure(0, weight=1)
        viewer.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(viewer, background='#e9ecef', highlightthickness=1,
                                highlightbackground='#b9bec4', takefocus=True)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        vertical = ttk.Scrollbar(viewer, orient='vertical', command=self.canvas.yview)
        horizontal = ttk.Scrollbar(viewer, orient='horizontal', command=self.canvas.xview)
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
        self.canvas.bind('<Button-1>', lambda _: self.canvas.focus_set())

        self.status = tk.StringVar(value='Abra um PDF para visualizar. Nesta etapa, nenhum arquivo será alterado ou exportado.')
        self.status_label = ttk.Label(self.window, textvariable=self.status, wraplength=570, padding=(12, 8, 12, 12))
        self.status_label.grid(row=3, column=0, sticky='ew')
        self.window.bind('<Configure>', self._resize_status)
        self._controls()
        self.window.after_idle(self.open_button.focus_set)
        self.window.after(80, self.poll)

    def _resize_status(self, event):
        if event.widget == self.window:
            self.status_label.configure(wraplength=max(120, event.width-32))

    def _scroll(self, axis, amount):
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
        self.render_token += 1
        self.render_request = None
        self.document = None
        self.path = None
        self.page = 0
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
                self.document, self.path = doc, candidate
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
                    self.canvas.create_image(0, 0, anchor='nw', image=image)
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
        self.closed = True
        self.render_token += 1
        self.render_request = None
        if self.inspect_future is not None:
            self.inspect_future.cancel()
        if self.render_future is not None:
            self.render_future[1].cancel()
        self.image = None
        self.window.destroy()
        # Variáveis Tcl devem ser liberadas na mesma thread que criou o Tk;
        # executores de processos podem disparar GC em suas próprias threads.
        self.filename = None
        self.page_label = None
        self.status = None
        self.ao_fechar()
