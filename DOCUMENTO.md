# Rastreamento antes do CRM: plano para a Clinic Cursos

**Miguel Sanz Boragan**, case Product Builder/FDE, 2026-10-28<br>
Demo e registro: repositório anexo (README.md, REGISTRO.md)

Proposta: auditar, padronizar e validar a entrada canal por canal. O CRM entra por piloto, só com canais aprovados num checklist medido. Origem ausente fica desconhecida, nunca suposta.

## 1. Perguntas e premissas

|#|Pergunta|Com quem / evidência|Decisão que depende|
|---|---|---|---|
|1|Que contas e integrações existem (GTM, GA4, Google Ads, Meta, RD Station Marketing, Hotmart, domínio) e quem é admin?|Fundador; usuários de cada conta|Escopo da semana 1; risco de conta presa em agência|
|2|Quem cria links, LPs, QR e impressos? Existe convenção?|Marketing, agência, tráfego, recepções; amostra de links e QR|Quem executa cada correção|
|3|Qual a jornada real até a venda, por unidade e produto, incluindo paciente modelo?|Acompanhar 1 turno de atendimento por unidade|Onde a origem se perde; qual fluxo vira piloto|
|4|Leads e vendas por canal e unidade em 90 dias: quanto divergem RD Station Marketing, Ozia/Aktos, ERP, Hotmart e Ads?|Exports dos cinco sistemas, mesmo período|Baseline e limites do checklist; ordem de correção|
|5|Como a venda chega ao ERP (balcão, Hotmart, paciente modelo) e com que ID? Ele guarda o `crm_opportunity_id`?|Dev do ERP; 1 venda de teste em homologação|Venda ligada por ID ou por regra|
|6|Quantos números de WhatsApp existem, em que conta Meta, e o que diz o contrato Ozia/Aktos (prazo, multa, exportação)?|Meta Business Manager; contrato|Ordem da migração do atendimento; como recuar|
|7|Que consentimento coletamos, quem responde pela LGPD e onde aparece dado de saúde?|Jurídico ou DPO; formulários atuais|O que pode ir a Pixel, CAPI e GA4; campos proibidos no CRM|
|8|Que números os fundadores precisam sustentar (venda por campanha, CAC por unidade, ocupação) e com que frequência?|Fundadores; relatórios atuais|O que entra primeiro no painel|

**Premissas** (valem até a resposta da pergunta entre parênteses):

- **P1** (5): o ERP expõe venda confirmada com ID, por webhook ou export (só export: atraso de D+1).
- **P2** (4): todo limite numérico aqui é proposta, a calibrar com o baseline.
- **P3** (6): ao menos um número oficial segue na Ozia/Aktos durante a transição.
- **P4**: o RD Station Marketing fica ativo ao menos 30 dias após o coletor entrar em paralelo.
- **P5** (2): existe gestor de tráfego, interno ou de agência. **P6**: histórico anterior ao padrão nunca vira origem observada.
- **P7**: uma pessoa dedicada (eu), 35 h por semana: 28 de construção e 7 observando a operação. **P8**: SP, RJ, Campinas e online.

## 2. Rastreamento em quatro passos

**1. Inventário e auditoria.** Planilha de inventário: ativo, `ep` proposto, destino, dono, problema, volume, verba. Tag duplicada: export do GTM e código das páginas (dois `page_view` por carga). Evento ausente: formulário de teste conferido no GA4 e no Events Manager. Redirecionamento que perde origem: crawler e `curl -IL` em cada URL de anúncio, bio, encurtador e checkout Hotmart. Entrada sem identificação: % sem origem por formulário no RD Station Marketing, wa.me sem texto, QR sem parâmetro. Orgânico: links próprios (bio, vídeos do YouTube, blog → LP) ganham UTM `organic_social`; busca orgânica só aparece pelo referrer, como canal sem campanha, e o relatório diz isso. Nas unidades, fotografo cada banner e QR. Prioridade: verba e volume altos com correção barata; reimpressão só sem outra saída.

**2. Padrão e correção.** Convenção mínima (a mesma da demo):

|Campo|Regra (exemplo)|
|---|---|
|Unidade|`sp`, `rj`, `cps`, `online`|
|`utm_source`|lista fechada: `google`, `meta`, `youtube`, `instagram`, `rd_email`, `hotmart`, `offline`, `indicacao`|
|`utm_medium`|lista fechada: `cpc`, `paid_social`, `organic_social`, `email`, `qr`, `wa_link`, `referral`|
|`utm_campaign`|`{unidade}-{produto}-{objetivo}-{aaaamm}`, produto = código do catálogo (`sp-micropigmentacao-captacao-202610`)|
|`utm_content`|criativo (`video-01`)|
|Ponto de entrada `ep`|`{tipo}-{unidade}-{local}-{nn}`, cadastrado com dono, destino e `exige_parametros` (`qr-cps-recepcao-01`, `lp-sp-micro-01`)|

Sem UTM, o canal sai da evidência: `qr_code` (`[ep]`), `meta_ctwa` (`referral`), `google` (`gclid`, `gbraid`, `wbraid`), `meta` (`fbclid`). Valor fora da lista abre a pendência `utm_fora_do_padrao` e não conta como cobertura. QR e botões de WhatsApp passam por um redirecionador próprio `/q/<ep>`, que registra a leitura e leva à LP com UTMs ou ao wa.me com `[<ep>]` no texto; o destino muda sem reimprimir. Fragilidade: se a pessoa apagar o código, o contato fica desconhecido. Executam: tráfego (anúncios), marketing ou agência (LPs, bio, vídeos), eu (GTM, campos ocultos, redirecionador), coordenações e gráfica (impressos). Prevenção: gerador de links que rejeita valor fora da lista; nenhuma campanha sem link do gerador.

**3. Preservação da jornada.** Na LP, um script guarda UTMs e click ids em cookie primário e preenche campos ocultos. O `gclid` precisa chegar à LP final; a importação de conversão offline aceita até 90 dias do clique (63 em conversões otimizadas para leads) [G1]. Cada contato vira um toque append-only; primeiro e último toque saem por consulta; sem fingerprint.

- Múltiplos contatos: formulário e WhatsApp com o mesmo telefone são uma pessoa com dois toques.
- Troca de dispositivo: vínculo só quando a pessoa informa o mesmo telefone ou e-mail; antes, dois anônimos.
- Retorno direto: novo toque desconhecido, sem herdar a origem anterior, que segue no histórico.
- Mais de um produto: uma pessoa, N oportunidades (produto + unidade).
- Anúncio que abre conversa (CTWA): o webhook traz `referral` com `source_id` e `ctwa_clid` (anúncio de Status vem sem `ctwa_clid`) [W1]; gravo na primeira mensagem que o trouxer.
- Venda: o CRM envia o `crm_opportunity_id` ao ERP na matrícula, e a venda volta com ele. Na Hotmart, a UTM não chega ao webhook; o link de checkout leva `sck` com o `ep` (até 30 caracteres, sem `_`), que volta em `data.purchase.origin.sck` [H1][H2].

**4. Validação e manutenção.** Leads sintéticos semanais por ponto de entrada (`is_test`) vão até o CRM e, em homologação, ao ERP. Conciliação diária formulários × CRM e plataformas × CRM. Alertas: % desconhecida por `ep` acima do limite, quarentena acumulando, `ep` não cadastrado, volume zerado. Responsáveis: eu, tráfego (anúncios), coordenações (impressos); revisão semanal no piloto, depois mensal. Privacidade: nenhum dado pessoal em URL, UTM, pixel ou GA4 [GA1]; o toque guarda só parâmetros de rastreio, e o payload bruto fica no log de eventos com acesso restrito e retenção curta (proposta: 90 dias, a calibrar com jurídico); CAPI e Google só com hash e consentimento; dado de saúde nunca vai a ferramenta de marketing.

**Tipos de origem.** Canal de contato não é origem: o WhatsApp diz por onde a pessoa falou, não por que veio.

|Tipo|Quando|Exemplo|Uso permitido|
|---|---|---|---|
|Observada|Evidência técnica: UTM válida, click id, `referral` CTWA, `[ep]` cadastrado|`gclid` na LP|Atribuição, automação, CAC|
|Declarada|Resposta a "como conheceu" (lista fechada), com `recorded_by`|"indicação de aluna", na recepção|Relatório próprio; não substitui a observada|
|Inferida|Regra explícita, com método e confiança gravados|primeiro contato 1 h após um post|Só análise; nunca promovida, nunca dispara automação ou comissão|
|Desconhecida|Sem evidência|WhatsApp de número salvo|Valor válido, linha própria no relatório, nunca redistribuída|

**Histórico irrecuperável.** Contatos do RD Station Marketing, Ozia/Aktos e planilhas entram com `source_system` e `import_batch`, tipo desconhecida (ou declarada, se o campo "como conheceu" existia), nunca observada. O webhook de conversão do RD Station Marketing tem payload fixo: de origem, só `funnel.origin` (junta utm_source e utm_medium) e os campos `cf_*` [R1]; o histórico sai do export ou da API de eventos do contato (a confirmar se ela traz UTM). Antes da data de corte, indicadores saem "não comparável".

<small>Fontes (consulta 2026-10-28): [G1] support.google.com/google-ads/answer/15081888; [W1] developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/text/; [H1] help.hotmart.com/pt-br/article/216441797/; [H2] developers.hotmart.com/docs/pt-BR/2.0.0/webhook/purchase-webhook/; [GA1] support.google.com/analytics/answer/6366371; [R1] developers.rdstation.com/reference/webhooks-payload-mkt.md</small>

### 2.1 Matriz de correção: quatro pontos de entrada

|Ativo/canal|Problema hipotético|Correção|Responsável|Evidência de validação|
|---|---|---|---|---|
|LP de Google Ads, SP (`lp-sp-micro-01`)|Encurtador descarta UTM e `gclid`; GA4 instalado duas vezes conta lead em dobro|URL final direta; remover a tag duplicada; campos ocultos|Gestor de tráfego (URL); eu (GTM e campos)|`curl -IL` com UTM e `gclid` no destino; 20 leads sintéticos observados; 1 evento por envio no DebugView|
|Botão de WhatsApp do site e bio (`wa-sp-site-01`)|wa.me direto: todo lead vira só "WhatsApp"|Via `/q/wa-sp-site-01`, chega com `[wa-sp-site-01]`; sem código, o atendimento pergunta "como conheceu"|Eu (redirecionador); marketing (bio)|10 mensagens de teste com `ep` reconhecido; % sem código reportada|
|QR da recepção de Campinas (`qr-cps-recepcao-01`)|QR impresso aponta para a home, sem unidade nem campanha|Reimprimir uma vez para `/q/qr-cps-recepcao-01`; depois, troca sem reimpressão|Eu (rota); coordenação de Campinas e gráfica|Foto instalada; leitura em 2 celulares; log de leituras bate com contatos `qr`|
|Balcão, telefone e indicação (3 unidades)|"Como conheceu" com "Instagram" pré-selecionado infla o canal|Obrigatório, sem padrão, lista fechada; indicação grava `ind-{id}`|Eu (CRM); coordenação (treino da recepção)|Auditoria de 30 registros: 0 com valor padrão; ≥90% preenchidos|

### 2.2 Checklist de liberação do primeiro fluxo do CRM

Por ponto de entrada; limites são proposta, a calibrar com o baseline (P2).

|Critério|Limite|Amostra / período|Por quê|
|---|---|---|---|
|Cobertura de origem: só observada em ponto pago (`exige_parametros`); observada ou declarada em balcão e telefone|≥95%|n ≥ 100 leads em 14 dias|Declarada esconderia UTM perdida. Com n = 100, ≥95 dá cobertura real provável acima de ~90% (limite inferior de 95%)|
|Inferida ou valor padrão gravado como observada|0|Auditoria manual de 30 registros|Erro de regra, não de amostra: 1 caso já pede correção|
|Conciliação formulário → CRM|Diferença ≤5% por dia|7 dias seguidos|Acima de 5% por 7 dias é perda sistemática, não atraso|
|Conciliação Ads → CRM|Diferença ≤15%, estável|14 dias|Plataformas contam com regra própria (janela, cookie bloqueado); olho tendência|
|Duplicidade|0 efeito duplicado em 50 reenvios; 0 pessoa duplicada em 20 retornos com telefone em outro formato|Teste dirigido|Automação duplicada manda 2 mensagens ao cliente|
|Ponta a ponta|20/20 leads sintéticos corretos|3 navegadores, no início e no fim|1 falha em 20 já é 5%, a folga inteira da cobertura|
|Quarentena|<2% dos eventos, nenhum parado >48 h|14 dias|2% de 100 leads = 2 casos, revisáveis à mão; 48 h = 2 revisões diárias|
|"Como conheceu" sem origem observada|≥90% preenchido|14 dias|Única fonte de origem em balcão e telefone|
|Recuo|Flag desligada em <15 min|1 ensaio|15 min = reapontar 1 link e conferir 1 lead sintético; o RD Station Marketing segue recebendo (P4)|
|Aprovação|Fundador e coordenação da unidade|1 reunião de 30 min com estes números|2 assinaturas: quem paga a mídia e quem atende o lead|

Volume baixo: abaixo de 100 leads em 14 dias, estendo para 28; se ainda faltar, uso contagem absoluta (no máximo 1 sem origem em 30, ou 97%) e libero marcado "amostra pequena". Expansão para indicadores de venda: ≥90% das vendas do ERP ligadas por ID.

## 3. CRM e atendimento: arquitetura

```
 LP/formulário, QR e botões /q/<ep>, Ads (custo), Hotmart, RD Station Marketing
                          | eventos (contrato v1)
 +------------------------v-------------------------------+crm_opportunity_id+---------------+
 | Coletor: recibo com chave única, log imutável,         |----------------->| ERP: venda,   |
 | quarentena, outbox de saída                            |<-----------------| pagto, turma, |
 +--------------------------------------------------------+  sale_confirmed  | vagas, preço  |
    ^ mensagem + referral            | pessoa, toque, oportunidade           +---------------+
    |                                v
 +-----------------------+ handoff +---------------------------+
 | Atendimento WhatsApp  |<------->| CRM: pessoa, oportunidade,|-> só leitura: BI, agente
 | (recebe webhook Meta) | contexto| toques, consentimento     |   de tráfego, Grande Cérebro
 +-----------------------+         +---------------------------+
```

|Informação|Dono (escreve)|Quem lê|
|---|---|---|
|Venda, pagamento, turma, vagas, preço, comissão|ERP|Todos, só leitura (cópia com data)|
|Pessoa, identificadores, oportunidade, toques, consentimento|CRM, via coletor|Atendimento, BI; o ERP recebe só o `crm_opportunity_id`|
|Conversa, fila, atendente, handoff|Atendimento|CRM (status e resumo)|
|Evento bruto recebido|Coletor (log imutável, retenção curta)|Auditoria, reprocessamento|
|Investimento e cliques|Google Ads, Meta|Agente de tráfego, BI|
|Prontuário do paciente modelo|Sistema clínico ou ERP|Nunca CRM nem marketing. A conversa pode ter dado sensível: acesso restrito no atendimento, sem cópia ao CRM|

**Identidade.** Uma pessoa entre canais e unidades, por identificador verificado, nunca por nome; caso ambíguo vai a fila humana, e a fusão (`merged_into`) pode ser desfeita. Aluna, paciente modelo e lead são papéis por unidade; cada interesse é uma oportunidade.

**Dois sentidos.** Cada campo tem um só escritor (tabela acima); eventos levam `origin_system` e quem recebe ignora o próprio eco. Lead direto pelo WhatsApp: o coletor cria pessoa e oportunidade e devolve o `crm_opportunity_id`.

**Venda.** O ERP publica `sale_confirmed` com `erp_sale_id` e `crm_opportunity_id`; a oportunidade vira ganha, ligada à jornada. Venda sem id, com id inexistente ou com produto ou unidade diferente da oportunidade vai para quarentena, sem nada aplicado. O reenvio com id corrigido é reprocessado: só recibo em quarentena pode trocar de conteúdo, porque nada foi aplicado.

**Repetição, atraso e falha.** Recibo com chave única (fonte + id do evento) na mesma transação dos efeitos; mesma chave com conteúdo diferente vira conflito, sem sobrescrever. Saídas por outbox com retentativa; timeout vira `incerto`, conferido antes de reenviar. Já usei esse padrão em produção num gateway de WhatsApp. A conciliação diária pega o que escapar; o contrato de evento é versionado.

**Permissões e auditoria.** Papel e unidade checados em toda consulta, no servidor: já corrigi em produção um IDOR entre empresas num CRM multiempresa. Log append-only de quem viu, alterou ou exportou; painel de atraso, quarentena e conflitos.

### 3.1 Paralelismo com uma pessoa

|Durante a auditoria (sem. 1 e 2: ~56 h de construção + ~14 h de observação)|Depende do padrão aprovado (sem. 3 e 4: ~56 h + ~14 h)|Só após validação do canal (dia 30 em diante)|
|---|---|---|
|Esquema e contrato v1; coletor em staging; redirecionador `/q/`; gerador de links; Chatwoot e API do ERP em teste|Campos ocultos nas LPs; cadastro de pontos de entrada; regras de origem; mapa de produto e unidade|Automações e reativação; IA respondendo cliente; origem em CAC/ROI; comissão|

Corte: se os acessos (perg. 1) atrasarem, a auditoria consome mais horas e o coletor em staging passa para o bloco de 30 dias; inventário e baseline não encolhem. Piloto com a flag `channel_validated` por ponto de entrada: lead de canal não validado entra no CRM, mas não aciona automação e fica fora de CAC/ROI; a flag cai sozinha se a cobertura ficar abaixo do limite por 3 dias. O piloto pede checklist 2.2 verde em 1 ou 2 canais pagos de uma unidade e no WhatsApp dela; expansão canal a canal. Especialistas: gestor de tráfego (sem. 1 a 3, contas de anúncio); jurídico ou DPO (sem. 1 a 2, antes de CAPI); dev do ERP (sem. 2 a 4, evento de venda); gráfica (sob demanda).

### 3.2 Construir, adaptar ou contratar

|Consulta 2026-10-28|Chatwoot (atendimento)|Twenty (CRM)|Do zero|
|---|---|---|---|
|Fonte|github.com/chatwoot/chatwoot|github.com/twentyhq/twenty|n/a|
|Licença|MIT no núcleo; pasta `enterprise/` com licença própria paga|AGPL-3.0; arquivos marcados `@license Enterprise` sob licença comercial|Própria|
|Manutenção|Release v4.19.1 em 2026-10-24|Release v2.52.0 em 2026-10-27|Só eu|
|Adequação|Caixa de entrada, filas, Agent Bot para IA, API, webhooks|Objetos customizáveis, API REST e GraphQL, webhooks [T2][T4]|Atende exatamente ao processo, mas custa meses de uma pessoa|
|WhatsApp oficial|Canal WhatsApp Cloud nativo [C3]|Não tem|Cloud API e tela próprias|
|Lacunas|`referral` CTWA vai em `content_attributes` (visto no código [C5]; testar com anúncio); papéis e permissões customizados só no plano pago|Sem atendimento; sem regras de origem|Tudo: fila, interface, permissões|
|Custo [C4] [T3]|Community US$ 0 (sem Captain, papéis customizados nem SLA); Premium Support US$ 19/agente/mês (Captain, papéis e permissões); Enterprise US$ 99/agente/mês (SSO, SLA)|Self-host US$ 0; nuvem US$ 9 a 39/usuário/mês, cobrança anual|Horas da pessoa dedicada|
|Hospedagem|Rails, Sidekiq, Postgres, Redis; mínimo 2 vCPU e 4 GB [C2]|Postgres e Redis, a partir de 2 GB|A definir|
|Saída|Banco Postgres próprio, API|Banco Postgres próprio, API|Total|

Descartados: Krayin (WhatsApp por extensão paga e pouco documentada), EspoCRM (webhooks em lote, por padrão a cada 5 min), Evolution API (integra Baileys e a Cloud API oficial; na Cloud API seria intermediário a mais, e a manutenção caiu: última estável v2.3.7 em 2025-12, 2.4.0-rc em 2026-05), n8n (cola; Sustainable Use License, não é open source OSI). Na Meta, o webhook de cada número vai a um único callback (o padrão do app ou um override por WABA ou por número) [W3]: um destino por número. Por isso o Chatwoot recebe e repassa ao coletor pelo webhook `message_created`, que leva o `referral` em `content_attributes` [C5] (validar com um anúncio CTWA de teste; plano B: o coletor recebe e encaminha intacto). Custo de mensagem é da Meta em qualquer opção: cobrança por mensagem desde 2025-07-01 [W2] e de mensagens de serviço desde 2026-10-01, com 1.000 grátis por número por mês [W4].

**Recomendação:** adaptar o Chatwoot Community (self-host) para atendimento, com a IA pelo Agent Bot e código nosso; construir só o núcleo fino (coletor, identidade, origem, oportunidade, contratos com o ERP). Twenty fica como interface de CRM se a fina não bastar (integração por API e webhooks fica fora da AGPL pela exceção da própria licença; se mexermos no núcleo, vale a AGPL inteira). Permissão por unidade no Community: cada unidade com sua caixa de entrada (a confirmar no teste); se não bastar, o Premium custa US$ 19/agente/mês. Controle da Clinic: WABA na conta Meta dela, banco e regras de origem próprios, saída por API; trocar o Chatwoot não perde origem nem oportunidade.

<small>Fontes (consulta 2026-10-28): [C2] developers.chatwoot.com/self-hosted; [C3] chatwoot.com/hc/user-guide/articles/1756799850-how-to-setup-a-whats_app-channel-manual-flow; [C4] chatwoot.com/pricing/self-hosted-plans/; [T2] docs.twenty.com/developers/extend/api; [T4] docs.twenty.com/developers/extend/webhooks; [T3] twenty.com/pricing; [W2] developers.facebook.com/docs/whatsapp/pricing/; [W3] developers.facebook.com/docs/whatsapp/embedded-signup/webhooks/override; [W4] developers.facebook.com/docs/whatsapp/pricing/updates-to-pricing/; [C5] github.com/chatwoot/chatwoot: app/services/whatsapp/incoming_message_base_service.rb e app/models/message.rb (`webhook_data`)</small>

## 4. Cronograma

||2 semanas|30 dias|90 dias|
|---|---|---|---|
|Problema resolvido|Não se sabe o que existe nem quanto se perde|Falta prova de que um canal entrega origem confiável|CRM e atendimento próprios sem perder origem nem continuidade|
|Entrega observável|Inventário priorizado; baseline de 90 dias; convenção e gerador; 3 a 5 ativos pagos corrigidos; coletor em staging|Piloto de 14 dias; coletor em paralelo ao RD Station Marketing; CRM mínimo sem automação; QR de Campinas redirecionado; venda do ERP em homologação|3 a 4 canais validados; atendimento próprio num número novo da unidade piloto; `sale_confirmed` em produção; histórico classificado; painel canal → venda|
|Responsável|Eu; gestor de tráfego; fundador (acessos)|Eu; coordenação da unidade piloto; dev do ERP|Eu; coordenações; atendentes; fundador aprova cada ativação|
|Dependências|Acessos (perg. 1); exports (perg. 4)|Padrão aprovado; DPO; API do ERP (P1)|Checklist verde; contrato Ozia/Aktos (perg. 6); WABA na conta da Clinic|
|Esforço|~70 h (56 + 14 de observação)|~70 h (56 + 14)|~280 h (8 semanas)|
|Riscos|Acesso demora; conta presa em agência|Volume baixo alonga o piloto; ERP sem evento|Migração do número principal interrompe atendimento; `referral` CTWA sem chegar no teste real|
|Critério de conclusão|Ativos pagos 100% inventariados; baseline aceito pelo fundador|Checklist 2.2 verde no piloto, ou motivo documentado|30 dias estáveis no número piloto; ≥90% das vendas ligadas por ID|
|Métrica|% de ativos inventariados; % de leads sem origem|Cobertura de origem; divergência da conciliação|% de vendas com jornada; tempo de 1ª resposta; % desconhecida por unidade|
|Migração e recuo|Nada é desligado|RD Station Marketing e coletor recebem o mesmo formulário (comparação diária); recuo = reapontar link ou flag|Piloto num número novo, na WABA da Clinic; o principal fica na Ozia/Aktos e migra só após 30 dias estáveis. Recuo: reapontar `/q/` (botões e QR) para o número antigo, em minutos|

CRM e atendimento são preparados desde a semana 1, em staging, sem cliente. O CRM ganha uso comercial com o checklist 2.2 verde no piloto; o atendimento próprio atende cliente primeiro no número novo do piloto. A importação do RD Station Marketing e da Ozia/Aktos deduplica por telefone e e-mail; ambíguos vão a fila humana.

## 5. IA no atendimento e Grande Cérebro

**Por onde começar.** Pré-venda informativa (curso, turma, preço, vaga) em uma unidade e um produto: resposta verificável no ERP, risco baixo. Agendamento, dúvida de aluno e reclamação: humano.

**Fontes e ações.** Preço e vaga nunca ficam no prompt: ferramentas tipadas, só leitura, consultam o ERP (`get_turmas`, `get_vagas`, `get_preco`) e devolvem `as_of`; RAG só para conteúdo institucional versionado. Automático: informar, mandar link, coletar produto, unidade e "como conheceu", abrir oportunidade. Com aprovação: reserva, desconto, link de pagamento, reagendamento. Humano na hora: dúvida clínica, reclamação, reembolso, dados pessoais, baixa confiança, duas falhas seguidas, pedido explícito ou fora do escopo. A ferramenta filtra pelo `person_id` da conversa no servidor; dado de saúde não entra no contexto; chave de idempotência (conversa + intenção + turno) barra ação duplicada.

**Avaliação e provedores.** Antes de ligar, 100 a 200 conversas anonimizadas de referência (proposta). Resolução real: sem transferência nem retorno do assunto em 72 h; auditoria de 50 conversas por semana, custo por resolvida e grupo de controle humano, em matrículas no ERP. Produto de chat serve à equipe; API de modelo é o que o agente usa, com contrato de dados; plataforma de bot pronta acelera, mas prende prompt e histórico. Por isso, camada própria fina (ferramentas, prompts versionados, log), e novo provedor só após passar no conjunto de referência.

**"Por que Campinas vendeu menos nesta semana e o que devemos fazer?"** Ordem: (1) o rastreamento quebrou (`ep` de `cps` sem eventos, desconhecida em alta)? (2) turmas e vagas no ERP; (3) verba e leads de `cps-*`; (4) tempo de 1ª resposta; (5) conversão por etapa contra as 4 semanas anteriores. Preparo hoje: `unidade` obrigatória em campanha, `ep` e oportunidade; venda oficial do ERP, com data; métricas versionadas; desconhecida à parte; log de ações dos agentes. Limites: correlação não é causa; poucos casos dão "inconclusivo". O agente propõe (ex.: follow-up de leads parados), um humano aprova. Vendas, saldo, vagas, comissões e DRE seguem calculados no ERP e no financeiro; o agente só lê.

## 6. Demonstração

Fatia: entrada identificada → oportunidade → atendimento → venda confirmada pelo ERP. FastAPI, SQLite e pytest; WhatsApp, ERP e IA simulados. `uv run pytest -v` e `uv run python scripts/demo.py`; saída esperada e limitações no README.md. A URL do envio faz o papel dos campos ocultos; o `liberado` de `/quality/report` alimentaria a flag `channel_validated` (taxa de leads com problema, sem amostra mínima nem período).

|Cenário|Teste|
|---|---|
|C1. Origem de campanha preservada até a venda|`test_c1_origem_campanha_preservada_ate_venda`|
|C2. QR de unidade × WhatsApp direto sem origem|`test_c2_qr_unidade_distinto_de_whatsapp_direto`|
|C3. Pessoa existente volta por outra campanha|`test_c3_pessoa_existente_nova_campanha`|
|C4. O mesmo evento chega duas vezes|`test_c4_evento_duplicado_sem_efeito`|
|C5. Venda do ERP atualiza a oportunidade|`test_c5_venda_erp_atualiza_oportunidade`|
|Falha: LP paga perde UTM no encurtador (desconhecida, `parametros_perdidos`)|`test_falha_lp_sem_utm_detectada`|
