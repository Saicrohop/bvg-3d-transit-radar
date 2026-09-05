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
| `supabase/sql/phase_2_import_vbb_static_local.sql` | Recarrega o GTFS estático, incluindo `stop_times.txt`, apenas localmente. |
| `supabase/sql/phase_2_after_stop_times_import.sql` | Pré-calcula `shape_fraction`, cria índice e executa `ANALYZE`. |
| `src/bvg_radar/realtime/models.py` | Define snapshots, resultados de fetch, timestamps separados, relacionamentos tipados e tombstones. |
| `src/bvg_radar/realtime/source.py` | Busca assíncrona Protobuf com `aiohttp`, validação estrutural e ETag transacional. |
| `src/bvg_radar/realtime/normalization.py` | Converte Protobuf em DTOs sem vazar tipos do transporte nem perder estados proto2. |
| `src/bvg_radar/realtime/postgis.py` | Adaptador para a função PostGIS privada. |
| `src/bvg_radar/realtime/worker.py` | Worker assíncrono e porta de publicação para a futura camada WebSocket. |
| `src/bvg_radar/realtime/runner.py` | Composition root de ciclo único; conecta `aiohttp`, `asyncpg`, worker e saída JSON Lines no console. |
| `scripts/validate_phase_2_local.sh` | Validação de integração contra o Supabase/PostGIS local. |

---

## Modelo de estimativa

1. A carga estática adiciona `stop_times.txt` e mantém horários como texto,
   pois GTFS permite horas acima de `24:00:00`.
2. Depois da carga, cada parada de uma viagem é projetada uma única vez na sua
   linha com `ST_LineLocatePoint`, persistindo `shape_fraction` entre `0` e `1`.
3. O backend combina horário estático com `StopTimeUpdate`:
   - tempo absoluto do GTFS-RT tem precedência;
   - caso não exista tempo absoluto, o atraso é aplicado ao horário estático.
4. Para um instante entre saída da parada anterior e chegada à próxima, a
   função calcula a fração temporal do segmento.
5. `ST_LineInterpolatePoint` produz longitude/latitude em EPSG:4326.
6. Bearing e velocidade usam a linha métrica EPSG:25833.

A função retorna somente estimativas seguras. Ela suprime o resultado quando a
projeção é ausente, o próximo segmento não avança na linha ou o intervalo
temporal não é positivo. Isso evita colocar veículos em ramos errados de shapes
com loops ou paradas repetidas.

---

## Contrato para a futura entrega WebSocket

O worker publica eventos JSON por uma porta assíncrona; a futura camada FastAPI
poderá consumir essa fila sem alterar a lógica de domínio.

```json
{
  "type": "vehicle_position",
  "source": "trip_update_interpolation",
  "is_estimated": true,
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
  "speed_mps": 8.2
}
```

`is_estimated: true` é obrigatório. Não rotule nem apresente esse dado como
posição GPS real.

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
porta local `54022`:

```bash
export BVG_DATABASE_URL='postgresql://[ROLE]:***@127.0.0.1:54022/postgres'
npm run test:integration:local
```

Sem `BVG_DATABASE_URL`, o teste registra `SKIPPED` com motivo explícito; ele não
é apresentado como integração executada.

### Dry-run server-side real

O runner de ciclo único busca o feed de produção, passa TripUpdates pelo
PostGIS e escreve no console até duas posições estimadas como JSON Lines. A
URL PostgreSQL deve vir de uma variável de ambiente/secret manager local, nunca
de um arquivo versionado:

```bash
export BVG_DATABASE_URL='postgresql://[ROLE]:[REDACTED]@127.0.0.1:[PORT]/postgres'
uv run python -m bvg_radar.realtime.runner --max-positions 2
```

Cada evento contém `estimated_next_arrival`, `longitude`, `latitude`,
`bearing_degrees`, `speed_mps`, `source=trip_update_interpolation` e
`is_estimated=true`, seguido por um resumo `ingestion_cycle`. O runner encerra
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

Após a importação e o pós-processamento local, foram verificados:

| Verificação | Resultado |
|---|---:|
| `gtfs.stop_times` carregados | 5.719.111 |
| `shape_fraction` nulo | 0 |
| Frações fora de `[0, 1]` | 0 |
| Segmentos não monotônicos suprimidos | 10.877 |
| TripUpdates recebidos no dry-run ao vivo | 5.828 |
| Posições estimadas impressas no dry-run | 2 |
| Integração opt-in Python → PostGIS | 1 aprovada |
| Testes Python padrão | 140 aprovados, 1 integração ignorada sem opt-in |
| Testes frontend | 23 aprovados |

A regressão de precisão de endpoint também é verificada de forma determinística:
os limites `1.0000000000000002` e `-0.0000000000000002` são normalizados para
`1.0` e `0.0`, respectivamente.

---

## Limites conhecidos

- O feed público validado pode mudar de cobertura e tipo de entidade; valide o
  conteúdo Protobuf antes de assumir que há veículos.
- `TripUpdate` não é `VehiclePosition`; a precisão depende de horários,
  paradas, shapes e atraso disponível.
- Não há serviço FastAPI nem endpoint WebSocket nesta fase; existe apenas o
  contrato, a porta de saída e o dry-run de console para que uma fase posterior
  implemente a entrega.
- Para uma operação contínua, o processo deve aplicar timeout, backoff e limite
  de polling compatíveis com a fonte. O runner atual é deliberadamente
  one-shot; um serviço contínuo deve reutilizar a sessão HTTP e o pool.
