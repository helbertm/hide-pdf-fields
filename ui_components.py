"""Small, native Tk components shared by the application's windows.

The widgets retain text labels and the operating system's keyboard interaction.
No icon font or external image package is required.
"""
import tkinter as tk
from tkinter import messagebox, ttk


class ColorSelector(ttk.Frame):
    """Readonly color choice with a bordered swatch and an ordinary combobox."""

    def __init__(self, parent, *, textvariable, colors, width=16):
        super().__init__(parent)
        self._variable = textvariable
        self._colors = {label: '#%02x%02x%02x' % tuple(rgb)
                        for label, rgb in colors.values()}
        # A border is essential: the white choice must remain visible on white.
        self.swatch = tk.Canvas(self, width=20, height=16, borderwidth=0,
                                highlightthickness=0, takefocus=False)
        self.swatch.pack(side='left', padx=(0, 6))
        self._rectangle = self.swatch.create_rectangle(1, 1, 19, 15,
                                                        outline='#737373', width=1)
        self.combo = ttk.Combobox(self, textvariable=textvariable,
                                  values=list(self._colors), state='readonly', width=width)
        self.combo.pack(side='left', fill='x', expand=True)
        self._trace = self._variable.trace_add('write', self._refresh)
        self.bind('<Destroy>', self._destroyed, add='+')
        self._refresh()

    def _refresh(self, *_):
        if self.swatch.winfo_exists():
            self.swatch.itemconfigure(self._rectangle,
                                      fill=self._colors.get(self._variable.get(), '#ffffff'))

    def _destroyed(self, event):
        if event.widget is self:
            try:
                self._variable.trace_remove('write', self._trace)
            except tk.TclError:
                pass
            finally:
                self._variable = None


class _Tooltip:
    def __init__(self, widget, text):
        self.widget, self.text = widget, text
        self.timer = None
        self.window = None
        for event in ('<Enter>', '<FocusIn>'):
            widget.bind(event, self.schedule, add='+')
        for event in ('<Leave>', '<FocusOut>', '<ButtonPress>', '<Escape>', '<Destroy>'):
            widget.bind(event, self.hide, add='+')

    def schedule(self, _event=None):
        self.hide()
        self.timer = self.widget.after(650, self.show)

    def show(self):
        self.timer = None
        if not self.widget.winfo_exists():
            return
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        label = tk.Label(self.window, text=self.text, justify='left', wraplength=320,
                         background='#fffbe5', foreground='#202020', relief='solid',
                         borderwidth=1, padx=7, pady=5)
        label.pack()
        self.window.update_idletasks()
        x = min(self.widget.winfo_rootx(),
                max(0, self.widget.winfo_screenwidth() - self.window.winfo_reqwidth()))
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        if y + self.window.winfo_reqheight() > self.widget.winfo_screenheight():
            y = max(0, self.widget.winfo_rooty() - self.window.winfo_reqheight() - 4)
        self.window.wm_geometry(f'+{max(0, x)}+{y}')

    def hide(self, _event=None):
        if self.timer is not None:
            try:
                self.widget.after_cancel(self.timer)
            except tk.TclError:
                pass
            self.timer = None
        if self.window is not None:
            try:
                self.window.destroy()
            except tk.TclError:
                pass
            self.window = None


def add_tooltip(widget, text):
    """Show a noninteractive hint for pointer hover or keyboard focus."""
    tooltip = _Tooltip(widget, text)
    # Keep the object alive for the lifetime of the widget.
    widget._ui_tooltip = tooltip
    return tooltip


def help_button(parent, title, text):
    """Return a keyboard-operable help button with a textual label."""
    button = ttk.Button(parent, text='Ajuda',
                        command=lambda: messagebox.showinfo(title, text, parent=parent))
    add_tooltip(button, 'Abrir ajuda sobre esta área.')
    return button


# Twelve by twelve monochrome glyphs. Transparent surroundings and textual
# button labels make them safe to use with both light and dark native themes.
_GLYPHS = {
    'folder': ('............','..####......','.#....#####.','.#.........#','.#.........#','.#.........#','.#.........#','.#.........#','.###########','............','............','............'),
    'open': ('............','..####......','.#....#####.','.#.........#','.#...#.....#','.#..###....#','.#...#.....#','.#.........#','.###########','............','............','............'),
    'process': ('............','...##.......','...####.....','...######...','...########.','...########.','...######...','...####.....','...##.......','............','............','............'),
    'stop': ('............','..########..','..########..','..########..','..########..','..########..','..########..','..########..','..########..','............','............','............'),
    'manual': ('............','........##..','.......###..','......###...','.....###....','....###.....','...###......','..###.......','..##........','............','............','............'),
    'compare': ('............','.####.####..','.#..#.#..#..','.#..#.#..#..','.#..#.#..#..','.#..#.#..#..','.#..#.#..#..','.####.####..','............','............','............','............'),
    'previous': ('............','......##....','.....##.....','....##......','...######...','....##......','.....##.....','......##....','............','............','............','............'),
    'next': ('............','...##.......','....##......','.....##.....','...######...','.....##.....','....##......','...##.......','............','............','............','............'),
    'delete': ('............','..########..','....####....','...######...','...#....#...','...#....#...','...#....#...','...#....#...','...######...','............','............','............'),
    'export': ('............','.....##.....','.....##.....','...######...','....####....','.....##.....','............','..#......#..','..########..','............','............','............'),
    'help': ('............','...####.....','..##..##....','......##....','.....##.....','....##......','....##......','............','....##......','............','............','............'),
}


def icon(widget, name):
    """Create an unobtrusive, theme-independent PhotoImage for a labelled action."""
    glyph = _GLYPHS[name]
    image = tk.PhotoImage(master=widget, width=12, height=12)
    # Mid-gray remains legible on both common native light and dark surfaces.
    for y, row in enumerate(glyph):
        for x, pixel in enumerate(row):
            if pixel == '#':
                image.put('#787878', (x, y))
    return image
