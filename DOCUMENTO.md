# Canal não é origem: rastreamento antes do CRM na Clinic Cursos

**Miguel Sanz Boragan**, case Product Builder/FDE, 2026-10-28. Demo e registro: repositório anexo (README.md, REGISTRO.md)

**Tese.** O WhatsApp diz por onde a pessoa falou, não por que ela veio. Cada real vendido no ERP prova por onde entrou ou aparece como receita sem origem. Todo lead entra no CRM desde o piloto; automação, CAC e comissão só usam o que o canal provou num checklist medido. Adapto o Chatwoot (código aberto, WhatsApp oficial) e construo só o núcleo: pessoa, origem, oportunidade e elo com a venda do ERP.

**Para os fundadores.**

- **O número que acompanho:** R$ de vendas confirmadas no ERP sem origem observada, por unidade e semana. O projeto dá certo quando ele cai, não quando o CRM liga. O CAC de cada canal sai como faixa (piso com todas as vendas sem origem, teto só com as observadas), que o rastreamento estreita.
- **Ordem de grandeza (hipótese):** R$ 50 mil/mês de mídia com 30% dos leads sem origem são R$ 15 mil/mês decididos no escuro. O baseline da semana 2 troca a hipótese pelo número real.
- **Prazos:** semana 2, baseline e 3 a 5 ativos pagos corrigidos; dia 30, um canal pago com origem provada até a venda; dia 90, painel canal → venda por unidade, verba cruzada com vagas e atendimento próprio num número novo.
- **Equipe:** nada muda por 2 semanas; depois, a recepção marca "como conheceu" em 1 clique e a vendedora vê curso e campanha antes de responder. Nada é desligado sem 30 dias estáveis e assinatura sua.
- **Custo (hipótese):** servidor de R$ 200 a 400/mês; Chatwoot Community R$ 0; mensagens da Meta como hoje. **No dia 1 preciso de:** admin de GTM, Google Ads, Meta, RD Station Marketing e Business Manager; exports de leads e vendas de 90 dias.

## 1. Perguntas e premissas

|#|Pergunta|Com quem / evidência|Decisão que depende|
|---|---|---|---|
|1|Que contas e integrações existem (GTM, GA4, Google Ads, Meta, RD Station Marketing, Hotmart, domínio) e quem é admin?|Fundador; usuários de cada conta|Escopo da semana 1; risco de conta presa em agência|
|2|Quem cria links, LPs, QR e impressos? Existe convenção?|Marketing, agência, tráfego, recepções; amostra de links e QR|Quem executa cada correção|
|3|Qual a jornada real até a venda, por unidade e produto, incluindo paciente modelo?|Acompanhar 1 turno de atendimento por unidade|Onde a origem se perde; qual fluxo vira piloto|
|4|Leads e vendas por canal e unidade em 90 dias: quanto divergem RD Station Marketing, Ozia/Aktos, ERP, Hotmart e Ads?|Exports dos cinco sistemas, mesmo período|Baseline e receita sem origem; ordem de correção|
|5|Como a venda chega ao ERP (balcão, Hotmart, paciente modelo) e com que ID? Ele guarda o `crm_opportunity_id`?|Dev do ERP; 1 venda de teste em homologação|Venda ligada por ID ou por regra|
|6|Os números estão na Cloud API via fornecedor, no app Business ou em conexão não oficial? A conta (WABA) é da Clinic? A Ozia/Aktos repassa o `referral` dos anúncios? O que diz o contrato?|Business Manager; painel e contrato Ozia/Aktos|Migrar a conta, abrir número novo ou recomeçar; como recuar|
|7|Que consentimento coletamos, quem responde pela LGPD e onde aparece dado de saúde?|Jurídico ou encarregado de dados; formulários|O que pode ir a Meta, Google e GA4|
|8|Que números os fundadores precisam sustentar (venda por campanha, CAC por unidade, ocupação de turma) e com que frequência?|Fundadores; relatórios atuais|O que entra primeiro no painel|

**Premissas** (até a resposta da pergunta entre parênteses). **P1** (5): o ERP expõe venda confirmada com ID, por webhook ou export (só export: atraso de D+1). **P2** (4): os limites deste documento são números de partida; recalibro uma vez, com o baseline, e registro o motivo. **P3** (6): ao menos um número oficial segue na Ozia/Aktos durante a transição. **P4**: o RD Station Marketing fica ativo ao menos 30 dias após o núcleo entrar em paralelo. **P5** (2): existe gestor de tráfego. **P6**: histórico anterior ao padrão nunca vira origem observada. **P7**: uma pessoa dedicada (eu), 35 h por semana, 7 delas observando a operação.

## 2. Rastreamento em quatro passos

**1. Inventário e auditoria.** A lista sai de: URLs finais do Google Ads e do Gerenciador de Anúncios, sitemap e crawler do site e do blog, LPs e formulários do RD Station Marketing, checkouts da Hotmart, números no Business Manager, bios e descrições do YouTube, fotos dos impressos das três unidades. Cada item ganha ponto de entrada (`ep`), dono, volume e verba. Tag duplicada: export do GTM e código da página (dois `page_view` por carga). Evento ausente: formulário de teste conferido no GA4 e no Events Manager. Redirecionamento que perde origem: `curl -IL` em cada URL de anúncio, bio, encurtador e checkout. Entrada sem identificação: % sem origem por formulário, wa.me sem texto, QR sem parâmetro. Orgânico: links próprios (bio, vídeo, blog → LP) ganham UTM `organic_social`; busca orgânica só aparece pelo referrer, como canal sem campanha, e o relatório diz isso. Corrijo primeiro o que tem verba, volume e correção barata.

**2. Padrão e correção.** Convenção mínima, a mesma da demo:

|Campo|Regra (exemplo)|
|---|---|
|Unidade|`sp`, `rj`, `cps`, `online`|
|`utm_source`|lista fechada: `google`, `fb`, `ig`, `msg`, `an` (valores do parâmetro dinâmico da Meta), `youtube`, `rd_email`, `hotmart`, `offline`, `indicacao`|
|`utm_medium`|lista fechada: `cpc`, `paid_social`, `organic_social`, `organic`, `email`, `qr`, `wa_link`, `referral`|
|`utm_campaign`|`{unidade}-{produto}-{objetivo}`, objetivo `captacao`, `paciente` ou `marca` (`sp-micropigmentacao-captacao`). Sem data: recriar campanha todo mês reinicia o aprendizado da plataforma|
|`utm_id`, `utm_content`|parâmetros dinâmicos (id da campanha e do anúncio). Custo junta por `utm_id`, nunca por nome|
|Ponto de entrada `ep`|`{tipo}-{unidade}-{local}-{nn}`, com dono, destino, `exige_parametros` e `sensivel` (`qr-cps-recepcao-01`)|

Sem UTM, o canal sai da evidência: `qr_code` (`[ep]`), `meta_ctwa` (`referral`), `google` (`gclid`, `gbraid`, `wbraid`), `meta` (`fbclid`, sem prova de anúncio). Valor fora da lista abre `utm_fora_do_padrao` e não conta como cobertura. QR e botões de WhatsApp passam pelo redirecionador próprio `/q/<ep>`, e o destino muda sem reimprimir. O QR impresso leva `[<ep>]` no texto do wa.me. O botão da LP vai além: o `/q/` grava o clique com UTMs e click ids e põe no texto um protocolo curto ("Quero informações, protocolo K7Q2M") ligado à sessão; a demo implementa só o `[ep]`. Sem código nem protocolo, a origem é desconhecida. Executam: tráfego (anúncios), marketing ou agência (LPs, bio, vídeos), eu (GTM, campos ocultos, `/q/`), coordenações e gráfica (impressos). Nenhuma campanha sobe sem link do gerador, que rejeita valor fora da lista.

**3. Preservação da jornada.** Na LP, um script guarda UTMs e click ids em cookie primário e preenche campos ocultos (na demo, a URL do envio faz esse papel); o `gclid` precisa chegar à LP final, e a importação offline aceita até 90 dias do clique [G1]. Cada contato grava um toque novo, sem editar os antigos; primeiro e último toque saem dessa lista. Ninguém é identificado por impressão digital do navegador.

- Múltiplos contatos: formulário e WhatsApp com o mesmo telefone são uma pessoa com dois toques. Troca de dispositivo: o vínculo só acontece quando a pessoa informa o mesmo telefone ou e-mail.
- Retorno direto: novo toque desconhecido, sem herdar a origem anterior. Mais de um produto: uma pessoa, N oportunidades (produto + unidade).
- Anúncio que abre conversa no WhatsApp (CTWA): o webhook traz `referral` com `source_id` e `ctwa_clid`, exceto em anúncio de Status [W1].
- Venda: o CRM envia o `crm_opportunity_id` ao ERP na matrícula, e a venda volta com ele. Na Hotmart, o link de checkout leva `sck` com o `ep`, que volta em `data.purchase.origin.sck` [H1].

**4. Validação e manutenção.** Leads sintéticos semanais por ponto de entrada (`is_test`) vão até o CRM e, em homologação, ao ERP. Conciliação diária registro a registro. Alertas: desconhecida acima do limite, quarentena acumulando, `ep` não cadastrado, volume zerado. Revisão semanal no piloto, depois mensal. Privacidade: nenhum dado pessoal em URL, UTM, pixel ou GA4 [GA1]. Do WhatsApp, o núcleo grava só `wamid`, telefone, hora, `referral` e `ep`; o texto é descartado. Payload de formulário expira em 30 dias. Meta e Google só recebem com consentimento por finalidade.

**Paciente modelo é outro funil e é dado sensível.** Campanha `objetivo=paciente`, fora do CAC de curso; a métrica é cadeira de modelo preenchida 72 h antes da aula. Ponto de entrada e produto levam `sensivel`: página sem Pixel nem tag de anúncio, e nenhum evento sensível vai a Meta ou Google, com ou sem consentimento (leitura conservadora da LGPD, art. 11, §4).

**Tipos de origem.** Canal de contato não é origem.

|Tipo|Quando|Exemplo|Uso permitido|
|---|---|---|---|
|Observada|Evidência técnica: UTM válida, click id, `referral`, `[ep]` ou protocolo|`gclid` na LP|Atribuição, automação, CAC|
|Declarada|Resposta a "como conheceu" (lista fechada), com `recorded_by`|"indicação de aluna", na recepção|Relatório próprio; não substitui a observada|
|Inferida|Regra explícita, com método e confiança gravados|primeiro contato 1 h após um post|Só análise; não vira observada nem dispara automação ou comissão|
|Desconhecida|Sem evidência|WhatsApp de número salvo|Linha própria no relatório; não é rateada entre canais|

**Histórico irrecuperável.** Contatos do RD Station Marketing, da Ozia/Aktos e de planilhas entram com `source_system` e `import_batch`, tipo desconhecida (ou declarada, se o "como conheceu" existia), nunca observada; o webhook do RD só traz `funnel.origin` e `cf_*` [R1], então o histórico sai do export. Antes da data de corte, indicadores saem "não comparável".

### 2.1 Matriz de correção: quatro pontos de entrada

|Ativo/canal|Problema hipotético|Correção|Responsável|Evidência de validação|
|---|---|---|---|---|
|LP de Google Ads, SP (`lp-sp-micro-01`)|Encurtador descarta UTM e `gclid`; GA4 instalado duas vezes conta lead em dobro|URL final direta; remover a tag duplicada; campos ocultos|Gestor de tráfego (URL); eu (GTM e campos)|`curl -IL` com UTM e `gclid` no destino; 20 leads sintéticos observados; 1 evento por envio no DebugView|
|Botão de WhatsApp do site e bio (`wa-sp-site-01`)|wa.me direto: todo lead vira só "WhatsApp" e o `gclid` da visita se perde|Botão via `/q/wa-sp-site-01`, com protocolo no texto; sem protocolo, o atendimento pergunta "como conheceu"|Eu (`/q/`); marketing (bio)|10 conversas de teste com protocolo resolvido até o `gclid`; % sem protocolo reportada|
|QR da recepção de Campinas (`qr-cps-recepcao-01`)|QR impresso aponta para a home, sem unidade nem campanha|Reimprimir uma vez para `/q/qr-cps-recepcao-01`; depois, troca sem reimpressão|Eu (rota); coordenação de Campinas e gráfica|Toda leitura gera registro; contatos `qr` ≤ leituras; taxa leitura → contato|
|Balcão, telefone e indicação (3 unidades)|"Como conheceu" com "Instagram" pré-selecionado infla o canal|Obrigatório, sem padrão, lista fechada; indicação grava `ind-{id}`|Eu (CRM); coordenação (treino da recepção)|Auditoria de 30 registros: 0 com valor padrão; ≥90% preenchidos|

### 2.2 Checklist de liberação do primeiro fluxo do CRM

O checklist não trava o atendimento: todo lead entra no CRM desde o piloto. Trava só o que causa dano com origem errada: automação ao cliente, CAC/ROI e comissão. Vale por ponto de entrada (P2).

|Critério|Limite|Amostra / período|Por quê|
|---|---|---|---|
|Cobertura de origem: só observada em ponto pago (`exige_parametros`); observada ou declarada em balcão e telefone|Libera com 0 sem origem em 30, ≤1 em 50, ≤2 em 75, ≤4 em 100|Até 28 dias|Cobertura real ≥90% com 95% de confiança em qualquer volume (Clopper-Pearson). Declarada esconderia UTM perdida|
|Bloqueio antecipado|Abaixo de 30 leads: >5% sem origem bloqueia; senão, `amostra_insuficiente`|Contínuo|Reprovar exige menos evidência que aprovar|
|Inferida ou valor padrão gravado como observada|0|Auditoria de 30 registros|Erro de regra: 1 caso pede correção|
|Formulário → CRM|0 envio sem recibo; cada falta explicada|100% dos envios, 7 dias|Uma contagem esconderia 1 perdido + 1 duplicado|
|Razão CRM ÷ plataforma de anúncio|±15% da razão do baseline|2 semanas|A razão não é 1; o que não pode é mudar|
|Duplicidade|0 efeito duplicado em 50 reenvios; 0 pessoa duplicada em 20 retornos com telefone em outro formato|Teste dirigido|Automação duplicada manda 2 mensagens ao cliente|
|Ponta a ponta|20/20 leads sintéticos corretos|3 navegadores, início e fim|1 falha em 20 já é 5%|
|Quarentena|<2% dos eventos, nenhum parado >48 h|14 dias|2% de 100 leads = 2 casos, revisáveis à mão|
|"Como conheceu" sem origem observada|≥90% preenchido|14 dias|Única fonte em balcão e telefone|
|Recuo e aprovação|Flag desligada em <15 min; assinatura do fundador e da coordenação|1 ensaio; reunião de 30 min|O RD Station Marketing segue recebendo (P4); quem paga a mídia e quem atende assinam|

Expansão para indicadores de venda: ≥90% das vendas do ERP ligadas a oportunidade por ID.

## 3. CRM e atendimento: arquitetura

```
 Meta (WhatsApp) -> Chatwoot: atendimento e tela do vendedor (recebe o webhook da Meta)
                         | message_created + leitura pela API a cada 15 min, chave wamid
                         v                         ^ origem, oportunidade e status no contato
 LP, /q/, Hotmart, RD -> Núcleo: recibo, identidade, origem, oportunidade, outbox (1 Postgres)
                         | crm_opportunity_id      ^ sale_confirmed        | conversões
                         v                         |                       v
                         ERP: venda, pagamento, turma, vagas               Google Ads, Meta
```

|Informação|Dono (escreve)|Quem lê|
|---|---|---|
|Venda, pagamento, turma, vagas, preço, comissão|ERP|Todos, só leitura (cópia com data)|
|Pessoa, oportunidade, toques, consentimento|Núcleo|Chatwoot (atributos do contato), BI, agentes; o ERP recebe o `crm_opportunity_id`|
|Conversa, fila, etiqueta de estágio|Chatwoot|Núcleo aplica o estágio; o texto não sai do Chatwoot|
|Evento bruto e investimento|Núcleo (recibo); Google Ads e Meta (custo)|Auditoria, agente de tráfego, BI (custo junta por `utm_id`)|
|Prontuário do paciente modelo|Sistema clínico ou ERP|Nunca núcleo nem marketing; conversa sensível com acesso restrito no Chatwoot|

**Identidade.** Uma pessoa entre canais e unidades, por identificador verificado, nunca por nome; ambíguo vai a fila humana, e a fusão (`merged_into`) pode ser desfeita. Aluna, paciente e lead são papéis; cada interesse, uma oportunidade.

**Dois sentidos.** O Chatwoot é a tela do atendente e do vendedor. O núcleo grava no contato origem, oportunidade e status do ERP; o vendedor muda o estágio por etiqueta, que volta pelo webhook e só o núcleo aplica. Cada campo tem um escritor e o núcleo só grava se o valor mudou: o eco morre aqui. A Meta entrega cada número a um único destino [W3], o Chatwoot. O núcleo recebe o `message_created` e, como segunda via, lê as mensagens pela API do Chatwoot a cada 15 min, as duas pelo mesmo recibo (chave `wamid`). Nada duplica, nada some se o núcleo cair, e o atendimento nunca depende do meu código.

**Venda.** O ERP publica `sale_confirmed` com `erp_sale_id` e `crm_opportunity_id`; a oportunidade vira ganha, ligada à jornada. Venda sem id, com id inexistente ou produto ou unidade diferente vai à quarentena sem efeito; o reenvio corrigido é reprocessado.

**Repetição, atraso e falha.** Todo evento ganha um recibo (fonte + id) gravado junto com o efeito: repetido, não faz nada; com conteúdo diferente, vai para revisão sem apagar o primeiro. O que sai para ERP, Chatwoot e plataformas entra numa fila com nova tentativa (outbox); sem resposta, fica `incerto` e confiro antes de reenviar. Já usei esse padrão em produção num gateway de WhatsApp. Permissão por papel e unidade é checada no servidor, e todo acesso fica em log.

**Volta às plataformas.** Venda ligada a click id vira conversão na outbox (`platform_conversion`, `event_id` = `erp_sale_id`) para o Google ou a Meta; produto sensível vira `bloqueado_sensivel` e nunca sai.

**A verba segue a vaga.** Relatório diário por turma: vagas do ERP × oportunidades abertas × dias até o início. Pipeline acima de 3× as vagas: proponho cortar a verba de `{unidade}-{produto}`; abaixo de 1× com início em até 21 dias: proponho reforçar. Um humano aprova. É a primeira tarefa do agente de tráfego.

### 3.1 Paralelismo com uma pessoa

Decisões da semana 1, nesta ordem: WABA na conta da Clinic (sem ela nada migra); contrato de venda com o dev do ERP; convenção aprovada pelo fundador; Chatwoot hospedado por nós.

|Durante a auditoria (sem. 1 e 2: ~56 h de construção + ~14 h de observação)|Depende do padrão aprovado (sem. 3 e 4: ~56 h + ~14 h)|Só após validação do canal (dia 30 em diante)|
|---|---|---|
|Esquema e contrato v1; núcleo em staging; `/q/`; gerador de links; Chatwoot e API do ERP em teste|Campos ocultos nas LPs; cadastro de pontos de entrada; regras de origem; mapa de produto e unidade|Automações e reativação; IA respondendo cliente; origem em CAC/ROI; comissão|

Corte: se os acessos (perg. 1) atrasarem, o núcleo em staging passa para o bloco de 30 dias; inventário e baseline não encolhem. A flag `channel_validated` por ponto de entrada liga automação e CAC; cai com 5 leads seguidos sem origem ou 7 sem origem nos últimos 50 (alarme falso perto de 1% com cobertura de 95%; pega 9 em 10 quedas para 80%). Piloto: 1 ou 2 canais pagos de uma unidade; expansão canal a canal. Especialistas: gestor de tráfego (sem. 1 a 3); jurídico ou encarregado de dados (sem. 1 a 2, antes de enviar conversões); dev do ERP (sem. 2 a 4); gráfica (sob demanda).

### 3.2 Construir, adaptar ou contratar

|Consulta 2026-10-28|Chatwoot (atendimento)|Twenty (CRM)|Do zero|
|---|---|---|---|
|Fonte|github.com/chatwoot/chatwoot|github.com/twentyhq/twenty|n/a|
|Licença|MIT no núcleo; pasta `enterprise/` com licença própria paga|AGPL-3.0; arquivos `@license Enterprise` sob licença comercial|Própria|
|Manutenção|Release v4.19.1 em 2026-10-24|Release v2.52.0 em 2026-10-27|Só eu|
|Adequação|Caixa de entrada, filas, Agent Bot para IA, API, webhooks|Objetos customizáveis, API REST e GraphQL, webhooks [T2]|Atende exatamente ao processo, mas custa meses de uma pessoa|
|WhatsApp oficial|Canal WhatsApp Cloud nativo [C3]|Não tem|Cloud API e tela próprias|
|Lacunas|`referral` em `content_attributes` (visto no código [C5]; testar com anúncio); papéis customizados só no pago|Sem atendimento; sem regras de origem|Tudo: fila, interface, permissões|
|Custo [C4] [T3]|Community US$ 0 (sem Captain, papéis customizados nem SLA); Premium Support US$ 19/agente/mês|Self-host US$ 0; nuvem US$ 9 a 39/usuário/mês|Horas da pessoa dedicada|
|Hospedagem e saída|Rails, Sidekiq, Postgres, Redis; mínimo 2 vCPU e 4 GB [C2]; banco próprio e API|Postgres e Redis; banco próprio e API|Total|

**Recomendação: adaptar, não construir.** Nos 90 dias, o Chatwoot Community, hospedado por nós, é a tela do atendente e do vendedor, com a IA pelo Agent Bot. Código nosso só no núcleo (livro-razão de eventos, identidade, origem, oportunidade) e no contrato com o ERP. Twenty, só após o dia 90 e só como tela, se o comercial pedir funil visual. A Clinic controla WABA, banco e regras de origem; trocar o Chatwoot não perde origem nem oportunidade. Descartados: Krayin, EspoCRM, Evolution API, n8n (motivos no REGISTRO.md).

<small>Fontes (consulta 2026-10-28): [C2] developers.chatwoot.com/self-hosted; [C3] chatwoot.com/hc/user-guide/articles/1756799850-how-to-setup-a-whats_app-channel-manual-flow; [C4] chatwoot.com/pricing/self-hosted-plans/; [C5] código do Chatwoot (incoming_message_base_service.rb); [T2] docs.twenty.com/developers/extend/api; [T3] twenty.com/pricing; [W3] developers.facebook.com/docs/whatsapp/embedded-signup/webhooks/override. Demais fontes ([G1], [W1], [H1], [GA1], [R1]) no REGISTRO.md.</small>

## 4. Cronograma

||2 semanas|30 dias|90 dias|
|---|---|---|---|
|Problema resolvido|Não se sabe o que existe nem quanto se perde|Falta prova de que um canal entrega origem|CRM e atendimento próprios sem perder origem nem continuidade|
|Entrega observável|Inventário priorizado; baseline com receita sem origem em R$; convenção e gerador; 3 a 5 ativos pagos corrigidos; núcleo em staging|Piloto; núcleo em paralelo ao RD Station Marketing; CRM com todo lead, sem automação; QR de Campinas no `/q/`; venda do ERP em homologação|3 a 4 canais validados; atendimento próprio num número novo; `sale_confirmed` em produção; conversões voltando às plataformas; relatório verba × vaga|
|Responsável|Eu; gestor de tráfego; fundador (acessos)|Eu; coordenação da unidade piloto; dev do ERP|Eu; coordenações; atendentes; fundador aprova cada ativação|
|Dependências|Acessos (perg. 1); exports (perg. 4); verificação da empresa na Meta|Padrão aprovado; encarregado de dados; API do ERP (P1)|Checklist verde; contrato Ozia/Aktos; WABA da Clinic; 3 templates aprovados|
|Esforço|~70 h (56 + 14 de observação)|~70 h (56 + 14)|~280 h (8 semanas)|
|Riscos|Acesso demora; conta presa em agência|Piloto em `amostra_insuficiente`; ERP sem evento|Migração do número principal; `referral` não chega no teste real|
|Critério de conclusão|Ativos pagos 100% inventariados; baseline aceito pelo fundador|Checklist 2.2 verde no piloto, ou motivo documentado|30 dias estáveis no número piloto; ≥90% das vendas ligadas por ID|
|Métrica|% da verba inventariada; receita sem origem em R$|Cobertura do piloto; envios sem recibo = 0|Receita sem origem caindo; faixa de CAC mais estreita; verba em turma lotada = R$ 0|
|Migração e recuo|Nada é desligado|RD Station Marketing e núcleo recebem o mesmo formulário, comparados registro a registro; recuo = reapontar link ou flag|Piloto num número novo, na WABA da Clinic; o principal fica na Ozia/Aktos e migra só após 30 dias estáveis. Recuo: reapontar `/q/` para o número antigo, em minutos|

CRM e atendimento são preparados desde a semana 1; automação, CAC e comissão ligam com o checklist verde, e o atendimento próprio começa no número novo. A importação do RD Station Marketing e da Ozia/Aktos deduplica por telefone e e-mail.

## 5. IA no atendimento e Grande Cérebro

**Fase 0: copiloto, sem falar com o cliente.** No piloto, a IA deixa como nota privada no Chatwoot o rascunho da resposta e a sugestão de produto, unidade e "como conheceu"; o atendente edita e envia. A origem sugerida grava como declarada. Isso gera de graça as conversas de referência; uma intenção só vira automática com ≥90% de rascunhos enviados sem edição em 100 conversas.

**Degraus.** (1) Triagem fora do horário, onde a alternativa é o silêncio; (2) agendamento de paciente modelo, com vaga lida da aula no ERP e confirmação humana; (3) dúvidas de aluno, com busca em conteúdo versionado. Cada degrau sobe após 4 semanas com resolução real ≥70% e zero incidente de dado; reclamação, financeiro e dúvida clínica seguem humanos.

**Fontes e regras.** Preço e vaga só em frase fixa preenchida pela ferramenta do ERP (`get_turmas`, `get_vagas`, `get_preco`, com data), nunca em texto livre: preço informado obriga a empresa (CDC, art. 30). Reserva, desconto e link de pagamento pedem aprovação humana. Humano na hora: dúvida clínica, reclamação, reembolso, dados pessoais, baixa confiança ou fora do escopo. A ferramenta filtra pelo `person_id` da conversa no servidor; conversa clínica sai do bot no 1º turno; chave conversa + intenção + turno barra ação duplicada. Fora da janela de 24 h só sai template: aprovo três antes do piloto (retomada, confirmação de agendamento, lembrete de aula).

**Avaliação e provedores.** Pré-venda se mede em matrícula no ERP contra grupo de controle sorteado; resolução real é não haver transferência nem retorno em 72 h; auditoria de 50 conversas por semana; custo por conversa resolvida. Produto de chat é da equipe; API de modelo é o que o agente usa, com contrato sem treino nem retenção; plataforma de bot pronta prende prompt e histórico. Camada própria fina (ferramentas, prompts versionados, log); provedor novo só entra se passar nas conversas de referência.

**"Por que Campinas vendeu menos nesta semana e o que devemos fazer?"** (1) O rastreamento quebrou (`ep` de `cps` sem eventos, desconhecida em alta)? Então não há decisão comercial. (2) Faltou vaga ou lead? Turmas do ERP × leads e verba de `cps-*`. (3) Faltou fechar? 1ª resposta e conversão por etapa contra 4 semanas. Ações: mover verba de turma lotada para turma com vaga; follow-up de leads parados, metade como controle. Preparo hoje: `unidade` obrigatória em campanha, `ep` e oportunidade; métricas versionadas; desconhecida à parte; log de ações; poucas vendas dão "inconclusivo". O agente propõe e um humano aprova; vendas, saldo, vagas, comissões e DRE seguem no ERP e no financeiro.

## 6. Demonstração

Entrada identificada → oportunidade → atendimento → venda do ERP, com WhatsApp, ERP e IA simulados: `uv run pytest -v` e `uv run python scripts/demo.py` (saída e limitações no README.md). Os testes conferem: C1, a venda volta com a origem observada; C2, QR de Campinas observado e WhatsApp direto desconhecido; C3, mesma pessoa, 2ª oportunidade, 1º toque intacto; C4, reenvio sem efeito; C5, oportunidade ganha, venda repetida sem efeito; falha: LP paga sem UTM fica desconhecida, abre `parametros_perdidos` e bloqueia o ponto sem perder o lead (`test_c1_` a `test_c5_`, `test_falha_lp_sem_utm_detectada`). **Evidência simulada:** `lp-sp-micro-01` `bloqueado` (2 leads, 1 com problema); `qr-cps-recepcao-01` e `site-online-contato-01` em `amostra_insuficiente`; `receita_sem_origem_cents` = 349000 (R$ 3.490 sem 1º toque observado); a venda da C1 (origem `ig`) vira conversão Meta com `event_id` `ERP-2026-5001`.
