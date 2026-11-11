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
        selector.combo.current(3)
        self.root.update()
        self.assertEqual(value.get(), 'Branco')
        self.assertEqual(selector.swatch.itemcget(selector._rectangle, 'fill'), '#ffffff')
        self.assertNotEqual(selector.swatch.itemcget(selector._rectangle, 'outline'), '')
        selector.combo.configure(state='disabled')
        self.assertIn('disabled', selector.combo.state())
        selector.combo.configure(state='readonly')
        self.assertIn('readonly', selector.combo.state())
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
        with patch('ui_components.messagebox.showinfo') as show:
            help_widget.invoke()
            show.assert_called_once_with('Título', 'Conteúdo', parent=self.root)
        for name in ('folder', 'open', 'process', 'stop', 'manual', 'compare',
                     'previous', 'next', 'delete', 'export', 'help'):
            image = icon(widget, name)
            self.assertEqual((image.width(), image.height()), (12, 12))


if __name__ == '__main__':
    unittest.main()
