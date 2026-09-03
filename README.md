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

## Gate de compatibilidade GTFS

Antes de importar ou usar um snapshot GTFS estático, compare seus `trip_id`s
com um snapshot atual do GTFS-Realtime VBB:

```bash
npm run gtfs:check-compatibility
```

O comando não altera arquivos nem o banco. Ele valida o status HTTP, o
`Content-Type` Protobuf e o corpo da resposta, separa viagens `SCHEDULED` e
`CANCELED` das relações excepcionais (`ADDED`, `DUPLICATED` e `UNSCHEDULED`) e
confirma os `route_id`s encontrados. A saída JSON inclui o timestamp do feed,
o parâmetro `schedule_sha256` quando fornecido pelo VBB, contagens e amostras
limitadas de incompatibilidades.

O gate retorna `0` somente quando pelo menos 99% das viagens `SCHEDULED` têm
correspondência em `data/gtfs-static/GTFS/trips.txt`; retorna `1` para snapshot
incompatível e `2` para erro operacional ou entrada inválida. Como o feed é
dinâmico, as contagens exatas variam entre execuções.

## Atualização do GTFS estático VBB

O VBB publica o arquivo GTFS estático oficial em `https://unternehmen.vbb.de/gtfs`
(atualizado duas vezes por semana). O script de atualização:

1. Baixa o ZIP em streaming com `aiohttp`, calculando SHA-256 do arquivo;
2. Extrai em staging isolado com defesa contra *Zip Slip*;
3. Valida os cinco arquivos obrigatórios (`routes.txt`, `trips.txt`, `stops.txt`,
   `shapes.txt`, `stop_times.txt`) e seus cabeçalhos;
4. Verifica se `calendar.txt` fornece intervalo de datas válido;
5. Gera manifest JSON de proveniência (URL, timestamp, SHA-256 do arquivo,
   SHA-256 por arquivo, intervalo do calendário);
6. Troca o snapshot antigo de forma atômica (`staging.replace(output)`);
7. Mantém o ZIP apenas com `--keep-archive`.

```bash
npm run gtfs:update-static
```

Saída JSON (com `--json`) inclui o manifest completo e `status: "installed"`.
O comando falha com exit `2` se download, validação ou troca não puderem ser
concluídos.

Após a atualização, repita o gate de compatibilidade:

```bash
npm run gtfs:check-compatibility
```

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

## 🚇 Berlin 3D Transit Radar & Analytics

Ever wondered if your S-Bahn is actually on time, or if it's just an urban legend? Welcome to the Berlin Transit Radar! 🐻✨

This project is more than just a map; it's a real-time, 3D heartbeat of Berlin's entire public transport network (VBB/BVG). I'm building this open platform not just to watch yellow buses and red trains cruise around the city in glorious 3D, but to bring real data transparency to our daily commute.

### 🎯 The Grand Vision

Currently, the radar tracks live vehicles across the city. But the ultimate goal is to turn this into the ultimate transit analytics hub for Berliners:

🏆 **The Efficiency Leaderboard:** Which lines are actually carrying the city on their backs? We will track and rank the most efficient and punctual routes.

🐌 **The Delay Wall of Shame:** Real-time data doesn't lie. We'll identify the lines that are constantly late so you know exactly what to avoid.

🚨 **Smart Commute Alerts:** Say goodbye to waiting on a freezing platform. The platform will push real-time alerts for delays, disruptions, or bottlenecks on your specific daily routes.

Grab your Club-Mate, watch the U-Bahn navigate the city in real-time, and let's bring some data-driven justice to our public transit! 🚦📊
