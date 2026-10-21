# PV3 — estudo de viabilidade de roteamento local sem API VBB

**Data:** 21/10/2026
**Escopo:** pesquisa local/read-only e comparação de opções. **Na data do estudo, nenhum motor tinha sido escolhido ou implementado.** Não houve acesso à API VBB, banco, serviço, navegador, GPU, migration ou dependência nova.

## Conclusão executiva

É viável avançar sem API com um **estudo e protótipo isolado de itinerários entre paradas** usando o GTFS estático local. O feed contém calendários, regras de transferência e caminhos internos de estação. Isso não equivale a um planejador porta-a-porta: não há rede de ruas para calcular caminhada até/de endereços, e a cobertura de Alert do GTFS-RT continua não validada. A ausência de Alert não pode ser apresentada como serviço normal.

A melhor próxima experiência de baixo risco seria uma prova CPU-only, descartável, de busca entre duas paradas selecionadas manualmente, consumindo calendário, `stop_times.txt`, `transfers.txt` e `pathways.txt`. Ela mediria se as conexões são temporalmente possíveis, sem banco, endpoint, instalação de engine ou alteração do frontend. Esse recorte ainda precisa da aprovação do usuário antes de virar implementação de produto.

## Evidência do GTFS local

Inventário somente leitura do snapshot existente em `data/gtfs-static/GTFS`; o manifesto informa download em **18/10/2026 18:07:48 UTC**, validade de calendário de **15/10/2026 a 12/12/2026** e schedule hash `7c93c04b`.

| Arquivo | Linhas | O que prova / limite |
|---|---:|---|
| `routes.txt` | 1.257 | Linhas do snapshot. |
| `trips.txt` | 186.451 | Viagens e `service_id`; 1.788 IDs de serviço distintos. |
| `stops.txt` | 41.965 | Paradas, plataformas e estações conforme o feed. |
| `stop_times.txt` | 3.997.644 | Horários por viagem/parada; 302.102.506 bytes. |
| `calendar.txt` | 1.788 | Serviço semanal e intervalo de datas. |
| `calendar_dates.txt` | 13.605 | Exceções de serviço; todos os 1.788 `service_id` de viagens existem em calendário ou exceções. |
| `transfers.txt` | 52.289 | Os IDs `from_stop_id` e `to_stop_id` das 52.289 linhas correspondem a paradas estáticas; códigos observados: `transfer_type=1` (3.859) e `2` (48.430). A regra deve seguir a semântica GTFS, não proximidade geográfica. |
| `pathways.txt` | 126.912 | Todos os extremos correspondem a IDs estáticos; todas as linhas declaram `is_bidirectional=0`, então são arestas direcionadas. Modos observados: 1 (120.235), 2 (4.394), 4 (755), 5 (1.528). |
| `levels.txt` | 358 | Níveis de estação referenciados pelo GTFS. |
| `frequencies.txt` | 0 | Arquivo presente, sem linhas nesta versão do snapshot. |

O padrão GTFS define calendários, transferências e `pathways.txt` como partes distintas do horário estático; pathways descrevem conexões dentro de estações, não uma rede geral de ruas.[1]

### Lacuna no armazenamento atual

O manifesto local contém esses arquivos, mas o loader `src/bvg_radar/static_gtfs.py` e o schema das migrations atuais não importam/tabelam `calendar`, `calendar_dates`, `transfers`, `pathways` ou `levels`. O schema atual concentra-se em rotas, viagens, paradas, shapes e stop times. Essa conclusão vem da leitura do código; nenhum banco foi consultado. Também não encontrei arquivo OSM `.pbf`/`.osm` sob `data/`, nem dependência de roteamento no `pyproject.toml`.

## Opções que permanecem abertas

| Opção | O que habilita | Limites/custos ainda não validados |
|---|---|---|
| **Router GTFS próprio, escopo stop-to-stop** | Pode usar a stack Python existente, calendários, horários, transferências e caminhos de estação; evita uma nova dependência de runtime. O feed público já forneceu uma amostra de cancelamentos por viagem mapeáveis ao GTFS, mas não Alert real. | Não faz busca por endereço nem calcula caminhada na rua. Exige algoritmo correto para calendários/exceções, horários após meia-noite, transferências e caminhos direcionados. Na data do estudo, o desempenho nos 3,99 milhões de stop times ainda não havia sido medido. Não oferece cobertura de interrupções sem fonte Alert validada. |
| **OpenTripPlanner self-hosted** | Candidato para combinar GTFS com rede de ruas e caminhada; sua documentação descreve construção de grafo com fontes GTFS/OSM.[2][3] | Não há arquivo OSM local nem runtime/serviço OTP no projeto. Acrescentaria Java, dados de mapa e rotina de construção/atualização de grafo. RAM, tempo de build, implantação e operação para Berlin/VBB precisam de ensaio; nada foi instalado. |
| **API oficial VBB** | Pode oferecer consultas de viagens e mensagens de tráfego nos endpoints documentados.[4] | O usuário informou que enviou um e-mail próprio solicitando acesso de teste; o assistente não enviou o e-mail nem verificou resposta ou credenciais. O acesso de produção depende de processo/condições separados.[5] Cobertura, termos, quotas e respostas reais permanecem desconhecidos. |

## Regras de produto que o protótipo não deve violar

- Horário estático é uma previsão de agenda, não confirmação de operação. A formulação já aprovada pelo usuário continua aplicável: **“Há previsão de passagem, mas não conseguimos confirmar se o serviço está operando.”**
- Um `TripUpdate CANCELED` é evidência para aquela viagem/instância, não para a linha inteira. Os IDs de origem devem manter `trip_id`, `route_id`, data de serviço e, quando aplicável, `start_time`.
- Ausência de `Alert`, `TripUpdate` ou VehiclePosition não significa serviço normal. Os quatro snapshots amostrados do feed não trouxeram Alert; PV1 segue parcial.
- Não transformar distância em linha reta em caminhada. Sem OSM local, qualquer caminhada externa deve ficar fora do primeiro spike ou usar somente uma conexão de caminhada explicitamente fornecida/validada pelo GTFS.
- Não adotar limite de caminhada de 10 minutos; esse valor não foi aprovado.

## Próxima decisão sugerida na data do estudo

Na data deste estudo, sugeri autorizar uma prova isolada de roteamento **somente entre paradas**, com fixtures/testes CPU e uma pequena amostra do GTFS estático; sem migration, DB, endpoint, dependência nova, API, frontend ou claim de cobertura de Alert. O usuário posteriormente pediu que uma alternativa sem API fosse implementada; o resultado está registrado abaixo. A prova continua não sendo um motor de produção aprovado para PV3.

## Atualização 1 — protótipo inicial de horário direto (etapa histórica)

O usuário informou que enviou por conta própria um e-mail solicitando acesso à API de teste do VBB. Não há confirmação de resposta ou liberação de acesso; o assistente não enviou outro e-mail nem acessou a conta. Enquanto isso, foi implementado `src/bvg_radar/planning/local_gtfs.py` como protótipo interno, sem dependências novas, banco, migration, API pública ou frontend.

O protótipo consulta somente o GTFS estático local, respeita `calendar.txt`/`calendar_dates.txt`, horários `stop_times.txt` inclusive acima de 24:00 e regras normais de embarque/desembarque. Ele retorna apenas viagens diretas em que o mesmo `trip_id` atende às duas plataformas selecionadas. Cada resultado contém `operation_confirmed=false` e a frase aprovada pelo usuário: **“Há previsão de passagem, mas não conseguimos confirmar se o serviço está operando.”** O índice compacto de horários é mantido em memória no objeto do planejador.

### Validação empírica do protótipo

- **GTFS estático, data de serviço 22/10/2026:** Bad Freienwalde, Busbahnhof → Bad Freienwalde, Markt. O feed local retornou viagens agendadas nas linhas 958 (05:44–05:46), 886 (06:23–06:24) e 889 (07:07–07:09). Isso valida a consulta ao horário estático, não operação ao vivo.
- **Uma execução medida:** construção do índice + primeira consulta: 37,896 s; consulta repetida com o índice em memória: 0,019 s; aumento de RSS durante a construção: 126,2 MiB. São medições pontuais, não p95 nem benchmark de produção.
- **Testes:** 710 testes totais, 701 passaram, 9 foram pulados por dependerem de `BVG_DATABASE_URL`; 0 falhas/erros. `test:phase1` e `test:phase2:sql` passaram. Nenhum banco foi acessado.

### Limites do primeiro incremento (histórico)

- Não calcula transferências, `pathways.txt`, caminhada externa, rota por endereço ou acesso entre entrada/estação e plataforma. O usuário precisa escolher `location_type=0` (plataforma); esta limitação evita inventar tempo de caminhada.
- Não consulta TripUpdates/Alerts e não detecta viagens canceladas em tempo real; o aviso de operação não confirmada é obrigatório. A cobertura de Alert continua não validada.
- A construção do índice custa cerca de 38 s neste ensaio; deve ocorrer em preparação/warm-up antes de qualquer uso interativo. O módulo não foi integrado ao servidor nem exposto a passageiros.
- O próximo incremento de transferências precisa modelar a especificidade de regras por `trip_id`/`route_id` e a orientação/tempos de `pathways`; o protótipo atual não seleciona um motor final para PV3.

## Atualização 2 — transferências explícitas e caminhos internos

O protótipo local foi ampliado, ainda isolado e sem dependência da API BVG:

- `transfers.txt`: seleciona a regra aplicável por especificidade de `trip_id`/`route_id`, respeita proibições e tempos mínimos; tipos não suportados continuam falhando fechados.
- `pathways.txt`: cria um grafo direcionado de conexões internas, usa o caminho com menor soma de `traversal_time` declarado e só cria a aresta reversa quando `is_bidirectional=1`. Trechos sem tempo não recebem duração inventada. Endpoints incompatíveis e `stop_access=1` são rejeitados.
- Quando há caminho e regra com tempo mínimo, a consulta exige o maior dos dois tempos, não a soma: o tempo mínimo de transferência se refere à conexão como um todo, então somar novamente o trajeto interno poderia contá-lo duas vezes.
- Cada transferência resultante pode informar os IDs e modos dos caminhos percorridos. A busca não faz caminhada externa, não geocodifica endereços e não filtra escadas/elevadores conforme mobilidade; não deve ser exposta como orientação acessível ou funcionalidade de produção.

A validação usou o snapshot local do manifesto: schedule hash `7c93c04b`, calendário de 15/10/2026 a 12/12/2026 e 126.912 linhas em `pathways.txt`; nele, todos os caminhos declarados são direcionados (`is_bidirectional=0`). Uma consulta ao grafo encontrou em Nollendorfplatz um caminho entre plataformas distintas de 130 s, composto por seis trechos. Isso prova apenas a leitura do grafo estático, não a operação em tempo real nem uma rota completa de passageiro pela rede.

**Verificações:** 23 testes focados do planejador passaram; a suíte Python passou com 718 aprovados e 9 ignorados (testes que exigem `BVG_DATABASE_URL`); `test:phase1` e `test:phase2:sql` passaram. Os testes de banco foram mantidos sem conexão. Nenhuma migration foi aplicada, API acessada, dependência de runtime adicionada, endpoint/frontend integrado ou validação visual executada.

**Limites atuais:** horários continuam sendo previsões estáticas com `operation_confirmed=false`; cobertura de Alert permanece não validada. Caminhos sem `traversal_time`, transfers tipo 4/5, acessibilidade e caminhada externa não são suportados. Ainda falta validar uma conexão completa com pathways no GTFS real antes de considerar a busca mais que um protótipo isolado.

## Sources

[1] https://gtfs.org/documentation/schedule/reference — GTFS Schedule Reference
[2] https://docs.opentripplanner.org/en/latest/Data-Sources — OpenTripPlanner data sources
[3] https://docs.opentripplanner.org/en/latest/Basic-Tutorial — OpenTripPlanner basic tutorial
[4] https://unternehmen.vbb.de/digitale-services/api — VBB API documentation
[5] https://unternehmen.vbb.de/digitale-services/api/zugang-produktivsystem — VBB production access requirements
