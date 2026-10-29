# Canal não é origem: rastreamento antes do CRM na Clinic Cursos

**Miguel Sanz Boragan**, case Product Builder/FDE, 2026-10-28. Anexos: README.md (demo), REGISTRO.md, FONTES.md

**Tese.** O WhatsApp diz por onde a pessoa falou, não por que veio. Todo lead entra no CRM, mas só ponto aprovado num checklist alimenta automação para o cliente e custo por canal.

**Para os fundadores.**

- **O problema:** no exemplo simulado, 18 de 61 vendas do mês (R$ 32 mil) não têm lead no RD: a verba é decidida sem saber de onde elas vieram.
- **Em 2, 30 e 90 dias:** o mapa do que gera lead, a perda em R$ e os anúncios caros corrigidos; um canal pago provado; atendimento próprio no WhatsApp oficial.
- **Para a equipe:** só as 2 vendedoras do piloto vão ao Chatwoot, na semana 5; as demais seguem na Ozia/Aktos até o dia 90. Mudam o link, o QR e o "como conheceu".
- **Onde entra dinheiro (hipótese):** R$ 3.560/mês de verba hoje sem resultado medido; medida, a que não vende ou enche turma lotada vai para turma com vaga. Reativar alunas é receita sem mídia (dia 45); no dia 90 sai a mensalidade da Ozia/Aktos.
- **No dia 1:** acesso de administrador às contas, planilhas de 90 dias de leads e vendas e uma hora com o mantenedor do ERP.

## 1. Perguntas e premissas

|#|Pergunta|Com quem / evidência|Decisão que depende|
|---|---|---|---|
|1|Quem administra cada conta, e quando vencem RD e Ozia/Aktos?|Fundador; contratos|Escopo da semana 1; saída sem multa|
|2|Quem cria links, páginas, QR e impressos?|Marketing, agência, recepções|Quem executa cada correção|
|3|Como um lead vira matrícula em cada unidade?|Um turno de observação por unidade|Onde a origem se perde; qual fluxo vira piloto|
|4|Quanto divergem leads e vendas entre as ferramentas e o ERP?|Planilhas de 90 dias|Linha de base; ordem de correção|
|5|Como a venda chega ao ERP, e com que id?|Mantenedor do ERP; venda de teste|Venda ligada por id ou por regra|
|6|O WhatsApp usa a API oficial em conta da Clinic?|Conta comercial da Meta|Migrar o número ou abrir um novo|
|7|Que consentimento os formulários coletam?|Encarregado de dados|O que vai às plataformas e quem reativar|
|8|Onde está o histórico de pacientes modelo?|Coordenação clínica; ERP|Que id une aluna e paciente|

**Premissas** (entre parênteses, a pergunta que confirma). P1 (perg. 5): o ERP entrega vendas confirmadas e canceladas com id. P2: só a tabela de liberação (30, 50, 75 e 100 leads) é calculada; os demais limites são valores iniciais, calibrados no piloto. P3 (perg. 6): um número segue na Ozia/Aktos na transição. P4 (perg. 2): há gestor de tráfego. P5 (perg. 7): o consentimento antigo é desconhecido. P6: só eu, 35 h por semana, 20% de reserva. P7 (perg. 8): dado clínico fica fora do núcleo. P8 (perg. 5): o mantenedor do ERP tem horas nas semanas 2 a 4.

## 2. Rastreamento em quatro passos

**1. Inventário e auditoria.** Começo pelo que tem verba. Fontes: URLs finais exportadas do Google Ads e da Meta, formulários instantâneos da Meta, páginas de destino do GA4 (90 dias, blog incluído), contêiner do GTM exportado, formulários e integrações do RD, links da Hotmart, Perfil da Empresa no Google, bio, YouTube, números de WhatsApp e foto de cada QR. Tudo numa planilha com ativo, destino, dono, verba, tags e status. Um rastreador do site lista, por página, os ids de GTM, GA4, Google Ads e Pixel; o Tag Assistant, o Pixel Helper e o "Testar eventos" da Meta mostram o que dispara de fato. **Conversão contada em dobro:** Google Ads e GA4 importado, ambos primários; `form_submit` junto do `generate_lead`; Pixel posto pelo RD e pelo GTM; Hotmart junto da CAPI. Fica uma primária por etapa, com o mesmo `event_id` no Pixel e na CAPI. **Evento ausente:** formulário sem `generate_lead` no DebugView, ou conversão zerada com leads no RD. Redirecionamento que perde origem aparece com `curl -IL`.

**Evidência simulada:**

|Ativo|Verba/mês|Problema|Sem origem|Impacto/mês (ordem de correção)|
|---|---|---|---|---|
|Página da Meta, micropigmentação SP|R$ 6.000|Anúncio sem parâmetros; GA4 em dobro|38%|R$ 2.280 de verba sem elo com a venda (1º)|
|Anúncio que abre o WhatsApp, RJ|R$ 2.000|A Ozia/Aktos não repassa o id do anúncio|64%|R$ 1.280 de verba (2º)|
|Conciliação RD × ERP, 30 dias|n/a|18 de 61 vendas sem lead no RD|30%|R$ 32 mil de receita (18 × R$ 1,8 mil)|

**2. Padrão e correção.** A convenção é a da demo: `utm_source` e `utm_medium` de listas fechadas, `utm_campaign` como `{unidade}-{produto}-{objetivo}`, com sufixo livre opcional, `utm_id` com o id da campanha (é por ele que o custo se junta) e ponto de entrada como `qr-cps-recepcao-01`, com dono. Um gerador de links recusa valor fora da lista, e o núcleo confere o formato da campanha no formulário. QR e botão de WhatsApp passam pelo endereço curto `/q/<ponto>`, que grava a leitura, repassa só parâmetros de rastreio (nunca dado pessoal) e põe na mensagem um protocolo com a origem. Corrijo na ordem da perda: anúncios com o tráfego, páginas e tags comigo, QR com a coordenação.

**3. Preservação da jornada.** A origem que está na URL da página do envio vai ao CRM em campos ocultos, sem cookie. Se a pessoa troca de página ou volta direto antes de enviar, a UTM se perde: conta contra a cobertura, com pendência própria, e o remédio é guardar o clique entre páginas, com cookie e aceite (depois do piloto). Cada contato grava um toque novo, sem editar os antigos.

- **Vários contatos, outro dispositivo, outro produto:** o mesmo telefone (ou o BSUID de quem usa nome de usuário no WhatsApp) liga tudo à mesma pessoa; o e-mail, só sem telefone divergente; cada produto abre sua oportunidade.
- **Retorno direto:** vira toque desconhecido. Atribuo pelo primeiro toque observado: um "oi" sem origem antes do anúncio não rouba a origem.
- **Até a venda:** o anúncio que abre o WhatsApp manda o próprio id no campo `referral` [W1]; a Hotmart devolve no `sck` o id da oportunidade (até 30 caracteres, sem `_`) [H1]; o ERP devolve o id da oportunidade.
- **Volta às plataformas:** a venda vai por lead, com o clique dele: ao Google pela Data Manager API, até 90 dias do gclid [G1]; à Meta pela CAPI, com `fbc` no site e `ctwa_clid` no WhatsApp, até 7 dias depois da venda [M1]. A Meta otimiza pelo que ocorre até 7 dias após o clique e a matrícula vem depois, por isso também envio o lead qualificado (etiqueta; desenho).

**4. Validação e manutenção.** Toda semana, leads de teste (`?teste=1`) vão de cada ponto ao CRM e ao ERP de homologação, fora dos relatórios; com `teste=1`, o GTM não dispara Pixel nem conversão do Google Ads e a CAPI usa `test_event_code`. Concilio todo dia, por ponto: leads nas plataformas × recibos do núcleo × oportunidades, e vendas do ERP × oportunidades ganhas; diferença acima de ±15% abre pendência para o dono do ponto. Alertas: desconhecida acima do limite, quarentena, ponto não cadastrado, volume zerado e chegada baixa no `/q/` (na demo, só a chegada baixa e a pendência de ponto não cadastrado). Corrijo no mesmo dia; o tráfego, em 2 dias úteis. **Privacidade:** nome, e-mail e telefone nunca em URL, UTM, Pixel ou GA4 [GA1]; Pixel e tag do Google só com aceite de anúncios, e sem ele a venda não volta. No anúncio que abre o WhatsApp, o aceite vai como botão na primeira mensagem.

**Paciente modelo é outro funil e dado sensível.** Campanha e fila próprias (`agenda-cps` na demo), fora do custo de curso, medida por cadeira preenchida. A página não tem Pixel, e dado de saúde não vai a Meta ou Google (LGPD, art. 11).

**Observada, declarada, inferida.** O QR prova o ponto de entrada, não o motivo.

|Tipo|Quando|Uso|
|---|---|---|
|Observada|UTM completa, id do clique ou do anúncio, QR, protocolo; buscador e `fbclid` só como canal|Atribuição, automação, custo|
|Declarada|"Como conheceu", com quem registrou|Relatório; não vira observada|
|Inferida|Regra explícita, com método gravado|Só análise|
|Desconhecida|Sem evidência|Linha própria, sem rateio|

**Histórico irrecuperável.** A base antiga (RD, Ozia/Aktos, planilhas) entra deduplicada, com lote e consentimento desconhecido (P5), como desconhecida ou declarada; a origem que o RD gravou (meio e fonte, sem campanha) entra como inferida, só para linha de base.

### 2.1 Matriz: quatro pontos de entrada

|Ativo/canal|Problema hipotético|Correção|Responsável|Evidência de validação|
|---|---|---|---|---|
|Página paga de SP na Meta (`lp-sp-micro-01`)|Anúncio sem parâmetros; GA4 duplicado|Parâmetros dinâmicos; tag duplicada removida|Gestor de tráfego; eu (tags)|20 leads de teste com origem; 1 Lead por envio nas plataformas|
|Botão de WhatsApp do site (`wa-sp-site-01`)|Link direto: o clique pago se perde|Botão pelo `/q/`|Eu; marketing (bio)|10 conversas de teste ligadas à visita|
|Banner com QR na recepção de Campinas (`qr-cps-recepcao-01`)|QR aponta para a home, sem unidade nem campanha|Reimprimir uma vez para o `/q/`; depois, só o destino muda|Eu; coordenação e gráfica|10 leituras, 10 conversas com a origem|
|Balcão, telefone e indicação (3 unidades)|"Como conheceu" com "Instagram" pré-marcado|Campo obrigatório sem padrão, com "não perguntei"; indicação grava quem indicou|Eu; coordenação (treino)|30 registros auditados, 0 com valor padrão|

### 2.2 Checklist de liberação do primeiro fluxo

O lead entra no CRM e na fila desde o piloto, e a venda volta às plataformas por lead; o checklist libera, por ponto, o primeiro fluxo: boas-vindas automáticas e custo por canal. **Origem não paga comissão:** meta e comissão seguem o ERP, e a vendedora nada ganha escolhendo a origem.

|Critério|Limite|Amostra e período|Por quê|
|---|---|---|---|
|Cobertura (pago: só observada; balcão: também declarada)|Nenhum sem origem até 49 leads (mínimo de 30, em 7 dias ou mais); depois, 1 em 50, 2 em 75 e 4 em 100; volta a bloquear com 7 sem origem em 50 ou 5 seguidos|Todo lead; com fim de semana|Se 1 em 10 perdesse a origem, 30 seguidos certos aconteceriam só 4% das vezes. Custo: canal com 95% real passa só ~44% das vezes em 100 (anexo do README)|
|Conciliação|0 envio sem recibo; razão CRM ÷ plataforma a ±15% da medida na semana 1|7 dias; a razão, 2 semanas|O total esconde perda e duplicata|
|Chegada no `/q/`|60% das leituras viram conversa|20 leituras|Valor inicial: abaixo disso, o QR perde gente entre leitura e conversa; é alerta, porque robô também lê|
|Ponta a ponta|20 de 20 testes certos; 0 efeito duplicado em 50 reenvios|Apps da Meta, iPhone, Android|1 falha em 20 já é 5%|

**Prazo (hipótese):** com 20 leads por semana, um canal com 97% ou mais libera em 2 a 5 semanas; pontos de pouco volume são liberados juntos, por tipo e unidade. **Expansão:** outra unidade entra com 2 canais liberados há 30 dias, conciliação a ±15%, 0 envio sem recibo e 90% das vendas do piloto ligadas por id.

## 3. CRM e atendimento: arquitetura

<figure class="diagrama"><svg viewBox="0 0 760 222">
<defs><marker id="a" refX="6" refY="3" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0L6,3L0,6z" style="fill:#55626e;stroke:none"/></marker></defs>
<style>text{font-family:'IBM Plex Sans Condensed',sans-serif;font-size:12px;fill:#55626e;text-anchor:middle}.t{font-size:13.5px;font-weight:600;fill:#16212b}.w{fill:#fff}.b{fill:#fff;stroke:#8a979f;stroke-width:1.2}.n{fill:#0b5d6b}.m{fill:#f6f9fa;stroke:#8a979f;stroke-dasharray:5,4}.l path{fill:none;stroke:#55626e;stroke-width:1.3;marker-end:url(#a)}.l text{font-size:11.5px;fill:#0b5d6b}.s{text-anchor:start}.e{text-anchor:end}.d{stroke-dasharray:4,3}</style>
<path d="M10,6h170v46H10z" class="b"/><text x="95" y="25" class="t">WhatsApp oficial</text><text x="95" y="42">número da Clinic na Meta</text>
<path d="M295,6h170v46H295z" class="b"/><text x="380" y="25" class="t">Chatwoot</text><text x="380" y="42">conversa e fila da vendedora</text>
<path d="M10,98h170v54H10z" class="b"/><text x="95" y="119" class="t">Site e formulários</text><text x="95" y="138">QR, banners e botões</text>
<path d="M295,92h170v66H295z" class="n"/><text x="380" y="113" class="t w">Núcleo (CRM próprio)</text><text x="380" y="130" class="w">pessoa, toques,</text><text x="380" y="145" class="w">oportunidades, consentimento</text>
<path d="M580,98h170v54H580z" class="b"/><text x="665" y="119" class="t">ERP (fonte oficial)</text><text x="665" y="138">venda, pagamento, turma, vagas</text>
<path d="M580,178h170v38H580z" class="b"/><text x="665" y="194" class="t">Google Ads e Meta</text><text x="665" y="209">investimento e conversões</text>
<path d="M10,178h400v38H10z" class="m"/><text x="210" y="194" class="t">Na migração, ligados ao núcleo</text><text x="210" y="209">RD Station Marketing · Hotmart · Ozia/Aktos</text>
<g class="l"><path d="M180,29H293"/><text x="237" y="23">mensagens</text>
<path d="M180,125H293"/><text x="237" y="119">lead com origem</text>
<path d="M95,98V54"/><text x="101" y="80" class="s">/q/ com protocolo</text>
<path d="M350,52V90"/><text x="344" y="75" class="e">mensagem, etiqueta</text>
<path d="M410,92V54"/><text x="416" y="75" class="s">origem, oportunidade</text>
<path d="M465,113H578"/><text x="521" y="107">id da oportunidade</text>
<path d="M580,138H467"/><text x="521" y="151">venda confirmada</text>
<path d="M440,158V197H578"/><text x="507" y="191">conversão por lead</text>
<path d="M360,178V160" class="d"/></g>
</svg></figure>

|Informação|Dono (escreve)|Quem lê|
|---|---|---|
|Venda (inclusive Hotmart), pagamento, turma, vagas, preço, comissão|ERP|Todos, só leitura|
|Pessoa, oportunidade, toques, consentimento|Núcleo|Chatwoot, relatórios, agentes; ERP recebe o id|
|Conversa, fila, etiqueta de estágio|Chatwoot|O núcleo lê o estágio; o texto não sai dali|
|Investimento por campanha|Google Ads e Meta|Agente de tráfego, relatórios|
|Prontuário do paciente modelo|Sistema clínico ou ERP (perg. 8)|Nunca o núcleo nem o marketing|

**Núcleo próprio, não o Twenty.** As regras de origem seriam nossas nos dois casos. Hipótese: 80 a 120 h para levar o núcleo da demo a produção; no Twenty, as mesmas regras, ~20 h de modelagem e um sistema a mais. Risco: só eu conheço o núcleo. Repositório, banco e contas ficam no nome da Clinic, com o fundador como administrador; no dia 60, outra pessoa executa o runbook (subir, restaurar o backup, religar o webhook), e reavalio o Twenty como tela lendo a API do núcleo, se o comercial pedir funil visual.

**Identidade.** Reconheço a pessoa por telefone, BSUID, e-mail ou id do ERP, nunca por nome; caso ambíguo (telefone ou e-mail de família) vai a um humano. Aluna, paciente e lead são papéis; cada interesse é uma oportunidade.

**Dois sentidos.** O núcleo grava no Chatwoot origem, oportunidades e status do ERP, que a vendedora vê na lateral da conversa; o funil do gestor é o relatório do núcleo. A etiqueta volta por webhook com o id da oportunidade e muda o estágio; se o núcleo cair, o atendimento segue. Reativação, upsell e cross-sell saem de listas do núcleo (aluna formada, lead parado há 30 dias), só com aceite.

**Venda.** A vendedora não digita id: o botão "matricular" na lateral do Chatwoot abre o cadastro no ERP com o id da oportunidade no código externo (perg. 5). O núcleo lê do ERP, a cada 5 minutos, vendas confirmadas e canceladas (desenho; a demo recebe por webhook). No piloto, antes do Chatwoot, o aviso do lead traz o id, que a vendedora cola no ERP. Venda sem oportunidade ou divergente vai à quarentena até alguém religar (na demo, pelo reenvio do ERP): erro de integração, separado da receita sem origem.

**Repetição, atraso e falha.** Cada evento tem recibo (fonte e id), gravado com o efeito. Repetido não faz nada; com conteúdo diferente, vai para revisão. O atrasado entra pela hora do evento. As saídas usam fila com nova tentativa; com o núcleo fora do ar, o Chatwoot segue atendendo e, na volta, o núcleo busca pela API dele as mensagens que perdeu (o mesmo recibo, pelo id da mensagem); o RD segue com o formulário.

**Permissões e manutenção.** A vendedora vê a unidade dela; o fundador vê tudo e aprova liberações; toda escrita vai ao log. Backup diário, restauração testada por mês.

**A verba segue a vaga.** Oportunidades acima de 3 vezes as vagas da turma pedem corte de verba; abaixo de 1 vez, a 21 dias do início, reforço (valores iniciais). Um humano aprova.

### 3.1 Paralelismo com uma pessoa

Caminho crítico da semana 1: WhatsApp em conta da Clinic e contrato de venda com o ERP. Sem eles, o atendimento próprio atrasa e a medição usa planilha.

|Durante a auditoria (semanas 1 e 2)|Depende do padrão (semanas 3 e 4)|Só depois da validação (dia 30 em diante)|
|---|---|---|
|Esquema de dados; núcleo em teste; gerador; pontos do piloto|Demais pontos; `/q/` em produção; Chatwoot e consulta do ERP em teste|Automações; reativação só com aceite; IA respondendo cliente; custo por canal|

O piloto começa no dia 15, com 1 ou 2 canais pagos de uma unidade e 2 vendedoras voluntárias, na Ozia/Aktos até a semana 5 e depois no Chatwoot; canal não liberado fica fora dos indicadores e da automação. Antes do primeiro lead real, o núcleo ganha o mínimo de produção: Postgres com backup, HTTPS, webhook assinado e login (16 h, o primeiro risco de prazo). **Especialistas pontuais:** tráfego nas semanas 1 e 2 (contas de anúncio); encarregado de dados na semana 2, antes de enviar às plataformas; ERP nas semanas 2 a 4 (venda com id); gráfica na semana 3 (QR). **Se atrasar, corto:** envio às plataformas, verba × vaga, copiloto; nunca a medição nem o checklist.

### 3.2 Construir, adaptar ou contratar

|Consulta em 2026-10-28|Chatwoot (atendimento), github.com/chatwoot/chatwoot|Twenty (CRM), github.com/twentyhq/twenty|Do zero (CRM e atendimento)|
|---|---|---|---|
|Licença|MIT no núcleo; pasta `enterprise/` paga|AGPL-3.0; arquivos Enterprise comerciais|Própria|
|Manutenção|v4.19.1 em 2026-10-24|v2.52.0 em 2026-10-27|Só eu|
|Adequação|Caixa de entrada, filas, Agent Bot, API, webhooks|Objetos customizáveis, API, webhooks [T2]|Exata, mas custa meses|
|WhatsApp oficial|Canal nativo da API oficial [C3]|Não tem|API e tela próprias|
|Lacunas|Id do anúncio a testar com anúncio real [C5]; papéis customizados só no pago|Sem atendimento nem regras de origem|Fila, interface, permissões|
|Custo [C4] [T3]|Community US$ 0; suporte US$ 19 por agente/mês|Próprio US$ 0; nuvem US$ 9 a 39 por usuário/mês|Horas da pessoa dedicada|
|Hospedagem e saída|2 vCPU e 4 GB [C2]; Postgres nosso; conversas saem pela API; o número é da Clinic|Banco e API próprios|Total|
|Operar (hipótese)|~4 h/mês: atualizar e fazer backup|~2 h/mês|Todo bug é meu|

**Recomendação: construir só o núcleo fino (origem, identidade, oportunidade) e adaptar o Chatwoot no atendimento.** Contratar (RD Station CRM ou a Ozia/Aktos) poupa esforço no início, mas deixa origem, identidade e elo com o ERP no fornecedor; fica de plano B. O Chatwoot Community, hospedado por nós, é a tela de atendimento; a Clinic controla núcleo, banco, contas e regras. Custo (hipótese): servidor de R$ 200 a 400 por mês, mais WhatsApp e IA por uso [W2] [W4]. Se o id do anúncio falhar no teste, o webhook da Meta vai primeiro ao núcleo.


## 4. Cronograma

||2 semanas|30 dias|90 dias|
|---|---|---|---|
|Problema resolvido|Não se sabe o que existe nem quanto se perde|Falta prova de que um canal entrega origem|CRM e atendimento próprios sem perder origem|
|Entrega observável|Inventário priorizado; perda em R$; padrão e gerador; ativos pagos corrigidos|Piloto com canal provado; todo lead no CRM, sem automação; venda ligada em teste; histórico de pacientes achado (perg. 8)|3 a 4 canais liberados; atendimento próprio no número principal; vendas em produção; verba × vaga; pacientes só com id e papel; 1 reativação de alunas|
|Responsável|Eu; gestor de tráfego; fundador (acessos)|Eu; coordenação do piloto; mantenedor do ERP|Eu; coordenações; fundador aprova|
|Dependências|Acessos e planilhas (perg. 1, 4)|Padrão aprovado; consulta do ERP|Checklist verde; WhatsApp da Clinic|
|Esforço (P6, hipótese)|Auditoria 22 h, construção 12 h, produção 16 h, observação 6 h, reserva 14 h|Construção 24 h, conciliação 18 h, correções 14 h, reserva 14 h|Núcleo ~100 h, número ~60 h, canais e histórico ~64 h, reserva 56 h|
|Riscos|Acesso demora; conta presa em agência|Piloto sem volume; ERP sem consulta; Meta restringir eventos de saúde|Migração do número; id do anúncio não chega|
|Critério de conclusão|Ativos pagos inventariados; perda aceita pelo fundador|Cobertura do piloto acima de 90% e liberação esperada entre os dias 30 e 50, ou motivo escrito|30 dias estáveis no número principal; 90% das vendas ligadas|
|Métrica|% da verba inventariada; receita sem origem em R$; primeira resposta por unidade|Cobertura do piloto; envios sem recibo = 0|Receita do ERP sem origem abaixo de 15% do total (hoje 30% no exemplo); R$ 0 em turma lotada|
|Migração e recuo|Nada é desligado|RD e núcleo em paralelo; base antiga sem duplicar; semana 5: piloto no Chatwoot, em número novo; recuo: volta à Ozia/Aktos|Dia 60: o principal migra após 30 dias estáveis do novo; dia 90: Ozia/Aktos desligada; recuo: `/q/` e anúncios voltam ao antigo; RD só para e-mail|

## 5. IA no atendimento e Grande Cérebro

**Começo pelo copiloto na pré-venda.** A IA sugere a resposta numa nota privada do Chatwoot; o atendente edita e envia. Uma intenção vira automática com 90% dos rascunhos sem edição em 100 conversas (valor inicial). Depois, um degrau por vez: triagem fora do horário, agendamento de paciente, dúvidas de aluno.

**Fontes e limites.** Curso, preço, vaga e agenda vêm de ferramentas que só leem o ERP e só veem a pessoa da conversa; preço sai em frase fixa, porque oferta obriga. Reserva, desconto e link de pagamento pedem aprovação. Dúvida clínica, reclamação, dado pessoal e fora do escopo vão a um humano na hora. Uma chave por conversa e intenção barra ação duplicada.

**Avaliação e provedores.** Meço matrícula no ERP contra grupo de controle sorteado, resolução por não voltar em 72 h, custo por conversa resolvida e 50 conversas auditadas por semana. Chat por assinatura serve à equipe, sem dado de aluna. O agente usa a API do modelo (por uso, com contrato de dados) pelo Agent Bot e por uma camada nossa, que troca de provedor. Escolho por LGPD, custo, português e uso de ferramentas.

**"Por que Campinas vendeu menos nesta semana e o que devemos fazer?"** Vejo, nesta ordem, se o rastreamento quebrou, se faltou vaga ou lead (turmas do ERP, leads e verba de Campinas) e se faltou fechar (primeira resposta, conversão por etapa). Ação: verba para turma com vaga ou contato com leads parados. **Limites de atribuição:** primeiro toque observado; desconhecida como faixa; correlação não é causa sem teste com controle. Preparo hoje unidade obrigatória em campanha e oportunidade, e log de ações. O agente propõe e um humano aprova; vendas, saldo, vagas, comissões e DRE ficam nos sistemas oficiais.

## 6. Demonstração

`uv run pytest -q` e `uv run python scripts/demo.py` cobrem os cinco cenários e a falha escolhida (LP paga sem parâmetros: lead desconhecido, pendência e ponto bloqueado, sem perder o lead). **Decisões de vocês na semana 1:** WhatsApp oficial no nome da Clinic, convenção de nomes, unidade e canais do piloto, quem assina cada liberação e o evento de venda com id no ERP.
