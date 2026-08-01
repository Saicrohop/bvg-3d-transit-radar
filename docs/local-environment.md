# Ambiente local — BVG 3D Transit Radar

Este guia prepara o ambiente local para a **Fase 1** e para os artefatos
server-side da **Fase 2**: Supabase/PostGIS, GTFS estático, `stop_times` e a
biblioteca Python de normalização GTFS-RT. Não inicializa FastAPI, um serviço
WebSocket público ou frontend.

## Ferramentas instaladas no projeto

- Node.js e npm já estavam disponíveis no host.
- Codex CLI está instalado como dependência local: `@openai/codex`.
- Supabase CLI está instalado como dependência local: `supabase`.
- Antigravity CLI está disponível no PATH como `agy`.
- Docker Desktop foi instalado no Windows.
- WSL 2 e Virtual Machine Platform estão ativos e o Docker Desktop foi validado.

## Solução de problemas de WSL/Docker

Neste ambiente, Docker Desktop e WSL 2 já foram validados. Caso uma instalação
futura apresente erro de WSL 2:

1. Reinicie o Windows para concluir a ativação do WSL/Virtual Machine Platform.
2. Se o Docker Desktop continuar falhando, entre no BIOS/UEFI e ative a
   virtualização de CPU: **Intel VT-x/VT-d** ou **AMD SVM/AMD-V**.
3. Inicie o Docker Desktop pelo Menu Iniciar e espere o motor ficar disponível.

## Depois da reinicialização

Abra um novo Git Bash e execute:

```bash
cd /c/Users/italo/projects/bvg-3d-radar

docker version
npm run supabase:start
npm run supabase:status
```

Resultados esperados:

- `docker version` mostra as seções Client e Server.
- `supabase:start` sobe os contêineres locais.
- Na primeira inicialização, `supabase:start` aplica automaticamente as
  migrations versionadas do diretório `supabase/migrations/`.
- `supabase:status` mostra as URLs locais, incluindo o Supabase Studio.

Use `npm run supabase:reset` somente quando quiser apagar deliberadamente o
banco **local** e reexecutar as migrations. Não use esse comando em um projeto
Supabase remoto.

Após extrair `routes.txt`, `stops.txt`, `shapes.txt`, `trips.txt` e
`stop_times.txt` em `data/gtfs-static/GTFS/`, importe tudo no banco Docker
local com:

```bash
npm run gtfs:import-local
```

O importador valida os cabeçalhos VBB, verifica checksums no staging, carrega
as tabelas na ordem segura, materializa as geometrias/índices e calcula a
fração de cada parada sobre o shape da viagem. O Studio local continua
disponível em `http://127.0.0.1:54323` para inspeção, mas não é necessário fazer
importações manuais por ele.

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
