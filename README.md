# BVG 3D Transit Radar

Radar local para visualização de posições **estimadas** do transporte VBB/BVG
em Berlim. O pipeline mantém o GTFS-Realtime Protobuf exclusivamente no
backend e entrega snapshots JSON normalizados ao cliente terminal e ao frontend
Orbital. A adoção do envelope v1 e a reconexão P9 foram implementadas; a
inspeção visual desta integração permanece pendente, exclusivamente a cargo do
usuário.

> `TripUpdate` não é telemetria GPS. Toda coordenada emitida pelo projeto é uma
> estimativa espacial e sempre inclui
> `source=trip_update_interpolation` e `is_estimated=true`.

## Estado das fases

- **Fase 1:** Supabase/PostGIS local e GTFS estático VBB — concluída.
- **Fase 2:** normalização server-side de `TripUpdate` e interpolação PostGIS — concluída.
- **Fase 3:** servidor FastAPI/WebSocket e cliente terminal de validação — concluída.
- **Frontend:** MapLibre **Lite por padrão** (pontos nativos, sem Deck/GLBs); **3D opcional** por escolha explícita e **Sem mapa** para manter apenas os painéis. Os cinco novos low-poly foram integrados em 2026-10-18, com geometria original preservada e U-Bahn dedicado. Os arquivos antigos permanecem preservados como legado.
- **P12:** bundle inicial reduzido com `LazyRadarMap`; verificado por testes CPU, lint e build. O chunk gráfico pesado permanece separado e o warning não foi ocultado.
- **P13-A:** configuração migrada para API `55030`, banco `55031`, Studio `55032` e email local `55033`, com guardas compartilhadas e testes CPU. `npm run runtime:check` fornece descoberta offline fail-closed, sem iniciar serviços nem consultar banco; exit 0 não representa aceite live. Gate live continua pendente: em 2026-10-17 Docker/CLI não foram encontrados; os testes PostGIS antigos são evidência histórica, não prova do estado atual.
- **P13-V:** gate visual 3D permanece `deferred_hardware`, sem browser, screenshots, WebGL ou GPU.

### Fase 4 — ScenegraphLayer de produção

O frontend Orbital consome snapshots v1 com validação atômica, substituição
integral das posições e preservação do último estado em mensagens inválidas.
Inclui busca, filtros, inspeção de viagem, controle de câmera e movimento
reduzido. A integração O3 adota os modelos versionados abaixo com calibração matemática em CPU; a inspeção visual permanece manual/pendente.

### Lite / 3D opcional — correções de 2026-10-14

- **LITE / 2D:** MapLibre com uma fonte GeoJSON e círculos por categoria, câmera superior, `pixelRatio: 1`, sem extrusões nem camadas Deck. Seleção, busca, filtros e localização continuam usando o snapshot real aceito.
- **3D opcional:** só o botão carrega o módulo Deck; não há preload/prefetch de GLBs no boot. O detalhe continua limitado por zoom, viewport e orçamento explícito de instâncias. Os novos GLBs usam PBR, escala métrica e transformação de eixos testada em CPU, sem extrapolar aceite visual.
- **Sem mapa:** desmonta o renderer e preserva telemetria/painéis. A escolha de modo não reinicia o WebSocket. Lite ainda usa GPU; não equivale a modo CPU nem a certificação de segurança elétrica.
- O build tem um gate que percorre dependências estáticas do entry e do Lite e rejeita Deck/luma/loaders ou módulos 3D nessa cadeia. O relatório é `frontend/dist/renderer-boundary.json`; não mede download real, FPS ou VRAM.
- Modelos O3: veja `docs/low-poly-model-delivery.md` e `frontend/public/models/lowpoly/README.md`. As versões aprovadas foram copiadas sem reexport/decimação; os GLBs antigos não foram sobrescritos.

Correções funcionais incluem CLI estrito de snapshots v1 (inclusive vazio e frame de 8 MiB), backoff reiniciado somente após snapshot válido, retry em memória de um ciclo pendente com `observed_at` original, rejeição de feed diferencial e limite upstream de 64 MiB decodificados. Configurações temporais exigem valores finitos positivos. O benchmark separa performance de smoke de dados: zero estimativas na amostra não aprova o resultado geral.

O servidor **opcional** de métricas passou a usar SQLite read-only, cutoff Unix UTC, rótulos desconhecidos como `null`, CORS/contexto loopback restrito e endpoints síncronos executados no threadpool. Isso não é autenticação e não é alteração no HTML independente de Mission Control. Consumidores antigos precisam aceitar os novos `null`/status `open` e `ended`; sucesso de sessão ou agente vivo não é inferido de registros históricos.

**Segurança de hardware:** não executar verificações de browser, screenshots,
WebGL ou 3D nesta máquina. O usuário relata crashes por carga de GPU/fonte e
fará a inspeção visual manualmente. Testes CPU, build e serviços locais não
constituem validação visual. Não abrir o radar automaticamente.

Posições normalizadas com `vehicle_category` reconhecida são agrupadas em
`ScenegraphLayer`s por modelo:

```text
s_bahn → /models/lowpoly/s_bahn_lowpoly_v1.glb
u_bahn → /models/lowpoly/u_bahn_lowpoly_v2.glb
bus    → /models/lowpoly/bvg_bus_lowpoly_v3.glb
tram   → /models/lowpoly/bvg_tram_lowpoly_v1.glb
regional → /models/lowpoly/regional_lowpoly_v2.glb
```

Os cinco modelos usam `[pitch, yaw, roll] = [0, 180 - heading, 90]`, escala 1 e
translação zero. A conversão foi testada com a matriz CPU do Deck instalado:
frente declarada +Z, altura +Y e base Y=0 no GLB passam ao frame do mapa. Isso
não confirma visualmente a ponta física. Labels ficam 2 m acima da altura de
cada modelo. Eventos sem categoria ou com falha continuam visíveis como pontos;
falhas de ônibus e U-Bahn agora são independentes. As cinco cópias preservam os
SHA-256 da entrega e somam 614.492 bytes, sem redução da geometria aprovada.

> **Estado da validação:** `functional_gate` pode ser validado com testes CPU,
> SQL, integração PostGIS read-only e probes de transporte. O gate visual está
> `deferred_hardware`: não executar browser, screenshots, WebGL ou 3D nesta
> máquina. A inspeção dos pixels será manual após a atualização da fonte e
> autorização explícita.

## Pré-requisitos locais

- Docker Desktop em execução;
- Node.js/npm;
- Python 3.11+ e `uv`;
- Supabase local iniciado e GTFS estático importado.

```bash
npm run runtime:check
uv sync --all-groups
```

Para retomar um ambiente existente, siga primeiro a descoberta e o inventário
em `docs/local-environment.md`. O preflight não inicia a stack nem comprova os
dados: confirme o contexto Docker local e os containers/volumes antes de decidir
qualquer startup. Importar GTFS é manutenção separada, não solução para recuperar
runtime ou forwarding; não use reset para nenhuma dessas operações.

O importador opera somente sobre o Supabase local identificado. Nunca o aponte
para um ambiente remoto.

A importação agora inclui tabelas e derivados em **uma transação**, com health gate antes do commit. É manutenção com locks: pausar o worker/leitores antes e retomar somente depois da validação. Não é troca online sem bloqueio. A correção recebeu validação CPU/estrutural, não uma execução real de import/rollback PostGIS nesta etapa. Nunca usar reset para atualizar o GTFS.

## P9 — conexão e atualidade

O frontend separa transporte de atualidade. O transporte expõe `connecting`,
`open`, `reconnecting`, `error` e `closed`. Os dados expõem `awaiting`, `fresh`
e `stale`, com motivos de proveniência temporal. O backoff começa em 1 s, cresce
exponencialmente até 30 s e usa jitter limitado de 20%. Após 45 s sem snapshot
válido recente, o último snapshot pode permanecer visível com aviso de dados
antigos; ele não é apresentado como frota ativa. Timestamps até 5 s no futuro
são tolerados; timestamps inválidos ou além desse limite tornam o estado stale.
Abrir e fechar sockets sem um snapshot válido não reinicia a progressão do backoff.

A implementação foi coberta por Vitest/jsdom e mocks de mapa. Isso comprova
transições de estado, não layout, pixels, FPS, consumo de GPU ou estabilidade da
fonte.

## Fase 3 — servidor WebSocket local

O servidor busca o feed de produção VBB no backend, normaliza `TripUpdate`s,
calcula posições conservadoras no PostGIS e publica um snapshot versionado e
atômico por ciclo atualizado. Cada snapshot contém apenas estimativas
normalizadas; nunca contém o Protobuf original.

### 1. Configure o acesso local ao banco

Forneça uma URL PostgreSQL de um papel de serviço local com somente as
permissões necessárias para consultar a função de estimativa. Não salve URL,
senha ou chave em arquivos versionados.

```bash
export BVG_DATABASE_URL='postgresql://[ROLE]:[PASSWORD]@127.0.0.1:55031/postgres'
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
do endpoint de produção `https://production.gtfsrt.vbb.de/data` e envia somente
estimativas seguras. Uma falha temporária no upstream é registrada e o worker
tenta novamente no próximo ciclo. O hub retém o snapshot mais recente para
clientes novos e limita cada envio por `BVG_WS_SEND_TIMEOUT_SECONDS` (padrão:
`1` segundo), removendo clientes lentos sem bloquear os demais.

> **Limite atual:** P8, P9, P10, P11 e P12 estão implementados no escopo
CPU-only. P12 separa o mapa em `LazyRadarMap` e reduziu o JavaScript inicial de
2.135.235 B para 212.818 B. P13-A passou nos testes estáticos, suites CPU e
> PostGIS interno read-only em checkpoints anteriores, mas a integração host/WebSocket e o benchmark live
> aguardam disponibilização do Docker e inventário dos volumes existentes. Em 2026-10-17 a antiga exclusão de portas não apareceu mais; não assumir que o bloqueio histórico continua sendo a causa atual. A verificação
visual 3D está `deferred_hardware` e será realizada somente pelo usuário. P13-V
depende da atualização da fonte e de autorização explícita.

### 3. Valide pelo terminal

Em outro Git Bash:

```bash
npm run ws:client -- --max-events 2
```

Para continuar escutando até interromper manualmente:

```bash
npm run ws:client -- --max-events 0
```

A saída é JSON Lines, com um envelope completo por ciclo atualizado:

```json
{
  "type": "vehicle_position_snapshot",
  "schema_version": 1,
  "cycle_id": "…",
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
      "trip_update_timestamp": "2026-07-19T10:38:18Z",
      "service_date": "2026-07-19",
      "vehicle_category": "s_bahn",
      "route_short_name": "S41",
      "entity_id": "…",
      "trip_id": "…",
      "route_id": "…",
      "shape_id": "…",
      "previous_stop_id": "…",
      "next_stop_id": "…",
      "delay_seconds": 42,
      "estimated_next_arrival": "2026-07-19T10:41:02Z",
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

Um HTTP 200 válido sem posições seguras ainda publica um snapshot com
`positions: []`; um HTTP 304 não publica mensagem nova. Consulte
[`docs/phase-3-websocket-snapshots.md`](docs/phase-3-websocket-snapshots.md) para
o contrato completo.

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

A fonte oficial é a página [Offene Datensätze des VBB](https://unternehmen.vbb.de/digitale-services/datensaetze/),
cujo download GTFS aponta para `https://unternehmen.vbb.de/gtfs`. O atualizador:

1. Baixa o ZIP para um arquivo temporário em streaming, calculando SHA-256 na
   mesma passagem;
2. Extrai em staging isolado com defesa contra *Zip Slip*;
3. Valida os cinco arquivos obrigatórios (`routes.txt`, `trips.txt`, `stops.txt`,
   `shapes.txt`, `stop_times.txt`), seus cabeçalhos e o intervalo de
   `calendar.txt`;
4. Baixa um snapshot GTFS-RT e só aceita evidência que contenha timestamp,
   tenha no máximo 900 segundos de idade (com tolerância de 120 segundos para
   relógio adiantado), represente pelo menos 1.000 `trip_id` `SCHEDULED` únicos
   e esteja coberta pelo calendário do candidato em `Europe/Berlin`;
5. Exige ao menos 99% de correspondência dos `trip_id` únicos e nenhuma
   divergência confirmada de `route_id` contra o `trips.txt` **em staging**;
6. Gera o manifest JSON de proveniência com URL, timestamps UTC de download e
   instalação, SHA-256 do ZIP recalculado no ponto de instalação, SHA-256 de
   todos os arquivos regulares, intervalo do calendário e a evidência completa
   que autorizou a promoção: instante da checagem, idade/data do feed, política
   efetiva e todos os campos do relatório de compatibilidade;
7. Renomeia o snapshot anterior para backup temporário, promove o staging e
   substitui o manifest; qualquer falha de troca restaura o snapshot anterior;
8. Remove arquivos temporários em sucesso ou erro. `--keep-archive` preserva o
   ZIP validado em `data/gtfs-static/gtfs.zip`.

```bash
npm run gtfs:update-static
```

A política pode ser ajustada explicitamente pelo CLI, por exemplo:

```bash
npm run gtfs:update-static -- \
  --minimum-unique-scheduled-trips 1000 \
  --max-feed-age-seconds 900 \
  --max-future-skew-seconds 120
```

Reduzir esses limites enfraquece o gate e deve ficar restrito a diagnóstico
controlado. A saída JSON informa `compatibility_policy`, o manifest e o
relatório de compatibilidade, incluindo contagens brutas e de `trip_id` únicos.
Os códigos de saída são `0` para instalação concluída, `1` para candidato válido
porém incompatível e `2` para falha operacional ou entrada inválida. O comando
não importa dados no PostGIS e não executa `supabase db reset`.

Depois da instalação, repita o gate independente:

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
- O WebSocket publica somente snapshots `vehicle_position_snapshot` versionados,
  contendo posições `vehicle_position` normalizadas; nunca faz relay de Protobuf
  VBB.
- Posições de loops, ramais ambíguos ou segmentos sem horário confiável são
  suprimidas em vez de fabricadas.
- Longitude/latitude usam WGS84 (EPSG:4326); métricas de bearing e velocidade
  são calculadas em EPSG:25833.

## 🚇 Berlin 3D Transit Radar & Analytics

Ever wondered if your S-Bahn is actually on time, or if it's just an urban legend? Welcome to the Berlin Transit Radar! 🐻✨

This project is more than just a map; it's a real-time, 3D heartbeat of Berlin's entire public transport network (VBB/BVG). I'm building this open platform not just to watch yellow buses and red trains cruise around the city in glorious 3D, but to bring real data transparency to our daily commute.

### 🎯 The Grand Vision

### Direção futura: Analytics e simulador

A interface atual não implementa Analytics persistente, ranking de linhas,
alertas inteligentes nem um simulador de cidade/trânsito. Esses recursos exigem
fases próprias após o gate funcional/dados e aprovação de suas definições. A
renderização 3D existente é uma camada de visualização do snapshot, não uma
simulação física do tráfego.

Currently, the backend tracks live **estimated** vehicle positions across the
city. The production UI consumes the versioned snapshot contract and P9
connection/freshness states; the visual gate remains `deferred_hardware` until
manual inspection is authorized.

🏆 **The Efficiency Leaderboard:** Which lines are actually carrying the city on their backs? We will track and rank the most efficient and punctual routes.

🐌 **The Delay Wall of Shame:** Real-time data doesn't lie. We'll identify the lines that are constantly late so you know exactly what to avoid.

🚨 **Smart Commute Alerts:** Say goodbye to waiting on a freezing platform. The platform will push real-time alerts for delays, disruptions, or bottlenecks on your specific daily routes.

Grab your Club-Mate, watch the U-Bahn navigate the city in real-time, and let's bring some data-driven justice to our public transit! 🚦📊
