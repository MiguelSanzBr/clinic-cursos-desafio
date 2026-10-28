# Demo local: da entrada identificada à venda confirmada pelo ERP

Fatia pedida no case: **entrada identificada → contato/oportunidade → encaminhamento do atendimento → venda confirmada pelo ERP**.
WhatsApp, ERP, atendimento e a IA de triagem são simulados. Não há interface gráfica: a verificação é por testes e por um script que imprime cada passo.

## O que a demo prova

- A origem de campanha de um lead chega intacta à venda, ligada pelo `crm_opportunity_id` que o ERP devolve.
- Lead de QR de unidade e contato direto pelo WhatsApp ficam registrados de forma diferente. O direto fica `desconhecida`, sem canal inventado.
- Quem volta é reconhecido por telefone ou e-mail normalizado, nunca por nome. Interesse novo vira oportunidade nova e o primeiro toque da antiga não muda.
- Evento repetido não gera efeito. Mesmo id com conteúdo diferente vira pendência e não sobrescreve o original. O recibo é imutável no banco.
- Venda confirmada fecha a oportunidade. Venda sem oportunidade, ou com produto/unidade diferente da oportunidade, fica em quarentena sem aplicar nada, e é reprocessada quando o ERP reenvia corrigida.
- Uma falha real de rastreamento (LP paga sem UTM) é detectada, registrada e bloqueia a liberação daquele ponto de entrada, sem perder o lead.
- O encaminhamento sai de uma outbox gravada junto com a oportunidade. Timeout fica `incerto` e não é reenviado às cegas.

## Como rodar

Requer [uv](https://docs.astral.sh/uv/) e Python 3.12 ou mais novo.

```bash
uv sync
uv run pytest -v
uv run python scripts/demo.py
```

Opcional, para explorar a API e o banco:

```bash
uv run fastapi dev app/main.py        # http://127.0.0.1:8000/docs
sqlite3 demo.db "SELECT id, opportunity_id, origin_type, source_channel, utm_campaign, entry_point FROM touchpoint"
```

`scripts/demo.py` apaga e recria `demo.db` a cada execução. Os testes usam banco em memória.

## Onde está cada coisa

| Arquivo | Conteúdo |
|---|---|
| `app/schema.sql` | Tabelas, `CHECK`s, índice único de oportunidade aberta, triggers append-only e de recibo imutável |
| `app/domain.py` | Regras puras: telefone, e-mail, origem, convenção de UTM, ponto de entrada, venda divergente, fila |
| `app/db.py` | Todo o SQL: recibo com dedup e reprocessamento, identidade, oportunidade, toque, consentimento, venda, relatório, outbox |
| `app/main.py` | Rotas FastAPI e validação de entrada (Pydantic) |
| `data/catalog.json` | A convenção: unidades, produtos, listas de `utm_source` e `utm_medium`, pontos de entrada, anúncios, limite de liberação |
| `data/eventos.json` | Payloads de exemplo (dados fictícios), usados pela demo e pelos testes |

Rotas: `POST /events/form`, `POST /events/whatsapp` (formato do webhook da WhatsApp Cloud API), `POST /events/erp/sale`, `GET /people/{id}/journey`, `GET /opportunities/{id}`, `GET /quality/report`.

## Cenários do enunciado e testes

| Cenário | Teste | O que verifica |
|---|---|---|
| Lead com campanha e ponto de entrada, origem preservada até a venda | `test_c1_origem_campanha_preservada_ate_venda` | Origem `observada`/`meta`, fila `comercial-sp`. Depois da venda, oportunidade `ganha` e o primeiro toque ainda tem `utm_campaign`, `utm_content`, `fbclid` e `lp-sp-micro-01`. Nenhum campo do toque contém `@`. O relatório atribui a venda a `observada:meta` |
| QR de unidade e WhatsApp direto, registrados de forma distinta | `test_c2_qr_unidade_distinto_de_whatsapp_direto` | QR: `observada`/`qr_code`, unidade `cps`, produto `paciente_modelo`, fila `comercial-cps`. Direto: `desconhecida`, `source_channel` nulo, sem UTM, click id, anúncio ou ponto de entrada, fila `triagem-bot`, nenhum alerta |
| Pessoa existente volta por outra campanha | `test_c3_pessoa_existente_nova_campanha` | Telefone em outro formato e outro nome no perfil caem na mesma pessoa. Segunda oportunidade (`harmonizacao`/`rj`, fila `comercial-rj`). Primeiro toque da primeira oportunidade inalterado. Terceiro contato do mesmo produto reusa a oportunidade e só muda o último toque |
| O mesmo evento chega duas vezes | `test_c4_evento_duplicado_sem_efeito` | Reenvio de `form-1001` e `wamid.QR001` responde `duplicado` com o mesmo `event_id`. Contagem de 8 tabelas igual antes e depois. `duplicatas_recebidas = 2` |
| Venda confirmada pelo ERP | `test_c5_venda_erp_atualiza_oportunidade` | Oportunidade `ganha`, venda listada nela, primeiro toque ainda é o evento do lead. Venda repetida não cria segunda linha. Oportunidade ganha não reabre: novo interesse vira oportunidade nova |
| Falha escolhida | `test_falha_lp_sem_utm_detectada`, `test_lp_sem_utm_com_como_conheceu_nao_libera` | Ver seção abaixo |

Testes de apoio:

| Teste | O que verifica |
|---|---|
| `test_duplicado_payload_diferente_registra_conflito` | Mesmo `submission_id` com telefone diferente: `conflito`, recibo original intacto, nenhum toque ou identificador novo, issue `evento_conflitante` |
| `test_venda_sem_oportunidade_quarentena` | Venda para a oportunidade 9999 e venda sem `crm_opportunity_id`: evento em `quarentena`, issue `venda_sem_oportunidade`, zero pessoa, toque, oportunidade ou venda |
| `test_venda_divergente_quarentena` | Venda de `harmonizacao/rj` apontando para oportunidade de `micropigmentacao/sp`: quarentena, issue `venda_divergente`, oportunidade continua `aberta` |
| `test_venda_em_quarentena_reprocessada` | Venda órfã reenviada com o id certo: o mesmo recibo troca de payload sem `evento_conflitante`, grava 1 venda, oportunidade `ganha`, recibo `processado`, issue `resolvida`, audit `venda.reprocessada` |
| `test_recibo_imutavel` | `UPDATE` de `source`, `dedup_key`, `payload` ou `payload_hash` num recibo processado levanta `sqlite3.IntegrityError`. O contador de duplicatas pode mudar |
| `test_relatorio_conta_leads_nao_mensagens` | Duas mensagens da mesma pessoa pelo mesmo anúncio contam 1 lead. Linha `(sem ponto de entrada)` com `liberado: null` |
| `test_anuncio_fora_do_catalogo_vai_para_triagem` | Anúncio fora de `catalog.ads`: segue `observada`/`meta_ctwa` (o `ad_id` é evidência), oportunidade nova em `triagem-bot`, issue `anuncio_desconhecido` |
| `test_click_id_da_url[gclid, gbraid, wbraid, fbclid]` | Cada click id da URL vira `observada` com o canal certo (`google` ou `meta`) e passa pelo `CHECK` do banco |
| `test_consentimento_registrado_na_jornada` | Consentimento de marketing gravado a cada formulário que o traz, histórico na jornada, campo ausente não vira "não", tabela append-only |
| `test_declarada_nao_vira_observada` | "Como conheceu: instagram" em `/contato` fica `declarada`, sem UTM, e conta como `declarada:instagram`, separada de qualquer canal observado |
| `test_touchpoint_append_only` | `UPDATE` ou `DELETE` direto em `touchpoint` levanta `sqlite3.IntegrityError` |
| `test_handoff_timeout_fica_incerto` | Timeout ao encaminhar deixa o handoff `incerto`, e a rodada seguinte não o reenvia |
| `test_formulario_sem_identificador_rejeitado` | Formulário sem telefone nem e-mail válidos: 422 e nada gravado |
| `test_identificadores_de_pessoas_diferentes_nao_fundem` | Telefone de uma pessoa com e-mail de outra: usa a do telefone, abre `identidade_conflitante`, não funde |
| `test_mensagem_sem_produto_continua_oportunidade_aberta` | "obrigada!" depois do QR segue na oportunidade da CPS, sem criar oportunidade `a_definir` nem mandar para a triagem |
| `test_id_inexistente_404_e_webhook_sem_mensagem_ignorado` | Id inexistente: 404. Webhook só com status de entrega: `ignorado` |
| `tests/test_domain.py` | Telefones em 4 formatos viram o mesmo E.164, fixo não ganha nono dígito, e-mail, as classes de origem, parâmetros da URL, UTM fora da lista e UTM com `@` descartada, página fora do catálogo, código `[ep]` não cadastrado |

## A falha escolhida: LP paga sem UTM

O ponto de entrada `lp-sp-micro-01` está no catálogo com `exige_parametros: true`: todo lead ali deveria chegar com UTM ou click id. O lead `form-1003` chega sem nenhum, com referrer `bit.ly`. O link passou por um encurtador que descartou a query string.

Como a demo trata:

1. O lead é aceito e encaminhado (`comercial-sp`). Falha de rastreamento não pode custar o lead.
2. A origem fica `desconhecida`. Não vira `meta` por ser a campanha ativa da LP nem por palpite sobre o referrer.
3. Abre a issue `parametros_perdidos` com `{"referrer_host": "bit.ly"}`, sem dado pessoal, apontando onde procurar o link quebrado.
4. `/quality/report` conta leads (primeiro toque de cada oportunidade). Lead com problema é o de origem `desconhecida` ou com issue aberta `parametros_perdidos` ou `utm_fora_do_padrao` no evento do primeiro toque. `lp-sp-micro-01` fica com `taxa_problema` 0,5, acima do limite 0,05 do catálogo, e `liberado: false`. Esse ponto de entrada não entra no primeiro fluxo do CRM até ser corrigido.
5. "Como conheceu" preenchido não esconde a perda. A origem vira `declarada`, mas a issue abre do mesmo jeito e o ponto continua sem liberar (`test_lp_sem_utm_com_como_conheceu_nao_libera`).

O WhatsApp direto sem código também é `desconhecida`, mas é esperado: entra na linha `(sem ponto de entrada)`, que não tem canal a liberar (`liberado: null`), e não gera alerta.

## Saída esperada do demo

`uv run python scripts/demo.py` (saída real, determinística):

```text
[C1] form-1001 Ana, LP paga com UTM -> processado (origem observada/meta, fila comercial-sp, pessoas=1, toques=1)
[C2] WhatsApp Bruna, QR da recepção CPS -> processado (origem observada/qr_code, fila comercial-cps, pessoas=2, toques=2)
[C2] WhatsApp direto, sem código -> processado (origem desconhecida/-, fila triagem-bot, pessoas=3, toques=3)
[C3] Ana volta por anúncio Click-to-WhatsApp RJ -> processado (origem observada/meta_ctwa, fila comercial-rj, pessoas=3, toques=4)
[C3] Ana de novo pelo mesmo anúncio -> processado (origem observada/meta_ctwa, fila comercial-rj, pessoas=3, toques=5)
[C4] reenvio form-1001 -> duplicado (pessoas=3, toques=5)
[C4] reenvio wamid.QR001 -> duplicado (pessoas=3, toques=5)
[C5] ERP confirma ERP-2026-5001 da oportunidade da Ana -> processado (pessoas=3, toques=5)
[FALHA] form-1003 Diego, LP paga sem UTM (veio de bit.ly) -> processado (origem desconhecida/-, fila comercial-sp, pessoas=4, toques=6)
[DECLARADA] form-1004 Carla, /contato com 'como conheceu' -> processado (origem declarada/-, fila comercial-rj, pessoas=5, toques=7)
[ORFA] ERP-2026-5002 para oportunidade 9999 -> quarentena (motivo venda_sem_oportunidade, pessoas=5, toques=7)
[ORFA] ERP reenvia ERP-2026-5002 com a oportunidade do Diego -> processado (pessoas=5, toques=7)
[DIVERGENTE] ERP-2026-5003 harmonizacao/rj na oportunidade da Bruna (paciente_modelo/cps) -> quarentena (motivo venda_divergente, pessoas=5, toques=7)

Jornada da Ana (GET /people/1/journey, campos nulos omitidos):
{
  "person_id": 1,
  "nome": "Ana Souza",
  "oportunidades": [
    {
      "id": 1,
      "product": "micropigmentacao",
      "unit": "sp",
      "status": "ganha"
    },
    {
      "id": 4,
      "product": "harmonizacao",
      "unit": "rj",
      "status": "aberta"
    }
  ],
  "toques": [
    {
      "id": 1,
      "person_id": 1,
      "opportunity_id": 1,
      "event_id": 1,
      "occurred_at": "2026-10-20T17:03:00+00:00",
      "contact_channel": "form",
      "origin_type": "observada",
      "source_channel": "meta",
      "utm_source": "meta",
      "utm_medium": "paid_social",
      "utm_campaign": "sp-micropigmentacao-captacao-202610",
      "utm_content": "video-01",
      "click_id_type": "fbclid",
      "click_id": "IwAR0abc",
      "entry_point": "lp-sp-micro-01",
      "unit": "sp",
      "product": "micropigmentacao"
    },
    {
      "id": 4,
      "person_id": 1,
      "opportunity_id": 4,
      "event_id": 4,
      "occurred_at": "2026-10-22T12:00:00+00:00",
      "contact_channel": "whatsapp",
      "origin_type": "observada",
      "source_channel": "meta_ctwa",
      "utm_campaign": "rj-harmonizacao-captacao-202610",
      "click_id_type": "ctwa_clid",
      "click_id": "ARAkLk9",
      "ad_id": "120210000000001",
      "unit": "rj",
      "product": "harmonizacao"
    },
    {
      "id": 5,
      "person_id": 1,
      "opportunity_id": 4,
      "event_id": 5,
      "occurred_at": "2026-10-23T12:00:00+00:00",
      "contact_channel": "whatsapp",
      "origin_type": "observada",
      "source_channel": "meta_ctwa",
      "utm_campaign": "rj-harmonizacao-captacao-202610",
      "click_id_type": "ctwa_clid",
      "click_id": "ARAkLk9b",
      "ad_id": "120210000000001",
      "unit": "rj",
      "product": "harmonizacao"
    }
  ],
  "consentimentos": [
    {
      "purpose": "marketing",
      "granted": true,
      "at": "2026-10-20T17:03:00+00:00",
      "event_id": 1
    }
  ]
}

Relatório de qualidade (GET /quality/report):
{
  "origem_por_canal": {
    "declarada:instagram": 1,
    "desconhecida": 2,
    "observada:meta": 1,
    "observada:meta_ctwa": 1,
    "observada:qr_code": 1
  },
  "pontos_de_entrada": [
    {
      "entry_point": "(sem ponto de entrada)",
      "total": 2,
      "desconhecida": 1,
      "com_problema": 1,
      "taxa_problema": 0.5,
      "liberado": null
    },
    {
      "entry_point": "lp-sp-micro-01",
      "total": 2,
      "desconhecida": 1,
      "com_problema": 1,
      "taxa_problema": 0.5,
      "liberado": false
    },
    {
      "entry_point": "qr-cps-recepcao-01",
      "total": 1,
      "desconhecida": 0,
      "com_problema": 0,
      "taxa_problema": 0.0,
      "liberado": true
    },
    {
      "entry_point": "site-online-contato-01",
      "total": 1,
      "desconhecida": 0,
      "com_problema": 0,
      "taxa_problema": 0.0,
      "liberado": true
    }
  ],
  "issues_abertas": {
    "parametros_perdidos": 1,
    "venda_divergente": 1
  },
  "eventos": {
    "processado": 9,
    "quarentena": 1,
    "duplicatas_recebidas": 3
  },
  "vendas": {
    "total": 2,
    "valor_cents": 698000,
    "por_origem_primeiro_toque": {
      "desconhecida": 1,
      "observada:meta": 1
    }
  }
}

Encaminhamento (db.dispatch_handoffs, atendimento simulado):
[ENCAMINHAMENTO] oportunidade 1 -> comercial-sp
[ENCAMINHAMENTO] oportunidade 2 -> comercial-cps
[ENCAMINHAMENTO] oportunidade 3 -> triagem-bot
[ENCAMINHAMENTO] oportunidade 4 -> comercial-rj
[ENCAMINHAMENTO] oportunidade 5 -> comercial-sp
[ENCAMINHAMENTO] oportunidade 6 -> comercial-rj
```

## Como a convenção vive em `data/catalog.json`

- `units` e `products`: valores aceitos. Valor fora da lista no formulário não é inventado nem rejeita o lead: cai no do ponto de entrada ou fica desconhecido (`a_definir`, `desconhecida`).
- `utm_sources` e `utm_mediums`: listas fechadas. Valor fora da lista fica gravado como veio (o toque continua `observada`) e abre `utm_fora_do_padrao`. Qualquer `utm_*` com `@` é descartado antes de gravar e também abre `utm_fora_do_padrao`.
- `utm_campaign` segue `{unidade}-{produto}-{objetivo}-{aaaamm}`, por exemplo `sp-micropigmentacao-captacao-202610`. `utm_content` identifica o criativo (`video-01`).
- `entry_points`: chave no padrão `{tipo}-{unidade}-{local}-{nn}` (`lp-sp-micro-01`, `site-online-contato-01`, `qr-cps-recepcao-01`), com caminho da página, unidade, produto, `exige_parametros` e dono. Formulário de página fora do catálogo abre `ep_desconhecido` com o caminho.
- QR: leva ao `wa.me` com texto pré-preenchido contendo `[qr-cps-recepcao-01]`. O código é procurado no texto (regex sem diferenciar maiúsculas) e conferido no catálogo. Código não cadastrado não vira origem e abre `ep_desconhecido`. Se a pessoa apagar o código, o contato fica `desconhecida`.
- `ads`: `source_id` do anúncio Click-to-WhatsApp para campanha, unidade e produto. Anúncio fora da lista abre `anuncio_desconhecido`.
- `liberacao.max_taxa_problema`: limite comparado com `taxa_problema` em `pontos_de_entrada[].liberado`.
- Fila: `comercial-{unidade}` quando a unidade é conhecida, `triagem-bot` quando não é.

## Decisões

- **Primeiro e último toque não são colunas.** Saem de `touchpoint` (append-only) por `ORDER BY occurred_at, id`. A atribuição da venda e o relatório usam um lugar só: `db.attributed_touch`.
- **`inferida` sem regra ativa.** O schema aceita o valor, mas nenhuma regra o produz. Inferência sem método validado seria origem inventada com outro nome.
- **Origem só com evidência no evento.** `observada` exige UTM, click id (`gclid`, `gbraid`, `wbraid`, `fbclid`, `ctwa_clid`), `referral` de anúncio ou código QR cadastrado. `declarada` é só "como conheceu". O resto é `desconhecida`, com `source_channel` nulo (o schema impede outro valor). `fbclid` indica Meta, não prova mídia paga.
- **Venda na dúvida vai para quarentena.** Sem `crm_opportunity_id`, com id inexistente ou com produto/unidade diferentes da oportunidade: o evento fica em `quarentena`, abre `venda_sem_oportunidade` ou `venda_divergente`, e nada é aplicado. Melhor uma venda parada do que fechar a oportunidade errada.
- **Reprocessamento pelo reenvio.** Reenvio do mesmo `erp_sale_id` com o recibo em quarentena troca o payload e processa de novo, sem `evento_conflitante`, porque nada tinha sido aplicado. Se ligar, a issue fecha e o audit registra `venda.reprocessada`.
- **Recibo imutável.** Um trigger barra mudança de `source` e `dedup_key` sempre, e de `payload`/`payload_hash` fora da quarentena. Exclusão LGPD seria a exceção, feita por rotina própria e registrada em `audit_log`.
- **Duplicado e conflito respondem 200.** O remetente (Meta, ERP) para de reenviar. O conflito fica como issue para alguém olhar. Payload inválido responde 422, id inexistente 404.
- **Recibo e efeitos numa transação.** `INSERT ... ON CONFLICT (source, dedup_key) DO NOTHING RETURNING id`: se não volta linha, é repetição; mesmo hash é `duplicado`, hash diferente é `conflito`.
- **Relatório conta leads, não mensagens.** Origem por canal e pontos de entrada usam o primeiro toque de cada oportunidade.
- **Identidade só por identificador.** Telefone em E.164 e e-mail em minúsculas, nunca nome. Telefone e e-mail de pessoas diferentes: usa a do telefone, abre `identidade_conflitante`, não funde.
- **Mensagem de continuação não é interesse novo.** Mensagem sem evidência de origem, sem produto e sem unidade, de quem já tem oportunidade aberta, segue nessa oportunidade. Com evidência (anúncio, código QR), abre ou reusa a oportunidade da chave dela.
- **Consentimento é histórico.** Cada formulário que traz `consent_marketing` grava uma linha append-only em `consent`. O vigente é o mais recente. Campo ausente não grava nada.
- **Dado pessoal fica fora do toque.** O toque guarda só `utm_*` e click ids. Nome, telefone e e-mail ficam em `person`, `person_identifier` e no payload bruto de `inbound_event`.
- **Encaminhamento como outbox.** O handoff é gravado na mesma transação da oportunidade. `db.dispatch_handoffs(send)` entrega depois (a demo imprime cada entrega). Timeout vira `incerto` e não é reenviado às cegas: o atendimento pode ter recebido, e alguém confere.
- **Triagem por IA é simulada.** `triagem-bot` é só a fila. O bot perguntaria produto, unidade e "como conheceu", e a resposta voltaria como toque `declarada`.

## O que é só desenho (não está na demo)

- `recorded_by` na origem declarada (quem registrou: formulário, atendente, bot).
- `merged_into` para fusão de pessoas reversível. Na demo, conflito de identidade só abre issue.
- `origin_system` para evitar loop na sincronização bidirecional entre CRM, atendimento e ERP.
- `is_test` para os leads sintéticos de teste ponta a ponta.
- Redirecionador `/q/<ep>` para QR impresso, com log de leituras. Na demo o QR já chega como código no texto do WhatsApp.
- Flag `channel_validated` por canal. O `liberado` do relatório é o cálculo que a alimentaria.
- Cookie primário e campos ocultos no formulário para levar os parâmetros entre páginas. Na demo, a `page_url` do envio faz esse papel.
- Classificação de busca orgânica pelo referrer.

## Limitações

Atalhos marcados no código com `# shortcut:`:

- Uma conexão SQLite compartilhada entre threads (`check_same_thread=False`), sem lock. Requisições simultâneas podem se misturar.
- Uma mensagem por webhook do WhatsApp. Lote responde 422 e a Meta reenvia.
- Sem conferência da assinatura `X-Hub-Signature-256` e sem o handshake GET de verificação da Meta.
- Sem sincronização atendimento → CRM: o status da conversa não volta.
- Só telefones do Brasil. Número estrangeiro de 10 ou 11 dígitos seria lido como DDD.
- Toda mensagem de WhatsApp vira toque, inclusive as de conversa já aberta. Isso pesa se a atribuição mudar para último toque.
- `liberado` olha só a taxa de problema. Amostra mínima e período de observação do checklist ficam fora da demo, por isso um ponto com 1 lead aparece liberado.

Outras, sem marcação no código:

- As rotas não têm autenticação nem permissão por papel. Os GET usam ids sequenciais, então qualquer um que alcance a API consegue listar nomes.
- `inbound_event.payload` guarda o texto integral da mensagem de WhatsApp e a URL completa do formulário. Proposta: retenção curta, 90 dias, para o payload bruto.
- `paciente_modelo` está modelado como produto. Na prática é uma oportunidade de atendimento (a pessoa é atendida numa aula), não a venda de um curso.
- Venda em quarentena só é reprocessada quando o ERP reenvia. Não há rotina que tente de novo quando a oportunidade aparece.
- `duplicatas_recebidas` conta todo reenvio com chave repetida, inclusive o reenvio que reprocessou uma venda da quarentena.
- Importar `app.main` abre `demo.db` (é o app do `fastapi dev`), então rodar os testes cria um `demo.db` vazio na raiz. Está no `.gitignore`.

## Mudanças de requisito que já são baratas

- **Nova unidade ou novo QR:** só `data/catalog.json` (`units` ou `entry_points`). A fila `comercial-{unidade}` sai sozinha.
- **Atribuição por último toque:** trocar o `ORDER BY` de `db.attributed_touch` para `DESC`. Relatório e atribuição de venda mudam juntos.
- **Exclusão LGPD:** cerca de 10 linhas: apagar `person_identifier` e `consent` da pessoa, zerar `person.name` e o `payload` dos eventos dela, gravar em `audit_log`. Exige a exceção no trigger do recibo, que hoje barra a troca de payload. `touchpoint` fica, porque não tem dado pessoal. O hash do recibo continua barrando reenvio.
- **ERP sem `crm_opportunity_id`:** hoje vai para quarentena. O fallback seria buscar por identificador + produto quando houver exatamente uma oportunidade aberta candidata, gravando como a ligação foi feita. Mais de uma candidata continua na quarentena.

## Uso de IA

Código gerado com Claude (Claude Code, Opus 5.5) a partir de plano revisado pelo candidato. Testes executados localmente.
