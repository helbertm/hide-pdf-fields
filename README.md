# Ocultar Dados - Pedido Interno e NFe

Aplicativo local para ocultar campos de dois layouts de PDF: pedido interno e nota fiscal de serviço. Tem seleção de campos por documento, comparação antes/depois, aviso com destinatário e processamento em lote. Os PDFs permanecem no computador.

## Instalar no Windows

Suporte: Windows 10/11 x64, PowerShell 5.1 ou superior, internet na instalação.

Abra o **PowerShell** e cole o comando publicado na [release](https://github.com/helbertm/hide-pdf-fields/releases). Ele verifica os hashes do instalador e do pacote, prepara Python 3.14.10/Tcl-Tk e um ambiente isolado, instala as dependências fixadas e cria o atalho **Ocultar Dados** na Área de Trabalho. Não precisa instalar Git nem executar como administrador. Se necessário, o Python completo é obtido de python.org com versão e SHA-256 fixados, e sua assinatura Authenticode é verificada antes da instalação. Um Python 3.14 x64 compatível já instalado pode ser reutilizado. O ícone utilizado é o ícone nativo do Python.

A instalação usa `%LOCALAPPDATA%\HidePdfFields`, não altera o PATH e não muda permanentemente a política de execução. Se a organização bloquear scripts ou instalações, o instalador respeita esse bloqueio.

A versão anterior é preservada em atualizações. O atalho só muda após a verificação da nova versão. Reexecutar o instalador cria outra instalação isolada e atualiza somente o atalho do aplicativo. Os PDFs não são removidos nem modificados durante a instalação.

Para desinstalar, feche o aplicativo, remova o atalho **Ocultar Dados** e a pasta `%LOCALAPPDATA%\HidePdfFields`. Python e PDFs salvos fora dessa pasta permanecem intactos.

## Usar

1. Abra o atalho **Ocultar Dados**.
2. Selecione a pasta de entrada. A saída usa a mesma pasta por padrão e pode ser alterada.
3. Informe o destinatário e clique **Carregar PDFs**.
4. Selecione cada arquivo e desmarque os campos que deseja manter visíveis.
5. Escolha a cor das tarjas (preto por padrão), clique **Processar** e confira **Original / Resultado tarjado**, com ampliação quando necessário.

Todos os campos começam marcados. ZIP, documentos de texto e imagens não são aceitos. Arquivos existentes não são sobrescritos. Veja [uso, limites e campos](USO.md).

## Desenvolvimento e verificações

Python 3.14 x64 é o runtime de distribuição Windows. Em um ambiente virtual:

```powershell
python -m pip install --require-hashes --only-binary=:all: -r requirements-win.lock
python scripts/verify.py
$env:TARJA_GUI_TESTS = '1'
python -m unittest test_interface -v
python scripts/build_release.py
```

Para desenvolvimento em outros sistemas, `requirements.txt` declara a dependência direta. A interface requer Tcl/Tk. O lock Windows não deve ser usado em outra plataforma.

O workflow Windows chama os comandos do repositório, verifica extração de ZIP, instala o pacote em caminho com espaços/acentos, provisiona Python pelo instalador oficial, testa uma segunda instalação e valida o atalho. O instalador aceita `-ArchivePath` e `-PythonExecutable` para esse teste local; os arquivos continuam sujeitos à mesma verificação de hash.

## Distribuição e confiança

As releases usam ZIP com lista explícita de arquivos e SHA-256. O comando fixa o instalador a um commit e inclui os hashes esperados. Hashes detectam alterações, mas não constituem assinatura independente do publicador. Não executamos texto recebido por `Invoke-Expression`.

Proteção da branch, checks obrigatórios, permissões de release e imutabilidade de releases são configurações do GitHub, externas ao código. Não são garantidas apenas pela presença dos workflows.

[Repositório](https://github.com/helbertm/hide-pdf-fields) · [Suporte](https://github.com/helbertm/hide-pdf-fields/issues) · [Dependências e licenças](THIRD_PARTY.md)
