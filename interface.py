#!/usr/bin/env python3
"""Interface local. Tk no processo principal; PDFs em um processo separado."""
from __future__ import annotations
import multiprocessing
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import sys
import os
import queue
import subprocess
import threading
import shutil
import copy
from atualizacao import consultar, baixar
try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
except ImportError:
    raise SystemExit('Tkinter indisponível. Instale Python com Tcl/Tk (python.org) ou o pacote python3-tk do sistema. O modo tarjar.py --pasta continua disponível.')
from tarjar import validar_destinatario, CORES
from lote import Resultado, descobrir, processar_arquivo, comparar, Recusado, CAMPOS

LABELS = {'aguardando':'Aguardando', 'processando':'Processando', 'concluido':'Concluído',
          'recusado':'Recusado', 'falhou':'Falhou', 'cancelado':'Cancelado', 'ignorado':'Ignorado'}
TIPOS = {'pedido':'Pedido', 'nota':'Nota fiscal', '':'—'}


class Aplicativo:
    def __init__(self, root):
        self.root = root
        root.title('Ocultar Dados - Pedido Interno e NFe')
        root.geometry('1120x860')
        root.minsize(900,650)
        self.pool = ProcessPoolExecutor(max_workers=1,mp_context=multiprocessing.get_context('spawn'))
        self.jobs = []
        self.choices = {}
        self.batch_choices = {}
        self.field_vars = {}
        self.detected = set()
        self.resize_after = None
        self.pool_broken = False
        self.running = False
        self.updating = False
        self.update_info = None
        self.update_queue = queue.Queue()
        self.update_checking = False
        self.stopping = False
        self.closing = False
        self.index = 0
        self.active = None
        self.preview_future = None
        self.preview_request = None
        self.preview_token = 0
        self.photos = {}
        self.source = tk.StringVar()
        self.target = tk.StringVar()
        self.recipient = tk.StringVar()
        self.batch_recipient = None
        self.color = tk.StringVar(value='Preto')
        self.batch_color = 'preto'
        self.summary = tk.StringVar(value='Escolha as pastas e carregue os PDFs para começar.')
        self.detail = tk.StringVar(value='Selecione um arquivo para conferir.')
        self._build()
        self.previous_source=''
        self.source.trace_add('write',self._source_changed)
        self.target.trace_add('write',self._paths_changed)
        root.protocol('WM_DELETE_WINDOW',self.close)
        root.after(80,self.poll)
        if sys.platform == "win32":
            self.check_update()
        root.after(150,self.poll_update)

    def _build(self):
        root = self.root
        root.columnconfigure(0,weight=1)
        root.rowconfigure(3,weight=1)
        folders = ttk.Frame(root,padding=(16,12))
        folders.grid(row=0,column=0,sticky='ew')
        folders.columnconfigure(1,weight=1)
        self.path_widgets = []
        for row,label,var in [(0,'Pasta de entrada',self.source),(1,'Pasta de saída',self.target)]:
            ttk.Label(folders,text=label).grid(row=row,column=0,sticky='w',padx=(0,12),pady=4)
            entry = ttk.Entry(folders,textvariable=var)
            entry.grid(row=row,column=1,sticky='ew',pady=4)
            button = ttk.Button(folders,text='Escolher…',command=lambda v=var:self.choose(v))
            button.grid(row=row,column=2,padx=(8,0),pady=4)
            self.path_widgets.extend([entry,button])
        ttk.Label(folders,text='Destinatário').grid(row=2,column=0,sticky='w',padx=(0,12),pady=4)
        self.recipient_entry=ttk.Entry(folders,textvariable=self.recipient)
        self.recipient_entry.grid(row=2,column=1,sticky='ew',pady=4)
        color_frame=ttk.Frame(folders)
        color_frame.grid(row=2,column=2,padx=(8,0),sticky='ew')
        ttk.Label(color_frame,text='Cor das tarjas').pack(side='left',padx=(0,6))
        self.color_combo=ttk.Combobox(color_frame,textvariable=self.color,values=[v[0] for v in CORES.values()],state='readonly',width=16)
        self.color_combo.pack(side='left')
        self.path_widgets.append(self.recipient_entry)
        ttk.Label(folders,text='Nome da saída: Destinatario-ddmmyy-nome-original.pdf. Até 120 caracteres no destinatário.').grid(row=3,column=1,columnspan=2,sticky='w')
        ttk.Label(folders,text='Saída padrão: pasta de entrada (pode alterar). Somente PDFs, sem subpastas. Originais preservados.').grid(row=4,column=0,columnspan=3,sticky='w',pady=(4,0))
        actions = ttk.Frame(root,padding=(16,0,16,10))
        actions.grid(row=1,column=0,sticky='ew')
        self.load_button = ttk.Button(actions,text='Carregar PDFs',command=self.load)
        self.load_button.pack(side='left')
        self.run_button = ttk.Button(actions,text='Processar',command=self.start,state='disabled')
        self.run_button.pack(side='left',padx=8)
        self.stop_button = ttk.Button(actions,text='Interromper',command=self.stop,state='disabled')
        self.stop_button.pack(side='left')
        self.progress = ttk.Progressbar(actions,mode='determinate',length=180)
        self.progress.pack(side='right',fill='x',expand=True,padx=(20,0))
        table = ttk.Frame(root,padding=(16,0))
        table.grid(row=2,column=0,sticky='ew')
        table.columnconfigure(0,weight=1)
        self.tree = ttk.Treeview(table,columns=('arquivo','tipo','status'),show='headings',height=6,selectmode='browse')
        for key,title,width in [('arquivo','Arquivo',600),('tipo','Tipo',130),('status','Status',150)]:
            self.tree.heading(key,text=title)
            self.tree.column(key,width=width,minwidth=90,stretch=(key=='arquivo'))
        self.tree.grid(row=0,column=0,sticky='ew')
        bar = ttk.Scrollbar(table,orient='vertical',command=self.tree.yview)
        bar.grid(row=0,column=1,sticky='ns')
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.bind('<<TreeviewSelect>>',lambda e:self.selection())
        self.detail_label=ttk.Label(table,textvariable=self.detail,wraplength=820)
        self.detail_label.grid(row=1,column=0,columnspan=2,sticky='w',pady=8)
        preview = ttk.Frame(root,padding=(16,0))
        preview.grid(row=3,column=0,sticky='nsew')
        preview.columnconfigure(0,weight=0,minsize=285)
        preview.columnconfigure(1,weight=1,uniform='p')
        preview.columnconfigure(2,weight=1,uniform='p')
        preview.rowconfigure(1,weight=1)
        fields = ttk.Frame(preview,padding=(0,0,12,0))
        fields.grid(row=0,column=0,rowspan=2,sticky='nsew')
        fields.columnconfigure(0,weight=1);fields.rowconfigure(2,weight=1)
        ttk.Label(fields,text='Campos a ocultar',font=('TkDefaultFont',11,'bold')).grid(row=0,column=0,sticky='w')
        ttk.Label(fields,text='Marcado: ocultar.\nDesmarcado: manter visível.').grid(row=1,column=0,sticky='w',pady=6)
        field_canvas=tk.Canvas(fields,width=270,highlightthickness=0)
        field_canvas.grid(row=2,column=0,sticky='nsew')
        field_scroll=ttk.Scrollbar(fields,orient='vertical',command=field_canvas.yview)
        field_scroll.grid(row=2,column=1,sticky='ns')
        field_canvas.configure(yscrollcommand=field_scroll.set)
        self.fields_frame=ttk.Frame(field_canvas)
        field_canvas.create_window(0,0,anchor='nw',window=self.fields_frame,width=265)
        self.fields_frame.bind('<Configure>',lambda e:field_canvas.configure(scrollregion=field_canvas.bbox('all')))
        self.fields_summary=tk.StringVar(value='Selecione um documento.')
        ttk.Label(fields,textvariable=self.fields_summary,wraplength=270).grid(row=3,column=0,sticky='w',pady=8)
        self.canvases = {}
        for col,(side,title) in enumerate([('antes','Original'),('depois','Resultado tarjado')],1):
            ttk.Label(preview,text=title,font=('TkDefaultFont',11,'bold')).grid(row=0,column=col,sticky='w',pady=(0,4))
            canvas = tk.Canvas(preview,background='#e9ecef',highlightthickness=1,highlightbackground='#b9bec4')
            canvas.grid(row=1,column=col,sticky='nsew',padx=(0,6) if col==1 else (6,0))
            self.canvases[side]=canvas
            canvas.bind('<Configure>',self._resized)
        self.zoom_button = ttk.Button(root,text='Ampliar comparação…',command=lambda:self.selection(zoom=True),state='disabled')
        self.zoom_button.grid(row=4,column=0,pady=8)
        footer = ttk.Frame(root,padding=(16,0,16,12))
        footer.grid(row=5,column=0,sticky='ew')
        self.summary_label=tk.Label(footer,textvariable=self.summary,wraplength=820,anchor='w',justify='left',padx=8,pady=5)
        self.summary_label.pack(anchor='w',fill='x')
        self.summary_default_bg=self.summary_label.cget('background')
        self.summary_default_fg=self.summary_label.cget('foreground')
        update_row=ttk.Frame(footer)
        update_row.pack(fill='x',pady=(4,0))
        self.update_button=ttk.Button(update_row,text='Atualização disponível',command=self.begin_update)
        self.update_status=tk.StringVar(value='')
        self.update_detail=ttk.Frame(footer)
        self.update_progress=ttk.Progressbar(self.update_detail,mode='determinate',length=130,maximum=100)
        self.update_label=ttk.Label(self.update_detail,textvariable=self.update_status)
        ttk.Label(update_row,text='Confira a visualização ampliada antes de compartilhar. A saída não terá texto selecionável.',wraplength=610).pack(side='left',fill='x',expand=True)

        self._clear_previews('Selecione um arquivo.')

    def choose(self,var):
        value=filedialog.askdirectory(parent=self.root,title='Escolha a pasta')
        if value:var.set(value)

    def _source_changed(self,*_):
        current=self.source.get()
        if not self.target.get().strip() or self.target.get()==self.previous_source:
            self.target.set(current)
        self.previous_source=current
        self._paths_changed()

    def _paths_changed(self,*_):
        if self.running:return
        self.summary_label.configure(background=self.summary_default_bg,foreground=self.summary_default_fg)
        self.detail_label.configure(foreground='')
        self.jobs=[]
        self.choices={}
        self.detected=set()
        self._show_fields()
        for item in self.tree.get_children():self.tree.delete(item)
        self.preview_token+=1
        self.preview_request=None
        self._clear_previews('Carregue os PDFs destas pastas.')
        self.run_button.configure(state='disabled')
        self.zoom_button.configure(state='disabled')
        self.detail.set('As pastas mudaram. Carregue a lista novamente.')

    def load(self):
        try:
            if not self.source.get().strip() or not self.target.get().strip():
                raise Recusado('Escolha as pastas de entrada e de saída.')
            files,output=descobrir(self.source.get(),self.target.get())
        except (Recusado,OSError) as e:
            self._paths_changed()
            messagebox.showerror('Não foi possível carregar',str(e) if isinstance(e,Recusado) else 'Verifique o acesso à pasta.',parent=self.root)
            return
        self.recipient_entry.configure(state='normal')
        self.color_combo.configure(state='readonly')
        self.summary_label.configure(background=self.summary_default_bg,foreground=self.summary_default_fg)
        self.output=output
        self.choices={}
        self.detected=set()
        self.jobs=[Resultado(str(p)) for p in files]
        self.preview_token+=1
        self.preview_request=None
        self._clear_previews('Selecione um arquivo.')
        for item in self.tree.get_children():self.tree.delete(item)
        for i,job in enumerate(self.jobs):self.tree.insert('', 'end',iid=str(i),values=(Path(job.origem).name,'—','Aguardando'))
        self.run_button.configure(state='normal')
        self.progress.configure(value=0,maximum=len(self.jobs))
        self.summary.set(f'{len(self.jobs)} PDF(s) carregado(s). Tipo identificado ao processar.')
        self.tree.selection_set('0')
        self.tree.focus('0')

    def selected(self):
        items=self.tree.selection()
        return int(items[0]) if items and int(items[0])<len(self.jobs) else None

    def _clear_previews(self,text):
        self.photos.clear()
        for c in self.canvases.values():
            c.delete('all')
            c.create_text(max(c.winfo_width(),300)/2,max(c.winfo_height(),150)/2,text=text,width=280,fill='#30363d',tags='message')

    def selection(self,zoom=False):
        i=self.selected()
        self.preview_token+=1
        if i is None:
            self.preview_request=None
            self._clear_previews('Selecione um arquivo.')
            self.zoom_button.configure(state='disabled')
            return
        job=self.jobs[i]
        self.detail_label.configure(foreground='#d32f2f' if job.status=='recusado' else '')
        self.detail.set(f'{Path(job.origem).name} — {LABELS[job.status]}. {job.mensagem}')
        self.zoom_button.configure(state='normal')
        self._show_fields()
        if not zoom:self._clear_previews('Carregando prévia…')
        canvas=self.canvases['antes']
        size=(1200,1700) if zoom else (max(canvas.winfo_width()-20,100),max(canvas.winfo_height()-20,100))
        self.preview_request=(self.preview_token,i,zoom,size)

    def _show_fields(self):
        for child in self.fields_frame.winfo_children():child.destroy()
        self.field_vars={}
        i=self.selected()
        if i is None or not self.jobs[i].tipo:
            ttk.Label(self.fields_frame,text=('Modelo não identificado; seleção de campos indisponível.' if i in self.detected else 'Identificando o modelo…') if i is not None else 'Selecione um documento.',wraplength=260).pack(anchor='w')
            self.fields_summary.set('Todos os campos são ocultados por padrão.')
            return
        job=self.jobs[i]
        defaults=list(CAMPOS[job.tipo])
        chosen=self.choices.get(i,defaults)
        editable=not self.running and not self.updating and job.status=='aguardando'
        buttons=ttk.Frame(self.fields_frame);buttons.pack(fill='x',pady=(0,8))
        for title,values in [('Marcar todos',defaults),('Desmarcar todos',[])]:
            ttk.Button(buttons,text=title,command=lambda v=values:self._set_fields(v),state='normal' if editable else 'disabled').pack(side='left',padx=(0,4))
        for key,label in CAMPOS[job.tipo].items():
            var=tk.BooleanVar(value=key in chosen)
            self.field_vars[key]=var
            ttk.Checkbutton(self.fields_frame,text=label.replace(' (','\n('),variable=var,command=self._fields_changed,state='normal' if editable else 'disabled').pack(anchor='w',pady=3)
        self._field_summary()

    def _field_summary(self):
        i=self.selected()
        if i is None or not self.jobs[i].tipo:return
        job=self.jobs[i];defaults=list(CAMPOS[job.tipo])
        hidden=len(self.choices.get(i,defaults))
        editable=not self.running and not self.updating and job.status=='aguardando'
        self.fields_summary.set(f'{hidden} grupo(s) a ocultar · {len(defaults)-hidden} a manter visíveis.' +
                                ('\nNenhum marcado: arquivo será ignorado.' if not hidden else '') +
                                ('\nPara alterar, recarregue em outro destino.' if not editable and not self.running else ''))

    def _set_fields(self,values):
        for key,var in self.field_vars.items():var.set(key in values)
        self._fields_changed()

    def _fields_changed(self):
        i=self.selected()
        if i is None or self.running or self.updating or self.jobs[i].status!='aguardando':return
        self.choices[i]=[key for key,var in self.field_vars.items() if var.get()]
        self._field_summary()
        any_selected=any(self.choices.get(j,None)!=[] for j in range(len(self.jobs)))
        self.run_button.configure(state='normal' if any_selected else 'disabled')
        if not any_selected:self.summary.set('Selecione pelo menos um campo em algum documento.')

    def _resized(self,event):
        canvas=event.widget
        canvas.coords('page',event.width/2,event.height/2)
        canvas.coords('message',event.width/2,event.height/2)
        if self.resize_after is not None:self.root.after_cancel(self.resize_after)
        self.resize_after=self.root.after(300,self._resize_preview)

    def _resize_preview(self):
        self.resize_after=None
        i=self.selected()
        if i is None or self.closing:return
        self.preview_token+=1
        c=self.canvases['antes']
        self.preview_request=(self.preview_token,i,False,(max(c.winfo_width()-20,100),max(c.winfo_height()-20,100)))

    def _paint(self,previews):
        self.photos.clear()
        for side,c in self.canvases.items():
            c.delete('all')
            data=previews.get(side)
            if data:
                photo=tk.PhotoImage(data=data,master=self.root)
                self.photos[side]=photo
                c.create_image(c.winfo_width()/2,c.winfo_height()/2,image=photo,tags='page')
            else:
                c.create_text(c.winfo_width()/2,c.winfo_height()/2,text=previews.get(side+'_erro','Prévia indisponível.'),width=max(c.winfo_width()-40,120),fill='#30363d',tags='message')

    def _zoom(self,previews,index):
        window=tk.Toplevel(self.root)
        window.title('Conferência ampliada — '+Path(self.jobs[index].origem).name)
        window.geometry('1000x780')
        notebook=ttk.Notebook(window)
        notebook.pack(fill='both',expand=True)
        window.photos=[]
        for side,title in [('antes','Original'),('depois','Resultado tarjado')]:
            frame=ttk.Frame(notebook);notebook.add(frame,text=title)
            frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
            canvas=tk.Canvas(frame,background='#e9ecef')
            canvas.grid(row=0,column=0,sticky='nsew')
            vertical=ttk.Scrollbar(frame,orient='vertical',command=canvas.yview)
            horizontal=ttk.Scrollbar(frame,orient='horizontal',command=canvas.xview)
            vertical.grid(row=0,column=1,sticky='ns');horizontal.grid(row=1,column=0,sticky='ew')
            canvas.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
            if previews.get(side):
                photo=tk.PhotoImage(data=previews[side],master=self.root)
                window.photos.append(photo)
                canvas.create_image(0,0,anchor='nw',image=photo)
                canvas.configure(scrollregion=(0,0,photo.width(),photo.height()))
            else:canvas.create_text(30,30,anchor='nw',text=previews.get(side+'_erro','Prévia indisponível.'),width=700)
        ttk.Label(window,text='Use as abas Original / Resultado tarjado e as barras de rolagem para conferir os detalhes.').pack(pady=8)

    def start(self):
        if not self.jobs or self.running or self.updating:return
        try:self.batch_recipient=validar_destinatario(self.recipient.get())
        except Recusado as e:
            messagebox.showerror('Destinatário necessário',str(e),parent=self.root)
            self.recipient_entry.focus_set();return
        if self.pool_broken:
            self.pool.shutdown(wait=False,cancel_futures=True)
            self.pool=ProcessPoolExecutor(max_workers=1,mp_context=multiprocessing.get_context('spawn'))
            self.pool_broken=False
        self.batch_color=next(key for key,(label,_) in CORES.items() if label==self.color.get())
        self.color_combo.configure(state='disabled')
        self.summary_label.configure(background=self.summary_default_bg,foreground=self.summary_default_fg)
        self.batch_time=datetime.now().astimezone()
        self.batch_choices={i:list(v) for i,v in self.choices.items()}
        self.running=True;self.stopping=False;self.index=0
        self.update_button.configure(state="disabled")
        self._show_fields()
        self.run_button.configure(state='disabled');self.load_button.configure(state='disabled')
        self.stop_button.configure(state='normal')
        for w in self.path_widgets:w.configure(state='disabled')
        self._next()

    def stop(self):
        self.stopping=True
        self.stop_button.configure(state='disabled')
        self.summary.set('Interrompendo após o arquivo atual. Os PDFs já concluídos serão mantidos.')

    def _update_row(self,i):
        job=self.jobs[i]
        self.tree.item(str(i),values=(Path(job.origem).name,TIPOS[job.tipo],LABELS[job.status]))

    def _next(self):
        if self.stopping:
            for i in range(self.index,len(self.jobs)):
                self.jobs[i].status='cancelado';self.jobs[i].mensagem='Não iniciado.';self._update_row(i)
            self.index=len(self.jobs)
        if self.index>=len(self.jobs):
            self.finish();return
        job=self.jobs[self.index]
        job.status='processando';self._update_row(self.index)
        self.summary.set(f'Processando {self.index+1} de {len(self.jobs)}: {Path(job.origem).name}')
        try:
            self.active=(self.index,self.pool.submit(processar_arquivo,job.origem,str(self.output),campos=self.batch_choices.get(self.index),destinatario=self.batch_recipient,gerado_em=self.batch_time,cor=self.batch_color))
        except Exception:
            job.status='falhou';job.mensagem='Processo indisponível. Recarregue o lote para tentar novamente.'
            self.pool_broken=True;self.stopping=True
            self._update_row(self.index);self.index+=1
            self.root.after(0,self._next)

    def finish(self):
        self.running=False
        self.active=None
        self.stop_button.configure(state='disabled')
        self.load_button.configure(state='normal')
        for w in self.path_widgets:w.configure(state='normal')
        self.recipient_entry.configure(state='disabled')
        counts={s:sum(j.status==s for j in self.jobs) for s in ('concluido','recusado','falhou','cancelado','ignorado')}
        attention=counts['recusado'] or counts['falhou'] or counts['cancelado'] or counts['ignorado']
        title='Interrompido' if counts['cancelado'] else ('Finalizado com pendências' if attention else 'Processamento concluído')
        self.summary_label.configure(background='#fff3cd' if attention else '#dff3e5',foreground='#664d03' if attention else '#14532d')
        self.summary.set(f"{title} — {counts['concluido']} concluído(s) · {counts['recusado']} recusado(s) · {counts['falhou']} falha(s) · {counts['cancelado']} cancelado(s) · {counts['ignorado']} ignorado(s). Recarregue para iniciar outro lote.")
        self.selection()
        if self.update_info:self.update_button.configure(state="normal")
        if sys.platform == "win32":self.check_update()

    def poll(self):
        if self.active and self.active[1].done():
            i,future=self.active
            try:self.jobs[i]=future.result()
            except Exception:
                self.jobs[i].status='falhou';self.jobs[i].mensagem='O processo de PDF foi encerrado inesperadamente.'
                self.stopping=True;self.pool_broken=True
            self._update_row(i)
            self.progress.configure(value=i+1)
            self.active=None
            self.index=i+1
            if self.selected()==i:self.selection()
            self._next()
        if self.preview_future and self.preview_future[1].done():
            request,future=self.preview_future
            self.preview_future=None
            token,i,zoom,_=request
            if token==self.preview_token and not self.closing:
                try:
                    previews=future.result()
                    self.detected.add(i)
                    if previews.get('tipo'):
                        self.jobs[i].tipo=previews['tipo'];self._update_row(i)
                    self._show_fields()
                    if zoom:self._zoom(previews,i)
                    else:self._paint(previews)
                except Exception:self._clear_previews('Prévia indisponível. O status do PDF permanece na lista.')
        if self.closing and not self.running and self.preview_future is None:
            self.pool.shutdown(wait=False,cancel_futures=True)
            self.root.destroy();return
        if self.preview_request and self.preview_future is None and not self.closing:
            request=self.preview_request;self.preview_request=None
            token,i,zoom,(w,h)=request
            try:self.preview_future=(request,self.pool.submit(comparar,self.jobs[i],w,h))
            except Exception:self._clear_previews('Prévia indisponível.')
        self.root.after(80,self.poll)

    def check_update(self):
        if self.update_checking or self.updating:return
        self.update_checking=True
        def work():
            try:self.update_queue.put(('checked',consultar()))
            except Exception:self.update_queue.put(('checked',None))
        threading.Thread(target=work,daemon=True).start()

    def begin_update(self):
        if self.running or self.updating or not self.update_info:return
        release=copy.deepcopy(self.update_info)
        if not messagebox.askyesno('Atualizar aplicativo?',f"Atualizar para {release['version']}?\n\nO aplicativo será encerrado para instalar a atualização. Os PDFs gerados serão preservados. As seleções atuais precisarão ser refeitas.",parent=self.root):return
        controls=[self.run_button,self.load_button,self.color_combo,*self.path_widgets]
        self.update_previous_states=[(widget,str(widget.cget('state'))) for widget in controls]
        self.active_update_info=release
        self.updating=True
        self._show_fields()
        self.update_button.configure(state='disabled')
        self.run_button.configure(state='disabled');self.load_button.configure(state='disabled')
        for w in self.path_widgets:w.configure(state='disabled')
        self.color_combo.configure(state='disabled')
        self.update_detail.pack(fill='x',pady=(4,0))
        self.update_label.pack(side='left',padx=5)
        self.update_progress.pack(side='left',padx=5)
        self.update_progress.configure(value=0)
        self.update_status.set('Baixando atualização…')
        def progress(current,total):self.update_queue.put(('progress',current*100/total))
        def work():
            try:self.update_queue.put(('downloaded',baixar(release,progress)))
            except Exception:self.update_queue.put(('failed',None))
        threading.Thread(target=work,daemon=True).start()

    def poll_update(self):
        if self.closing:return
        try:
            while True:
                event,value=self.update_queue.get_nowait()
                if event=='checked':
                    self.update_checking=False
                    if value:
                        self.update_info=value
                        self.update_button.configure(text='Atualizar para '+value['version'],state='disabled' if self.running or self.updating else 'normal')
                        self.update_button.pack(side='right',padx=(8,0))
                elif event=='progress':self.update_progress.configure(value=value)
                elif event=='failed':self.update_failed()
                elif event=='downloaded':
                    self.update_status.set('Atualização verificada.')
                    messagebox.showinfo('Atualização pronta','O aplicativo será encerrado. Acompanhe a instalação na janela que será aberta.',parent=self.root)
                    try:
                        release=self.active_update_info
                        subprocess.Popen(['powershell.exe','-NoProfile','-NoExit','-ExecutionPolicy','Bypass','-File',str(value/'install.ps1'),'-Version',release['version'],'-ArchiveSha256',release['assets']['hide-pdf-fields-windows.zip']['sha256'],'-ArchivePath',str(value/'hide-pdf-fields-windows.zip')],creationflags=subprocess.CREATE_NEW_CONSOLE)
                        self.updating=False
                        self.close()
                    except Exception:
                        shutil.rmtree(value,ignore_errors=True)
                        self.update_failed()
        except queue.Empty:pass
        if not self.closing:self.root.after(150,self.poll_update)

    def update_failed(self):
        self.updating=False
        self.update_detail.pack_forget()
        self.update_button.configure(state='normal')
        for widget,state in self.update_previous_states:widget.configure(state=state)
        self._show_fields()
        messagebox.showerror('Atualização não concluída','Não foi possível preparar a atualização. Verifique a conexão e tente novamente. A versão atual continua disponível.',parent=self.root)

    def close(self):
        if self.updating and not self.closing:
            messagebox.showinfo('Atualização em andamento','Aguarde o fim da preparação da atualização.',parent=self.root);return
        if self.running:
            if not messagebox.askyesno('Encerrar após arquivo atual?','O arquivo em andamento será concluído. Os seguintes não serão iniciados. Deseja encerrar?',parent=self.root):return
            self.stop()
        self.closing=True
        self.preview_request=None
        self.preview_token+=1
        self.summary.set('Encerrando tarefas locais…')


def main():
    multiprocessing.freeze_support()
    try:root=tk.Tk()
    except tk.TclError:
        raise SystemExit('Não foi possível abrir Tk. Execute em uma sessão gráfica com Python/Tcl-Tk instalado. A CLI tarjar.py --pasta permanece disponível.')
    Aplicativo(root)
    root.lift()
    root.mainloop()


if __name__=='__main__':main()
