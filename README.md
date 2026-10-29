# Demo local: da entrada identificada à venda confirmada pelo ERP

Fatia pedida no case: **entrada identificada → contato/oportunidade → encaminhamento do atendimento → venda confirmada pelo ERP**.
WhatsApp, ERP e atendimento são simulados, e a IA de triagem é só a fila `triagem-bot`; o webhook segue o formato da Cloud API da Meta (com `referral`) e o `message_created` do Chatwoot, pelo mesmo fluxo e o mesmo recibo. Sem interface gráfica: a verificação é por testes e por um script.

## Verifique em 2 minutos

Requer [uv](https://docs.astral.sh/uv/) e Python 3.12+.

```bash
uv sync
uv run pytest -q                 # termina com "174 passed" e não cria arquivo na raiz
uv run python scripts/demo.py    # recria demo.db e imprime cada passo
uv run python scripts/demo.py | diff - saida-esperada.txt && echo "saída igual à esperada"
```

Linhas-chave do demo (saída completa e determinística em [`saida-esperada.txt`](saida-esperada.txt)):

```text
[C1] form-1001 Ana, LP paga com UTM -> processado (origem observada:ig/paid_social, fila comercial-sp, pessoas=1, toques=1)
[C4] reenvio form-1001 -> duplicado (pessoas=3, toques=5)
[C4] mensagem da Ana repassada pelo Chatwoot (segunda via) -> duplicado (pessoas=3, toques=5)
[C5] ERP confirma ERP-2026-5001 da oportunidade da Ana -> processado (pessoas=3, toques=5)
[C5] oportunidade 1 ganha com ERP-2026-5001; origem atribuída observada:ig/paid_social, sp-micropigmentacao-captacao, lp-sp-micro-01
[FALHA] form-1003 Diego, LP paga sem UTM (link do anúncio sem parâmetros) -> processado (origem desconhecida, fila comercial-sp, pessoas=4, toques=6)
      "status": "bloqueado"
  "receita_sem_origem_cents": 349000,
[CONVERSAO] ERP-2026-5001 -> meta pendente (fbclid=IwAR0abc, event_id=ERP-2026-5001)
```

C1 a C5 são os cenários do enunciado (C2 e C3 na saída completa); FALHA é a falha escolhida, e `lp-sp-micro-01` é o único ponto `bloqueado`. A receita sem origem é a venda do Diego (R$ 3.490); a em quarentena (R$ 4.200) fica à parte. A conversão da Ana sai `pendente` com a LP bloqueada: é do lead, que tem UTM completa, não do ponto.

## Leia em 5 minutos

O coração da fatia são cinco funções; o resto é tratamento de borda (entrada ruim, concorrência, reenvio):

- `domain.classify`: observada, declarada ou desconhecida, só pela evidência do próprio evento.
- `db.receive`: recibo idempotente (`ON CONFLICT DO NOTHING`), na mesma transação dos efeitos.
- `db.attributed_touch`: o toque que leva a origem, o primeiro observado.
- `db.record_sale`: liga a venda pela oportunidade, ou a estaciona na quarentena.
- `domain.release_status`: libera ou bloqueia cada ponto de entrada.

## Explorar

```bash
uv run fastapi dev app/main.py   # http://127.0.0.1:8000/docs; banco em demo.db ou em CLINIC_DB
```

`app/schema.sql` (tabelas, `CHECK`s, triggers), `app/domain.py` (regras puras), `app/db.py` (todo o SQL), `app/main.py` (rotas e leitura tolerante). Convenção (UTMs, pontos de entrada, anúncios, robôs de prévia, liberação) em `data/catalog.json`; payloads fictícios em `data/eventos.json`.

## Cenários do enunciado → testes

| Cenário | Teste | O que verifica |
|---|---|---|
| C1. Lead com campanha, origem preservada até a venda | `test_c1_origem_campanha_preservada_ate_venda` | `observada`/`ig/paid_social`, `comercial-sp`; depois da venda o 1º toque mantém campanha, criativo, `fbclid` e ponto, sem `@` |
| C2. QR de unidade × WhatsApp direto | `test_c2_qr_unidade_distinto_de_whatsapp_direto` | QR: `observada`/`offline/qr`, fila `agenda-cps` (paciente modelo). Direto: `desconhecida`, sem canal, `triagem-bot`, sem alerta |
| C3. Pessoa existente, nova campanha | `test_c3_pessoa_existente_nova_campanha` | Mesmo telefone em outro formato e outro nome, mesma pessoa; oportunidade nova `harmonizacao/rj`; 1º toque da antiga intacto |
| C4. Evento duplicado | `test_c4_evento_duplicado_sem_efeito` | `duplicado` com o mesmo `event_id`; 8 tabelas iguais |
| C5. Venda confirmada pelo ERP | `test_c5_venda_erp_atualiza_oportunidade` | `ganha`, venda ligada, 1º toque preservado; não reabre |
| Falha escolhida | `test_falha_lp_sem_utm_detectada`, `test_lp_sem_utm_com_como_conheceu_nao_libera` | Ver a seção abaixo |
| Mensagem pelo Chatwoot | `test_chatwoot_com_referral_herda_o_anuncio`, `test_mesma_mensagem_pela_meta_e_pelo_chatwoot_e_duplicado`, `test_chatwoot_so_mensagem_recebida_vira_contato` | Herda o anúncio; a mesma mensagem pelas duas rotas é `duplicado`; `outgoing` é `ignorado` |
| Clique do QR/LP que se perde no WhatsApp | `test_q_mensagem_com_protocolo_herda_a_campanha`, `test_q_protocolo_vencido_ou_inexistente`, `test_q_protocolo_reutilizado_por_outra_pessoa`, `test_q_protocolo_vence_referral_de_post`, `test_q_taxa_de_chegada`, `test_q_chegada_baixa`, `test_q_head_e_previa_de_link_nao_gravam_leitura`, `test_q_nao_repassa_dado_pessoal` | Protocolo herda UTM e ponto; vencido ou usado por outra pessoa abre `protocolo_invalido`; 20 leituras com chegada abaixo de 60% abrem alerta; `HEAD` e robô de prévia não contam; só utm_* e click id seguem |
| Atendimento → CRM | `test_etiqueta_do_atendimento_muda_o_estagio`, `test_etiqueta_com_duas_abertas_exige_a_oportunidade`, `test_etiqueta_gravada_pelo_nucleo_e_eco` | `em_negociacao` grava `stage`, `perdida` fecha; duas abertas sem id dão `etiqueta_ambigua`; eco ignorado |

Os demais testes têm nomes que dizem o que verificam (`uv run pytest -v`), por tema: recibo e idempotência; entrada ruim que não perde lead (`test_telefone_numerico_no_formulario`); identidade e oportunidade (`test_anuncio_fora_do_catalogo_entra_na_oportunidade_aberta`); origem e atribuição (`test_atribuicao_pelo_primeiro_toque_observado`, `test_oi_no_whatsapp_direto_nao_rouba_a_origem`); venda e quarentena; relatório e liberação; conversões (`test_venda_gera_conversao_para_plataforma`); concorrência, outbox e auditoria. Em `tests/test_domain.py`: normalização, origem, formato de `utm_campaign`, precedência da conversão e a tolerância contra a binomial.

Mutações conferidas, cada uma derruba teste: sem `ON CONFLICT` no recibo, sem `db.LOCK` na escrita ou na leitura, sem a posse `enviando` da outbox, `ORDER BY` de `db.attributed_touch` invertido ou sem a prioridade do toque observado.

## A falha escolhida: LP paga sem UTM

`lp-sp-micro-01` tem `exige_parametros: true`. O `form-1003` chega sem UTM nem click id, com referrer `l.instagram.com`: o link do anúncio foi cadastrado sem parâmetros.

1. O lead é aceito e encaminhado: falha de rastreamento não custa o lead.
2. A origem fica `desconhecida`, não `ig`: referrer de app pode ser anúncio.
3. Abre `parametros_perdidos` com `{"referrer_host": "l.instagram.com"}`, sem dado pessoal.
4. No `/quality/report` a LP fica `bloqueado`, e o CAC dela espera o link ser corrigido. Lead com problema é o `desconhecida` ou com `parametros_perdidos` ou `utm_fora_do_padrao` aberta (inclui `utm_campaign` fora de `{unidade}-{produto}-{objetivo}[-livre]`).
5. "Como conheceu" preenchido não esconde a perda: vira `declarada`, mas a pendência abre.
6. Sem referrer (retorno direto, favorito), a pendência é `retorno_sem_parametro`: conta contra a cobertura do mesmo jeito, mas o remédio é guardar o clique entre visitas, não corrigir o link.

`domain.release_status` refaz em ordem os leads do ponto, sem estado guardado: abaixo de 30, taxa acima de 5% bloqueia; com 30 ou mais, bloqueia acima da tolerância (0 em 30, 1 em 50, 2 em 75, 4 em 100) e só libera com 7 dias de observação. Liberado só volta a bloquear com 7 problemas em 50 ou 5 seguidos (ver o anexo).

## Decisões

- **Origem só com evidência no evento.** `observada` exige UTM completa, click id, `referral`, protocolo do `/q/`, QR ou referrer de buscador; `declarada` é só "como conheceu"; o resto é `desconhecida`.
- **Atribuição pelo primeiro toque observado** (`db.attributed_touch`); sem nenhum, o primeiro toque. Um "oi" no WhatsApp direto antes do formulário pago não leva a origem.
- **Protocolo do `/q/`.** A leitura grava UTMs e click id numa `click_session` e leva "protocolo XXXXX" ao WhatsApp; a mensagem com protocolo de até 7 dias herda a origem, se ninguém de outro telefone já o usou; a leitura do protocolo e a gravação do toque ficam sob a mesma trava. O redirecionamento só repassa utm_* e click id; `HEAD` e robô de prévia não são leitura.
- **Identidade só por identificador** (E.164, BSUID do WhatsApp para quem chega sem telefone, e-mail minúsculo); conflito abre `identidade_conflitante` sem fundir.
- **Lead de teste tem oportunidade própria** (`opportunity.is_test`) e vai à fila `teste`: o lead real do mesmo telefone nunca cai nela.
- **Campo que o toque não sabe não rebaixa o que a oportunidade sabe**: o formulário do `/contato` com produto e sem unidade entra na aberta de SP, sem outra fila em paralelo.
- **Mensagem sem produto nem unidade** (um "obrigada", anúncio fora do catálogo) entra na oportunidade aberta mais recente.
- **Nenhum lead rejeitado**: só a falta da chave de idempotência dá 422; no lote do WhatsApp, a mensagem sem `id` vira pendência e o resto segue (um 422 faria a Meta reenviar o lote para sempre).
- **Recibo e efeitos numa transação** (`ON CONFLICT DO NOTHING`); hash diferente é `conflito`; recibo imutável por trigger.
- **Venda na dúvida vai para quarentena**, sem aplicar nada.
- **Conversão é do lead, não do ponto**, por outbox, com o click id mais recente de cada plataforma. Precedência: `sensivel`, sem `consent_ads`, vencido e `pendente`. Quem casa o clique com o anúncio é a plataforma: um `fbclid` sozinho não prova a campanha para a nossa atribuição, mas sai como sinal para a Meta. A Meta só aceita o evento até 7 dias depois da venda: esperar o ponto liberar perderia as vendas do piloto.
- **Atendimento → CRM por etiqueta**, com o id da oportunidade (o telefone só é exigido sem ele); eco do núcleo é ignorado.
- **Paciente modelo é outro funil**: fila `agenda-{unidade}`, conversão bloqueada (produto sensível) e contagem à parte no relatório (`paciente_modelo`), fora da origem e da receita de curso.
- **Só ponto liberado entra no custo por canal**: o relatório separa `valor_em_pontos_liberados_cents` do total. Automação não existe na demo; a trava dela por ponto é desenho.
- **Encaminhamento por outbox**; timeout vira `incerto`, sem reenvio às cegas.

O porquê das decisões de borda está no comentário do código.

## O que é só desenho (não está na demo)

- Fusão reversível de pessoas; identidade pelo id do ERP e papéis (aluna, paciente, lead); feed de vendas do ERP por cursor, cancelamento e estorno; botão "matricular" no Chatwoot.
- Envio real das conversões e do lead qualificado (etiqueta) às plataformas.
- Alertas de volume zerado, desconhecida acima do limite e quarentena: na demo, só a chegada baixa do `/q/` e o status de cada ponto no relatório.
- Cookie primário para levar os parâmetros entre páginas; liberação de pontos de baixo volume por família.
- Formulários instantâneos da Meta; expiração de oportunidade por rotina diária.

## Limitações

Marcadas com `# shortcut:` no código: SQLite serializado por `db.LOCK`; sem `X-Hub-Signature-256` nem remetente conferido no Chatwoot; robô de prévia só pelo User-Agent; do atendimento só volta a etiqueta; no formulário, só telefone do Brasil; toda mensagem de WhatsApp vira toque; sem a retenção de 30 dias do payload do formulário.

Sem marcação: sem autenticação (ids sequenciais); formato de `utm_campaign` conferido só no formulário, não no `/q/`; evento sem data legível usa a hora de recebimento; quarentena só é reprocessada no reenvio; evento em conflito guarda só o hash do conteúdo novo (o conteúdo se pede ao remetente); a atribuição é calculada na leitura, então um toque importado depois com data antiga pode mudar a origem de uma venda (em produção, gravar o toque atribuído na venda); venda em oportunidade de teste é aceita sem pendência; o alerta de chegada baixa conta leitura de robô que se passa por navegador (por isso não bloqueia sozinho); `enviando` de processo que caiu fica parado até alguém conferir.

## Uso de IA

Gerei o código com o Claude Code (modelo Claude Opus 5.5) a partir de um plano que eu aprovei; os testes rodam localmente. O que eu revisei e o que a IA fez estão no REGISTRO.

## Anexo: estatística da liberação

Cada checagem pergunta se dá para afirmar que o ponto rastreia pelo menos 90% dos leads. Se a cobertura real fosse só 90%, ver tão poucos problemas teria chance de 4,2% (0 em 30), 3,4% (1 em 50), 1,6% (2 em 75) e 2,4% (4 em 100): abaixo de 5%, logo 95% de confiança (binomial, Clopper-Pearson unilateral). Um problema a mais passa de 5%, por isso cada faixa é o máximo; `test_tabela_de_tolerancia_garante_cobertura_de_90` refaz a conta.

**Margem de rebloqueio.** Com a mesma tabela, o ponto saudável oscilaria: com 5% de problemas reais, 2 ou mais em 50 acontecem 72% das vezes. Já 7 em 50 nesse ponto é 1,2%; com 10% de problemas, 23% das janelas; com 20%, 90%. Os 5 seguidos pegam a quebra brusca (link trocado sem parâmetros) sem esperar a janela.

**Custo da regra.** A janela conta os problemas anteriores: um problema seguido de 30 leads limpos ainda bloqueia até perto de 50. Um ponto com 95% de cobertura real passa ~44% das vezes com 100 leads; com 97%, 82%. Por isso pontos pequenos liberam em grupo e o ponto ruim se corrige, não se espera.

**Confiança por checagem.** A regra é recalculada a cada lead, então os 95% valem por checagem, não para a sequência: um ponto com 90% de cobertura tem muitas chances de passar uma vez por sorte. A margem compensa: o liberado segue vigiado, e o de 90% bate 7 em 50 em quase uma janela a cada quatro e volta a bloquear, enquanto o saudável não bloqueia por ruído.
