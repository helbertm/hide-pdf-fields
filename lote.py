"""Orquestração compartilhada por CLI e GUI; previews não são gravados em disco."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
from datetime import datetime
import re
import unicodedata
from pathlib import Path
from typing import Callable
import pymupdf as pdf
from tarjar import Recusado, SemTarjas, CAMPOS, plan, redact, validar_destinatario


@dataclass
class Resultado:
    origem: str
    destino: str = ''
    status: str = 'aguardando'
    tipo: str = ''
    mensagem: str = ''
    sha256_origem: str = ''
    sha256_saida: str = ''


def descobrir(entrada, saida=None):
    entrada = Path(entrada).expanduser().resolve()
    saida = entrada if saida is None else Path(saida).expanduser().resolve()
    if not entrada.is_dir():
        raise Recusado('Escolha uma pasta de entrada existente.')
    if saida.exists() and not saida.is_dir():
        raise Recusado('O destino deve ser uma pasta.')
    files = sorted((p for p in entrada.iterdir() if p.is_file() and p.suffix.lower() == '.pdf'),
                   key=lambda p: (p.name.casefold(), p.name))
    if not files:
        raise Recusado('Nenhum PDF encontrado. Subpastas não são incluídas.')
    return files, saida


def normalizar_nome(valor):
    slug = unicodedata.normalize('NFKD',valor).encode('ascii','ignore').decode('ascii')
    slug = re.sub(r'\s+', '_',slug)
    return re.sub(r'[^A-Za-z0-9_]', '',slug).strip('_')


def nome_saida(origem, destinatario, instante):
    slug = normalizar_nome(validar_destinatario(destinatario))
    original = normalizar_nome(Path(origem).stem)
    if not slug:
        raise Recusado('O destinatário deve conter letras ou números para formar o nome do arquivo.')
    if not original:
        raise Recusado('O nome original deve conter letras ou números para formar o nome de saída.')
    return f'{slug}-{instante:%d%m%y}-{original}.pdf'


def processar_arquivo(origem, pasta_saida, tipo='auto', dpi=300, campos=None, destinatario=None, gerado_em=None, cor='preto'):
    origem = Path(origem)
    try:
        instante = gerado_em if gerado_em is not None else datetime.now().astimezone()
        destino = Path(pasta_saida) if pasta_saida is not None else origem.parent
        destino = destino / nome_saida(origem,destinatario,instante)
        if origem.suffix.lower() != '.pdf' or not origem.is_file():
            raise Recusado('Entrada permitida apenas para arquivos PDF existentes.')
        # Vincula a futura conferência ao documento que realmente foi processado.
        before = hashlib.sha256(origem.read_bytes()).hexdigest()
        info = redact(origem, destino, tipo, dpi, campos, destinatario, gerado_em=instante,cor=cor)
        if hashlib.sha256(origem.read_bytes()).hexdigest() != before:
            return Resultado(str(origem), status='falhou', mensagem='A origem mudou durante o processamento; confira a pasta de saída.')
        mensagem = f"{len(info['regioes'])} grupo(s) ocultado(s); {len(info['mantidos'])} mantido(s) por escolha."
        if info['paginas_descartadas']:
            mensagem += f" Apenas a primeira página foi mantida; {info['paginas_descartadas']} página(s) descartada(s)."
        if info['ausentes']:
            mensagem += ' Observações finais: não encontradas.'
        return Resultado(str(origem), str(destino), 'concluido', info['tipo'],
                         mensagem,
                         before, info['sha256_saida'])
    except SemTarjas as e:
        return Resultado(str(origem), status='ignorado', mensagem=str(e))
    except Recusado as e:
        return Resultado(str(origem), status='recusado', mensagem=str(e))
    except Exception:
        # Bibliotecas podem incluir conteúdo do PDF em suas exceções.
        return Resultado(str(origem), status='falhou', mensagem='Falha de leitura/gravação. Confira o PDF, permissões e espaço em disco.')


def processar_lote(arquivos, saida, tipo='auto', dpi=300,
                    interromper: Callable[[], bool] = lambda: False, destinatario=None, cor='preto'):
    """Iterador sequencial; cancelamento só entre arquivos."""
    instante = datetime.now().astimezone()
    for origem in list(arquivos):
        if interromper():
            yield Resultado(str(origem), status='cancelado', mensagem='Não iniciado por solicitação do usuário.')
        else:
            yield processar_arquivo(origem, saida, tipo, dpi, destinatario=destinatario,gerado_em=instante,cor=cor)


def _miniatura(path, largura, altura, expected_hash=''):
    if Path(path).suffix.lower() != '.pdf':
        raise Recusado('Prévia permitida apenas para arquivos PDF.')
    data = Path(path).read_bytes()
    if expected_hash and hashlib.sha256(data).hexdigest() != expected_hash:
        raise Recusado('Arquivo alterado após o processamento; recarregue e processe em outro destino.')
    with pdf.open(stream=data, filetype='pdf') as d:
        if not d.is_pdf or d.needs_pass or not len(d):
            raise Recusado('Prévia disponível apenas para PDF íntegro, sem senha.')
        if len(d) > 1:
            plan(d)
        p = d[0]
        escala = min(largura/p.rect.width, altura/p.rect.height)
        pix = p.get_pixmap(matrix=pdf.Matrix(escala, escala), colorspace=pdf.csRGB, alpha=False)
        return pix.tobytes('png')


def comparar(resultado, largura=420, altura=600):
    """Somente bytes PNG/strings atravessam a fronteira de processos."""
    largura, altura = min(max(int(largura),100),1600), min(max(int(altura),100),2200)
    previews = {}
    try:
        with pdf.open(resultado.origem) as d:
            tipo, _, _ = plan(d)
            previews['paginas_origem'] = len(d)
        previews['tipo'] = tipo
    except Exception:
        previews['tipo'] = ''
    for side, path, expected in [
        ('antes', resultado.origem, resultado.sha256_origem),
        ('depois', resultado.destino if resultado.status == 'concluido' else '', resultado.sha256_saida),
    ]:
        if not path:
            previews[side] = None
            previews[side+'_erro'] = 'Ainda não processado.' if resultado.status in ('aguardando','processando') else 'Sem resultado deste processamento.'
            continue
        try:
            previews[side] = _miniatura(path,largura,altura,expected)
            previews[side+'_erro'] = ''
        except Recusado as e:
            previews[side] = None
            previews[side+'_erro'] = str(e)
        except Exception:
            previews[side] = None
            previews[side+'_erro'] = 'Não foi possível gerar a prévia deste PDF.'
    return previews
