"""Tests for local version announcements and acknowledgement."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import novidades


class NovidadesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'estado' / 'novidades.json'
        self.version = '1.3.2'

    def test_sem_marcador_e_confirmacao_por_versao(self):
        self.assertTrue(novidades.deve_exibir(self.version, self.path))
        self.assertTrue(novidades.marcar_vista(self.version, self.path))
        self.assertFalse(novidades.deve_exibir(self.version, self.path))
        self.assertEqual(json.loads(self.path.read_text())['versoes_vistas'], [self.version])
        self.assertFalse(novidades.deve_exibir('9.9.9', self.path))
        self.assertIsNone(novidades.obter_novidades('9.9.9'))
        with mock.patch.dict(novidades.NOTAS, {'9.9.9': 'Nova funcionalidade'}):
            self.assertTrue(novidades.deve_exibir('9.9.9', self.path))
            self.assertTrue(novidades.marcar_vista('9.9.9', self.path))
            self.assertFalse(novidades.deve_exibir('9.9.9', self.path))
            self.assertFalse(novidades.deve_exibir(self.version, self.path))

    def test_pacote_exige_registro_explicito_da_versao(self):
        novidades.verificar_notas_da_versao(self.version)
        with self.assertRaisesRegex(ValueError, 'Cadastre a versão'):
            novidades.verificar_notas_da_versao('9.9.9')
        with mock.patch.dict(novidades.NOTAS, {'9.9.9': ''}):
            novidades.verificar_notas_da_versao('9.9.9')
            self.assertFalse(novidades.deve_exibir('9.9.9', self.path))

    def test_arquivo_corrompido_ou_inesperado_permitem_exibir(self):
        self.path.parent.mkdir()
        for value in ('{', '[]', '{"versoes_vistas": 3}', 'x' * 9000):
            self.path.write_text(value)
            self.assertTrue(novidades.deve_exibir(self.version, self.path))

    def test_falha_ao_gravar_nao_interrompe_e_nao_confirma(self):
        with mock.patch('novidades.os.replace', side_effect=PermissionError):
            self.assertFalse(novidades.marcar_vista(self.version, self.path))
        self.assertTrue(novidades.deve_exibir(self.version, self.path))
        self.assertEqual(list(self.path.parent.iterdir()), [])

    def test_caminho_fora_de_diretorio_de_instalacao(self):
        with mock.patch.object(novidades.sys, 'platform', 'win32'), mock.patch.dict(novidades.os.environ, {'LOCALAPPDATA': str(Path(self.temp.name) / 'local')}):
            self.assertEqual(novidades.caminho_padrao(), Path(self.temp.name) / 'local' / 'HidePdfFields' / 'novidades-vistas.json')
        with mock.patch.object(novidades.sys, 'platform', 'darwin'), mock.patch.object(novidades.Path, 'home', return_value=Path(self.temp.name)):
            self.assertEqual(novidades.caminho_padrao(), Path(self.temp.name) / 'Library' / 'Application Support' / 'HidePdfFields' / 'novidades-vistas.json')
        with mock.patch.object(novidades.sys, 'platform', 'linux'), mock.patch.dict(novidades.os.environ, {'XDG_STATE_HOME': str(Path(self.temp.name) / 'state')}):
            self.assertEqual(novidades.caminho_padrao(), Path(self.temp.name) / 'state' / 'HidePdfFields' / 'novidades-vistas.json')


if __name__ == '__main__':
    unittest.main()
