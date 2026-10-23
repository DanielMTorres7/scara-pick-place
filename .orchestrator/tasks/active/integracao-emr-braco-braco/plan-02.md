# Plano 02 — conexão pela tela (executar inline, TDD)
Spec: 02-conexao-pela-tela.md. Comandos de teste como no plan.md.

1. Braço `conexao.py`: `Conexao(caminho)` com `.token`, `.emr_url`, `.conectada`, `salva(token, emr_url)` (escrita
   atômica), `valida_conexao(corpo) -> (token, emr_url)` (token ≥16 car., emr_url http(s)). Testes test_conexao.py.
2. Braço `servidor_os.py`: `cria_servidor(porta, conexao, novo_job)`; `POST /conectar` só loopback (403), 400 inválido,
   200 grava; `/os` 503 sem conexão, 401 token ≠ conexao.token; `/saude` + `"conectado"`. `main()` sem env:
   `novo_job` usa `Sistema(callback_de(conexao.emr_url, os), conexao.token)`. README sem env. Apaga integracao.sh.
3. EMR modelo `BracoConfig` (tabela braco_config: id, robot_id FK, url, token, updated_at) + `braco_service.py`:
   `config(db) -> BracoConfig | None`, `BracoService(db).conectar(robot_id, endereco, emr_url)`, `.desconectar()`,
   `.status() -> BracoStatus`; `_parear(url, token, emr_url)` monkeypatchável; erros tipados
   `BracoInacessivel`/`SeparadorInvalido`. Testes test_braco_service.py.
4. EMR: dispatch, require_robo_token, robo_event_service e serial_service passam a usar `config(db)`; remove
   robo_token/robo_code/os_json_url do Settings; conftest com fixture que grava a config. Suíte inteira verde.
5. EMR router `/api/braco` (status/conectar/desconectar; auth + CSRF) + testes via client.
6. Front: botão "Braço" + modal (padrão do modal serial), status no botão. node --check + ensaio via API.
7. README do EMR sem variáveis; ensaio e2e (pareamento real pela API + OS).
