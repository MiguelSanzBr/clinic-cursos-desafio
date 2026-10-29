# Registro breve

Miguel Sanz Boragan. Case recebido em 28/10 às 11:58. Relógio: início 11:58, fim PREENCHER.

## Tempo por atividade

| Atividade | Quando | Meu tempo | Agentes de IA | O que foi verificado |
|---|---|---|---|---|
| Leitura do PDF | 11:58 a 12:04 | 6 min | | Markdown conferido contra o PDF |
| Planejamento e decisões | 12:04 a 12:29 | 25 min | 5 em paralelo | Fatos sem fonte direta marcados "a confirmar" |
| Produção: demo, documento, revisão, fontes, visual | 12:29 a 13:40 | sem mim | 7 agentes | Testes numa cópia limpa; fontes oficiais abertas; PDF com 5 páginas |
| Avaliadores simulados e rodadas de correção | 13:43 a PREENCHER | PREENCHER | 76 agentes avaliadores em 12 bancas | Contas estatísticas conferidas com scipy |
| Minha revisão do doc e do código | PREENCHER | PREENCHER | | PREENCHER |
| QA final e envio | PREENCHER | PREENCHER | | PREENCHER |
| **Total** | | **PREENCHER** | | |

## Uso de IA

Claude Code com o modelo Claude Opus 5.5 (Anthropic). Um agente principal orquestrou subagentes de pesquisa, código (com teste antes), texto e revisão. A IA escreveu a primeira versão do código, dos testes, do documento, do README e deste registro. Depois, por pedido meu, agentes fizeram o papel de avaliadores com óticas diferentes; usei as críticas para decidir o que corrigir.

**Decidido por mim:** a divisão do trabalho (a IA produz, eu reviso e defendo); Python + FastAPI + SQLite + pytest; Markdown → PDF; repositório privado + zip; citar minha experiência só de passagem; quais sugestões dos avaliadores entrar (receita sem origem em R$, verba segue a vaga, paciente modelo à parte, conversões de volta às plataformas); nos conflitos, Chatwoot recebe o webhook da Meta e o núcleo lê pela API como segunda via, e campanha sem data. PREENCHER: decisões que eu mudar na revisão.

**O que eu fiz com as mãos:**
- PREENCHER: o que mudei no texto ou no código (antes → depois e por quê).
- PREENCHER: uma mutação que eu mesmo fiz, qual teste caiu e o comando.
- PREENCHER: as fontes que eu mesmo abri.
- PREENCHER: erros da IA que eu achei.
- PREENCHER: o que eu não revisei.

## Erros da IA encontrados no processo

1. **Contradições entre texto e código**, achadas pelas revisões: todo lead entra no CRM × CRM só com checklist; prontuário "não copiado" × texto do WhatsApp gravado; regra de volume baixo mais fraca que a principal (85%, não 90%); ponto de entrada liberado com 1 lead; venda aceita em oportunidade expirada.
2. **Bugs da demo**, corrigidos com teste: venda em quarentena nunca reprocessada; LP sem UTM aparecendo liberada; lead perdido com 60 formulários ao mesmo tempo; erro 500 com dado malformado; telefone estrangeiro virando brasileiro; aluna tratada como lead; encaminhamento enviado duas vezes; `www.` no endereço desligava a falha escolhida; formulário com produto e sem unidade abria uma segunda oportunidade; protocolo do `/q/` repassado a outra pessoa virava origem; lead de teste ia para a fila da vendedora e, depois da correção, prendia o lead real do mesmo telefone; mensagem de quem usa nome de usuário no WhatsApp (sem telefone) ia para a quarentena; lead de teste gravava o aceite e o e-mail da QA na pessoa real e expirava a oportunidade dela; etiqueta exigia telefone mesmo com o id da oportunidade; formulário de aluna sem produto ia ao atendimento de aluna, não a uma oportunidade nova; lead de teste travava a etiqueta da vendedora. Também havia texto do documento que não batia com o código (alertas da demo, "30 leads seguidos", reenvio do webhook), corrigido.
3. **Fatos de fornecedor errados no primeiro texto**, conferidos na fonte: callback por WABA ou número existe; cobrança de mensagens de serviço desde 01/10/2026 confirmada; plano de US$ 19 do Chatwoot é "Premium Support"; Evolution API também integra a Cloud API; `sck` da Hotmart aceita só 30 caracteres, sem `_`.
4. **Afirmações erradas**: "recriar campanha reinicia o aprendizado"; `bit.ly` como referrer; "R$ 15 mil no escuro" (o que fica sem origem é o retorno, não a verba); anúncio de Status "sem referral" (é sem `ctwa_clid`).
5. **IA respondendo preço sozinha** vira oferta pelo CDC (art. 30): passou a começar como copiloto.
6. PREENCHER: correções que eu fizer na minha revisão.

## Fontes

Lista com URL, data e o que foi conferido em cada uma: [FONTES.md](FONTES.md).

## Verificações feitas

- `uv run pytest -q`: 174 testes verdes, também numa cópia limpa (`uv sync` do zero); o pytest não cria arquivo de banco.
- Mutações que derrubam testes: tirar a trava de escrita e leitura; trocar o primeiro toque pelo último; tirar ou trocar o `ON CONFLICT` do recibo.
- `uv run python scripts/demo.py`: saída idêntica a `saida-esperada.txt` em duas rodadas.
- Tabela de liberação conferida por teste contra a binomial.
- PDF com 5 páginas A4; nenhum dado real, credencial ou `.env` no repositório.
- PREENCHER: o que eu conferi pessoalmente.

## Pendências

- **Na demo:** assinatura do webhook da Meta e handshake GET; regra de origem inferida (o schema aceita, nenhuma regra ativa); exclusão LGPD; autenticação nas rotas de consulta; telefone de formulário só do Brasil.
- **Só desenho:** cookie e campos ocultos; consentimento no banner e opt-in de WhatsApp; cancelamento de venda; feed de vendas do ERP; fusão reversível de pessoas; conciliação diária; envio real às APIs do Google e da Meta.
- **Fora do recorte:** inventário real e integração real com ERP, Chatwoot, Hotmart e RD Station Marketing.
