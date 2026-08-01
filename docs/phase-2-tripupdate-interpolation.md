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

Ele retorna Protobuf GTFS-Realtime. A amostra validada continha `TripUpdate`s,
não `VehiclePosition`s. Portanto latitude, longitude, bearing e velocidade
produzidos nesta fase são **estimativas**, não telemetria GPS observada.

Não use `https://staging.gtfsrt.vbb.de/data` como fonte operacional.

---

## Artefatos

| Arquivo | Finalidade |
|---|---|
| `supabase/migrations/20260719110000_trip_update_interpolation.sql` | Cria `gtfs.stop_times`, a função de conversão de horário GTFS e `gtfs.estimate_trip_position(...)`. |
| `supabase/migrations/20260719113000_clamp_stop_shape_fraction.sql` | Corrige precisão IEEE-754 de `ST_LineLocatePoint` nos endpoints de linha. |
| `supabase/sql/phase_2_import_vbb_static_local.sql` | Recarrega o GTFS estático, incluindo `stop_times.txt`, apenas localmente. |
| `supabase/sql/phase_2_after_stop_times_import.sql` | Pré-calcula `shape_fraction`, cria índice e executa `ANALYZE`. |
| `src/bvg_radar/realtime/source.py` | Busca assíncrona Protobuf com `aiohttp` e reutilização de ETag. |
| `src/bvg_radar/realtime/normalization.py` | Converte Protobuf em DTOs sem vazar tipos do transporte. |
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

Com Supabase local ativo e o GTFS importado, execute a integração PostGIS:

```bash
npm run test:phase2:local
```

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
| `gtfs.stop_times` carregados | 5.799.125 |
| `shape_fraction` nulo | 0 |
| Frações fora de `[0, 1]` | 0 |
| Segmentos não monotônicos suprimidos | 13.229 |
| TripUpdates recebidos no dry-run ao vivo | 7.052 |
| Posições estimadas impressas no dry-run | 2 |
| Testes Python | 9 aprovados |

A regressão de precisão de endpoint também foi reproduzida e tratada: o valor
bruto `1.0000000000000002` é persistido como `1.0`.

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
