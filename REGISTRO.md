# Registro breve

Candidato: Miguel Sanz Boragan. Case recebido em 2026-10-28 às 11:58.

## Tempo por atividade

Duas colunas de tempo: o meu (relógio de quem está trabalhando) e o dos agentes de IA, que rodaram em paralelo e não somam ao meu.

| Atividade | Quando | Meu tempo | Agentes | Quem / ferramenta | O que foi verificado e como |
|---|---|---|---|---|---|
| Leitura do PDF e conversão para Markdown | 28/10 11:58–12:04 | 6 min | | Eu + Claude | Markdown conferido contra o PDF |
| Planejamento e pesquisa | 28/10 12:04–12:29 | 25 min | 5 em paralelo, ~6 min | Eu decidi recorte, stack, prazo, formato e divisão do trabalho; Claude com 2 agentes de pesquisa web e 3 de desenho | Fatos sem fonte oficial direta marcados "a confirmar"; convenções divergentes entre agentes unificadas |
| Demo com TDD e documento | 28/10 12:29–12:54 | 0 (aguardando) | 2 em paralelo, 16 e 22 min | Agente de código (TDD) e agente de texto | 38 testes verdes; demo determinística; mutação da idempotência derrubou 3 testes; PDF com 5 páginas |
| Revisão independente | 28/10 12:54–13:04 | 0 (aguardando) | 1, ~9 min | Agente revisor que não viu o plano, só enunciado, doc e código | 20 achados; os 3 mais graves eram bugs de verdade (ver "Erros da IA") |
| Correções da revisão e verificação final | 28/10 13:05–13:14 | 0 (aguardando) | 2 em paralelo, 5 e 8 min | Agentes de código e texto retomados; 3 fatos de fornecedor conferidos na fonte antes de mandar corrigir | 51 testes verdes numa cópia limpa (só os arquivos do repositório); mutação da idempotência derrubou 4; PDF com 5 páginas |
| Verificação de fontes e do servidor real | 28/10 13:15–13:31 | 0 (aguardando) | 1 agente, ~11 min | Agente verificador abriu cada fonte oficial; eu li o código do Chatwoot e subi o servidor com `fastapi dev` | Nenhum fato errado; 2 pendências resolvidas pela doc e pelo código; 5 imprecisões corrigidas; rotas reais respondendo (200, 422, 404, duplicado); saída do README idêntica à real |
| Visual do PDF | 28/10 13:33–13:40 | 0 (aguardando) | | Claude seguindo a skill web-design-guidelines (Vercel): tipografia IBM Plex, uma cor de destaque, tabelas sem grade, aspas curvas e espaço não separável no build | PDF segue com 5 páginas; páginas renderizadas e conferidas; contraste do texto ≥ 6:1; 0 aspas retas no PDF |
| Minha revisão do doc e do código | PREENCHER | PREENCHER | | Eu | PREENCHER: leitura de cada seção, fontes ⚠ abertas, testes rodados, mutação feita por mim |
| QA final e envio | PREENCHER | PREENCHER | | Eu | PREENCHER |
| **Total** | | **PREENCHER** | | | |

## Uso de IA

Ferramenta: Claude Code com o modelo Claude Opus 5.5 (Anthropic). Um agente principal orquestrou subagentes: 2 de pesquisa web, 3 de desenho (documento, demo, visão do avaliador), 1 que escreveu o código com testes antes, 1 que escreveu o documento e 1 revisor independente.

- **Gerado pela IA:** primeira versão do código, dos testes, do documento, do README e deste registro.
- **Decidido por mim:** que a IA faria a maior parte e eu revisaria; Python + FastAPI + SQLite + pytest; prazo; formato Markdown → PDF; entrega em repositório privado + zip; citar minha experiência só de passagem. PREENCHER: decisões de conteúdo que eu mudar na revisão.
- **Adaptado e verificado:** ver tabela acima e "Verificações".

### Erros da IA encontrados no processo

1. Dois agentes de desenho propuseram convenções diferentes para o ponto de entrada (`CPS-QR-BANNER01` × `qr-cps-recepcao-01`). Unificado em `{tipo}-{unidade}-{local}-{nn}`, minúsculo.
2. O documento ia dizer que dado pessoal vazado na URL "nunca é gravado". O agente de código apontou que o payload bruto guarda a URL inteira. O texto passou a descrever o log bruto com acesso restrito e retenção curta.
3. O timestamp de exemplo do WhatsApp caía em 2025, não em 2026. Corrigido nos dados.
4. A revisão independente achou 3 bugs: venda em quarentena nunca era reprocessada; uma LP paga que perdia UTM em 100% dos leads aparecia liberada quando o "como conheceu" estava preenchido; um toque com evidência de anúncio era colado na oportunidade aberta de outro produto. Corrigidos com testes novos.
5. Fatos de fornecedor errados ou desatualizados no primeiro texto, conferidos na fonte: a Meta permite callback alternativo por WABA ou número (não "1 webhook por app"); a cobrança de mensagens de serviço desde 2026-10-01 já está confirmada; o plano de US$ 19 do Chatwoot se chama "Premium Support"; a Evolution API também integra a Cloud API oficial.
6. A convenção mandava a campanha para a Hotmart sem notar que `sck` aceita só 30 caracteres e não aceita `_` (o exemplo de `utm_campaign` tem 35). O documento passou a mandar o `ep` no `sck`.
7. O texto dizia que o webhook do RD Station Marketing trazia "só `funnel.origin` e `cf_*`"; o certo é que, de origem, traz só isso (o payload tem também nome, e-mail e telefone).
8. PREENCHER: correções que eu fizer na minha revisão.

## Fontes consultadas (2026-10-28)

| Fonte | Para quê |
|---|---|
| github.com/chatwoot/chatwoot (LICENSE, enterprise/LICENSE, releases) | Licença MIT do núcleo, pasta enterprise paga, v4.19.1 de 2026-10-24 |
| chatwoot.com/pricing/self-hosted-plans/ | Community US$ 0, Premium Support US$ 19, Enterprise US$ 99 (conferido por mim via leitura da página) |
| developers.chatwoot.com/self-hosted | Requisitos de hospedagem |
| chatwoot.com/hc/user-guide/articles/1756799850-how-to-setup-a-whats_app-channel-manual-flow | Canal WhatsApp Cloud nativo |
| github.com/twentyhq/twenty; twenty.com/pricing; docs.twenty.com/developers/extend/api | Licença AGPL-3.0 + arquivos Enterprise, v2.52.0, API e preço |
| developers.facebook.com/docs/whatsapp/pricing/ e /updates-to-pricing/ | Cobrança por mensagem; serviço cobrado desde 2026-10-01, 1.000 grátis/mês/número |
| developers.facebook.com/docs/whatsapp/embedded-signup/webhooks/override | Callback alternativo por WABA ou número |
| developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/text/ | Objeto `referral` do anúncio Click-to-WhatsApp |
| developers.facebook.com/docs/marketing-api/conversions-api/deduplicate-pixel-and-server-events | Deduplicação Pixel × CAPI |
| support.google.com/google-ads/answer/15081888 | Prazo de importação de conversão offline |
| support.google.com/analytics/answer/6366371 | GA4 proíbe dado pessoal em URL e UTM |
| help.hotmart.com/pt-br/article/216441797/ | `sck` e `src` para origem da venda |
| developers.hotmart.com/docs/pt-BR/2.0.0/webhook/purchase-webhook/ e /docs/pt-BR/changelog | Campo `data.purchase.origin` do webhook; limite do `sck` |
| docs.twenty.com/developers/extend/webhooks | Webhooks do Twenty |
| github.com/chatwoot/chatwoot (código, tag v4.19.1) | `referral` em `content_attributes`, enviado no webhook `message_created` (desde v4.15.0, PR #14681) |
| developers.rdstation.com/reference/webhooks-payload-mkt.md | Payload fixo do webhook do RD Station Marketing |
| Krayin, EspoCRM, Evolution API, n8n (repositórios e páginas de licença) | Motivo do descarte |

Chatwoot e `referral`: conferido no código-fonte (branch develop, 2026-10-28). `app/services/whatsapp/incoming_message_base_service.rb` grava o `referral` da mensagem em `content_attributes[:referral]`, e `Message#webhook_data` envia `content_attributes` no webhook. Falta testar com um anúncio real.

Hotmart: `sck`, `src` e `xcod` chegam em `data.purchase.origin` (referência do Webhook 2.0 e changelog de 2024-04-25); UTM não chega ao webhook; `sck` aceita até 30 caracteres, sem `_`. Falta ver um evento real preenchido.

Ainda a confirmar: se a API de eventos de contato do RD Station Marketing traz UTM (o schema documentado não mostra).

## Verificações feitas

- `uv run pytest -v`: 51 testes, todos verdes, também numa cópia limpa só com os arquivos do repositório (`uv sync` do zero).
- `uv run python scripts/demo.py`: saída idêntica à do README em duas rodadas.
- Mutação: sem o `ON CONFLICT` do recibo, 4 testes falham (entre eles `test_c4_evento_duplicado_sem_efeito`); restaurado, voltam a passar.
- `bash scripts/build_pdf.sh`: PDF com 5 páginas A4 (`pdfinfo`), páginas renderizadas e conferidas, diagrama sem quebra (`pdftotext -layout`).
- Busca por dado real, credencial e `.env` no repositório: nada encontrado. Todos os dados são fictícios (domínio clinic.exemplo).
- PREENCHER: o que eu conferi pessoalmente.

## Pendências

- Na demo: assinatura do webhook da Meta (`X-Hub-Signature-256`) e handshake GET; lote com mais de uma mensagem; sincronização atendimento → CRM; regra de origem inferida (o schema aceita, nenhuma regra ativa); exclusão LGPD; autenticação nas rotas de consulta; amostra mínima e período no cálculo de liberação.
- Só desenho, sem código: redirecionador `/q/`, cookie e campos ocultos, fusão reversível de pessoas, flag `channel_validated`, conciliação diária.
- Fora do recorte: inventário real, integração real com ERP, Chatwoot, Hotmart e RD Station Marketing.
