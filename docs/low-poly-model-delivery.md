# Entrega e integração dos modelos low-poly

O usuário entregou e autorizou a integração dos cinco modelos Blender em **2026-10-18**, incluindo os acréscimos intencionais de geometria. As cópias em `frontend/public/models/lowpoly/` preservam os hashes e materiais originais; os arquivos legados não foram sobrescritos. O checklist continua sendo referência para entregas futuras.

Versões selecionadas: ônibus v3, U-Bahn v2, S-Bahn v1, Tram v1 e Regional v2.
O conjunto tem 614.492 bytes. Os limites de triângulos inicialmente propostos
não são critérios de rejeição destas versões aprovadas: não foi aplicada decimação.

A calibração CPU usa escala 1, translação zero e `[0, 180 - heading, 90]`,
verificada com a implementação de matrizes instalada do Deck e os bounds dos
GLBs. O eixo de frente +Z permanece uma convenção declarada, sem confirmação
visual. Materiais `doubleSided=true` foram mantidos, e labels usam altura + 2 m.
Lite continua padrão/3D opt-in; o gate visual permanece manual e pendente.

## Alvo de arte e organização

- Silhueta blocky reconhecível no zoom do mapa: carroceria, janelas, rodas e articulações simples; sem interior ou detalhes mecânicos invisíveis.
- Priorizar poucas faces e poucos materiais. Uma malha Blender unida pode continuar tendo vários material slots/primitives no GLB; `Ctrl+J` sozinho não prova uma única chamada de desenho.
- Preferir uma malha, uma primitive e um material por veículo. Usar Color Attributes/vertex colors para a paleta se o export conservar `COLOR_0` e o material a utilizar. Não depender apenas da cor do viewport Blender.
- Preferir superfícies opacas sem texturas. Isso reduz recursos de imagem, **não zera VRAM**, nem elimina buffers, shaders, picking ou iluminação.
- Sem animações, rig, câmeras, luzes, geometria interna oculta ou modifiers não aplicados que aumentem silenciosamente o mesh exportado.

## Convenção para os candidatos

**Proposta de entrega**, não conversão automática dos assets atuais:

1. Blender em metros; dimensões em escala real. A tabela abaixo adota os tamanhos aproximados fornecidos pelo usuário como alvo esquemático, não ficha técnica da frota.
2. Geometria centralizada em X/Y; parte mais baixa em Z=0 no Blender. Cursor em (0,0,0), origem no cursor, objeto em (0,0,0).
3. Aplicar rotação e escala; conferir escala (1,1,1) e rotação (0,0,0). Conferir dimensões novamente depois de aplicar modifiers e antes do export.
4. Frente apontada para -Y no Blender, altura em +Z. Registrar isso por escrito e incluir uma imagem lateral/frontal feita pelo próprio usuário.
5. Export glTF 2.0 Binary (`.glb`), selecionados apenas, com conversão padrão glTF +Y up. Não acrescentar rotação manual para imitar constantes antigas do código.
6. Conferir o arquivo exportado no seu Blender/viewer. Enviar também o `.blend` e a versão/opções do exportador. A integração verificará eixos/transformações reais do GLB; exportar base no chão não prova que todas as constantes do renderer passam automaticamente a zero.

| Candidato | Comprimento × largura × altura (m) |
|---|---|
| Ônibus BVG | 12 × 2,55 × 3,2 |
| U-Bahn esquemático | 30 × 2,65 × 3,5 |
| Tram articulado | 30 × 2,4 × 3,4 |
| S-Bahn | 36 × 3,0 × 3,6 |
| Regional esquemático | 40 × 2,8 × 4,6 |

Paleta proposta pelo usuário: BVG `#F0D722`, DB `#EC0016`, janelas `#1A242B`; S-Bahn creme/vermelho. O U-Bahn dedicado foi integrado com autorização explícita e possui modelo/camada/chave de falha separados do ônibus. A presença de `COLOR_0` foi verificada; aparência da paleta no renderer continua pendente de inspeção manual.

## Arquivos para enviar

Usar nomes de candidatos, por exemplo `bvg_bus_lowpoly_v1.glb`, `bvg_tram_lowpoly_v1.glb`, `s_bahn_lowpoly_v1.glb`, `regional_lowpoly_v1.glb`. **Não sobrescrever** `frontend/public/models/*` diretamente: calibração/cache e modelo têm de ser atualizados em conjunto.

Junto de cada modelo, informar:

- dimensões, eixo da frente e localização da origem;
- triângulos/vertices, meshes, primitives/material slots, materiais e texturas;
- tamanho em bytes e licença/autoria;
- se há pontas idênticas (eixo longitudinal visível não prova uma frente única);
- captura produzida pelo usuário, quando seguro em seu hardware.

Não fixamos promessa de 10–25 KB, redução de 99,8%, 4 draw calls ou FPS. Esses resultados só podem ser avaliados nos arquivos exportados e no renderer real.

## Como entra no projeto

1. Receber candidatos em localização separada e inventariar/hash em CPU.
2. Validar estrutura, limites, materiais e transformações com nova autorização para inspeção de modelos. Usar relatório do export efetivo, não contagem apenas do Blender.
3. Atualizar mapping e calibração por asset, com testes de coordenadas/orientação/grounding.
4. Comparar ScenegraphLayer atual com outra opção **somente se houver motivo mensurável**. GLB não vira automaticamente um mesh compatível com SimpleMeshLayer; hierarquia, atributos e material precisam de adaptação explícita.
5. Validação gráfica/manual exclusivamente pelo usuário, após hardware seguro e autorização. Lite permanece padrão e o 3D opt-in.

## Referência técnica e limites

Manual oficial Blender 4.4, seção glTF 2.0: o export triangula faces; normais/UVs descontínuos podem duplicar vértices; glTF usa +Y up e o export suporta Color Attributes. São características do formato/exportador, não uma certificação do nosso candidato. A página `latest` recusou extração HTTP (403); a consulta recuperou a documentação oficial versionada, não uma verificação da versão instalada do Blender do usuário.

```text
https://docs.blender.org/manual/ru/4.4/addons/import_export/scene_gltf2.html
```
