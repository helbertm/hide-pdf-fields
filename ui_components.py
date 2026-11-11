"""Small, native Tk components shared by the application's windows.

The widgets preserve the operating system's keyboard interaction.
No icon font or external image package is required.
"""
import tkinter as tk
from tkinter import messagebox, ttk


class _ColorMenuButton(ttk.Menubutton):
    """Native menu button retaining the former readonly selector interface."""

    def __init__(self, parent, *, textvariable, values, width):
        self._values = list(values)
        self._variable = textvariable
        super().__init__(parent, textvariable=textvariable, width=width, takefocus=True)
        self.state(['readonly'])
        self.bind('<Down>', self._open_menu, add='+')
        self.bind('<Return>', self._open_menu, add='+')

    def _open_menu(self, _event=None):
        if 'disabled' not in self.state():
            self.tk.call('ttk::menubutton::Popdown', self._w)
        return 'break'

    def configure(self, cnf=None, **kwargs):
        if isinstance(cnf, dict):
            kwargs = {**cnf, **kwargs}
            cnf = None
        requested = kwargs.get('state')
        if requested == 'readonly':
            kwargs['state'] = 'normal'
        result = super().configure(cnf, **kwargs)
        if requested == 'readonly':
            self.state(['readonly', '!disabled'])
        return result

    config = configure

    def cget(self, key):
        value = super().cget(key)
        if key == 'state':
            return 'readonly' if str(value) == 'normal' else str(value)
        return value

    def current(self, index=None):
        if index is None:
            try:
                return self._values.index(self._variable.get())
            except ValueError:
                return -1
        self._variable.set(self._values[index])


class ColorSelector(ttk.Frame):
    """Color selector with a bordered sample in each native menu item."""

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
        self.combo = _ColorMenuButton(self, textvariable=textvariable,
                                      values=self._colors, width=width)
        self.menu = tk.Menu(self.combo, tearoff=False)
        self._images = []
        for label, color in self._colors.items():
            sample = tk.PhotoImage(master=self.combo, width=16, height=14)
            sample.put('#606060', to=(0, 0, 16, 14))
            sample.put(color, to=(1, 1, 15, 13))
            self._images.append(sample)
            self.menu.add_radiobutton(label=label, variable=textvariable, value=label,
                                      image=sample, compound='left')
        self.combo.configure(menu=self.menu)
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
                self.combo._variable = None


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
    """Return a focusable help button with its own contextual hint."""
    button = ttk.Button(parent, text='?', width=3, takefocus=True,
                        command=lambda: messagebox.showinfo(title, text, parent=parent))
    add_tooltip(button, f'Ajuda: {title}')
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
    'help': ('....####....','..##....##..','.#...##...#.','.#..#..#..#.','#......#...#','#.....#....#','#....#.....#','#..........#','.#...#....#.','.#........#.','..##....##..','....####....'),
}


def icon(widget, name):
    """Render dark symbols with a light outline for light and dark surfaces."""
    glyph = _GLYPHS[name]
    image = tk.PhotoImage(master=widget, width=14, height=14)
    points = {(x + 1, y + 1) for y, row in enumerate(glyph)
              for x, pixel in enumerate(row) if pixel == '#'}
    # The two-tone edge remains distinguishable on a mid-gray button as well
    # as on light and dark themes, without guessing the native button color.
    outline = {(x + dx, y + dy) for x, y in points
               for dx in (-1, 0, 1) for dy in (-1, 0, 1)
               if 0 <= x + dx < 14 and 0 <= y + dy < 14}
    for x, y in outline - points:
        image.put('#ffffff', (x, y))
    for x, y in points:
        image.put('#101010', (x, y))
    return image
