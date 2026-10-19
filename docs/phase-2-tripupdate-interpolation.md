# Fase 2 — Interpolação de posições estimadas a partir de TripUpdates VBB

## Escopo entregue

Esta fase adiciona uma camada **exclusivamente server-side** para transformar
`TripUpdate`s GTFS-Realtime da VBB em posições estimadas sobre os shapes do
GTFS estático. Ela não entrega FastAPI, WebSocket público, React, MapLibre ou
Deck.gl.

```text
VBB GTFS-RT Protobuf
        │ aiohttp + Protobuf, somente no backend
        ▼
TripUpdate normalizado
        │ trip_id + data de serviço + StopTimeUpdate
        ▼
Supabase/PostGIS privado (gtfs)
        │ stop_times + shapes + interpolação espacial
        ▼
Contrato de evento vehicle_position
source=trip_update_interpolation; is_estimated=true
```

O browser nunca recebe o Protobuf e nunca acessa a fonte VBB diretamente.

---

## Endpoint VBB confirmado

A URL antiga abaixo é inválida e retorna HTTP 404:

```text
https://vbb.de/gtfs-rt-vehicle-positions
```

O endpoint de produção validado para o backend é:

```text
https://production.gtfsrt.vbb.de/data
```

O cliente identifica a aplicação com `User-Agent: bvg-3d-radar/1.0`. A
validação real mostrou que uma requisição sem essa identificação recebe HTTP
403, enquanto a mesma fonte responde normalmente com o cabeçalho explícito.

Ele retorna Protobuf GTFS-Realtime. A amostra validada continha `TripUpdate`s,
não `VehiclePosition`s. Portanto latitude, longitude, bearing e velocidade
produzidos nesta fase são **estimativas**, não telemetria GPS observada.

Não use `https://staging.gtfsrt.vbb.de/data` como fonte operacional.

---

## Preservação semântica GTFS-Realtime

A normalização mantém separados os tempos de procedência:

- `FeedHeader.timestamp` identifica o snapshot e é armazenado como
  `GtfsRealtimeSnapshot.feed_timestamp`;
- `TripUpdate.timestamp` pertence à previsão da entidade e é armazenado como
  `TripUpdate.trip_update_timestamp`.

Os relacionamentos de viagem são preservados como enums de domínio:
`SCHEDULED`, `ADDED`, `UNSCHEDULED`, `CANCELED`, `REPLACEMENT`, `DUPLICATED`,
`DELETED`, `NEW` e `UNKNOWN`. O binding Protobuf instalado não declara todos os
valores atuais; por isso, valores enum retidos no conjunto de campos
`unknown` do proto2 são inspecionados antes de aceitar o default
`SCHEDULED`. Os valores atuais `DELETED=7` e `NEW=8` são reconhecidos; qualquer
valor futuro não compreendido torna-se `UNKNOWN`.

Somente uma viagem `SCHEDULED` com `trip_id`, `route_id` e data de serviço
válidos pode chegar ao interpolador baseado no GTFS estático. Os demais estados
continuam disponíveis no snapshot para ciclo de vida e auditoria, mas não geram
uma posição artificial sobre uma viagem programada.

Nos `StopTimeUpdate`s, `SCHEDULED`, `SKIPPED`, `NO_DATA`, `UNSCHEDULED` e
`UNKNOWN` também são preservados. Paradas `SKIPPED` e `NO_DATA` mantêm os dados
recebidos no DTO, porém seus horários e atrasos são removidos do payload enviado
ao estimador.

Uma `FeedEntity` com `is_deleted=true` prevalece sobre qualquer
`trip_update` incorporado. Seu `entity_id` é registrado como tombstone e chega
ao resultado do ciclo; a aplicação desses tombstones ao snapshot WebSocket
pertence à etapa posterior de ciclo de vida da entrega.

O cliente HTTP distingue os estados condicionais:

- HTTP `200` com Protobuf válido, mesmo sem entidades, produz `UPDATED` com um
  snapshot;
- HTTP `304` produz `NOT_MODIFIED` sem snapshot.

Em respostas `200`, o corpo precisa conter uma `FeedMessage` Protobuf
inicializada, inclusive os campos obrigatórios do header. O ETag só é promovido
após parse e normalização bem-sucedidos; uma resposta válida sem ETag limpa o
validador anterior.

---

## Artefatos

| Arquivo | Finalidade |
|---|---|
| `supabase/migrations/20260719110000_trip_update_interpolation.sql` | Cria `gtfs.stop_times`, a função de conversão de horário GTFS e `gtfs.estimate_trip_position(...)`. |
| `supabase/migrations/20260719113000_clamp_stop_shape_fraction.sql` | Corrige precisão IEEE-754 de `ST_LineLocatePoint` nos endpoints de linha. |
| `supabase/migrations/20260902223000_trip_update_timing_evidence.sql` | Torna o atraso nullable e classifica a procedência temporal como absoluta, atraso explícito ou `schedule_only`. |
| `supabase/migrations/20260909050337_batch_trip_position_estimation.sql` | Adiciona a API privada `gtfs.estimate_trip_positions_batch(...)` e suas ACLs. |
| `supabase/migrations/20260909052610_set_based_batch_trip_position_estimation.sql` | Substitui a chamada SQL unitária por TripUpdate por uma interpolação set-based. |
| `supabase/migrations/20260909054609_optimize_batch_dynamic_updates.sql` | Remove o scan correlacionado dos updates dinâmicos e usa joins pré-deduplicados por sequência e parada. |
| `supabase/sql/phase_2_import_vbb_static_local.sql` | Recarrega o GTFS estático, incluindo `stop_times.txt`, apenas localmente. |
| `supabase/sql/phase_2_after_stop_times_import.sql` | Pré-calcula `shape_fraction`, cria índice e executa `ANALYZE`. |
| `src/bvg_radar/realtime/models.py` | Define snapshots, resultados de fetch, timestamps separados, relacionamentos tipados e tombstones. |
| `src/bvg_radar/realtime/source.py` | Busca assíncrona Protobuf com `aiohttp`, validação estrutural e ETag transacional. |
| `src/bvg_radar/realtime/normalization.py` | Converte Protobuf em DTOs sem vazar tipos do transporte nem perder estados proto2. |
| `src/bvg_radar/realtime/postgis.py` | Adaptador com batching limitado, correlação por `input_index` e enriquecimento de rota na mesma consulta. |
| `src/bvg_radar/realtime/worker.py` | Worker assíncrono que filtra entradas não interpoláveis e envia um lote lógico ao adaptador. |
| `src/bvg_radar/realtime/benchmark.py` | Instrumentação das fronteiras e gate fail-closed de p95/orçamento de consultas. |
| `src/bvg_radar/realtime/runner.py` | Composition root de ciclo único; conecta `aiohttp`, `asyncpg`, worker e saída JSON Lines no console. |
| `scripts/benchmark_realtime_cycle.py` | Benchmark reproduzível do ciclo completo contra o Supabase/PostGIS local. |
| `scripts/validate_phase_2_local.sh` | Validação de integração contra o Supabase/PostGIS local. |

---

## Modelo de estimativa

1. A carga estática adiciona `stop_times.txt` e mantém horários como texto,
   pois GTFS permite horas acima de `24:00:00`.
2. Depois da carga, cada parada de uma viagem é projetada uma única vez na sua
   linha com `ST_LineLocatePoint`, persistindo `shape_fraction` entre `0` e `1`.
3. O backend combina horário estático com `StopTimeUpdate` sem fabricar evidência:
   - tempo absoluto do GTFS-RT tem precedência e gera
     `timing_source=absolute_realtime_time`;
   - caso não exista tempo absoluto, um atraso explícito é aplicado ao horário
     estático e gera `timing_source=realtime_delay`;
   - sem tempo nem atraso para a próxima chegada, o horário estático ainda pode
     sustentar a interpolação visual, mas gera `timing_source=schedule_only` e
     `delay_seconds=null` — nunca um atraso observado igual a zero.
4. Para um instante entre saída da parada anterior e chegada à próxima, a
   função calcula a fração temporal do segmento.
5. `ST_LineInterpolatePoint` produz longitude/latitude em EPSG:4326.
6. Bearing e velocidade usam a linha métrica EPSG:25833.

A função retorna somente estimativas seguras. Ela suprime o resultado quando a
projeção é ausente, o próximo segmento não avança na linha ou o intervalo
temporal não é positivo. Isso evita colocar veículos em ramos errados de shapes
com loops ou paradas repetidas.

### Batching e orçamento de consultas

O worker envia todos os `TripUpdate`s compatíveis a `estimate_many(...)`. O
adaptador os divide em chunks de 256 e executa exatamente
`ceil(entradas_compativeis / 256)` consultas por ciclo completo. A função batch
usa `input_index` para correlacionar respostas, ordena os resultados pela ordem
de entrada e rejeita índices inválidos ou duplicados antes da publicação.

A interpolação batch é set-based: updates dinâmicos são pré-deduplicados por
`stop_sequence` e, como fallback, por `stop_id`, depois associados aos horários
estáticos por joins. `route_type` e `route_short_name` são retornados na mesma
consulta, de modo que a classificação do veículo não cria um segundo N+1. A
função unitária permanece disponível para compatibilidade e para o teste de
equivalência semântica; o caminho operacional usa apenas a função batch.

---

## Contrato de posição e entrega WebSocket

O contrato semântico abaixo representa cada posição estimada. No backend P8,
o worker não publica esses registros isoladamente: ele os encapsula em um único
`vehicle_position_snapshot` versionado e autoritativo por ciclo aceito. O
contrato completo do envelope está em
[`phase-3-websocket-snapshots.md`](phase-3-websocket-snapshots.md).

```json
{
  "type": "vehicle_position",
  "source": "trip_update_interpolation",
  "is_estimated": true,
  "position_status": "estimated_from_trip_update",
  "timing_source": "realtime_delay",
  "feed_timestamp": "2026-07-19T04:00:00Z",
  "trip_update_timestamp": "2026-07-19T04:00:05Z",
  "service_date": "2026-07-19",
  "vehicle_category": "s_bahn",
  "route_short_name": "S41",
  "entity_id": "entity-…",
  "trip_id": "…",
  "route_id": "…",
  "shape_id": "…",
  "previous_stop_id": "…",
  "next_stop_id": "…",
  "delay_seconds": 120,
  "estimated_next_arrival": "2026-07-19T04:04:00Z",
  "longitude": 13.4,
  "latitude": 52.5,
  "bearing_degrees": 91.5,
  "speed_mps": 8.2,
  "observed_at": "2026-07-19T04:00:10Z"
}
```

`is_estimated: true` é obrigatório. Não rotule nem apresente esse dado como
posição GPS real. `timing_source` informa exclusivamente a procedência temporal
da próxima chegada usada pelo estimador. Eventos `schedule_only` continuam
sendo estimativas visuais válidas, mas carregam `delay_seconds=null` e não podem
entrar em indicadores de pontualidade observada. Um zero numérico só representa
pontualidade quando acompanhado de `realtime_delay` ou
`absolute_realtime_time`. `position_status` também é obrigatório e, para este
contrato, deve ser `estimated_from_trip_update`. `feed_timestamp` e
`trip_update_timestamp` são campos obrigatórios: cada valor é `null` quando a
fonte não o fornece ou um timestamp ISO 8601 válido serializado em UTC com
sufixo `Z`; string vazia ou timestamp malformado é inválido. `service_date`
deve ser uma data de calendário válida em `YYYY-MM-DD`.

---

## Operação local

Prepare o ambiente Python uma vez:

```bash
uv sync --all-groups
```

Para validar código e SQL sem precisar de Docker:

```bash
npm test
```

Com Supabase local ativo e o GTFS importado, execute a integração SQL/PostGIS:

```bash
npm run test:phase2:local
```

A integração Python → PostGIS é opt-in e usa o adapter real em uma transação
somente leitura. Ela seleciona dinamicamente um segmento seguro do snapshot
instalado, sem fixar `trip_id`, e recusa URLs que não apontem para loopback na
porta local `55031`:

```bash
export BVG_DATABASE_URL='postgresql://[ROLE]:***@127.0.0.1:55031/postgres'
npm run test:integration:local
```

Sem `BVG_DATABASE_URL`, o teste registra `SKIPPED` com motivo explícito; ele não
é apresentado como integração executada.

### Benchmark do ciclo completo

O benchmark P7 busca um feed completo por amostra, normaliza, interpola no
PostGIS, serializa as posições dentro do snapshot e mede o JSON do envelope
completo em um sink local. Ele recusa qualquer banco que não seja PostgreSQL em
loopback na porta `55031`:

```bash
export BVG_DATABASE_URL='postgresql://[ROLE]:***@127.0.0.1:55031/postgres'
npm run benchmark:p7:local -- --iterations 5
```

A saída é um único documento JSON. O processo falha de forma fechada se o p95
do ciclo for maior ou igual a 15 segundos, se a amostra inteira não demonstrar
estimativas a partir de TripUpdates compatíveis, ou se o total de consultas divergir de
`ceil(TripUpdates_compativeis / batch_size)`. Ciclos vazios/304 individuais são
legítimos; `performance_passed` e `data_gate_passed` são separados, e `passed`
exige ambos. P95 usa nearest rank e informa tamanho/limitação da amostra, sem
alegar carga sustentada. `positions_published` conta os
registros aninhados, `snapshots_published` conta envelopes e `payload_bytes`
mede o JSON completo. A duração de publicação mede serialização JSON no
processo; ela não é uma medição de fan-out por socket ou renderização no
browser.

### Dry-run server-side real

O runner de ciclo único busca o feed de produção, passa TripUpdates pelo
PostGIS e escreve um snapshot JSON Lines contendo até duas posições estimadas.
A URL PostgreSQL deve vir de uma variável de ambiente/secret manager local,
nunca de um arquivo versionado:

```bash
export BVG_DATABASE_URL='postgresql://[ROLE]:[REDACTED]@127.0.0.1:[PORT]/postgres'
uv run python -m bvg_radar.realtime.runner --max-positions 2
```

O primeiro objeto contém o envelope `vehicle_position_snapshot`; cada item de
`positions` inclui `estimated_next_arrival`, coordenadas, bearing, velocidade,
`source=trip_update_interpolation`, `is_estimated=true`, `timing_source`, atraso
nullable e proveniência temporal. O objeto seguinte resume o
`ingestion_cycle`, incluindo posições e snapshots publicados. O runner encerra
suas conexões ao fim desse único ciclo; ele não inicia servidor HTTP/WebSocket
nem polling contínuo.

Para recarregar o feed GTFS estático local, inclusive `stop_times.txt`:

```bash
npm run gtfs:import-local
```

> `gtfs:import-local` executa `TRUNCATE` somente no banco local Docker. Nunca
> use este comando contra Supabase hospedado ou um contexto Docker remoto.

O cliente de produção deve abrir uma sessão `aiohttp` reutilizável e uma
conexão/pool PostgreSQL configurados fora do repositório. Nunca grave URL de
banco, senha, chave de serviço ou dados operacionais em `.env` versionado.

---

## Validação local registrada

Os números abaixo pertencem aos fechamentos P6/P7 registrados em **2026-09-09**;
não devem ser interpretados como o resultado da verificação final P8.

Após a importação e o pós-processamento local, foram verificados:

| Verificação | Resultado |
|---|---:|
| `gtfs.stop_times` carregados | 5.719.111 |
| `shape_fraction` nulo | 0 |
| Frações fora de `[0, 1]` | 0 |
| Segmentos não monotônicos suprimidos | 10.877 |
| TripUpdates recebidos no dry-run ao vivo P6 | 9.218 |
| Posições estimadas impressas no dry-run P6 | 2 (`absolute_realtime_time`) |
| Baseline serial P7 | 10.456 entradas compatíveis, 12.595 consultas, ciclo de 83,458 s |
| Batch P7, 5 ciclos completos | 10.364–10.368 entradas compatíveis por ciclo, 41 consultas por ciclo |
| p95 do ciclo batch P7 | 8,523 s (`target < 15 s`, gate aprovado) |
| Integração opt-in Python → PostGIS | 1 aprovada (`absolute_realtime_time`, `realtime_delay`, `schedule_only` e equivalência unitário/batch) |
| Testes Python padrão | 160 aprovados, 1 integração ignorada sem opt-in |
| Testes frontend | 37 aprovados |

O baseline serial e o benchmark batch foram capturados em momentos distintos do
feed ao vivo. A comparação demonstra a mudança de escala das consultas e o
cumprimento da cadência nas amostras observadas; não é um A/B sobre um snapshot
idêntico.

A regressão de precisão de endpoint também é verificada de forma determinística:
os limites `1.0000000000000002` e `-0.0000000000000002` são normalizados para
`1.0` e `0.0`, respectivamente.

---

## Limites conhecidos

- O feed público validado pode mudar de cobertura e tipo de entidade; valide o
  conteúdo Protobuf antes de assumir que há veículos.
- `TripUpdate` não é `VehiclePosition`; a precisão depende de horários,
  paradas, shapes e atraso disponível.
- O serviço FastAPI/WebSocket contínuo está documentado separadamente em
  `phase-3-websocket-snapshots.md`; este documento permanece focado na
  normalização e interpolação server-side.
- O frontend Orbital consome o envelope P8 `vehicle_position_snapshot` v1 e a
  política de conexão/atualidade P9. A reconexão automática usa backoff inicial
  de 1 s, teto de 30 s e jitter limitado; `stale` ocorre após 45 s sem snapshot
  válido recente, com tolerância de 5 s para timestamp futuro.
- Os testes de P9 usam Vitest/jsdom e mocks de mapa. Não são validação visual.
  O gate 3D está `deferred_hardware` por instabilidade de GPU/fonte e aguarda
  inspeção manual do usuário. Posição interpolada não é GPS.
