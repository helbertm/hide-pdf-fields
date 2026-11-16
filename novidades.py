"""Novidades por versão e confirmação local, sem registrar dados dos PDFs."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

# Novas versões devem ter suas próprias notas; não reutilize as antigas.
NOTAS = {
    '1.4.0': (
        'Modo manual disponível\n\n'
        'Agora você pode ocultar informações em PDFs de diferentes modelos. '
        'Abra um arquivo, marque as áreas que deseja ocultar, escolha as páginas '
        'e indique onde inserir o aviso ao destinatário.\n\n'
        'O aplicativo gera uma nova cópia para você conferir antes de compartilhar. '
        'O arquivo original é preservado.'
    ),
}


def verificar_notas_da_versao(versao: str) -> None:
    """Require an explicit notes entry before building a release."""
    if versao not in NOTAS:
        raise ValueError(
            f'Cadastre a versão {versao} em novidades.NOTAS antes de gerar o pacote; '
            'use texto vazio quando não houver novidades.'
        )


def obter_novidades(versao: str) -> str | None:
    return NOTAS.get(versao)


def caminho_padrao() -> Path:
    if sys.platform == 'win32':
        local = os.environ.get('LOCALAPPDATA')
        if local:
            return Path(local) / 'HidePdfFields' / 'novidades-vistas.json'
        return Path.home() / 'AppData' / 'Local' / 'HidePdfFields' / 'novidades-vistas.json'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'HidePdfFields' / 'novidades-vistas.json'
    local = os.environ.get('XDG_STATE_HOME')
    return (Path(local) if local and Path(local).is_absolute() else Path.home() / '.local' / 'state') / 'HidePdfFields' / 'novidades-vistas.json'


def _ler(caminho: Path) -> set[str]:
    try:
        with caminho.open('rb') as arquivo:
            dados = arquivo.read(8193)
        if len(dados) > 8192:
            return set()
        versoes = json.loads(dados).get('versoes_vistas', [])
        if not isinstance(versoes, list) or not all(isinstance(v, str) for v in versoes):
            return set()
        return set(versoes)
    except (OSError, ValueError, TypeError, AttributeError):
        return set()


def deve_exibir(versao: str, caminho: Path | None = None) -> bool:
    if not obter_novidades(versao):
        return False
    try:
        return versao not in _ler(Path(caminho) if caminho is not None else caminho_padrao())
    except (OSError, RuntimeError, ValueError):
        return True


def marcar_vista(versao: str, caminho: Path | None = None) -> bool:
    if not obter_novidades(versao):
        return False
    temporario = None
    try:
        destino = Path(caminho) if caminho is not None else caminho_padrao()
        destino.parent.mkdir(parents=True, exist_ok=True)
        vistas = _ler(destino)
        vistas.add(versao)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=destino.parent,
                                         prefix='.novidades-', delete=False) as arquivo:
            temporario = Path(arquivo.name)
            json.dump({'versoes_vistas': sorted(vistas)}, arquivo, ensure_ascii=False)
            arquivo.write('\n')
        os.replace(temporario, destino)
        temporario = None
        return True
    except (OSError, RuntimeError, ValueError):
        return False
    finally:
        if temporario is not None:
            try:
                temporario.unlink(missing_ok=True)
            except OSError:
                pass
