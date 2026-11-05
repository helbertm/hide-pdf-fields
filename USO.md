# Uso e limites

## Entrada e saída

O programa aceita somente PDFs com texto nativo nos dois layouts reconhecidos em A4. A nota fiscal deve ter uma página. Um pedido com várias páginas é aceito quando a primeira contém o fechamento reconhecido e a opção de ocultar observações está marcada: a saída mantém apenas a primeira página e descarta todas as seguintes. A prévia identifica a primeira página e o resultado informa a quantidade descartada. PDFs digitalizados, imagens renomeadas, recortes, rotação, senha ou posições de campos incompatíveis são recusados. Cada arquivo é independente: uma recusa não impede os demais.

A lista inclui arquivos `.pdf`/`.PDF` diretamente na pasta, sem subpastas. É lida uma vez por lote. A pasta de saída acompanha a entrada até ser escolhida uma pasta diferente. Nenhum arquivo existente é sobrescrito.

Nome de saída: `Destinatario-ddmmyy-nome_original.pdf`. Destinatário e nome original recebem normalização: espaços viram `_`, acentos são removidos e caracteres especiais são excluídos. Exemplo: `João da Silva` e `Nota 123.pdf` tornam-se `Joao_da_Silva-051126-Nota_123.pdf` em 05/11/2026. A extensão final é `.pdf`.

Se recarregar a mesma pasta, os resultados anteriores também serão listados e recusados por não corresponderem à entrada textual suportada. Não há exclusão automática por semelhança de nome.

## Campos

Todos são marcados por padrão. Desmarcar mantém o campo visível apenas naquele documento.

- Pedido: gestora, consultor; razão social, nome fantasia, CNPJ e inscrição estadual de matriz e filial; bloco completo do endereço fiscal/entrega/cobrança; observações finais, quando houver.
- Nota: autenticidade, QR code, bloco do tomador e chave de acesso nacional.

Endereço e tomador são grupos completos, incluindo seus rótulos internos. Descrições, códigos e referências identificadoras em outras regiões podem permanecer visíveis. Não se trata de anonimização integral.

Sem nenhum campo selecionado, o arquivo é ignorado sem produzir PDF. Se apenas observações estiverem selecionadas e não forem encontradas, também não há saída. Escolhas ficam congeladas durante o lote. Recarregar restaura todos marcados.

## Aviso com destinatário

O destinatário é obrigatório, até 120 caracteres, em uma linha. Acentos portugueses são suportados. Nome e data/hora ficam congelados no início do lote, segundo o relógio local do computador.

O aviso usa fonte de 7 pontos, normalmente em cinza na área branca inferior. Se necessário, aparece em cinza claro sobre a tarja da observação:

> Dados sigilosos ocultados intencionalmente. Documento gerado em dd/mm/yy hh:mm.
> Uso exclusivo de {destinatário}, gentileza não compartilhar com terceiros.

O destinatário mantém acentos no documento. Se a área estiver ocupada, a geração é recusada. O texto expressa o uso pretendido; não impede tecnicamente cópia ou compartilhamento.

## Remoção e conferência

As tarjas substituem pixels pela cor sólida escolhida: Preto (padrão), Vermelho escuro, Cinza escuro ou Branco. Branco também remove os dados efetivamente, sem manter conteúdo por baixo. A cor é comum ao lote e fica congelada durante o processamento. Um PDF novo recebe somente a imagem já tarjada e o aviso; objetos do original, anexos, metadados e texto oculto não são copiados. A imagem incorporada é reextraída e comparada byte a byte; a tarja é verificada na cor escolhida antes de inserir o aviso; no resultado final, a única exceção é a área do aviso quando ele estiver sobre a observação. O original é preservado.

A saída perde texto selecionável/pesquisável e não conserva assinaturas digitais do original. OCR posterior pode ler o que ficou visível, mas não recupera os pixels substituídos.

Confira cada saída ampliada antes de compartilhar. Âncoras com tolerância de 0,25 ponto limitam os layouts aceitos, mas não provam que um valor longo não extrapolou sua célula. Mudanças no modelo exigem ajuste do perfil. O pedido pressupõe observações após o fechamento identificado e uma margem de 4 pontos. Quando a observação selecionada ocupa a área do aviso, ela é removida até o fim da primeira página e o aviso é colocado sobre essa tarja. Se o pedido tiver páginas extras e as observações estiverem desmarcadas, o arquivo é recusado para não descartar conteúdo que se pediu para manter.

Previews ficam em memória. O resultado exibido vem do arquivo salvo e tem seu hash conferido. Parar/fechar durante um lote permite terminar o arquivo atual e cancela os seguintes.

## Terminal

```powershell
python tarjar.py --pasta "entrada" --destinatario "Equipe Financeira"
python tarjar.py "pedido.pdf" "nota.pdf" --saida "saida" --destinatario "Equipe Financeira"
```

O argumento `--saida` é opcional. A seleção individual de campos está na interface. Chamadas diretas à API com `destinatario=None` omitem o aviso por compatibilidade; interface e CLI sempre exigem destinatário.

Use **Processar** para iniciar e **Interromper** para parar após o arquivo atual. Ao concluir todos os arquivos, uma faixa verde informa o sucesso sem modal. Lotes com recusas, falhas ou interrupção mostram um resumo de atenção com contagens. O motivo do arquivo selecionado em **Recusado** aparece em vermelho.
