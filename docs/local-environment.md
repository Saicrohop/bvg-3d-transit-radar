# Ambiente local — BVG 3D Transit Radar

Este guia prepara o baseline local das Fases 1–2 e orienta a operação das fases
P8/P9: Supabase/PostGIS, GTFS estático, interpolação server-side, snapshots
WebSocket e frontend Orbital. Os comandos de validação aqui descritos não abrem
browser nem executam renderização visual 3D.

## Ferramentas declaradas e disponibilidade real

Node.js/npm e `uv` são usados pelos comandos do projeto. `@openai/codex` e
`supabase` estão declarados no package.json; isso não prova que os CLIs estejam
instalados no ambiente atual. Instalações históricas de Docker/WSL e Antigravity
não devem ser tratadas como disponibilidade presente.

No checkpoint de 2026-10-17, Docker e o entrypoint Supabase local não foram
encontrados; `agy` também não apareceu no PATH. O estado dos volumes permanece
**desconhecido**, não perdido nem validado. Use a descoberta offline abaixo em
cada retomada e mantenha o Docker Desktop sob controle manual.

## Solução de problemas de WSL/Docker

Caso uma instalação apresente erro de WSL 2:

1. Reinicie o Windows para concluir a ativação do WSL/Virtual Machine Platform.
2. Se o Docker Desktop continuar falhando, entre no BIOS/UEFI e ative a
   virtualização de CPU: **Intel VT-x/VT-d** ou **AMD SVM/AMD-V**.
3. Inicie o Docker Desktop pelo Menu Iniciar e espere o motor ficar disponível.

## Retomada segura e descoberta offline

Abra um novo Git Bash e execute:

```bash
cd /c/Users/italo/projects/bvg-3d-radar
npm run runtime:check
```

O runner usa somente Node.js local e o Python **já provisionado** do projeto:
`.venv/Scripts/python.exe` no Windows ou `.venv/bin/python` nos demais sistemas
(Python 3.11+). Não chama `uv`, não cria/sincroniza ambiente, não baixa Python ou
pacotes e não altera locks; se o intérprete faltar ou falhar, retorna exit **2**
com diagnóstico sanitizado (`project_python_missing`/`project_python_failed`),
sem fallback global. O único processo filho do launcher é esse Python, com
`-I -S -B`: ignora configuração Python herdada e `site`/`.pth`, desabilita escrita
de bytecode e importa o checker stdlib deste checkout. Variáveis `UV_*` e
`PYTHON*` não são repassadas; `UV_ENV_FILE` não é interpretado. Isso delimita o
launcher/checker, não promete isolamento contra npm/Node/Python hospedeiros maliciosos.

O comando versionado verifica o project_id, o contrato **55030–55033** e a
presença do CLI Docker e do entrypoint Supabase **do projeto**. Se faltar alguma
dependência, não chega aos probes de portas. Quando ambas são encontradas,
consulta TCP e tenta binds temporários exclusivamente em `127.0.0.1`, nas quatro
portas aprovadas, fechando todos os sockets. Não executa nenhum CLI de serviço,
consulta banco, inicia serviços, instala pacotes ou lê `.env`.

- Exit **2**: bloqueio esperado por configuração inválida, ferramenta ausente,
  porta ocupada ou probe indisponível. Erros não ecoam configurações nem DSNs.
- Exit **0**: somente descoberta offline aprovada. Presença de arquivo não prova
  executabilidade/versão do CLI, daemon ativo, contexto Docker local, banco,
  volumes, forwarding ou GTFS íntegro. `live_gate` continua `not_run`.
- Uma porta ocupada pode pertencer à stack existente: é motivo para inspecionar,
  não para matar processos ou remover containers/volumes automaticamente.
- O comando é independente de `npm run verify`: indisponibilidade do Docker não
  transforma os testes CPU em testes live nem bloqueia CI offline.

Depois de o usuário disponibilizar/iniciar Docker Desktop manualmente:

1. Confirmar que o contexto/endpoint Docker aponta para a máquina local, não um
   daemon remoto; verificar Client e Server.
2. Inventariar containers e volumes existentes do project_id `bvg-3d-radar`.
3. Decidir a recuperação do banco persistido antes de qualquer `supabase:start`.
   Não inicializar um baseline vazio sem esclarecer o estado dos dados.
4. Restaurar o CLI Supabase do lock do projeto se necessário, sem instalação
   implícita de outra versão; só então iniciar a stack conforme a decisão.
5. Validar PostGIS/GTFS read-only, snapshots reais e benchmark limitado.

**Não executar reset para recuperar o ambiente nem atualizar GTFS.** Esta etapa
não autoriza apagar banco/volumes ou reexecutar migrations para contornar um
problema de runtime. A migração de portas não exige reset nem reimportação.

Com a stack local identificada, os volumes inventariados e os CSVs compatíveis
em `data/gtfs-static/GTFS/`, a importação é manutenção separada e deliberada:

```bash
npm run gtfs:import-local
```

### Atualizar o snapshot GTFS estático com segurança

Antes de trocar os CSVs, registre o diagnóstico do snapshot atual:

```bash
npm run gtfs:check-compatibility
```

Atualize a partir da fonte oficial VBB com:

```bash
npm run gtfs:update-static
```

O atualizador baixa o ZIP para um arquivo temporário, valida os cabeçalhos e o
calendário em staging, calcula checksums e compara o `trips.txt` candidato com
um snapshot GTFS-RT. A promoção exige, por padrão:

- timestamp presente e idade máxima de 900 segundos;
- tolerância máxima de 120 segundos para timestamp futuro;
- ao menos 1.000 `trip_id` `SCHEDULED` únicos;
- data do feed coberta pelo calendário em `Europe/Berlin`;
- ao menos 99% de correspondência dos IDs únicos;
- nenhuma divergência confirmada de `route_id`.

Os três limites operacionais podem ser passados explicitamente:

```bash
npm run gtfs:update-static -- \
  --minimum-unique-scheduled-trips 1000 \
  --max-feed-age-seconds 900 \
  --max-future-skew-seconds 120
```

A saída JSON registra a política efetiva em `compatibility_policy`. O manifest
instalado registra os timestamps UTC de download e instalação, recalcula o
SHA-256 do ZIP no ponto de instalação e inclui o SHA-256 de todos os arquivos
regulares. Ele também persiste, em `compatibility`, o instante da checagem, idade
e data operacional do feed, a política aplicada e o relatório completo
(incluindo contagens brutas, IDs únicos, cancelamentos, exceções, `route_id` e
amostras limitadas). Assim, a decisão de promoção pode ser auditada sem depender
da saída do terminal. Durante a promoção, o diretório anterior é mantido como
backup temporário e restaurado se a troca do snapshot ou do manifest falhar.
ZIP, CSVs e manifest continuam locais e ignorados pelo Git.

Esse comando não altera o banco. Depois de um update bem-sucedido, execute
novamente `npm run gtfs:check-compatibility` e só então faça a importação local.
Não use `supabase db reset` para atualizar GTFS.

O importador valida os cabeçalhos VBB, verifica checksums no staging, carrega
as tabelas na ordem segura, materializa as geometrias/índices e calcula a
fração de cada parada sobre o shape da viagem. O Studio configurado usa
`http://127.0.0.1:55032` (disponibilidade depende da stack) para inspeção, mas não é necessário fazer
importações manuais por ele.

O caminho do import é um único `psql -X --single-transaction`, incluindo COPY,
refresh, projeção e health gate que aborta antes do commit se inválido. Cada
execução usa staging exclusivo e advisory lock transacional. **Pausar worker e
leitores antes da manutenção**: TRUNCATE/refresh retêm locks e não constituem
troca online sem bloqueio. Falhas fazem rollback da transação; essa propriedade
foi verificada estruturalmente em CPU, sem executar import/rollback real nesta
etapa. Não usar as antigas chamadas separadas para publicar tabelas antes dos
derivados.

### Contrato de portas migrado — 2026-10-17

Configuração e guardas migradas, **sem iniciar/recriar a stack ou alterar banco**:

| Serviço | Porta antiga | Porta configurada |
|---|---:|---:|
| API | 54021 | 55030 |
| PostgreSQL | 54022 | 55031 |
| Studio | 54023 | 55032 |
| Email local | 54024 | 55033 |

O project_id continua `bvg-3d-radar`. Shadow DB `54020`, analytics de infraestrutura
Supabase `54027`, pooler desativado `54029` e inspector `8083` permaneceram como
antes; nenhuma quinta porta `55034` foi introduzida. Analytics de logs do Supabase
não é o futuro produto Analytics do radar, que não foi iniciado.

Benchmark e integração usam a mesma guarda: somente PostgreSQL em loopback
exato na porta `55031`, sem query/fragment/parâmetros de URL. URLs antigas e
overrides como `?host=...` ou `?port=...` falham antes de conexão. Erros de parse
não ecoam a URL ou o texto recebido como porta.

**Bloqueio atual observado em 2026-10-17:** Docker não apareceu no PATH, nos locais
padrão, nos processos ou no registro. O CLI Supabase local também estava ausente.
Não foi possível inventariar volumes, PostGIS ou conteúdo GTFS. Não afirmar que
dados foram perdidos ou preservados sem essa verificação. As quatro novas portas
aceitaram bind na checagem, e a antiga exclusão Windows `53973–54072` não consta
mais; disponibilidade de bind não prova encaminhamento Docker.

Para retomar, disponibilizar o Docker Desktop manualmente e avisar. Antes de
qualquer start, inventariar containers/volumes e decidir como recuperar os dados
existentes. Restaurar o CLI do lock do projeto quando necessário; não usar npx
sem limite que instale outra versão implicitamente. Não executar reset, import
ou startup que inicialize um baseline vazio sem conferir o estado persistido.
P13-A live permanece pendente até banco, GTFS compatível, snapshots e benchmark
serem efetivamente verificados. Nunca abrir browser/preview para essa etapa.

As dependências frontend foram restauradas com `npm --prefix frontend ci`; a
primeira tentativa de gate não encontrou Vitest. O gate foi repetido depois,
sem alterar package-lock ou atualizar bibliotecas globais.

## Backend Python da Fase 2

Instale as dependências isoladas do projeto e execute os testes:

```bash
uv sync --all-groups
npm test
```

Com o Supabase local ativo e o GTFS carregado, valide a função PostGIS de
interpolação com dados reais:

```bash
npm run test:phase2:local
```

O código Python recebe apenas o endpoint GTFS-RT e a URL do banco em tempo de
execução; não registre credenciais nem URLs de banco em arquivos versionados.
Consulte `docs/phase-2-tripupdate-interpolation.md` para limites, contrato de
evento e operação detalhada.

## P8/P9 — serviços locais

Com o Supabase local ativo e a configuração PostgreSQL fornecida apenas pelo
ambiente, o servidor contínuo publica snapshots v1 no loopback:

```bash
npm run ws:serve
```

O frontend Orbital pode ser servido em outro terminal:

```bash
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Ele consome somente `ws://127.0.0.1:8000/ws/positions` por padrão. A variável
`VITE_POSITIONS_WS_URL` permite apontar para outro endpoint local explicitamente;
nunca coloque uma URL GTFS-RT ou credencial no bundle.

O modo padrão é MapLibre Lite; 3D só por escolha explícita. `/?map=off` permite
iniciar somente os painéis, sem importar renderer. Os modelos low-poly versão local
já estão integrados no caminho 3D opcional; a inspeção visual deles continua
manual e diferida até o usuário liberar a verificação de hardware.

A paleta oficial por linha S-Bahn/U-Bahn está em
`docs/berlin-transit-line-colors.md`; os ícones de paradas/estações e a camada de
percurso ainda precisam ser ligados no frontend.

### Servidor opcional de métricas (8001)

Permanece independente do radar e do HTML Mission Control. Bind somente loopback;
não há autenticação. CORS e guardas de contexto aceitam origens exatas
`http://127.0.0.1:8001`, `http://localhost:8001` e `http://[::1]:8001`, somente GET.
Mudar portas/origens exige configuração explícita, não wildcard. Os handlers
bloqueantes rodam no threadpool e o SQLite é read-only.

Consumidores devem aceitar indicadores desconhecidos como `null` e estados
`open`/`ended`/`failed`. Registro de sessão aberto não comprova agente vivo;
ausência de erro não comprova sucesso. “Hoje” usa UTC e atribui totais às sessões
iniciadas nesse dia, não ao instante exato do consumo. O HTML independente não
foi alterado nem seu comportamento com os novos `null` validado nesta etapa.

O P9 reconecta automaticamente e sinaliza `awaiting`, `fresh` e `stale`. A
conexão aberta não garante um snapshot atual. A validação funcional pode usar
`npm run verify`, testes Vitest/jsdom, integração PostGIS read-only e clientes de
terminal; não use esses comandos como prova de pixels.

A inspeção visual do mapa/modelos está `deferred_hardware`: não executar browser,
Playwright, screenshots, WebGL ou WebGPU neste host até a fonte ser atualizada e
o usuário autorizar a retomada.

Para um ciclo real de prova, injete a URL PostgreSQL local de forma efêmera no
ambiente e execute o composition root. O comando imprime no console até duas
posições estimadas em JSON Lines e não abre HTTP/WebSocket:

```bash
export BVG_DATABASE_URL='postgresql://[ROLE]:[REDACTED]@127.0.0.1:[PORT]/postgres'
uv run python -m bvg_radar.realtime.runner --max-positions 2
```

## Agentes locais

Verifique o Codex após concluir o login com ChatGPT:

```bash
npm run codex -- login status
npm run codex -- --version
```

Verifique o Antigravity:

```bash
npm run antigravity -- --version
npm run antigravity -- -p "Reply exactly ANTIGRAVITY_LOCAL_READY." --mode plan
```

Os dois agentes recebem as regras de escopo em `AGENTS.md` quando usados na
raiz do projeto.

## Parar o ambiente

```bash
npm run supabase:stop
```
