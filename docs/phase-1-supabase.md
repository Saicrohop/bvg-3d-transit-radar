# Fase 1 — Supabase/PostGIS e GTFS estático VBB

## Limite desta fase

Esta fase cria somente a fundação espacial e o armazenamento de GTFS estático:

```text
GTFS estático VBB (.txt) ──> Supabase/PostGIS (schema gtfs)
                                      ├─ stops.geom (Point, EPSG:4326)
                                      └─ route_shapes_geom (LineString por shape)
```

O desenho completo está confirmado: o feed **GTFS-RT Protobuf jamais será baixado ou interpretado pelo navegador**. Nas fases seguintes, somente o backend Python o buscará/processará e o frontend receberá mensagens já normalizadas por WebSocket.

Nenhum código de Python, FastAPI, WebSocket, React, MapLibre ou Deck.gl faz parte deste documento.

---

## Artefatos entregues

| Arquivo | Quando executar | Finalidade |
|---|---|---|
| `supabase/migrations/20260717163000_gtfs_static_postgis.sql` | Antes da carga | Habilita PostGIS, cria o schema privado `gtfs`, as quatro tabelas GTFS, RLS e a materialized view vazia. |
| `scripts/validate_vbb_gtfs_static.py` | Antes da carga local | Confere os cabeçalhos da exportação VBB atualmente suportada. |
| `supabase/sql/phase_1_import_vbb_static_local.sql` | Durante a carga local | Faz a carga por `\copy` dentro de uma transação sem conceder permissões de leitura de arquivos ao servidor. |
| `supabase/sql/phase_1_after_static_gtfs_import.sql` | Depois da carga | Constrói índices espaciais, popula `route_shapes_geom` e executa verificações. |
| `scripts/import_static_gtfs_local.sh` | Carga local completa | Faz staging com checksum, importa e executa o pós-processamento. |

### Decisões intencionais

- As tabelas ficam em `gtfs`, e não em `public`, para não expor dados brutos automaticamente pelo PostgREST/Supabase.
- `stops.geom` é uma coluna **generated stored**. Ela é criada automaticamente a partir de `stop_lon`/`stop_lat`; não é necessário rodar `UPDATE stops SET geom = ...`.
- `route_shapes_geom` guarda a linha em dois SRIDs:
  - `geom_4326`: WGS84, adequado para serializar coordenadas para o mapa.
  - `geom_25833`: ETRS89/UTM 33N, adequado para cálculos métricos futuros em Berlim (snap de GPS e distância).
- O frontend continuará consumindo apenas a API/WebSocket do backend; não recebe permissão de leitura das tabelas GTFS.

---

## 1. Aplicar a migration estrutural

No **Supabase SQL Editor**, execute o conteúdo de:

```text
supabase/migrations/20260717163000_gtfs_static_postgis.sql
```

Ou, se o projeto estiver ligado ao Supabase CLI, aplique a migration pelo fluxo normal do repositório. A conta que executa o script precisa poder criar extensões; no SQL Editor do Supabase isso é esperado.

Resultado esperado:

- extensão `postgis` no schema `extensions`;
- schema `gtfs`;
- tabelas `gtfs.routes`, `gtfs.trips`, `gtfs.stops`, `gtfs.shapes`;
- materialized view ainda vazia `gtfs.route_shapes_geom`;
- RLS ativo nas quatro tabelas físicas.

---

## 2. Baixar e extrair o GTFS estático oficial VBB

Baixe o ZIP GTFS estático atual fornecido pela VBB e extraia, no mínimo:

```text
routes.txt
trips.txt
stops.txt
shapes.txt
```

Ignore nesta fase calendários, tarifas, `stop_times.txt` e demais arquivos. Eles podem ser adicionados depois sem mudar o contrato espacial definido aqui.

> **Importante:** não use o feed GTFS-RT nesta etapa. Ele não é parte da carga estática.

---

## 3. Carregar os quatro arquivos

A carga inicial precisa usar uma conexão direta PostgreSQL / importador de CSV, e não inserts linha a linha por REST.

### Ordem obrigatória

```text
1. routes.txt
2. stops.txt
3. shapes.txt
4. trips.txt
```

`trips.route_id` possui chave estrangeira para `routes.route_id`.

### Opção recomendada: importador local VBB

Extraia a exportação VBB para `data/gtfs-static/GTFS/` e execute na raiz do projeto:

```bash
npm run gtfs:import-local
```

O comando foi construído para os cabeçalhos da exportação VBB atualmente
carregada. Ele valida os quatro arquivos, confere o checksum após o staging no
container, limpa/recarrega somente o banco **local** em uma transação e executa
o script de geometrias e índices. A carga usa `psql \copy`, portanto não exige
conceder `pg_read_server_files` ao papel PostgreSQL do Supabase.

> Não execute esse comando com um contexto Docker remoto nem use-o para um
> projeto Supabase hospedado. Os arquivos GTFS são importados apenas no banco
> local criado pelo Docker Desktop.

Se uma versão futura da VBB alterar os cabeçalhos, o validador interrompe a
carga antes de qualquer `TRUNCATE`. Atualize o mapeamento de colunas de forma
explícita; nunca importe CSV por posição sem essa verificação.

---

## 4. Gerar geometrias e índices

`npm run gtfs:import-local` já executa esta etapa automaticamente depois da
carga. Execute manualmente no SQL Editor apenas se tiver usado outro processo
de importação:

```text
supabase/sql/phase_1_after_static_gtfs_import.sql
```

O script:

1. gera uma `LineString` ordenada para cada `shape_id`;
2. cria índices B-tree e GIST após o bulk load;
3. constrói a versão métrica em EPSG:25833;
4. executa `ANALYZE`;
5. devolve as contagens de validação.

Na primeira execução, o refresh é bloqueante por ser a primeira população da materialized view. Para substituições futuras do GTFS estático, use diretamente e fora de uma transação explícita:

```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY gtfs.route_shapes_geom;
```

---

## 5. Critérios de aceite da Fase 1

A última consulta do script pós-carga deve mostrar:

- `routes`, `trips`, `stops`, `shape_points` e `route_shape_lines` maiores que zero;
- `stops_without_geom = 0`;
- `invalid_wgs84_shape_lines = 0`.

Para uma inspeção espacial manual:

```sql
SELECT
  stop_id,
  stop_name,
  extensions.st_astext(geom) AS point_wgs84
FROM gtfs.stops
LIMIT 5;

SELECT
  shape_id,
  vertex_count,
  extensions.st_geometrytype(geom_4326) AS geometry_type,
  extensions.st_srid(geom_25833) AS metric_srid
FROM gtfs.route_shapes_geom
LIMIT 5;
```

Quando esses critérios forem atendidos, a Fase 1 estará concluída e pronta para a ingestão GTFS-RT do backend na Fase 2.
