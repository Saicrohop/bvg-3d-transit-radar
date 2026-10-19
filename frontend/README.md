# Orbital frontend

Frontend React/TypeScript/Vite do BVG 3D Transit Radar. A aplicação recebe
somente snapshots JSON normalizados do backend local; não baixa nem interpreta o
Protobuf GTFS-Realtime da VBB.

## Estado do produto

- O consumidor usa o envelope `vehicle_position_snapshot`, `schema_version: 1`.
- Um snapshot válido substitui a lista inteira. Um snapshot vazio válido limpa a
  lista. Mensagens inválidas preservam o último snapshot aceito.
- O P9 adiciona reconexão automática com backoff inicial de 1 s, teto de 30 s e
  jitter limitado de 20%.
- Estados de transporte: `connecting`, `open`, `reconnecting`, `error` e
  `closed`.
- Estados de dados: `awaiting`, `fresh` e `stale`. O limite padrão de atualidade
  é 45 s; timestamps até 5 s no futuro são tolerados para relógios desalinhados.
- Posição é estimativa por `TripUpdate`/GTFS estático, nunca GPS.

## Lite padrão / 3D opt-in

- **LITE / 2D** é o padrão: MapLibre com GeoJSON/círculos por categoria, câmera superior e resolução `pixelRatio: 1`. Não monta Deck, GLBs, TextLayer ou extrusões de edifícios.
- **3D opcional** só é importado ao escolher o botão. Usa os cinco modelos versionados integrados na O3, com PBR e calibração matemática CPU. Não há prewarm de GLBs no início da aplicação.
- **Sem mapa** desmonta o renderer e mantém os dados, busca, filtros, inspeção e WebSocket. Para começar sem importar nenhum renderer, usar `/?map=off`. A URL `?map=3d` não habilita 3D; é necessária uma escolha explícita na interface.
- Trocar de renderer recria a câmera a partir da vista padrão ou da última solicitação de localização; não há persistência de pan/zoom entre Lite e 3D.
- Lite ainda usa GPU. Nenhum destes modos certifica segurança do hardware ou FPS.

No 3D, o viewport é lido no load e em `moveend`; cada snapshot usa o viewport mais recente. Fora da tela não consome o orçamento. Abaixo de zoom 12,5 só há pontos; a partir daí são no máximo **250 modelos** visíveis, com desconhecidos, falhas de asset e excedentes como pontos. Labels entram em zoom ≥14,5 e são limitadas a **100**. Estes limites são políticas conservadoras, não um limiar medido como seguro para esta GPU/fonte.

Categorias vazias não criam ScenegraphLayers. Dados são ordenados por `trip_id` sem mutar o snapshot, mas a interpolação de 1000 ms só é habilitada quando a identidade ordenada de cada camada continua igual (e sem movimento reduzido). Inclusão, remoção, troca de categoria ou alteração dos textos de labels invalida a continuidade; ordenar sozinho não impede um índice de representar outra viagem.

O build gera `dist/renderer-boundary.json` e `.vite/manifest.json`. Um gate atravessa os imports estáticos transitivos do shell e do Lite e falha se encontrar Deck/luma/loaders/módulos 3D. Isso verifica dependências, não pixels. O chunk comum de MapLibre ainda é grande e o warning de tamanho permanece visível.

### Modelos integrados — O3, 2026-10-18

Os GLBs em `public/models/lowpoly/` são cópias exatas da entrega: ônibus v3,
U-Bahn v2, S-Bahn v1, Tram v1 e Regional v2. O usuário aprovou explicitamente
a geometria mais detalhada; nenhuma decimação ou troca de material foi feita.
O conjunto soma 614.492 bytes. Os GLBs antigos permanecem preservados no diretório pai.

U-Bahn possui `ScenegraphLayer` e chave de falha próprios; não reutiliza o ônibus.
Os modelos estão em metros, com escala 1, translação zero e orientação
`[0, 180 - heading, 90]`, a partir de +Y up/frente declarada +Z. Testes CPU usam
o atualizador de matrizes instalado do Deck e os bounds dos arquivos exportados
para conferir cardeais, vertical e contato com o chão. Labels usam altura do
modelo + 2 m. Isso não substitui confirmação visual do usuário.

Ver `public/models/lowpoly/README.md` e `../docs/low-poly-model-delivery.md`.
Os limites de 250 modelos/100 labels, fallback em pontos, Lite padrão e 3D
opt-in permanecem inalterados; a integração não aprova o gate gráfico.

## Atualizações com a aba oculta — O2

O shell/painéis, parsing, WebSocket e política de frescor continuam funcionando
normalmente. Apenas as props encaminhadas ao mapa ficam no último estado visível;
no retorno, recebem diretamente o snapshot aceito mais recente, inclusive vazio.
Não existe fila de snapshots gráficos intermediários nem alteração do contrato v1.

Se a página começar oculta, nenhum módulo de mapa é solicitado até ficar visível.
Se um import já em andamento resolver depois de ocultar a aba, cada adapter espera
sua primeira visibilidade antes de construir MapLibre/overlay. `Sem mapa` sempre
desmonta o renderer, mesmo na aba oculta, sem reativá-lo no retorno.

Um renderer já criado **permanece montado** para preservar câmera e falhas
latched, evitando retry gráfico automático em hide/show. Esta é pausa do repasse
de novos dados, não desligamento completo da engine: animações/pedidos internos
já em andamento podem continuar. Não comprova zero GPU, VRAM ou tráfego nem torna
o hardware seguro. Para liberar o renderer, usar **Sem mapa**.

Esses comportamentos são testados em CPU/jsdom com renderers mockados; não são
medição de uma aba real nem aceite visual.

## Executar localmente

Na raiz do projeto:

```bash
npm --prefix frontend install
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

O backend deve publicar em:

```text
ws://127.0.0.1:8000/ws/positions
```

O endpoint pode ser substituído sem editar o código:

```bash
export VITE_POSITIONS_WS_URL='ws://127.0.0.1:8000/ws/positions'
```

O browser deve receber apenas JSON normalizado. A URL GTFS-RT da VBB e a URL do
banco pertencem ao backend e não devem aparecer no frontend.

## Verificações não visuais

```bash
npm --prefix frontend run test
npm --prefix frontend run lint
npm --prefix frontend run build
```

A suíte usa Vitest/jsdom e mocks de mapa para testar contrato, reconexão,
frescor, filtros e integração de estado. O P12 usa `LazyRadarMap` para manter o
shell independente do chunk gráfico: no checkpoint histórico P12 o JS inicial caiu de 2.135.235 B para
212.818 B. Esse resultado histórico não significava que o mapa era opt-in; a separação Lite/3D é um incremento posterior. O chunk do mapa continua reportado separadamente; nenhuma dessas
medições representa FPS, consumo de GPU, potência ou tempo até mapa utilizável.

## Limite de hardware e aceite visual

Por instabilidade causada por carga de GPU e potência da fonte, não executar
browser automatizado, screenshots, Playwright, WebGL/WebGPU, picking, FPS ou
qualquer verificação visual neste ambiente. O gate visual está
`deferred_hardware` e será inspecionado manualmente pelo usuário depois da troca
da fonte e de autorização explícita.

A existência de `RadarMap`, `ScenegraphLayer` ou arquivos `.glb` não significa
que o aceite visual foi concluído. Os arquivos legados permanecem preservados;
os novos modelos possuem apenas aceite estrutural/matemático CPU. O simulador
de cidade/trânsito e Analytics são escopos futuros separados.

## Estrutura principal

- `src/App.tsx` — composição da aplicação e endpoint configurável;
- `src/realtime/vehiclePositions.ts` — tipos e validação do snapshot v1;
- `src/realtime/connectionPolicy.ts` — backoff e política de atualidade;
- `src/realtime/useEstimatedVehiclePositions.ts` — WebSocket, reconexão e estado;
- `src/ui/OrbitalRadar.tsx` — shell, filtros e avisos de estado;
- `src/ui/LazyRadarMap.tsx` — limites dinâmicos Lite/3D/Off e isolamento de falha;
- `src/map/mapTypes.ts` — props neutras, sem dependência runtime de renderer;
- `src/map/MapLibreLite.tsx` e `liteVehicleLayer.ts` — adapter e conversor de pontos nativos;
- `src/map/RadarMap.tsx` — MapLibre/Deck.gl opt-in;
- `src/map/renderPolicy.ts` e `transitionIdentity.ts` — budgets/viewport e continuidade por camada;
- `build/rendererBoundary.ts` — gate de isolamento do bundle.

As mudanças de política e wiring têm testes CPU/mockados. Aparência, orientação visual e estabilidade elétrica continuam fora desse aceite.
