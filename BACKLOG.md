# Backlog

## Histórico e registros locais em SQLite

Proposta para uma etapa futura: manter um banco SQLite local com histórico de
arquivos processados e destinatários, data de instalação, eventos gerais e
erros, além de tentativas de atualização de versão com seus sucessos e falhas.

Antes de implementar, definir quais dados serão registrados, por quanto tempo
serão mantidos, como o usuário poderá consultar e excluir o histórico, e quais
medidas de privacidade, proteção e consentimento serão necessárias. Evitar o
registro do conteúdo dos documentos e de dados que não sejam necessários.

## PDFs protegidos por senha

Avaliar, em etapa futura, o suporte no modo manual do aplicativo e, conforme a
viabilidade das ferramentas disponíveis, em uma eventual versão web:

- Permitir que a pessoa informe a senha para abrir e autenticar um PDF protegido.
- Oferecer a geração da cópia sem senha por padrão ou, opcionalmente, protegida
  com a mesma senha ou com outra escolhida pela pessoa.
- Não armazenar senhas nem incluí-las no histórico ou nos registros; mantê-las
  somente pelo tempo necessário ao processamento.
- Definir previamente o tratamento de senha incorreta, cancelamento, recursos
  e permissões do documento, além de testes de abertura, geração e proteção da
  cópia nos sistemas e navegadores suportados.

A implementação deve respeitar as permissões aplicáveis ao documento e não
pressupor que todo arquivo protegido possa ser aberto ou alterado.
