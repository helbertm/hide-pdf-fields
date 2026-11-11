"""Native checks for the shared widgets (TARJA_GUI_TESTS=1)."""
import os
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.environ.get('TARJA_GUI_TESTS') == '1', 'Requer sessão gráfica')
class SharedUiTest(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.tk = tk
        self.root = tk.Tk()

    def tearDown(self):
        self.root.destroy()

    def test_color_selection_updates_visible_swatch_and_keeps_state(self):
        from tarjar import CORES
        from ui_components import ColorSelector
        value = self.tk.StringVar(self.root, 'Preto')
        selector = ColorSelector(self.root, textvariable=value, colors=CORES)
        selector.pack()
        self.root.update()
        self.assertEqual(selector.swatch.itemcget(selector._rectangle, 'fill'), '#000000')
        self.assertEqual(selector.menu.index('end'), 3)
        for index, (name, color) in enumerate(CORES.values()):
            self.assertEqual(selector.menu.type(index), 'radiobutton')
            self.assertEqual(selector.menu.entrycget(index, 'label'), name)
            self.assertTrue(selector.menu.entrycget(index, 'image'))
            self.assertEqual(selector._images[index].get(2, 2), color)
            self.assertEqual(selector._images[index].get(0, 0), (96, 96, 96))
        selector.menu.invoke(1)
        self.assertEqual(value.get(), 'Vermelho escuro')
        selector.combo.current(3)
        self.root.update()
        self.assertEqual(value.get(), 'Branco')
        self.assertEqual(selector.swatch.itemcget(selector._rectangle, 'fill'), '#ffffff')
        self.assertNotEqual(selector.swatch.itemcget(selector._rectangle, 'outline'), '')
        selector.combo.configure(state='disabled')
        self.assertIn('disabled', selector.combo.state())
        self.assertEqual(selector.combo.cget('state'), 'disabled')
        self.assertEqual(selector.combo._open_menu(), 'break')
        selector.combo.configure(state='readonly')
        self.assertIn('readonly', selector.combo.state())
        self.assertEqual(selector.combo.cget('state'), 'readonly')
        selector.destroy()
        value.set('Preto')  # Destroyed widgets must release their variable trace.

    def test_hint_and_help_are_keyboard_operable(self):
        from tkinter import ttk
        from ui_components import add_tooltip, help_button, icon
        widget = ttk.Button(self.root, text='Abrir')
        widget.pack()
        hint = add_tooltip(widget, 'Orientação')
        hint.schedule()
        hint.show()
        self.assertIsNotNone(hint.window)
        hint.hide()
        self.assertIsNone(hint.window)
        help_widget = help_button(self.root, 'Título', 'Conteúdo')
        self.assertEqual(help_widget.cget('text'), '?')
        self.assertEqual(int(help_widget.cget('width')), 3)
        self.assertEqual(help_widget._ui_tooltip.text, 'Ajuda: Título')
        self.assertFalse(help_widget.cget('image'))
        self.assertTrue(int(help_widget.cget('takefocus')))
        with patch('ui_components.messagebox.showinfo') as show:
            help_widget.invoke()
            show.assert_called_once_with('Título', 'Conteúdo', parent=self.root)
        for name in ('folder', 'open', 'process', 'stop', 'manual', 'compare',
                     'previous', 'next', 'delete', 'export', 'help'):
            image = icon(widget, name)
            self.assertEqual((image.width(), image.height()), (14, 14))
            pixels = {image.get(x, y) for x in range(14) for y in range(14)
                      if not image.transparency_get(x, y)}
            self.assertIn((16, 16, 16), pixels)
            self.assertIn((255, 255, 255), pixels)

    def test_menu_keyboard_requests_native_menu_and_keeps_focus(self):
        from tarjar import CORES
        from ui_components import ColorSelector
        value = self.tk.StringVar(self.root, 'Preto')
        selector = ColorSelector(self.root, textvariable=value, colors=CORES)
        selector.pack()
        self.root.update()
        selector.combo.focus_force()
        self.root.update()
        # Native macOS menu posting enters a blocking OS event loop; substitute
        # only that routine to verify Tk's key dispatch without hanging CI.
        self.root.tk.eval('rename ttk::menubutton::Popdown ttk::menubutton::OriginalPopdown')
        self.root.tk.eval('set ::color_menu_posts 0; proc ttk::menubutton::Popdown {w} {incr ::color_menu_posts}')
        try:
            for event in ('<Down>', '<Return>', '<space>'):
                selector.combo.event_generate(event)
                self.root.update()
            self.assertEqual(int(self.root.tk.getvar('::color_menu_posts')), 3)
            self.assertEqual(self.root.focus_get(), selector.combo)
            self.assertEqual(value.get(), 'Preto')
        finally:
            self.root.tk.eval('rename ttk::menubutton::Popdown {}; rename ttk::menubutton::OriginalPopdown ttk::menubutton::Popdown')


if __name__ == '__main__':
    unittest.main()
