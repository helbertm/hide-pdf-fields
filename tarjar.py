#!/usr/bin/env python3
"""Tarjas destrutivas em pixels para os dois modelos documentados no README."""
from __future__ import annotations
import argparse
from datetime import datetime
import unicodedata
import hashlib
import math
import os
from pathlib import Path
import sys
import tempfile
import pymupdf as pdf


class Recusado(ValueError):
    """Entrada incompatível ou saída que não passou na verificação."""


class SemTarjas(Recusado):
    """Nenhuma região aplicável; não produzir cópia com nome tarjado."""


CORES = {
    'preto': ('Preto', (0, 0, 0)),
    'vermelho_escuro': ('Vermelho escuro', (128, 0, 0)),
    'cinza_escuro': ('Cinza escuro', (64, 64, 64)),
    'branco': ('Branco', (255, 255, 255)),
}


CAMPOS = {
    'pedido': {
        'gestora': 'Nome da gestora',
        'consultor': 'Nome do consultor',
        'matriz_razao_social': 'Matriz: razão social',
        'matriz_nome_fantasia': 'Matriz: nome fantasia',
        'matriz_cnpj': 'Matriz: CNPJ',
        'matriz_inscricao_estadual': 'Matriz: inscrição estadual',
        'filial_razao_social': 'Filial: razão social',
        'filial_nome_fantasia': 'Filial: nome fantasia',
        'filial_cnpj': 'Filial: CNPJ',
        'filial_inscricao_estadual': 'Filial: inscrição estadual',
        'endereco_completo': 'Endereço fiscal/entrega/cobrança (bloco)',
        'observacoes_finais': 'Observações finais, quando houver',
    },
    'nota': {
        'autenticidade': 'Código de autenticidade',
        'qr_code': 'QR code',
        'tomador_completo': 'Dados do tomador (bloco completo)',
        'chave_nacional': 'Chave de acesso nacional',
    },
}


def selecionar_campos(tipo, campos):
    if campos is None:
        return list(CAMPOS[tipo])
    if not isinstance(campos, (list, tuple, set)) or any(not isinstance(c,str) for c in campos):
        raise Recusado('A seleção de campos deve ser uma lista de identificadores válidos.')
    if set(campos) - set(CAMPOS[tipo]):
        raise Recusado('Campo desconhecido ou incompatível com o tipo de documento.')
    return [c for c in CAMPOS[tipo] if c in campos]


# Coordenadas em pontos PDF, origem no canto superior esquerdo.
# As âncoras validam o modelo, não os valores pessoais dos exemplos.
PEDIDO = [
    ('PEDIDO Nº:', 1, 227.7, 30.2), ('GESTORA:', 1, 427.9, 30.2),
    ('CONSULTOR:', 1, 418.6, 41.5), ('MATRIZ', 1, 285.0, 69.9),
    ('FILIAL', 1, 287.2, 126.6), ('RAZÃO SOCIAL:', 2, 36.7, 86.3),
    ('NOME FANTASIA:', 2, 31.1, 97.7), ('CNPJ:', 2, 74.4, 109.0),
    ('INSC. ESTADUAL:', 2, 317.0, 109.0),
    ('ENDEREÇO FISCAL ENTREGA / COBRANÇA', 1, 215.9, 177.0),
    ('ITENS ADQUIRIDOS - APLICAÇÃO DE VENDA:', 1, 179.6, 245.1),
]
NOTA = [
    ('Prefeitura Municipal de Itaúna - MG', 1, 82.1, 22.0),
    ('Dados do Prestador de Serviço', 1, 33.3, 69.2),
    ('Cód. de Autenticidade', 1, 395.7, 124.7),
    ('Identificação da Nota Fiscal Eletrônica', 1, 33.3, 171.7),
    ('Dados do Tomador de Serviços', 1, 33.3, 230.3),
    ('Dados do Intermediário de Serviços', 1, 33.3, 326.4),
    ('Descrição dos Serviços', 1, 33.3, 368.1),
    ('Detalhamento dos Tributos', 1, 33.3, 493.2),
    ('Informações Adicionais', 1, 33.3, 587.1),
    ('Chave de acesso no Ambiente de Dados Nacional:', 1, 33.3, 622.4),
    ('Consulte a autenticidade deste documento', 1, 104.8, 647.7),
]


# Elementos gráficos estruturais observados nas bordas das células da nota.
# Apenas retângulos simples nestas posições podem cruzar uma região sensível.
NOTA_BORDAS = {
    'autenticidade': [
        ('s',(29.44,65.13,579.83,166.16)),
        ('f',(391.54,83.85,392.25,165.10)), ('f',(392.25,83.85,392.95,165.10)),
        ('f',(392.25,144.61,491.16,145.32)), ('f',(392.95,144.61,491.16,145.32)),
        ('f',(491.16,83.85,491.87,165.10)),
    ],
    'tomador_completo': [
        ('f',(29.09,320.54,580.18,321.25)), ('f',(579.48,227.28,580.18,321.25)),
        ('f',(29.09,227.28,579.48,243.53)), ('f',(578.77,227.28,579.48,243.53)),
        ('f',(29.09,227.28,29.79,243.53)), ('f',(29.09,243.53,579.48,244.23)),
        ('f',(29.09,243.53,29.79,320.54)),
    ],
    'chave_nacional': [
        ('f',(29.09,645.54,580.18,646.25)), ('f',(579.48,581.96,580.18,646.25)),
        ('f',(29.09,584.08,579.48,600.33)), ('f',(29.09,584.08,29.79,600.33)),
        ('f',(29.09,600.33,579.48,601.03)), ('f',(29.09,600.33,29.79,645.54)),
    ],
}


def borda_estrutural(name, drawing):
    items = drawing['items']
    if len(items) != 1 or items[0][0] != 're':
        return False
    actual = drawing['rect']
    return any(drawing['type'] == typ and all(abs(a-b) <= 0.25 for a,b in zip(actual,expected))
               for typ,expected in NOTA_BORDAS[name])


def anchor(page, text, count=1):
    found = sorted(page.search_for(text), key=lambda r: (r.y0, r.x0))
    if len(found) != count:
        raise Recusado(f'Âncora ausente ou ambígua: {text!r}. Modelo não suportado.')
    return found


def validate_anchors(page, specs, tolerance=0.25):
    for text, count, x, y in specs:
        found = anchor(page, text, count)
        for i, r in enumerate(found):
            expected_y = y + i * 56.7  # linhas equivalentes matriz/filial
            if abs(r.x0 - x) > tolerance or abs(r.y0 - expected_y) > tolerance:
                raise Recusado(f'Posição inesperada de {text!r}. Revise o modelo.')


def plan(doc, requested='auto'):
    if not doc.is_pdf or doc.needs_pass or doc.is_repaired:
        raise Recusado('Exige PDF íntegro e sem senha.')
    if len(doc) < 1:
        raise Recusado('PDF sem páginas.')
    p = doc[0]
    if p.rotation or p.cropbox != p.mediabox or p.rect.x0 or p.rect.y0:
        raise Recusado('Rotação ou recorte de página não suportado.')
    if abs(p.rect.width - 595) > 1 or abs(p.rect.height - 842) > 1:
        raise Recusado('Tamanho de página incompatível com os modelos A4 enviados.')
    if list(p.annots() or []) or list(p.widgets() or []):
        raise Recusado('Anotações/formulários não suportados neste modelo.')
    candidates = []
    if p.search_for('PEDIDO Nº:'):
        candidates.append('pedido')
    if p.search_for('Dados do Tomador de Serviços'):
        candidates.append('nota')
    if len(candidates) != 1:
        raise Recusado('Modelo não identificado. PDFs digitalizados exigem outro fluxo; OCR não é usado.')
    kind = candidates[0]
    if kind == 'nota' and len(doc) != 1:
        raise Recusado('Notas fiscais com mais de uma página não são suportadas.')
    if requested not in ('auto', kind):
        raise Recusado('Tipo solicitado não corresponde ao documento.')
    # A nota admite variações subponto em todas as âncoras; o pedido mantém o perfil existente.
    validate_anchors(p, PEDIDO if kind == 'pedido' else NOTA, tolerance=0.25 if kind == 'pedido' else 0.6)
    tail = None
    if kind == 'pedido':
        masks = [('gestora', (465, 28.4, 566.8, 40.3)),
                 ('consultor', (465, 40.3, 566.8, 51.4))]
        for section, offset in [('matriz', 0), ('filial', 56.7)]:
            masks += [(section + '_razao_social', (98,85+offset,488,96.4+offset)),
                      (section + '_nome_fantasia', (98,96.4+offset,566.8,107.8+offset)),
                      (section + '_cnpj', (98,107.8+offset,313.5,119.2+offset))]
            insc = anchor(p, 'INSC. ESTADUAL:', 2)[0 if offset == 0 else 1]
            masks.append((section + '_inscricao_estadual',
                          (insc.x1+0.5,107.8+offset,566.8,119.2+offset)))
        masks.append(('endereco_completo', (28.5,187,566.8,233)))
        payments = [r for r in p.search_for('PAGAMENTO') if 250 < r.x0 < r.x1 < 350]
        if len(payments) != 1:
            raise Recusado('Cabeçalho PAGAMENTO ausente ou ambíguo.')
        payment = payments[0]
        totals = p.search_for('VALOR TOTAL DO PEDIDO:')
        billings = p.search_for('Faturamento na entrega?') + p.search_for('Faturamentos na entrega?')
        if len(totals) > 1 or len(billings) > 1 or not (totals or billings):
            raise Recusado('Fechamento do pedido ausente ou ambíguo na primeira página.')
        total = totals[0] if totals else None
        billing = billings[0] if billings else None
        if (total and abs(total.x0-357.3)>1) or (billing and abs(billing.x0-36.9)>1):
            raise Recusado('Posição inesperada do fechamento do pedido.')
        for marker in (total, billing):
            if marker and not (290 < payment.y0 < marker.y0 < 760):
                raise Recusado('Estrutura de pagamento/rodapé incompatível.')
        if total and billing and (billing.y0 <= total.y0 or abs(billing.y0-total.y0-17.2) > 3):
            raise Recusado('Rodapé do pedido fora do padrão.')
        # O conteúdo depois do fechamento é tratado como observação.
        tail = (billing or total).y1 + 4
    else:
        masks = [('autenticidade', (394,132,491.5,144.8)),
                 ('qr_code', (492,83,579,166)),
                 ('tomador_completo', (30,243,579,322)),
                 ('chave_nacional', (30,600,579,646))]
        # As áreas textuais sensíveis devem caber integralmente nas máscaras.
        # Uma pequena margem detecta dados que estejam escapando das bordas.
        auth_label = anchor(p, 'Cód. de Autenticidade')[0]
        words = [pdf.Rect(word[:4]) for word in p.get_text('words')]
        images = [pdf.Rect(image['bbox']) for image in p.get_image_info()]
        drawings = p.get_drawings()
        paint_log = p.get_bboxlog()
        painted_text = [pdf.Rect(item[1]) for item in paint_log if item[0] in ('fill-text','stroke-text')]
        for name, coords in masks:
            if name == 'qr_code':
                continue
            target = pdf.Rect(coords)
            guard = (pdf.Rect(390,132,495,145) if name == 'autenticidade'
                     else target + (-0.6,-0.6,0.6,0.6))
            for bounds in words:
                if name == 'autenticidade' and auth_label.contains(bounds):
                    continue
                if bounds.intersects(guard) and not target.contains(bounds):
                    raise Recusado(f'Conteúdo de {name} fora da região suportada.')
            for bounds in painted_text:
                if bounds.intersects(guard) and not target.contains(bounds):
                    raise Recusado(f'Texto pintado de {name} fora da região suportada.')
            for bounds in images:
                if bounds.intersects(guard) and not target.contains(bounds):
                    raise Recusado(f'Imagem de {name} fora da região suportada.')
            for drawing in drawings:
                bounds = pdf.Rect(drawing['rect'])
                indices = [drawing['seqno']]
                if drawing['type'] == 'fs':
                    indices.append(drawing['seqno'] + 1)
                for index in indices:
                    if index >= len(paint_log) or paint_log[index][0] not in ('fill-path','stroke-path'):
                        raise Recusado('Não foi possível verificar os limites gráficos da nota.')
                    bounds |= pdf.Rect(paint_log[index][1])
                if bounds.intersects(guard) and not target.contains(bounds) and not borda_estrutural(name,drawing):
                    raise Recusado(f'Gráfico de {name} fora da região suportada.')
        qr = [i for i in p.get_image_info() if pdf.Rect(i['bbox']).intersects(pdf.Rect(492,83,579,166))]
        if len(qr) != 1 or not pdf.Rect(492,83,579,166).contains(pdf.Rect(qr[0]['bbox'])):
            raise Recusado('Imagem do QR code ausente ou fora da região esperada.')
    return kind, [(name, pdf.Rect(r)) for name, r in masks], tail


def pixel_box(rect, dpi, width, height):
    s = dpi / 72
    return pdf.IRect(max(0, math.floor(rect.x0*s)), max(0, math.floor(rect.y0*s)),
                     min(width, math.ceil(rect.x1*s)), min(height, math.ceil(rect.y1*s)))


def tail_mask(pix, start, dpi):
    """Detecta tinta no rodapé renderizado, incluindo imagens e texto sem título."""
    first = math.floor(start*dpi/72)
    samples = pix.samples_mv
    white = b'\xff' * pix.stride
    for row in range(pix.height-1, first-1, -1):
        if samples[row*pix.stride:(row+1)*pix.stride] != white:
            return pdf.Rect(0, start, pix.width*72/dpi, min(pix.height*72/dpi, (row+3)*72/dpi))
    return None


def verify_output(path, expected_pix, masks, dpi, cor_rgb=(0,0,0), aviso_sobre_tarja=False, area_aviso=None):
    """Verifica estrutura e bytes RGB reextraídos, não apenas texto vazio."""
    with pdf.open(path) as d:
        if len(d) != 1 or d.embfile_count() or d.get_xml_metadata() or d.get_toc():
            raise Recusado('Falha na verificação da estrutura de saída.')
        if any(d.metadata.get(k) for k in ('title','author','subject','keywords','creator','producer','creationDate','modDate')):
            raise Recusado('Metadados inesperados na saída.')
        p = d[0]
        if p.get_text().strip() or list(p.annots() or []) or list(p.widgets() or []) or p.get_links() or p.get_fonts():
            raise Recusado('Conteúdo não raster inesperado na saída.')
        images = p.get_images(full=True)
        if len(images) != 1 or images[0][1] != 0:
            raise Recusado('Imagem adicional ou transparência inesperada.')
        pix = pdf.Pixmap(d, images[0][0])
        if (pix.width, pix.height, pix.n) != (expected_pix.width, expected_pix.height, 3):
            raise Recusado('Geometria raster inesperada.')
        if hashlib.sha256(pix.samples).digest() != hashlib.sha256(expected_pix.samples).digest():
            raise Recusado('Pixels do PDF diferem dos pixels já tarjados.')
        samples = pix.samples_mv
        for name, rect in masks:
            box = pixel_box(rect, dpi, pix.width, pix.height)
            for y in range(box.y0, box.y1):
                row_start=y*pix.stride
                excluded = pixel_box(area_aviso or AREA_AVISO,dpi,pix.width,pix.height) if aviso_sobre_tarja and name == 'observacoes_finais' else None
                segments = [(box.x0,box.x1)]
                if excluded and excluded.y0 <= y < excluded.y1:
                    segments = [(box.x0,min(box.x1,excluded.x0)),(max(box.x0,excluded.x1),box.x1)]
                for left,right in segments:
                    if left < right and samples[row_start+left*3:row_start+right*3] != bytes(cor_rgb)*(right-left):
                        raise Recusado('Tarja não opaca na imagem extraída.')


AREA_AVISO = pdf.Rect(30, 770, 565, 818)


def validar_destinatario(valor):
    if not isinstance(valor,str) or any(unicodedata.category(c).startswith('C') or c in '\n\r\t' for c in valor):
        raise Recusado('Informe um destinatário em uma única linha, sem caracteres de controle.')
    valor = ' '.join(unicodedata.normalize('NFKC',valor).split())
    if not valor or len(valor)>120:
        raise Recusado('Informe o destinatário com 1 a 120 caracteres.')
    fonte = pdf.Font('helv')
    if any(not fonte.has_glyph(ord(c)) for c in valor):
        raise Recusado('O destinatário contém caracteres não suportados pela fonte. Use letras, números e pontuação comum.')
    return valor


def texto_aviso(destinatario, instante):
    return (f'Dados sigilosos ocultados intencionalmente. Documento gerado em {instante:%d/%m/%y %H:%M}.\n'
            f'Uso exclusivo de {destinatario}, gentileza não compartilhar com terceiros.')


def verificar_area_aviso(pix, masks, dpi):
    if any(AREA_AVISO.intersects(r) for _,r in masks):
        raise Recusado('Sem área branca livre para o aviso: região ocupada por tarja.')
    box = pixel_box(AREA_AVISO,dpi,pix.width,pix.height)
    white = b'\xff' * ((box.x1-box.x0)*3)
    pixels = pix.samples_mv
    for y in range(box.y0,box.y1):
        if pixels[y*pix.stride+box.x0*3:y*pix.stride+box.x1*3] != white:
            raise Recusado('Sem área branca livre no rodapé para o aviso. Nenhum PDF foi gerado.')


def inserir_aviso(pix, tamanho, destinatario, dpi, instante, fundo=None, area=None):
    # Superfície nova: contém somente o texto intencional do aviso.
    area = area or AREA_AVISO
    with pdf.open() as aviso:
        page = aviso.new_page(width=tamanho.width,height=tamanho.height)
        font = pdf.Font('helv')
        if fundo is not None:
            page.draw_rect(page.rect, color=None, fill=tuple(c/255 for c in fundo))
        page.insert_font(fontname='Aviso',fontbuffer=font.buffer)
        caixa = area + (3,3,-3,-3)
        restante = page.insert_textbox(caixa,texto_aviso(destinatario,instante),
                                      fontname='Aviso',fontsize=7,color=((0.75,0.75,0.75) if fundo is not None and fundo != (255,255,255) else (0.47,0.47,0.47)),lineheight=1.3)
        if restante < 0:
            raise Recusado('O aviso não cabe na área reservada. Abrevie o destinatário.')
        marca = page.get_pixmap(dpi=dpi,colorspace=pdf.csRGB,alpha=False,clip=area)
        pix.copy(marca,marca.irect)


def redact(source, destination, kind='auto', dpi=300, campos=None, destinatario=None, gerado_em=None, cor='preto'):
    if not isinstance(cor,str) or cor not in CORES:
        raise Recusado('Cor de tarja inválida. Escolha uma das quatro opções disponíveis.')
    rgb = CORES[cor][1]
    source, destination = Path(source), Path(destination)
    if source.suffix.lower() != '.pdf' or not source.is_file():
        raise Recusado('Entrada permitida apenas para arquivos PDF existentes. ZIP, documentos e imagens não são aceitos.')
    if dpi not in (200, 300, 400):
        raise Recusado('DPI permitido: 200, 300 ou 400.')
    if source.resolve() == destination.resolve() or destination.exists():
        raise Recusado('Saída já existe ou coincide com o original; use outro destino.')
    if destinatario is not None:
        destinatario = validar_destinatario(destinatario)
    original = source.read_bytes()
    with pdf.open(stream=original, filetype='pdf') as doc:
        detected, masks, tail = plan(doc, kind)
        paginas_descartadas = len(doc)-1
        escolhidos = selecionar_campos(detected, campos)
        if not escolhidos:
            raise SemTarjas('Nenhum campo selecionado; arquivo ignorado, sem gerar PDF.')
        if len(doc)>1 and detected == 'pedido' and 'observacoes_finais' not in escolhidos:
            raise Recusado('Pedido com várias páginas: selecione Observações finais para descartar as páginas seguintes.')
        pix = doc[0].get_pixmap(dpi=dpi, colorspace=pdf.csRGB, alpha=False, annots=False)
        if tail is not None:
            r = tail_mask(pix, tail, dpi)
            if len(doc)>1 and 'observacoes_finais' in escolhidos:
                r = pdf.Rect(0,tail,doc[0].rect.x1,doc[0].rect.y1)
            if r:
                if len(doc)>1 or r.intersects(AREA_AVISO):
                    r.y1 = doc[0].rect.y1
                masks.append(('observacoes_finais', r))
        presentes = {name for name, _ in masks}
        ausentes = [name for name in escolhidos if name not in presentes]
        masks = [(name, r) for name, r in masks if name in escolhidos]
        if not masks:
            raise SemTarjas('Observações finais não encontradas; nenhuma tarja aplicável, sem gerar PDF.')
        area_aviso = pdf.Rect(AREA_AVISO)
        obs = next((r for name,r in masks if name == 'observacoes_finais'), None)
        if obs and obs.intersects(area_aviso) and not obs.contains(area_aviso):
            top = max(area_aviso.y0, obs.y0 + 1)
            area_aviso = pdf.Rect(area_aviso.x0, top, area_aviso.x1, top + AREA_AVISO.height)
        aviso_sobre_tarja = destinatario is not None and obs is not None and obs.contains(area_aviso)
        if destinatario is not None and not doc[0].rect.contains(area_aviso):
            raise Recusado('Sem área suficiente para o aviso. Nenhum PDF foi gerado.')
        if destinatario is not None and not aviso_sobre_tarja:
            verificar_area_aviso(pix,masks,dpi)
        for _, r in masks:
            pix.set_rect(pixel_box(r, dpi, pix.width, pix.height), rgb)
        # Comprove a remoção antes de compor qualquer texto sobre a tarja.
        for _, r in masks:
            box = pixel_box(r,dpi,pix.width,pix.height)
            for y in range(box.y0,box.y1):
                if pix.samples_mv[y*pix.stride+box.x0*3:y*pix.stride+box.x1*3] != bytes(rgb)*(box.x1-box.x0):
                    raise Recusado('Falha na remoção dos pixels protegidos.')
        if destinatario is not None:
            inserir_aviso(pix,doc[0].rect,destinatario,dpi,gerado_em if gerado_em is not None else datetime.now().astimezone(),fundo=rgb if aviso_sobre_tarja else None,area=area_aviso)
        with pdf.open() as out:
            page = out.new_page(width=doc[0].rect.width, height=doc[0].rect.height)
            page.insert_image(page.rect, pixmap=pix)
            out.set_metadata({})
            out.xref_set_key(out.pdf_catalog(), 'Info', 'null')
            result = out.tobytes(garbage=4, deflate=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Temporário contém somente dados já tarjados. Publicação sem sobrescrita.
    fd, tmp = tempfile.mkstemp(prefix='.tarja-', suffix='.pdf', dir=destination.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(result)
        verify_output(tmp, pix, masks, dpi, rgb, aviso_sobre_tarja, area_aviso)
        if source.read_bytes() != original:
            raise Recusado('O arquivo de entrada mudou durante o processamento.')
        os.link(tmp, destination)  # falha atomicamente se destino existir
    finally:
        os.unlink(tmp)
    return {'tipo': detected, 'regioes': [name for name, _ in masks],
            'selecionados': escolhidos, 'ausentes': ausentes,
            'mantidos': [c for c in CAMPOS[detected] if c not in escolhidos],
            'paginas_descartadas': paginas_descartadas, 'dpi': dpi, 'sha256_saida': hashlib.sha256(result).hexdigest()}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Remove campos dos modelos pedido/NFS-e enviados, com tarjas em pixels. Saída sem texto selecionável; originais preservados.')
    parser.add_argument('arquivos', nargs='*', type=Path, help='PDFs individuais (alternativa a --pasta)')
    parser.add_argument('--pasta', type=Path, help='Processar todos os PDFs diretamente nesta pasta')
    parser.add_argument('--saida', type=Path, help='Pasta de saída; por padrão usa a pasta de entrada. Nunca sobrescreve')
    parser.add_argument('--destinatario', required=True, help='Nome que aparecerá no aviso de uso exclusivo (até 120 caracteres)')
    parser.add_argument('--cor', choices=list(CORES), default='preto', help='Cor sólida das tarjas')
    parser.add_argument('--tipo', choices=['auto','pedido','nota'], default='auto')
    parser.add_argument('--dpi', type=int, choices=[200,300,400], default=300)
    args = parser.parse_args(argv)
    if bool(args.pasta) == bool(args.arquivos):
        parser.error('Informe --pasta OU uma lista de arquivos.')
    from lote import descobrir, processar_lote, Recusado as ErroLote
    try:
        files, output = descobrir(args.pasta,args.saida) if args.pasta else (args.arquivos,args.saida)
    except (ErroLote, OSError) as e:
        print(str(e) if isinstance(e,ErroLote) else 'Não foi possível acessar a pasta.', file=sys.stderr)
        return 1
    errors = 0
    for i, result in enumerate(processar_lote(files,output,args.tipo,args.dpi,destinatario=args.destinatario,cor=args.cor),1):
        if result.status == 'concluido':
            print(f'[{i}/{len(files)}] OK ({result.tipo}): {Path(result.destino).name}')
        else:
            errors += 1
            print(f'[{i}/{len(files)}] {Path(result.origem).name}: {result.status.upper()} - {result.mensagem}',file=sys.stderr)
    print(f'{len(files)-errors} concluído(s); {errors} não concluído(s).')
    return 1 if errors else 0



if __name__ == '__main__':
    sys.exit(main())
