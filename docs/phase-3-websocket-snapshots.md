# Fase 3 — snapshots WebSocket de posição

## Escopo do P8

O backend publica uma visão completa e versionada das posições estimadas de cada
ciclo GTFS-Realtime aceito. O navegador nunca recebe nem interpreta Protobuf da
VBB.

O P8 foi concluído como incremento **backend-only**. O frontend Orbital agora
consome o envelope v1 com validação integral antes de substituir o estado,
remoção de IDs ausentes, limpeza em snapshot vazio válido e preservação do
último snapshot em entrada inválida. Mensagens do contrato incremental legado não
são aceitas.

A inspeção visual 3D está `deferred_hardware` e será feita exclusivamente pelo
usuário. Não executar browser, screenshots ou WebGL: há instabilidade de
GPU/fonte. Testes CPU e probes HTTP/WebSocket não validam os pixels do mapa.

## P9 — ciclo de conexão e atualidade

O hook do frontend separa estados de transporte e dados:

- transporte: `connecting`, `open`, `reconnecting`, `error`, `closed`;
- dados: `awaiting`, `fresh`, `stale`;
- backoff inicial de reconexão: `1000 ms`;
- teto de backoff: `30000 ms`;
- jitter limitado: `20%`;
- stale após `45000 ms` sem snapshot válido recente;
- tolerância de relógio futuro: `5000 ms`.

A reconexão preserva o último snapshot da mesma origem, ignora callbacks de
sockets antigos e começa vazia quando a URL muda. Mensagens inválidas não
renovam o relógio de frescor. Um snapshot vazio válido é autoritativo e limpa as
posições; uma falha operacional ou um `304` não produz limpeza sintética.
O contador de backoff só é reiniciado depois de um snapshot válido. Sockets que
abrem/fecham sem dados aceitos continuam aumentando a espera; JSON inválido não
conta como progresso.

P9 foi validado com Vitest/jsdom e mocks de mapa. Isso comprova lógica de
estado, não layout, modelos, pixels, FPS, temperatura, consumo de GPU ou
estabilidade da fonte.

## Contrato de transporte

Cada mensagem de sucesso em `ws://127.0.0.1:8000/ws/positions` é um snapshot
completo:

```json
{
  "type": "vehicle_position_snapshot",
  "schema_version": 1,
  "cycle_id": "d1dcfd11-f6df-52e1-9f85-02be9c230bbc",
  "feed_timestamp": "2026-07-19T10:38:20Z",
  "observed_at": "2026-07-19T10:40:00Z",
  "positions": [
    {
      "type": "vehicle_position",
      "source": "trip_update_interpolation",
      "is_estimated": true,
      "position_status": "estimated_from_trip_update",
      "timing_source": "realtime_delay",
      "feed_timestamp": "2026-07-19T10:38:20Z",
      "trip_update_timestamp": "2026-07-19T10:39:55Z",
      "service_date": "2026-07-19",
      "vehicle_category": "s_bahn",
      "route_short_name": "S41",
      "entity_id": "entity-42",
      "trip_id": "trip-42",
      "route_id": "route-s41",
      "shape_id": "shape-s41",
      "previous_stop_id": "stop-1",
      "next_stop_id": "stop-2",
      "delay_seconds": 30,
      "estimated_next_arrival": "2026-07-19T10:42:00Z",
      "longitude": 13.405,
      "latitude": 52.52,
      "bearing_degrees": 91.5,
      "speed_mps": 8.2,
      "observed_at": "2026-07-19T10:40:00Z"
    }
  ],
  "statistics": {
    "trip_updates_received": 1,
    "positions_estimated": 1,
    "positions_suppressed": 0
  }
}
```

Invariantes do envelope:

- `type` é `vehicle_position_snapshot` e `schema_version` é exatamente `1`;
- `cycle_id` é não vazio e determinístico para a identidade do ciclo;
- timestamps são timezone-aware e serializados em UTC com sufixo `Z`;
- cada `trip_id` aparece no máximo uma vez;
- todas as posições têm o mesmo `feed_timestamp` e `observed_at` do envelope;
- contadores são inteiros não negativos; booleanos não são aceitos;
- `positions_estimated == positions.length`;
- `positions_estimated + positions_suppressed == trip_updates_received`.

Uma posição continua sendo interpolada a partir de `TripUpdate` e GTFS estático;
não é uma observação GPS. `schedule_only` continua com `delay_seconds: null`.

## Semântica de ciclo

| Resultado da fonte | Publicação |
|---|---|
| HTTP 200 válido e atualizado | exatamente um snapshot completo |
| HTTP 200 válido sem entidades ou posições seguras | um snapshot com `positions: []` |
| HTTP 304 `Not Modified` | nenhuma mensagem nova |
| falha de download, parse, estimativa ou serialização | nenhuma limpeza sintética |

O snapshot vazio é estado novo e autoritativo: o frontend substitui o conjunto
anterior por vazio. Uma falha operacional ou um 304 preserva o último estado
aceito; conexão aberta não garante atualidade do feed.

O upstream autoritativo aceita somente `FULL_DATASET`; `DIFFERENTIAL`, enums
desconhecidos e incrementality malformada são rejeitados antes de avançar ETag. Timestamps absolutos do header/TripUpdate/StopTime também
precisam ser representáveis pela conversão UTC da plataforma; entrada inválida
é rejeitada antes de ocupar a pendência. O download usa streaming com teto padrão de 64 MiB de bytes decodificados.

Depois de receber um ciclo atualizado, uma falha transitória de estimativa,
serialização ou publicação deixa **um único ciclo pendente em memória**. Falhas
determinísticas tipadas de contrato descartam o ciclo inválido para permitir a
próxima busca; uma exceção genérica de uma porta externa não é presumida permanente.
Antes de buscar outro
feed, o worker repete esse ciclo usando `observed_at` e limite originais. Isso
impede que o ETag seguido de 304 torne o ciclo perdido. Após publicação
bem-sucedida a pendência é removida; um 304 normal não republica. Retry não é
fila durável: restart perde a pendência; uma publicação parcialmente aplicada
pode repetir o mesmo cycle_id. Não há garantia exactly-once.

O cliente de terminal valida o envelope inteiro e rejeita o legado. Aceita
snapshot vazio válido e configura frame máximo de **8 MiB**. `--max-events N`
conta envelopes aceitos, não o número de posições dentro deles.

## Hub WebSocket

O `PositionWebSocketHub`:

- retém uma cópia do último snapshot mesmo sem clientes conectados;
- registra o cliente e captura o estado atual sob um lock curto;
- usa um lock de envio por cliente para garantir replay antigo antes de
  publicação nova sem serializar replays de clientes diferentes;
- reproduz imediatamente somente o snapshot mais recente para um cliente novo;
- serializa publicações concorrentes para manter a ordem dos ciclos;
- envia cópias isoladas aos clientes em paralelo;
- limita cada envio por `BVG_WS_SEND_TIMEOUT_SECONDS` (padrão: `1` segundo);
- remove clientes que falham ou excedem o timeout e notifica o endpoint para
  cancelar o receive pendente e fechar o socket, sem bloquear clientes saudáveis.

Configuração local relevante:

```bash
export BVG_DATABASE_URL='postgresql://[ROLE]:***@127.0.0.1:55031/postgres'
export BVG_WS_SEND_TIMEOUT_SECONDS='1'
npm run ws:serve
```

Nunca versione a URL real, senha, chave de serviço ou conteúdo operacional do
feed.

## Benchmark e diagnóstico

O benchmark distingue explicitamente:

- `positions_published`: quantidade de posições dentro do envelope;
- `snapshots_published`: quantidade de envelopes publicados (`1` por ciclo
  atualizado, inclusive vazio; `0` para 304);
- `payload_bytes`: JSON do envelope inteiro;
- `contract_serialization_seconds`: soma da serialização das posições;
- `publication_json_seconds`: serialização/publicação do único envelope em sink
  local, não fan-out real nem renderização no browser.

O resumo agora separa `performance_passed` e `data_gate_passed`; `passed` é a
conjunção. O smoke de dados exige posições em pelo menos um ciclo da amostra;
ciclos atualizados vazios e 304 individuais continuam legítimos. Isso não prova
cobertura da frota nem compatibilidade estática representativa.

O script rotula `scenario=full_download_per_cycle`, cria uma source por
iteração e não mede economia de requests condicionais. P95 usa nearest rank,
informa tamanho da amostra, sinaliza menos de 20 amostras e nunca é declarado
prova de carga sustentada. Os limites de duração/configuração são finitos e
positivos. O gate P13-A live continua separado dos testes CPU/sintéticos.

## Validação backend

```bash
uv run pytest \
  tests/test_estimated_vehicle_position_contract.py \
  tests/test_trip_update_worker.py \
  tests/test_trip_update_worker_integration.py \
  tests/test_websocket_hub.py \
  tests/test_websocket_server.py \
  tests/test_realtime_runner.py \
  tests/test_realtime_cycle_benchmark.py -q
```

A aceitação ao vivo deve registrar, sem credenciais: IDs de ciclos consecutivos,
timestamps, contagem de posições, diferenças de `trip_id` e replay imediato para
um cliente conectado depois da primeira publicação.
