"""Geração segura do modo manual a partir de um snapshot imutável.

Todos os objetos de origem são descartados. O temporário contém apenas páginas
já rasterizadas e tratadas; nenhuma saída é publicada antes da verificação.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

import pymupdf as pdf

from manual_pdf import ManualPdfErro, _abrir, _inspecionar_documento, _ler
from tarjar import CORES, Recusado, inserir_aviso, validar_destinatario


class ManualExportErro(ValueError):
    """Solicitação ou saída incompatível com a geração manual."""


# Aproximadamente 180 MB de RGB por página, excluindo overhead do PDF.
MAX_EXPORT_PIXELS = 60_000_000
MAX_EXPORT_DIMENSAO = 20_000
DPIS = (200, 300, 400)


def _indice(valor, total):
    if isinstance(valor, bool) or not isinstance(valor, int) or not 0 <= valor < total:
        raise ManualExportErro('Página inválida na seleção. Reabra o PDF e tente novamente.')
    return valor


def _retangulo(valor, largura, altura):
    if not isinstance(valor, (list, tuple)) or len(valor) != 4:
        raise ManualExportErro('Área inválida. Redesenhe a marcação e tente novamente.')
    if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in valor):
        raise ManualExportErro('Área inválida. Redesenhe a marcação e tente novamente.')
    x0, y0, x1, y1 = map(float, valor)
    if not (0 <= x0 < x1 <= largura and 0 <= y0 < y1 <= altura):
        raise ManualExportErro('Área fora da página. Redesenhe a marcação e tente novamente.')
    return (x0, y0, x1, y1)


def _caixa_pixels(rect, dpi, width, height):
    # Uma margem de um pixel cobre a diferença de arredondamento entre a
    # imagem raster inteira e sua apresentação nas dimensões exatas do PDF.
    escala = dpi / 72
    return pdf.IRect(max(0, math.floor(rect[0]*escala)-1),
                     max(0, math.floor(rect[1]*escala)-1),
                     min(width, math.ceil(rect[2]*escala)+1),
                     min(height, math.ceil(rect[3]*escala)+1))


def _conferir_mascara(pix, box, rgb):
    esperado = bytes(rgb) * (box.x1 - box.x0)
    pixels = pix.samples_mv
    for y in range(box.y0, box.y1):
        if pixels[y*pix.stride+box.x0*3:y*pix.stride+box.x1*3] != esperado:
            raise ManualExportErro('Não foi possível confirmar a remoção dos dados selecionados.')


def _validar(snapshot, paginas):
    if not isinstance(snapshot, dict):
        raise ManualExportErro('Seleção inválida. Revise o documento e tente novamente.')
    total = len(paginas)
    excluidas = snapshot.get('excluidas')
    if not isinstance(excluidas, (list, tuple)):
        raise ManualExportErro('Seleção de páginas inválida.')
    indices = [_indice(x,total) for x in excluidas]
    if len(set(indices)) != len(indices):
        raise ManualExportErro('Seleção de páginas duplicada.')
    exclusoes = set(indices)
    mantidas = [i for i in range(total) if i not in exclusoes]
    if not mantidas:
        raise ManualExportErro('O resultado precisa manter pelo menos uma página.')
    marcas = snapshot.get('marcas')
    if not isinstance(marcas, dict):
        raise ManualExportErro('Seleção de tarjas inválida.')
    normalizadas = {}
    for indice, lista in marcas.items():
        _indice(indice,total)
        if not isinstance(lista, (list,tuple)):
            raise ManualExportErro('Seleção de tarjas inválida.')
        pagina = paginas[indice]
        normalizadas[indice] = []
        for marca in lista:
            if not isinstance(marca, dict):
                raise ManualExportErro('Seleção de tarjas inválida.')
            cor = marca.get('cor')
            if not isinstance(cor, str) or cor not in CORES:
                raise ManualExportErro('Cor de tarja inválida.')
            rect = _retangulo(marca.get('rect'),pagina['largura'],pagina['altura'])
            normalizadas[indice].append((rect, CORES[cor][1]))
    aviso = snapshot.get('aviso')
    if not isinstance(aviso,dict):
        raise ManualExportErro('Defina a área do aviso antes de gerar o PDF.')
    indice_aviso = _indice(aviso.get('pagina'),total)
    if indice_aviso in exclusoes:
        raise ManualExportErro('O aviso está em uma página excluída. Restaure a página ou redefina o aviso.')
    pagina_aviso = paginas[indice_aviso]
    area_aviso = _retangulo(aviso.get('rect'),pagina_aviso['largura'],pagina_aviso['altura'])
    if area_aviso[2]-area_aviso[0] <= 6 or area_aviso[3]-area_aviso[1] <= 6:
        raise ManualExportErro('O aviso não cabe nesta área. Remova-a e desenhe uma área maior.')
    try:
        destinatario = validar_destinatario(snapshot.get('destinatario'))
    except Recusado as exc:
        raise ManualExportErro(str(exc)) from None
    instante_iso = snapshot.get('instante')
    try:
        if not isinstance(instante_iso,str):
            raise ValueError
        instante = datetime.fromisoformat(instante_iso)
    except ValueError:
        raise ManualExportErro('Data da geração inválida. Tente novamente.') from None
    dpi = snapshot.get('dpi')
    if isinstance(dpi,bool) or not isinstance(dpi,int) or dpi not in DPIS:
        raise ManualExportErro('Resolução de geração inválida.')
    for indice in mantidas:
        page = paginas[indice]
        w = math.ceil(page['largura'] * dpi / 72)
        h = math.ceil(page['altura'] * dpi / 72)
        if w <= 0 or h <= 0 or max(w,h) > MAX_EXPORT_DIMENSAO or w*h > MAX_EXPORT_PIXELS:
            raise ManualExportErro(f'A página {indice+1} é grande demais para a geração nesta resolução.')
    return mantidas, normalizadas, indice_aviso, area_aviso, destinatario, instante, dpi


def _hash_arquivo(caminho):
    digest = hashlib.sha256()
    with open(caminho,'rb') as arquivo:
        for bloco in iter(lambda: arquivo.read(1024*1024), b''):
            digest.update(bloco)
    return digest.hexdigest()


def _validar_destino(origem, destino):
    if not isinstance(destino, (str, Path)):
        raise ManualExportErro('Escolha um nome de arquivo PDF de saída.')
    try:
        destino = Path(destino).expanduser()
        if destino.suffix.lower() != '.pdf' or not destino.name or not destino.parent.is_dir():
            raise ManualExportErro('Escolha um arquivo PDF em uma pasta de saída existente.')
        if destino.resolve() == origem.resolve() or os.path.lexists(destino):
            raise ManualExportErro('A saída já existe ou coincide com o original. Escolha outro destino.')
        return destino
    except ManualExportErro:
        raise
    except (OSError, ValueError, RuntimeError):
        raise ManualExportErro('Não foi possível usar o destino escolhido.') from None


def _verificar_saida(caminho, esperadas):
    """Verifica cada imagem efetivamente incorporada e a estrutura da cópia."""
    try:
        with pdf.open(caminho) as doc:
            if (not doc.is_pdf or doc.is_repaired or len(doc) != len(esperadas)
                    or doc.embfile_count() or doc.get_xml_metadata() or doc.get_toc()):
                raise ManualExportErro('Falha na verificação da estrutura do PDF gerado.')
            if any(doc.metadata.get(k) for k in ('title','author','subject','keywords','creator','producer','creationDate','modDate')):
                raise ManualExportErro('Metadados inesperados no PDF gerado.')
            for pagina, esperado in zip(doc, esperadas):
                w,h,px_w,px_h,digest = esperado
                if abs(pagina.rect.width-w) > 0.01 or abs(pagina.rect.height-h) > 0.01 or pagina.rotation:
                    raise ManualExportErro('Dimensões inesperadas no PDF gerado.')
                if pagina.get_text().strip() or list(pagina.annots() or []) or list(pagina.widgets() or []) or pagina.get_links() or pagina.get_fonts():
                    raise ManualExportErro('Conteúdo não raster inesperado no PDF gerado.')
                imagens = pagina.get_images(full=True)
                if len(imagens) != 1 or imagens[0][1] != 0:
                    raise ManualExportErro('Imagem adicional ou transparência inesperada no PDF gerado.')
                pix = pdf.Pixmap(doc,imagens[0][0])
                if (pix.width,pix.height,pix.n) != (px_w,px_h,3) or hashlib.sha256(pix.samples).digest() != digest:
                    raise ManualExportErro('Pixels do PDF gerado diferem da cópia processada.')
    except ManualExportErro:
        raise
    except Exception:
        raise ManualExportErro('Não foi possível verificar o PDF gerado.') from None


def exportar(snapshot):
    """Gera uma cópia validada; a entrada e arquivos existentes não são alterados.

    ``snapshot`` contém origem, sha256_origem, destino, excluidas, marcas,
    aviso, destinatario, instante (ISO 8601) e dpi. Índices são sempre os
    índices originais, a partir de zero. O retorno contém o caminho de saída,
    seu SHA-256, os índices originais das páginas preservadas e se a limpeza
    do arquivo temporário sanitizado ficou pendente.
    """
    if not isinstance(snapshot,dict):
        raise ManualExportErro('Seleção inválida. Revise o documento e tente novamente.')
    caminho = snapshot.get('origem')
    esperado_hash = snapshot.get('sha256_origem')
    if not isinstance(caminho,(str,Path)) or not isinstance(esperado_hash,str) or not re.fullmatch(r'[0-9a-f]{64}',esperado_hash):
        raise ManualExportErro('Identificação do PDF inválida. Abra o arquivo novamente.')
    origem = Path(caminho).expanduser()
    destino = _validar_destino(origem,snapshot.get('destino'))
    try:
        dados = _ler(origem)
        if hashlib.sha256(dados).hexdigest() != esperado_hash:
            raise ManualExportErro('O PDF original foi alterado. Abra o arquivo novamente.')
        with _abrir(dados) as original:
            paginas = _inspecionar_documento(original)
            mantidas, marcas, aviso_pagina, aviso_rect, destinatario, instante, dpi = _validar(snapshot,paginas)
            # Validar encaixe antes de criar temporário ou processar páginas.
            from manual_pdf import visualizar_aviso
            visualizar_aviso(destinatario,aviso_rect[2]-aviso_rect[0],aviso_rect[3]-aviso_rect[1],instante.isoformat())
            fd, temporario = tempfile.mkstemp(prefix='.ocultar-',suffix='.pdf',dir=destino.parent)
            os.close(fd)
            limpeza_pendente = False
            try:
                esperadas = []
                for numero, indice in enumerate(mantidas):
                    pagina = original[indice]
                    pix = pagina.get_pixmap(dpi=dpi,colorspace=pdf.csRGB,alpha=False,annots=True)
                    if pix.n != 3 or pix.alpha:
                        raise ManualExportErro('Não foi possível preparar a imagem opaca da página.')
                    for rect,rgb in marcas.get(indice,[]):
                        caixa = _caixa_pixels(rect,dpi,pix.width,pix.height)
                        pix.set_rect(caixa,rgb)
                        _conferir_mascara(pix,caixa,rgb)
                    if indice == aviso_pagina:
                        inserir_aviso(pix,pagina.rect,destinatario,dpi,instante,area=pdf.Rect(aviso_rect))
                    esperadas.append((float(pagina.rect.width),float(pagina.rect.height),pix.width,pix.height,hashlib.sha256(pix.samples).digest()))
                    if numero == 0:
                        with pdf.open() as saida:
                            out = saida.new_page(width=pagina.rect.width,height=pagina.rect.height)
                            out.insert_image(out.rect,pixmap=pix,keep_proportion=False)
                            saida.set_metadata({})
                            saida.save(temporario,garbage=4,deflate=True)
                    else:
                        with pdf.open(temporario) as saida:
                            out = saida.new_page(width=pagina.rect.width,height=pagina.rect.height)
                            out.insert_image(out.rect,pixmap=pix,keep_proportion=False)
                            saida.saveIncr()
                    del pix
                _verificar_saida(temporario,esperadas)
                if hashlib.sha256(_ler(origem)).hexdigest() != esperado_hash:
                    raise ManualExportErro('O PDF original foi alterado. Abra o arquivo novamente.')
                digest = _hash_arquivo(temporario)
                try:
                    os.link(temporario,destino)
                except FileExistsError:
                    raise ManualExportErro('A saída já existe. Escolha outro destino.') from None
            finally:
                try:
                    os.unlink(temporario)
                except FileNotFoundError:
                    pass
                except OSError:
                    limpeza_pendente = True
            return {'destino': str(destino), 'sha256_saida': digest,
                    'paginas_originais': mantidas, 'limpeza_pendente': limpeza_pendente}
    except ManualExportErro:
        raise
    except (ManualPdfErro,Recusado) as exc:
        raise ManualExportErro(str(exc)) from None
    except Exception:
        raise ManualExportErro('Não foi possível gerar o PDF. Confira o arquivo, o destino e o espaço disponível.') from None
