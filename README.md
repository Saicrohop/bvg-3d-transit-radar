# BVG 3D Transit Radar

Radar local para visualização de posições **estimadas** do transporte VBB/BVG
em Berlim. O pipeline mantém o GTFS-Realtime Protobuf exclusivamente no
backend e entrega ao cliente somente eventos JSON normalizados.

> `TripUpdate` não é telemetria GPS. Toda coordenada emitida pelo projeto é uma
> estimativa espacial e sempre inclui
> `source=trip_update_interpolation` e `is_estimated=true`.

## Estado das fases

- **Fase 1:** Supabase/PostGIS local e GTFS estático VBB — concluída.
- **Fase 2:** normalização server-side de `TripUpdate` e interpolação PostGIS — concluída.
- **Fase 3:** servidor FastAPI/WebSocket e cliente terminal de validação — concluída.
- **Fase 4:** frontend visual e modelos 3D categorizados — implementada; S-Bahn usa o asset DB vermelho/creme e U-Bahn, ônibus e tram usam o asset BVG compartilhado.

### Fase 4 — ScenegraphLayer de produção

Eventos normalizados com `vehicle_category` reconhecida são agrupados em
`ScenegraphLayer`s por modelo:

```text
s_bahn → /models/s_bahn_db.glb
u_bahn → /models/bvg_bus.glb
bus    → /models/bvg_bus.glb
tram   → /models/bvg_bus.glb
```

O S-Bahn mantém a calibração de orientação `[0, 180 - heading, 90]`, as
escalas/translações aprovadas e iluminação PBR. Eventos sem categoria ou com
falha de carregamento continuam visíveis como pontos 2D estimados. O asset
`s_bahn_db.glb` foi verificado por SHA-256 antes de ser colocado em
`frontend/public/models/`.

A captura visual de produção depende da disponibilidade de `TripUpdate`s no
feed VBB. Um feed vazio não deve ser substituído por mocks para afirmar que o
modelo está operando ao vivo.

## Pré-requisitos locais

- Docker Desktop em execução;
- Node.js/npm;
- Python 3.11+ e `uv`;
- Supabase local iniciado e GTFS estático importado.

```bash
npm run supabase:start
npm run gtfs:import-local
uv sync --all-groups
```

O importador opera somente sobre o Supabase local. Nunca aponte
`gtfs:import-local` ou `supabase:reset` para um ambiente remoto.

## Fase 3 — servidor WebSocket local

O servidor busca o feed de produção VBB no backend, normaliza `TripUpdate`s,
calcula posições conservadoras no PostGIS e publica somente eventos estimados
em WebSocket.

### 1. Configure o acesso local ao banco

Forneça uma URL PostgreSQL de um papel de serviço local com somente as
permissões necessárias para consultar a função de estimativa. Não salve URL,
senha ou chave em arquivos versionados.

```bash
export BVG_DATABASE_URL='postgresql://[ROLE]:[PASSWORD]@127.0.0.1:54322/postgres'
```

### 2. Inicie o servidor

```bash
npm run ws:serve
```

O serviço é limitado ao loopback e abre:

```text
ws://127.0.0.1:8000/ws/positions
```

Ele reutiliza uma sessão `aiohttp` e um pool `asyncpg`, faz polling responsável
do endpoint de produção `https://production.gtfsrt.vbb.de/data` e envia
somente estimativas seguras. Uma falha temporária no upstream é registrada e o
worker tenta novamente no próximo ciclo.

### 3. Valide pelo terminal

Em outro Git Bash:

```bash
npm run ws:client -- --max-events 2
```

Para continuar escutando até interromper manualmente:

```bash
npm run ws:client -- --max-events 0
```

A saída é JSON Lines semelhante a:

```json
{
  "type": "vehicle_position",
  "source": "trip_update_interpolation",
  "is_estimated": true,
  "trip_id": "…",
  "longitude": 13.405,
  "latitude": 52.52,
  "bearing_degrees": 91.5,
  "speed_mps": 8.2
}
```

O cliente nunca acessa VBB GTFS-Realtime diretamente e não recebe Protobuf.

## Testes de regressão

```bash
npm run test
npm run test:phase2:local
```

A primeira suíte valida os artefatos SQL das Fases 1 e 2 e os testes Python. A
segunda executa a validação integrada contra o PostGIS local com o GTFS
carregado.

## Segurança e limites

- Não versionar `.env`, URLs de banco, senhas, service-role keys ou GTFS operacional.
- O WebSocket publica somente eventos `vehicle_position` normalizados; nunca
  faz relay de Protobuf VBB.
- Posições de loops, ramais ambíguos ou segmentos sem horário confiável são
  suprimidas em vez de fabricadas.
- Longitude/latitude usam WGS84 (EPSG:4326); métricas de bearing e velocidade
  são calculadas em EPSG:25833.
