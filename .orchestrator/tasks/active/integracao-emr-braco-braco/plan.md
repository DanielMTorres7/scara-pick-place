# OS do EMR executada pelo braço — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a OS lançada no EMR é executada pelo braço SCARA (remédios + quantidades) e o EMR recebe a contagem real; faltando remédio → OS pausada com mensagem; ESP32 só espelha.

**Architecture:** braço roda `servidor_os.py` (HTTP stdlib) que recebe a OS e roda um `JobOS` (máquina de estado pura, hardware injetado) numa thread; cada caixa solta → `POST /api/robo/{os}/evento` no EMR, cuja resposta traz o estado da OS (running/paused/cancelled/completed) que o job obedece. EMR ganha router `/api/robo` com token, `robots.pause_reason`, dispatch completo e reenvio ao retomar; `serial_service` repassa `unit`/motivo ao ESP32; firmware deixa de simular.

**Tech Stack:** braço: Python ≥3.10, stdlib (`http.server`, `urllib`), pytest. EMR: FastAPI, SQLAlchemy 2, SQLite, Pydantic v2, pytest + httpx (TestClient). Firmware: ESP-IDF 6 / LVGL 8.3 (C).

**Spec:** `.orchestrator/tasks/active/integracao-emr-braco-braco/spec.md`

## Global Constraints
- Repos e branches: `~/projects/scara` → branch `feat/integracao-emr` (a partir de `chore/ambiente-linux`; não commitar `calibracao_braco.json`/`dados_grade.json`, que são alterações do usuário); `~/projects/3emr/Software-Challenge-3EMR` → `feat/braco-real`; `~/projects/3emr/Painel_ARIS` → `feat/espelho-sistema`. **Sem push.**
- Commits PT-BR imperativo `{type}({scope}): {goal}` + linha `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Braço sem dependências novas. Token do braço: env `ROBO_TOKEN`. EMR: `EMR_ROBO_TOKEN`, `EMR_ROBO_CODE`, `EMR_PUBLIC_BASE_URL` (default `http://127.0.0.1:8765`), `EMR_OS_JSON_URL` (existente). Nunca editar `.env`.
- Contagem = fim do ciclo (caixa solta na coletora + Z subiu). Evento `unit` leva o **total acumulado**.
- Estados devolvidos pelo EMR: `"running" | "paused" | "cancelled" | "completed"`.
- Mensagens: `"Remédios faltando: 1× ARPADOL, 2× MICPURE"`, `"Erro no braço: <msg>"`, `"Braço indisponível"`.
- Polling de pausa: 2 s. Porta default do servidor do braço: 8770.
- Comandos: braço `uv run pytest`; EMR (na raiz do repo) `uv run --with-requirements requirements.txt --with-requirements requirements-dev.txt pytest backend/tests -q`.

## Review Focus
1. EMR fora do ar no meio da OS → o braço não pode perder contagem nem pegar caixa sem registrar: estaciona, espera o EMR voltar e reenvia o total (teste em Task 4: `test_sistema_cai_e_volta`).
2. Mesma OS reenviada (retomar) com o job vivo → 202 sem segundo job nem segundo movimento (Task 6: `test_mesma_os_reenviada_nao_duplica`).
3. Evento `unit` atrasado/duplicado com total menor → ignorado, nunca diminui contagem (Task 9: `test_unit_menor_ignorado`).
4. Caixa fora do alcance (IK falha) → pulada e entra no "faltando", não derruba a OS (Task 4: `test_caixa_inalcancavel_vira_faltando`).
5. Evento para OS já concluída/cancelada (ex.: cancelada pela tela durante a caixa) → 200 com estado final, sem erro, braço encerra (Task 9: `test_evento_em_os_cancelada`).

---

## Braço (`~/projects/scara`)

### Task 1: Seleção de caixas e pendências (`selecao.py`)

**Files:** Create `selecao.py`, `tests/test_selecao.py`; Modify `pick_place.py` (importar `mesmo_nome`/`_norm` de `selecao` em vez de definir).

**Interfaces — Produces:**
- `mesmo_nome(pedido: str, lido: str) -> bool` (movida de `pick_place.py`, mesma regra).
- `pendentes(itens: list[dict], quantidade: int, feitos: dict[str, int]) -> list[dict]` → `[{"nome": str, "faltam": int}]` na ordem de `itens`; sem itens → `[{"nome": "", "faltam": quantidade - soma(feitos)}]` (vazio se ≤0). `itens` = `[{"nome": str, "quantidade": int}]`.
- `escolhe_caixas(caixas: list[dict], pend: list[dict]) -> list[tuple[dict, str]]` → fila `(caixa, nome_item)`: para cada pendência em ordem, até `faltam` caixas ainda não usadas cujo `caixa["nome"]` casa (`nome == ""` casa qualquer caixa); dentro de um item, caixas ordenadas por `centro[1]`.

- [ ] Step 1: testes — `test_pendentes_respeita_ordem_e_feitos` (itens micpure×2, arpadol×1, feitos {"micpure":1} → `[{"micpure",1},{"arpadol",1}]`); `test_pendentes_sem_itens` (quantidade 3, feitos {"":1} → `[{"",2}]`); `test_escolhe_respeita_quantidade` (3 caixas micpure, pend micpure×2 → 2 na fila); `test_escolhe_nao_reusa_caixa`; `test_escolhe_falta_quando_nao_ha` (0 arpadol na mesa → fila sem arpadol); `test_mesmo_nome_tolera_erro` ("micpure" vs "Miopure" → True).
- [ ] Step 2: `uv run pytest tests/test_selecao.py -q` → FAIL (módulo inexistente).
- [ ] Step 3: implementar; `pick_place.py` importa de `selecao`.
- [ ] Step 4: `uv run pytest -q` → tudo PASS.
- [ ] Step 5: commit `feat(os): seleção de caixas por remédio e quantidade`.

### Task 2: Progresso local por OS (`progresso.py`)

**Files:** Create `progresso.py`, `tests/test_progresso.py`; Modify `.gitignore` (+`os_progresso.json`).

**Interfaces — Produces:**
- `class Progresso(caminho: Path)`: `carrega(os: str) -> dict[str, int]`, `salva(os: str, feitos: dict[str, int]) -> None` (escrita atômica: tmp + `os.replace`).
- `reconcilia(itens: list[dict], quantidade: int, separadas: int, salvo: dict[str, int]) -> dict[str, int]`: `sum(salvo) == separadas` → `salvo`; `separadas == 0` → `{}`; senão os primeiros `separadas` da lista expandida de `itens` (sem itens → `{"": separadas}`).

- [ ] Step 1: testes `test_salva_e_carrega` (tmp_path), `test_reconcilia_usa_salvo`, `test_reconcilia_zera_em_restart`, `test_reconcilia_diverge_usa_ordem` (itens micpure×2, arpadol×1, separadas 3, salvo {} → {"micpure":2,"arpadol":1}).
- [ ] Step 2: rodar → FAIL. Step 3: implementar. Step 4: PASS.
- [ ] Step 5: commit `feat(os): progresso por remédio salvo em disco`.

### Task 3: Cliente do sistema (`sistema.py`)

**Files:** Create `sistema.py`, `tests/test_sistema.py`.

**Interfaces — Produces:**
- `Estado = Literal["running", "paused", "cancelled", "completed"]`; `class SistemaIndisponivel(RuntimeError)`.
- `class Sistema(callback: str, token: str, tentativas: int = 3, espera: float = 1.0)`: `evento(tipo: str, separadas: int, **extra) -> Estado` → `POST {callback}/evento`; `estado() -> Estado` → `GET {callback}/estado`. Header `Authorization: Bearer <token>`, JSON, timeout 5 s. Falha de rede/5xx repete `tentativas` vezes e levanta `SistemaIndisponivel`; 404 → `"cancelled"`; 401 → `SistemaIndisponivel` imediato.

- [ ] Step 1: testes com `http.server` em thread (porta 0): `test_evento_envia_token_e_corpo` (servidor registra header e JSON `{"tipo":"unit","separadas":2}`; resposta `{"estado":"running"}` → `"running"`); `test_404_vira_cancelled`; `test_rede_fora_levanta` (porta fechada, `espera=0`).
- [ ] Step 2: FAIL. Step 3: implementar com `urllib.request`. Step 4: PASS.
- [ ] Step 5: commit `feat(os): cliente HTTP do sistema EMR`.

### Task 4: Job da OS (`job_os.py`)

**Files:** Create `job_os.py`, `tests/test_job_os.py`.

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces:
  - `class CaixaInalcancavel(ValueError)`.
  - Protocolo `Executor`: `preparar() -> list[dict]` (foto + coletora + nomes; caixas com `"nome"`, `"centro"`), `pegar(caixa: dict, i: int) -> None` (um ciclo completo; levanta `CaixaInalcancavel` ou outra exceção), `estacionar() -> None`, `parar() -> None` (motores), `fechar() -> None`.
  - `class JobOS(pedido: dict, executor_factory: Callable[[], Executor], sistema: Sistema, progresso: Progresso, espera_pausa: float = 2.0, dormir=time.sleep)`; `rodar() -> None`; `os: str` (propriedade).
- Algoritmo de `rodar()` (é a decisão do plano):
  ```
  feitos = reconcilia(itens, quantidade, pedido["separadas"], progresso.carrega(os)); ex = factory()
  try:
    while True:
      fila = escolhe_caixas(ex.preparar(), pendentes(...)); est = "running"
      for i,(cx,nome) in enumerate(fila):
          if est != "running": break
          try: ex.pegar(cx, i)
          except CaixaInalcancavel: continue
          feitos[nome]+=1; progresso.salva; est = _evento("unit")      # _evento: SistemaIndisponivel → "indisponivel"
      ex.estacionar()
      if est in ("cancelled","completed"): return
      if est == "running":
          pend = pendentes(...)
          est = _evento("concluida") if not pend else _evento("faltando", faltando=pend)
          if not pend and est != "indisponivel": return
      est = _espera(): polling estado() a cada espera_pausa (SistemaIndisponivel = continua esperando)
            até "running" (→ reenvia _evento("unit") se o último falhou; continua o while) ou cancelled/completed (→ return)
  except Exception as e: ex.parar(); tenta _evento("erro", mensagem=str(e)); 
  finally: ex.fechar()
  ```

- [ ] Step 1: testes com `ExecutorFalso` (lista de caixas por chamada de `preparar`, registra chamadas) e `SistemaFalso` (fila de estados a devolver, registra eventos):
  - `test_pega_tudo_e_conclui` → eventos `unit 1, unit 2, concluida 2`; `fechar` chamado.
  - `test_faltando_pausa_e_retoma` → 1ª foto sem arpadol: `unit 1, unit 2, faltando [{"arpadol",1}]`; `estado()` devolve paused, running; 2ª foto com arpadol: `unit 3, concluida 3`; `preparar` chamado 2×.
  - `test_pausa_no_meio_estaciona` → `unit` devolve paused: para de pegar, `estacionar`, espera; running → nova foto.
  - `test_cancelado_encerra` → `unit` devolve cancelled: sem mais `pegar`, `fechar` chamado, nenhum `concluida`.
  - `test_erro_manda_erro_e_fecha` → `pegar` levanta `RuntimeError("placa z: FIM")`: `parar`, evento `erro` com `mensagem`, `fechar`.
  - `test_caixa_inalcancavel_vira_faltando` (Review Focus 4).
  - `test_sistema_cai_e_volta` (Review Focus 1): `unit` levanta `SistemaIndisponivel`; braço estaciona, `estado()` falha 1× depois running; reenvia `unit` com o mesmo total antes de pegar a próxima.
  - `test_retoma_do_progresso_salvo` → progresso {"micpure":1}, separadas 1: só pega o que falta.
- [ ] Step 2: FAIL. Step 3: implementar. Step 4: `uv run pytest -q` PASS.
- [ ] Step 5: commit `feat(os): job da OS com pausa, faltando, cancelamento e erro`.

### Task 5: `PickPlace` como executor

**Files:** Modify `pick_place.py`.

**Interfaces — Produces:** métodos de `PickPlace` que cumprem `Executor` (Task 4): `preparar() -> list[dict]` (relé repouso, Z_ALTO, PARQUE, limpa eventos, foto `fotos/pp_mesa.jpg`, `planejar`, `nomes_gemini`; guarda pontos de soltura em `self._solta`), `pegar(caixa, i)` (o corpo atual do laço de `rodar`, soltura em `self._solta[i % len(self._solta)]`, `ValueError` da IK → `CaixaInalcancavel`, termina com `checar_eventos`), `estacionar()` (Z_ALTO se abaixo, PARQUE), `parar()` (`self.r.parar()`), `fechar()` (existente). Gemini só é chamado se alguma caixa precisar de nome — `preparar(com_nomes: bool = True)`.
- `rodar(nome, alvo_px, ordem)` passa a usar esses métodos; comportamento da CLI igual.

- [ ] Step 1: refatorar sem mudar comportamento da CLI.
- [ ] Step 2: `uv run pytest -q` PASS; `uv run python -c "import pick_place"` sem erro.
- [ ] Step 3: commit `refactor(pick-place): ciclo exposto como executor da OS`.
- (Validação com hardware é manual, no fim — ver Task 13.)

### Task 6: Servidor HTTP do braço (`servidor_os.py`)

**Files:** Create `servidor_os.py`, `tests/test_servidor_os.py`; Modify `README.md` (seção "Integração com o EMR": env `ROBO_TOKEN`, `python servidor_os.py --porta 8770`, exemplo de payload).

**Interfaces:**
- Consumes: `JobOS` (Task 4).
- Produces: `cria_servidor(porta: int, token: str, novo_job: Callable[[dict], JobOS]) -> ThreadingHTTPServer`; `valida_pedido(corpo: object) -> dict` (levanta `ValueError`): `os` str não vazia, `callback` começando com `http://` ou `https://`, `quantidade` int ≥0, `separadas` int ≥0, `itens` lista de `{nome: str, quantidade: int ≥1}` (outras chaves ignoradas).
- Rotas: `POST /os` → 401 sem `Bearer` válido (`hmac.compare_digest`); 400 corpo inválido; job vivo com a mesma `os` → 202 `{"aceito": true, "retomada": true}` sem novo job; job vivo com outra `os` → 409; senão cria job, `threading.Thread(target=job.rodar, daemon=True)`, 202. `GET /saude` → 200 `{"ocupado": bool, "os": str|null}`.
- `main()`: `--porta` (8770); `ROBO_TOKEN` vazio → sai com erro; `novo_job` monta `JobOS(pedido, PickPlace, Sistema(pedido["callback"], token), Progresso(Path("os_progresso.json")))`.

- [ ] Step 1: testes com servidor real em porta 0 e `novo_job` falso (job controlável por `threading.Event`): `test_sem_token_401`, `test_payload_invalido_400`, `test_aceita_202_e_roda_job`, `test_outra_os_ocupado_409`, `test_mesma_os_reenviada_nao_duplica` (Review Focus 2), `test_saude`.
- [ ] Step 2: FAIL. Step 3: implementar. Step 4: `uv run pytest -q` PASS.
- [ ] Step 5: commit `feat(os): servidor HTTP que recebe a OS do EMR`.

## Sistema (`~/projects/3emr/Software-Challenge-3EMR`)

### Task 7: Base de testes, config e motivo da pausa

**Files:** Create `requirements-dev.txt` (`pytest>=8`, `httpx>=0.27`), `backend/tests/conftest.py`, `backend/tests/test_pause_reason.py`; Modify `backend/app/config.py`, `backend/app/models/entities.py` (`Robot.pause_reason: Mapped[str | None] = mapped_column(Text, nullable=True)`), `backend/app/bootstrap/sqlite_migrations.py` (ADD COLUMN `pause_reason TEXT`), `backend/app/schemas/robot.py` (`RobotDetail.pause_reason: str | None = None`), `backend/app/services/robot_service.py`, `.gitignore` (+`__pycache__/`, `.pytest_cache/`).

**Interfaces — Produces:**
- `Settings.robo_token: str = ""`, `Settings.robo_code: str = ""`, `Settings.public_base_url: str = "http://127.0.0.1:8765"`.
- `RobotService.pause_separation(robot_id: int, reason: str | None = None)` grava `pause_reason`; `resume_separation`, `complete_current_order`/`_apply_order_completion`, `cancel_current_order` e `AssignmentService.assign_order_to_robot` limpam (`None`). `_to_detail` expõe.
- `conftest.py`: põe `backend/` no `sys.path`, define `EMR_DATABASE_URL=sqlite:///<tmp>/t.db`, `EMR_ROBO_TOKEN=tok`, `EMR_ROBO_CODE=SCARA-01` **antes** de importar `app`; fixtures `db` (Session; `create_all` + migrações) e `client` (`TestClient(create_app ou app)`), e `robo_em_os(db, itens=...) -> (robot, order)` que cria separador `SCARA-01` idle + OS via `AssignmentService.create_manual_order_and_assign` (com `os_dispatch` desligado por monkeypatch).

- [ ] Step 1: testes `test_pausa_com_motivo_aparece_no_detalhe`, `test_retomar_limpa_motivo`, `test_concluir_limpa_motivo`, `test_cancelar_limpa_motivo`.
- [ ] Step 2: rodar comando do EMR → FAIL. Step 3: implementar. Step 4: PASS.
- [ ] Step 5: commit `feat(robos): motivo da pausa e base de testes`.

### Task 8: Dispatch completo da OS

**Files:** Modify `backend/app/services/os_dispatch.py`, `backend/app/services/assignment_service.py` (passa `robot`), `backend/app/services/robot_service.py` (`resume_separation` chama dispatch após commit); Create `backend/tests/test_os_dispatch.py`.

**Interfaces — Produces:**
- `order_json_payload(order: ServiceOrder, robot: Robot, separadas: int) -> dict` → `{"os", "cliente", "robot_code", "quantidade", "separadas", "medicamento", "itens": [{"remedio_id","remedio","nome","quantidade"}], "callback": f"{public_base_url}/api/robo/{os_code}"}`; `itens` agrega `medicines_json` por `remedio_id` na ordem da 1ª ocorrência; `nome = medicine_first_name` do SKU.
- `dispatch_order_json(order: ServiceOrder, robot: Robot) -> None`: só envia se `os_json_url` e `robo_code` não vazios e `robot.code == robo_code`; POST com `Authorization: Bearer <robo_token>` numa thread via `_em_segundo_plano(fn, *args)` (monkeypatchável); qualquer falha (rede, HTTP ≠ 202) → abre `SessionLocal`, se o robô ainda está `running` com essa OS → `pause_separation(robot.id, reason="Braço indisponível")`.

- [ ] Step 1: testes (com `_em_segundo_plano` executando inline e `_post_json` monkeypatchado): `test_payload_agrega_itens` (MICPURE×2, ARPADOL×1 → itens com quantidade 2 e 1, `nome` "micpure"), `test_so_envia_para_robo_configurado`, `test_falha_pausa_com_braco_indisponivel`, `test_retomar_reenvia_com_separadas`.
- [ ] Step 2: FAIL. Step 3: implementar. Step 4: PASS.
- [ ] Step 5: commit `feat(os): envia OS completa ao braço e reenvia ao retomar`.

### Task 9: Router `/api/robo` (eventos do braço)

**Files:** Create `backend/app/schemas/robo.py`, `backend/app/services/robo_event_service.py`, `backend/app/api/routers/robo.py`, `backend/tests/test_robo.py`; Modify `backend/app/api/router.py` (incluir **sem** `_auth`), `backend/app/api/dependencies.py` (`require_robo_token`).

**Interfaces — Produces:**
- Schemas: `EventoUnit{tipo: Literal["unit"], separadas: int ≥0}`, `EventoFaltando{tipo, separadas, faltando: list[ItemFaltando{nome: str, faltam: int ≥1}] (min 1)}`, `EventoConcluida{tipo, separadas}`, `EventoErro{tipo, separadas, mensagem: str (≤500)}`; `EventoRobo = Annotated[Union[...], Field(discriminator="tipo")]`; `EstadoOS{estado: Literal[...], separadas: int, mensagem: str | None}`.
- `require_robo_token(authorization: str | None = Header(None))`: `robo_token` vazio → 503; ausente/diferente (`hmac.compare_digest`) → 401.
- `class RoboEventService(db)`: `estado(os_code) -> EstadoOS` (OS inexistente → `OSNaoEncontrada` → 404; atual de um robô → status do robô (`running`/`paused`); `completed` → completed; `cancelled`/outro → cancelled); `aplicar(os_code, ev: EventoRobo) -> EstadoOS`: se a OS não é a atual de um robô → só devolve `estado`; `separadas > robot.units_separated` → `update_units_separated` (pode auto-concluir); `faltando` com robô running → `pause_separation(reason="Remédios faltando: " + ", ".join(f"{f.faltam}× {f.nome.upper()}"))`; `erro` running → `pause_separation(reason=f"Erro no braço: {mensagem}")`; `concluida` ainda atual → `complete_current_order`. Ações registram auditoria via `OrderEventRepository` já usado pelos métodos do `RobotService` (nada extra).
- Rotas: `POST /robo/{os_code}/evento` → `EstadoOS`; `GET /robo/{os_code}/estado` → `EstadoOS`.

- [ ] Step 1: testes via `client` com header `Authorization: Bearer tok`: `test_sem_token_401`, `test_token_vazio_503` (monkeypatch settings), `test_unit_atualiza_e_devolve_running`, `test_unit_menor_ignorado` (Review Focus 3), `test_faltando_pausa_com_mensagem` (mensagem exata `"Remédios faltando: 1× ARPADOL"`), `test_erro_pausa`, `test_concluida_fecha_os`, `test_unit_ultima_autoconclui_devolve_completed`, `test_evento_em_os_cancelada` (Review Focus 5), `test_estado_os_inexistente_404`, `test_estado_pausado`.
- [ ] Step 2: FAIL. Step 3: implementar. Step 4: PASS.
- [ ] Step 5: commit `feat(robo): endpoint de eventos e estado da OS para o braço`.

### Task 10: Serial repassa contagem e motivo ao ESP32

**Files:** Modify `backend/app/services/serial_service.py` (`get_robot_state` inclui `"pause_reason"`; `_EMRPoller.tick`); Create `backend/tests/test_serial_poller.py`.

**Interfaces — Produces:** no mesmo OS: `curr_units != prev_units` → `send_cmd({"cmd":"unit","num":os,"done":curr_units})`; transição para paused → `{"cmd":"os_pause","num":os,"reason": pause_reason or ""}`; pausa já ativa e `pause_reason` mudou → reenvia `os_pause` com o novo `reason`. Demais comandos iguais.

- [ ] Step 1: testes com cliente/escritor falsos: `test_envia_unit_quando_muda`, `test_pause_leva_motivo`, `test_nova_os_nao_envia_unit_duplicado` (os_assign na primeira vez, sem `unit` 0).
- [ ] Step 2: FAIL. Step 3: implementar. Step 4: PASS.
- [ ] Step 5: commit `feat(serial): repassa contagem e motivo da pausa ao painel`.

### Task 11: Front web

**Files:** Modify `frontend/index.html` (tirar `checked` de `#manual-os-simulate`), `frontend/app.js` (reset do form volta a `checked = false` nas 2 ocorrências; detalhe do separador mostra `pause_reason` quando `status === "paused"`, num aviso ao lado do status, usando classes existentes de alerta/badge).

- [ ] Step 1: editar.
- [ ] Step 2: verificar: `python run_dev.py`, criar OS manual com o checkbox desmarcado → contagem não anda sozinha; `curl` de um evento `faltando` → detalhe mostra a mensagem.
- [ ] Step 3: commit `feat(front): simulação desligada por padrão e motivo da pausa visível`.

## Painel (`~/projects/3emr/Painel_ARIS`)

### Task 12: Firmware só espelha

**Files:** Modify `main/main.c`.

- Remover contagem local: `os_start_manual` e `os_resume` não chamam `os_schedule_next_pick`; remover `os_pick_timer_cb`/`os_schedule_next_pick`/`serial_bridge_unit_deferred_cb` e os estados `s_bridge_unit_pending*` (e `os_pick_timer_stop` onde ficar órfão).
- `CMD_UNIT`: reconhecer `"cmd":"unit"` (comparar a string `"\"cmd\":\"unit\""`, não só `"unit"`), extrair `"done"`; no timer: OS ativa e `num` igual → `s_os_meds_done = min(done, total)`, `ui_os_paint_labels()`. Conclusão só por `CMD: os_complete`.
- `os_pause` com `reason`: guardar em `s_os_pause_reason[128]`; label novo no painel ativo (abaixo do contador) visível só quando pausado e motivo não vazio; limpa em resume/finalize.
- [ ] Step 1: editar.
- [ ] Step 2: verificar: se `idf.py` existir, `idf.py build`; senão `gcc -fsyntax-only` não é viável (LVGL) — revisar diff à mão e registrar "não compilado".
- [ ] Step 3: commit `feat(painel): espelha contagem e motivo da pausa vindos do sistema`.

## Fechamento

### Task 13: Ensaio ponta a ponta (manual, com o usuário)
- [ ] EMR: `EMR_ROBO_TOKEN`, `EMR_ROBO_CODE=<código do separador>`, `EMR_OS_JSON_URL=http://127.0.0.1:8770/os`; cadastrar separador com esse código, status idle.
- [ ] Braço: `ROBO_TOKEN=<mesmo> uv run python servidor_os.py`.
- [ ] Lançar OS com 2 remédios na mesa e 1 faltando → contagem sobe a cada caixa, pausa com "Remédios faltando", repor, retomar, conclui.
- [ ] Atualizar README do EMR (`GATEWAY_README.md` ou seção nova) com as variáveis e o fluxo — no commit da Task 8 se couber, senão aqui.
