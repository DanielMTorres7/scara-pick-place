# 03 — Calibração pela tela do sistema (spec + plano)

Pedido (23/10): botões no sistema EMR para calibrar braço e câmera. Decidido com o user: **dois botões**;
recalibrar câmeras **pede o J1 alinhado à mão** (0 mecânico) antes de começar.

## Contrato braço (servidor_os.py) ↔ sistema

`POST /calibrar` — `Authorization: Bearer <token>` (o mesmo das OS), `Content-Type: application/json`,
corpo `{"tipo": "soltar" | "braco" | "cameras"}`
- 202 `{"aceito": true, "tipo": ...}` · 400 tipo inválido · 401 token · 409 `{"erro": "braço ocupado ..."}` (OS ou
  outra calibração rodando) · 503 braço não conectado
- `soltar`: fecha o braço aberto (bomba, câmeras, **energia cortada**: motores soltos para alinhar o J1 à mão)
- `braco`: referencia (reinicia a placa do Z, Z e J2 pelas chaves, homing do J1 pela câmera, leva J1 ao 0) ~1 min
- `cameras`: J1 = 0 onde está (alinhado à mão), Z e J2 pelas chaves, grade (J1 -125:125:25, J2 -120:120:30,
  Z -60/10/70; ~150 pontos, ~10-15 min), ajusta o modelo de cada câmera (calibrar.ajustar) e **só aplica** se o erro
  mediano novo for menor que o do modelo atual nos mesmos pontos (cópia do antigo em calibracao_<cam>.<data>.json);
  no fim refaz o homing com o modelo novo

`GET /saude` ganha: `"tarefa": null | "os" | "soltar" | "braco" | "cameras"` (o que está rodando) e
`"calibracao": null | {"tipo", "ok": bool, "msg": str, "fim": "<ISO>"}` (última calibração terminada).
Campos atuais (`ocupado`, `os`, `conectado`) iguais.

## Sistema (3emr, branch feat/braco-real)
- `POST /api/braco/calibrar` `{"tipo"}` (login + CSRF) → `BracoService.calibrar(tipo)` manda ao braço com o token;
  devolve `BracoStatus`. Erros: braço não configurado 400 · 409 do braço → 409 · inacessível → 502 · tipo → 422.
- `BracoStatus` ganha `tarefa: str | None` e `calibracao: {tipo, ok, msg, fim} | None` (lidos do `/saude`).
- Tela (modal do braço, conectado): seção "Calibração" com **Referenciar braço** e **Recalibrar câmeras**.
  Recalibrar: confirma → `soltar` → instrução "Motores soltos: alinhe o J1 reto (0°) e clique Iniciar" →
  **Iniciar recalibração** → `cameras`. Enquanto `tarefa` != null: mostra "Calibrando…" e consulta o status a cada 3 s;
  ao terminar mostra o resultado (`calibracao.msg`). Botões desabilitados com o braço ocupado/offline.

## Plano
Braço (TDD): PickPlace.referenciar() (extraído do preparar) · grade.coletar aceita r/câmeras abertos e dist_max ·
calibracao.py (Calibracao: job com rodar/encerrando/tarefa/resultado; recalibrar_cameras) · servidor_os /calibrar +
/saude · reiniciar servidor.
Sistema (TDD, subagente): schema + service + router + testes; tela.
