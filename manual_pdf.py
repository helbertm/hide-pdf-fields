"""Inspeção e renderização somente leitura para o modo manual de PDF.

Os valores devolvidos são serializáveis e não carregam objetos PyMuPDF. O hash
vincula cada renderização ao mesmo documento que foi previamente inspecionado.
"""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

import pymupdf as pdf


class ManualPdfErro(ValueError):
    """Documento ou solicitação incompatível com o leitor manual."""


# 100% corresponde a 96 pixels lógicos por polegada, em coordenadas de tela.
ESCALA_100 = 96 / 72
# Evita pedidos de alocação desproporcionais com páginas grandes/corrompidas.
MAX_PIXELS_PAGINA = 50_000_000
MAX_DIMENSAO_PIXELS = 20_000


def _ler(caminho):
    try:
        path = Path(caminho)
        if path.suffix.lower() != '.pdf' or not path.is_file():
            raise ManualPdfErro('Selecione um arquivo PDF existente.')
        return path.read_bytes()
    except ManualPdfErro:
        raise
    except (OSError, TypeError, ValueError):
        raise ManualPdfErro('Não foi possível ler o arquivo PDF.') from None


def _abrir(dados):
    try:
        documento = pdf.open(stream=dados, filetype='pdf')
    except Exception:
        raise ManualPdfErro('O arquivo não é um PDF íntegro e legível.') from None
    if not documento.is_pdf or documento.needs_pass or documento.is_repaired:
        documento.close()
        raise ManualPdfErro('PDF inválido, reparado ou protegido por senha não é suportado.')
    return documento


def _inspecionar_documento(documento):
    try:
        if len(documento) < 1:
            raise ManualPdfErro('O PDF não contém páginas.')
        paginas = []
        for indice, pagina in enumerate(documento):
            # page.rotation é a rotação efetiva, inclusive herdada da árvore PDF.
            if pagina.rotation != 0:
                raise ManualPdfErro(f'A página {indice + 1} tem rotação; arquivos com páginas rotacionadas não são aceitos.')
            retangulo = pagina.rect
            valores = [retangulo.width, retangulo.height, *pagina.cropbox, *pagina.mediabox]
            if not all(math.isfinite(valor) for valor in valores):
                raise ManualPdfErro(f'A página {indice + 1} tem dimensões inválidas.')
            largura, altura = float(retangulo.width), float(retangulo.height)
            if largura <= 0 or altura <= 0:
                raise ManualPdfErro(f'A página {indice + 1} tem dimensões inválidas.')
            pixels_x, pixels_y = math.ceil(largura * ESCALA_100), math.ceil(altura * ESCALA_100)
            if max(pixels_x, pixels_y) > MAX_DIMENSAO_PIXELS or pixels_x * pixels_y > MAX_PIXELS_PAGINA:
                raise ManualPdfErro(f'A página {indice + 1} é grande demais para a visualização em 100%.')
            paginas.append({'indice': indice, 'largura': largura, 'altura': altura,
                            'cropbox': list(pagina.cropbox), 'mediabox': list(pagina.mediabox)})
        return paginas
    except ManualPdfErro:
        raise
    except Exception:
        raise ManualPdfErro('Não foi possível inspecionar todas as páginas do PDF.') from None


def inspecionar(caminho):
    """Valida o documento completo sem alterá-lo; devolve hash e geometria."""
    dados = _ler(caminho)
    with _abrir(dados) as documento:
        paginas = _inspecionar_documento(documento)
    return {'sha256': hashlib.sha256(dados).hexdigest(),
            'total_paginas': len(paginas), 'paginas': paginas}


def renderizar(caminho, sha256, indice):
    """Gera PNG em memória de uma página validada, sempre em escala fixa de 100%."""
    if not isinstance(sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', sha256):
        raise ManualPdfErro('A identificação do documento é inválida. Abra o PDF novamente.')
    if not isinstance(indice, int) or isinstance(indice, bool) or indice < 0:
        raise ManualPdfErro('Número de página inválido.')
    dados = _ler(caminho)
    if hashlib.sha256(dados).hexdigest() != sha256:
        raise ManualPdfErro('O PDF foi alterado. Abra o arquivo novamente.')
    with _abrir(dados) as documento:
        paginas = _inspecionar_documento(documento)
        if indice >= len(paginas):
            raise ManualPdfErro('Número de página inválido.')
        try:
            pagina = documento[indice]
            imagem = pagina.get_pixmap(matrix=pdf.Matrix(ESCALA_100, ESCALA_100),
                                       colorspace=pdf.csRGB, alpha=False)
            resultado = imagem.tobytes('png')
        except Exception:
            raise ManualPdfErro('Não foi possível visualizar esta página do PDF.') from None
    if hashlib.sha256(_ler(caminho)).hexdigest() != sha256:
        raise ManualPdfErro('O PDF foi alterado. Abra o arquivo novamente.')
    return resultado
