# Spec — OS do EMR executada pelo braço, com contagem real

## Intenção
Hoje o EMR lança a OS, faz POST "dispara e esquece" de `{os, quantidade, cliente, medicamento}` (só o 1º remédio)
e o progresso é **simulado** em dois lugares: o firmware do ESP32 (`os_pick_timer_cb`, +1 a cada 2–10 s →
`BRIDGE: unit`) e o front web (checkbox "Simular separação"). Objetivo: a OS lançada no sistema é executada de
verdade pelo braço SCARA (pick and place por nome, com quantidades) e o sistema recebe a **contagem real**.

## Papéis (decididos pelo usuário)
- **Sistema** (backend EMR, repo `Software-Challenge-3EMR`): fonte da verdade. Lança a OS, guarda estado/contagem.
- **Braço** (este repo `scara`): executa a OS e reporta ao sistema.
- **Painel** (tela ESP32-P4, repo `Painel_ARIS`): segundo plano, **só espelha** o sistema. Pode **pausar e
  cancelar** (já existe: `BRIDGE: os_pause / os_cancel` → sistema). Não conta unidades sozinho.
- Front web do EMR: continua como está, mas sem simulação quando o braço está integrado.

## Fluxo
1. Operador lança a OS no sistema com itens (`remedio_id` × quantidade; catálogo da planilha).
2. Sistema faz POST no braço (`EMR_OS_JSON_URL`) com a OS completa (formato abaixo). Braço responde `202` na hora;
   se ocupado, `409`. Falha de rede/HTTP no POST → sistema loga e põe a OS **pausada** com a mensagem
   "Braço indisponível" (o operador vê e decide).
3. Braço, em thread própria: foto da mesa → acha coletora e caixas → Gemini lê nomes → monta a fila de caixas
   respeitando **ordem da lista e quantidade de cada remédio**.
4. Para cada caixa que cai na coletora: braço manda `unit` com o total acumulado. Sistema grava
   (`units_separated`), repassa ao ESP32 (`CMD: unit`) e devolve o **estado atual da OS** na resposta.
5. Antes de cada caixa o braço olha o último estado recebido:
   - `running` → segue;
   - `paused` → termina a caixa em curso (não larga caixa pendurada), sobe, estaciona (PARQUE) e consulta o
     estado a cada ~2 s até mudar;
   - `cancelled`/`completed`/OS não é mais a atual → sobe, estaciona, encerra o job.
6. Se faltou caixa na mesa para algum remédio (fila não cobre o pedido): braço pega o que tem e depois manda
   `faltando` com `[{nome, faltam}]`. Sistema **pausa** a OS e grava a mensagem
   `"Remédios faltando: 1× ARPADOL, 2× MICPURE"`; painel web e ESP32 mostram.
7. **Retomada**: operador repõe as caixas e retoma (web ou ESP32). Braço percebe `running` no polling, fotografa
   de novo e pega **só o que falta**. Ainda faltando → pausa de novo com mensagem atualizada.
8. Pegou tudo → `concluida`. Sistema conclui a OS (fluxo existente de `complete_current_order`; o
   `update_units` já auto-conclui ao bater a meta — manter idempotente).
9. Erro do braço (evento de placa: TMC/24 V/fim de curso/emergência; exceção qualquer no ciclo) → braço para os
   motores e manda `erro {mensagem}`. Sistema **pausa** a OS com a mensagem `"Erro no braço: …"` (não muda o
   separador para `error`, para o operador poder retomar depois de rodar `diagnostico.py`). Ao retomar, o braço
   recomeça do passo 3 (nova foto).

## Decisões do construtor (validadas na revisão)
- **Contagem = fim do ciclo** (decisão do usuário): `unit` sai logo depois de soltar a caixa na coletora e subir.
  Sem sensor de vácuo; sem conferência por câmera.
- **Retomada/reabertura reenviam a OS** (minha decisão): `resume_separation` e reabertura "resume" chamam o
  dispatch de novo. Payload leva `separadas` (verdade do sistema). Braço aceita a mesma OS do job atual sem 409
  (vira retomada). Braço guarda progresso por item em `os_progresso.json` (por `os`): se o total salvo == `separadas`,
  continua dali; se `separadas == 0`, zera; se diverge, assume os primeiros `separadas` da lista expandida como feitos.
  Polling de pausa continua para o job vivo (retomar pela tela ESP32 também funciona).
- **Erro encerra o job** (minha decisão): braço para motores, manda `erro`, fecha placas/câmera/bomba (libera para
  `diagnostico.py --corrigir`). Retomar → reenvio → job novo (reabre hardware, Z sobe a Z_ALTO antes de mover juntas).
- **Só o separador `EMR_ROBO_CODE`** recebe a OS do braço (minha decisão); demais separadores: comportamento atual.
  Front web: simulação desmarcada por padrão.
- OS criada pelo ESP32 com o braço ocupado: já recusada pelo sistema (`robot_busy`).

## Contratos

### Sistema → braço: `POST {EMR_OS_JSON_URL}` (ex.: `http://<notebook-braço>:8770/os`)
```json
{
  "os": "OS-001", "cliente": "Fulano", "robot_code": "SCARA-01",
  "quantidade": 3, "separadas": 0,
  "itens": [{"remedio_id": "123", "remedio": "MICPURE 10MG 30CPR", "nome": "micpure", "quantidade": 2},
            {"remedio_id": "456", "remedio": "ARPADOL 400MG", "nome": "arpadol", "quantidade": 1}],
  "callback": "http://<emr>:8765/api/robo/os-001"
}
```
- `itens` agregado a partir de `medicines_json` (lista expandida) preservando a ordem da 1ª ocorrência.
- `nome` = 1ª palavra do SKU em minúsculas (mesma regra de `medicine_first_name`); é o que o braço compara com o
  nome lido pelo Gemini (`mesmo_nome`). Mantém `medicamento` (1º nome) por compatibilidade.
- OS sem itens (criada só com quantidade, ex. pelo ESP32): braço pega **qualquer** caixa até a quantidade.
- Header `Authorization: Bearer <EMR_ROBO_TOKEN>`; braço rejeita (`401`) sem token válido.

### Braço → sistema: `POST /api/robo/{os_code}/evento` (router novo, sem sessão/CSRF, auth por token)
Header `Authorization: Bearer <EMR_ROBO_TOKEN>` (comparação em tempo constante). Corpo (Pydantic, `tipo` discriminado):
- `{"tipo": "unit", "separadas": 2}` — total acumulado (não incremento). Monotônico: menor que o atual é ignorado.
- `{"tipo": "faltando", "separadas": 2, "faltando": [{"nome": "arpadol", "faltam": 1}]}`
- `{"tipo": "concluida", "separadas": 3}`
- `{"tipo": "erro", "separadas": 2, "mensagem": "placa z: ['FIM']"}`

Resposta `200`: `{"estado": "running" | "paused" | "cancelled" | "completed", "separadas": N, "mensagem": "..."}`.
`404` se a OS não existe; se a OS não está mais em andamento, responde `200` com o estado final (o braço encerra).

### Braço → sistema: `GET /api/robo/{os_code}/estado` — mesmo corpo de resposta, mesmo token. Usado no polling da pausa.

### Sistema → ESP32 (serial, `serial_service._EMRPoller`)
- Novo `CMD:{"cmd":"unit","num":"OS-001","done":2}` sempre que `units_separated` mudar.
- `CMD:{"cmd":"os_pause","num":...,"reason":"Remédios faltando: …"}` — `reason` novo (firmware mostra na tela).
- `os_assign / os_resume / os_complete / os_cancel` como hoje.

## Mudanças por repo

### `scara` (braço)
- `servidor_os.py` (novo): servidor HTTP stdlib (`http.server` + thread), `POST /os`, `GET /saude`. Um job por
  vez (409 se ocupado). Token via env `ROBO_TOKEN`; URL do sistema vem no `callback` do payload.
- `pick_place.py`: extrair a seleção de caixas para função pura testável
  `escolhe_caixas(caixas_lidas, itens) -> (fila, faltando)` (respeita ordem + quantidade; sem itens = qualquer
  caixa até `quantidade`). `rodar` ganha um gancho por caixa concluída (callback) e um ponto de checagem antes de
  cada caixa (pode pedir para parar). Uso por CLI (`--nome/--ordem`) continua funcionando.
- Cliente do sistema (`sistema.py` novo): `evento(tipo, …) -> estado`, `estado()`; `urllib`, timeout curto,
  retry simples em falha de rede no `unit` (não perder contagem).
- Testes: `escolhe_caixas`, máquina de estado do job (running/paused/cancelled/faltando/retomada) com robô e
  sistema falsos, validação do payload, token.

### `Software-Challenge-3EMR` (sistema)
- `os_dispatch.py`: payload novo (itens agregados, `nome`, `robot_code`, `callback`), header Bearer; falha no POST
  → pausa a OS com mensagem "Braço indisponível". Hoje é chamado dentro de `assign_order_to_robot` — mantém.
- Router novo `robo.py` (`/api/robo/...`), schema Pydantic do evento, serviço que aplica o evento sobre o
  `RobotService` existente (`update_units_separated`, `pause_separation`, `complete_current_order`).
- Mensagem de pausa: coluna nova `robots.pause_reason` (texto, nulo) via `bootstrap/sqlite_migrations.py`; limpa ao
  retomar/concluir/cancelar; exposta em `RobotDetail`. Front web mostra a mensagem no detalhe do separador.
- `config.py`: `robo_token: str = ""` (`EMR_ROBO_TOKEN`), `public_base_url` para montar o `callback`. Token vazio →
  router `/api/robo` responde `503` (integração desligada). Atualizar `.env.example` se existir (nunca `.env`).
- `serial_service.py`: `CMD: unit` ao mudar unidades; `reason` no `os_pause`.
- Front web: checkbox "Simular separação" desmarcado por padrão (simulação continua disponível só para testes
  sem braço).
- Testes (pytest) para o router/serviço do evento e para o payload.

### `Painel_ARIS` (firmware ESP32-P4)
- Remover a contagem própria: `os_start_manual`/`os_resume` não agendam mais `os_pick_timer`; sem
  `BRIDGE: unit` gerado localmente.
- Tratar `CMD: unit` → `s_os_meds_done = done`, repinta. Conclusão só por `CMD: os_complete`.
- `CMD: os_pause` com `reason` → mostra o texto na tela da OS ativa (label existente ou novo) enquanto pausada.
- Pausar/cancelar pela tela: mantém (`BRIDGE: os_pause/os_cancel`).
- Sem como compilar/gravar/testar aqui: alteração entregue para revisão; validar na bancada.

## Não-objetivos
- Push nos repos do Renan (`Software-Challenge-3EMR`, `Painel_ARIS`): só branch local + commits; push só se o
  usuário pedir.
- Mudar como o braço acha/pega caixas (visão, cinemática, alturas).
- Várias OS em paralelo / vários braços. Um braço, um job por vez.
- `serial_gateway.py` standalone (o backend já tem o `serial_service` interno): não alterar além do necessário.

## Anti-objetivos
- Contagem que não corresponde a caixa realmente solta na coletora.
- Braço se mexendo com a OS pausada/cancelada no sistema (exceto terminar a caixa em curso e estacionar).
- Simulação ligada junto com o braço (dupla contagem).

## Restrições
- Braço: Python ≥3.10, sem dependências novas (stdlib para HTTP).
- Sistema: FastAPI + SQLAlchemy + SQLite, padrões do repo (services/repositories/schemas, exceções → HTTP).
- Token compartilhado só em `.env` (nunca em código).
- Gemini (only-vision) é necessário para OS com itens.

## Deixado para o construtor
- Nome/porta exata do servidor do braço (sugestão 8770), intervalo do polling (sugestão 2 s).
- Layout da mensagem no front web e no ESP32.
- Retry/timeout exatos do cliente HTTP.
