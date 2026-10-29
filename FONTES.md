# Fontes consultadas (2026-10-28)

Referência do REGISTRO.md e das chaves citadas no DOCUMENTO.md.


As chaves entre colchetes são as citadas no DOCUMENTO.md. Salvo indicação, a leitura de cada página foi feita pela IA nesta data.

| Fonte | Para quê |
|---|---|
| [GA2] support.google.com/analytics/answer/9756891 | Agrupamento de canais padrão do GA4: tráfego que não casa com nenhuma regra vira "Unassigned"; agrupamento personalizado é a alternativa editável |
| [M2] developers.facebook.com/documentation/ads-commerce/conversions-api/parameters | A Conversions API aceita eventos de mensagens ("business messaging") e tem o parâmetro `ctwa_clid` (sem hash); o `action_source` é `business_messaging`, listado em [M1] (conferido em 28/10) |
| [M1] developers.facebook.com/docs/marketing-api/conversions-api/parameters/server-event | `event_time` da CAPI até 7 dias antes do envio, sem exceção por `action_source` (conferido de novo em 28/10): a venda vai à Meta em até 7 dias depois de confirmada; a idade do clique é outra regra |
| webkit.org/blog/8613/ (ITP 2.1) e webkit.org/blog/9521/ (ITP 2.2) | Safari: cookie criado por script limitado a 7 dias; 24 h quando a pessoa chega por link com parâmetros vindo de domínio classificado como rastreador |
| support.google.com/google-ads/answer/6305348 e /9054021 | ValueTrack (`{campaignid}`, `{creative}`) e sufixo de URL final do Google Ads |
| facebook.com/business/help/1016122818401732 | Parâmetros de URL dos anúncios da Meta (`{{campaign.id}}`, `{{ad.id}}`). **Não conferido:** a leitura automática não carregou a página; conferir no navegador |
| support.google.com/analytics/answer/9976101 | Consent mode: com `ad_storage` negado, cookies de anúncio não são gravados nem lidos |
| developers.facebook.com/docs/marketing-api/conversions-api/using-the-api | `test_event_code` para testar eventos da CAPI sem treinar o algoritmo; tirar em produção |
| github.com/chatwoot/chatwoot (LICENSE, enterprise/LICENSE, releases) | Licença MIT do núcleo, pasta enterprise paga, v4.19.1 de 2026-10-24 |
| [C4] chatwoot.com/pricing/self-hosted-plans/ | Community US$ 0, Premium Support US$ 19, Enterprise US$ 99 |
| [C2] developers.chatwoot.com/self-hosted | Requisitos de hospedagem |
| [C3] chatwoot.com/hc/user-guide/articles/1756799850-how-to-setup-a-whats_app-channel-manual-flow | Canal WhatsApp Cloud nativo |
| [T2] [T3] github.com/twentyhq/twenty; twenty.com/pricing; docs.twenty.com/developers/extend/api | Licença AGPL-3.0 + arquivos Enterprise, v2.52.0, API e preço |
| [W2] [W4] developers.facebook.com/docs/whatsapp/pricing/ e /updates-to-pricing/ | Cobrança por mensagem; serviço cobrado desde 2026-10-01, 1.000 grátis/mês/número |
| developers.facebook.com/docs/whatsapp/embedded-signup/webhooks/override | Callback alternativo por WABA ou número |
| [W1] developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/text/ | Objeto `referral` do anúncio Click-to-WhatsApp |
| developers.facebook.com/documentation/business-messaging/whatsapp/business-scoped-user-ids | BSUID em `messages[].from_user_id` e `contacts[].user_id` desde abril de 2026; quem adota nome de usuário (a partir de 29/06/2026) pode chegar sem `from`/`wa_id` (conferido em 28/10) |
| developers.facebook.com/docs/marketing-api/conversions-api/deduplicate-pixel-and-server-events | Deduplicação Pixel × CAPI |
| [G1] support.google.com/google-ads/answer/15081888 | Prazo de importação de conversão offline |
| [GA1] support.google.com/analytics/answer/6366371 | GA4 proíbe dado pessoal em URL e UTM |
| [H1] help.hotmart.com/pt-br/article/216441797/ | `sck` e `src` para origem da venda |
| developers.hotmart.com/docs/pt-BR/2.0.0/webhook/purchase-webhook/ e /docs/pt-BR/changelog | Campo `data.purchase.origin` do webhook; limite do `sck` |
| docs.twenty.com/developers/extend/webhooks | Webhooks do Twenty |
| [C5] github.com/chatwoot/chatwoot (código, tag v4.19.1) | `referral` em `content_attributes`, enviado no webhook `message_created` (desde v4.15.0, PR #14681) |
| developers.rdstation.com/reference/webhooks-payload-mkt.md | Payload fixo do webhook do RD Station Marketing |
| github.com/krayin/laravel-crm; krayincrm.com/extensions/krayin-crm-whatsapp-extension/ | Krayin descartado: MIT, mas WhatsApp só por extensão paga (US$ 1.499) sem dizer se usa a Cloud API oficial |
| github.com/espocrm/espocrm; docs.espocrm.com/administration/webhooks/ | EspoCRM descartado: AGPL-3.0; webhooks enviados em lote, por padrão a cada 5 min (ajustável), lento para atendimento |
| github.com/evolution-foundation/evolution-api | Evolution API descartada: integra Baileys (não oficial) e Cloud API; na Cloud API seria intermediário a mais; última estável v2.3.7 (2025-12), 2.4.0-rc em 2026-05 |
| github.com/n8n-io/n8n (LICENSE.md) | n8n como cola, não como produto: Sustainable Use License (uso interno), não é open source OSI |

Chatwoot e `referral`: conferido no código-fonte (branch develop, 2026-10-28). `app/services/whatsapp/incoming_message_base_service.rb` grava o `referral` da mensagem em `content_attributes[:referral]`, e `Message#webhook_data` envia `content_attributes` no webhook. Falta testar com um anúncio real.

Hotmart: `sck`, `src` e `xcod` chegam em `data.purchase.origin` (referência do Webhook 2.0 e changelog de 2024-04-25); UTM não chega ao webhook; `sck` aceita até 30 caracteres, sem `_`. Falta ver um evento real preenchido.

RD Station Marketing: o webhook traz `funnel.origin`, a origem do contato como `utm_medium` e `utm_source`, sem campanha (conferido em 28/10). Na transição, os formulários do RD ganham campos ocultos de `utm_campaign`, `gclid` e `fbclid`.

Contexto que não coube no documento: anúncio de Status traz o `referral` sem `ctwa_clid` [W1]; Chatwoot Community sem Captain, sem papéis customizados e sem SLA, e roda com Sidekiq; Twenty com API REST e GraphQL; base legal proposta, a validar com o encarregado: contrato para atender, legítimo interesse para guardar a origem, consentimento para enviar dados à Meta e ao Google; sem hash de contato enviado às plataformas até o encarregado aprovar. Também: `fbclid` sozinho em ponto pago conta como problema (só canal); post orgânico não conta como anúncio; campanha de paciente modelo otimiza por conversa iniciada no WhatsApp; export grande só com gestor; Twenty só depois do dia 90, se o comercial pedir funil visual; estatística da regra de liberação (com cobertura real de 95%, um canal passa ~44% das vezes com 100 leads, 82% com 97%; ~1% de bloqueio falso por janela de 50, conferido com scipy).

