# Backlog

## Histórico e registros locais em SQLite

Proposta para uma etapa futura: manter um banco SQLite local com histórico de
arquivos processados e destinatários, data de instalação, eventos gerais e
erros, além de tentativas de atualização de versão com seus sucessos e falhas.

Antes de implementar, definir quais dados serão registrados, por quanto tempo
serão mantidos, como o usuário poderá consultar e excluir o histórico, e quais
medidas de privacidade, proteção e consentimento serão necessárias. Evitar o
registro do conteúdo dos documentos e de dados que não sejam necessários.

## Senhas de PDF

### 1. Aplicativo: abrir PDF com senha

Permitir que a pessoa informe a senha para abrir e processar um PDF protegido.
Nesta etapa, a cópia gerada continua sendo salva sem senha.

### 2. Aplicativo: proteger a cópia gerada

Oferecer a opção de definir uma senha para abrir o PDF gerado, independentemente
de o arquivo original ter senha. Quando o original exigir senha, permitir usar
a mesma ou outra escolhida pela pessoa; manter a opção de gerar sem senha.

### 3. Projeto web: suporte a senhas

Avaliar e implementar, na eventual versão web, a abertura de PDFs com senha e a
opção de proteger a cópia gerada, conforme a viabilidade das ferramentas web.

Em todas as etapas, não armazenar senhas nem incluí-las em histórico ou logs;
mantê-las somente pelo tempo necessário. Definir o tratamento de senha incorreta,
cancelamento e permissões, e testar a abertura e a proteção da cópia nos sistemas
e navegadores suportados. Respeitar as permissões aplicáveis ao documento.
