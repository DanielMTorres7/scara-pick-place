# Spec 02 — Conexão sistema ↔ braço pela tela (sem variáveis de ambiente)

Decidido pelo usuário (2026-10-20): mesma máquina; hub USB físico com placas do braço + ESP32. O painel ESP32 já
conecta pela tela (botão "ESP32" → porta serial + separador) — não muda. O braço passa a conectar do mesmo jeito.
Nada de .env: EMR_ROBO_TOKEN / EMR_ROBO_CODE / EMR_OS_JSON_URL saem do código; ROBO_TOKEN / EMR_URL saem do braço.

## Sistema
- Botão "Braço" no cabeçalho (ao lado do ESP32) → modal "Conectar braço": separador (select), endereço do braço
  (default `127.0.0.1:8770`), Conectar / Desconectar, bolinha de estado (conectado + braço respondendo).
- Conectar: gera token (secrets), chama `POST <braço>/conectar {"token", "emr_url"}` (emr_url = base da requisição
  do navegador), grava no banco (tabela `braco_config`, 1 linha: robot_id, url, token). Falha → 502, nada gravado.
- Desconectar: apaga a linha (dispatch para; /api/robo responde 503).
- dispatch, /api/robo (token + escopo do separador) e serial (contagem não diminui) leem a config do banco.
- API: `GET /api/braco/status`, `POST /api/braco/conectar {robot_id, endereco}`, `POST /api/braco/desconectar`
  (sessão + CSRF).

## Braço
- `uv run python servidor_os.py [--porta 8770]`, sem variáveis.
- `POST /conectar {token, emr_url}`: só de 127.0.0.1/::1 (403 fora disso); grava `braco_conexao.json` (gitignored)
  e vale a partir da próxima OS. Sem conexão: `POST /os` → 503.
- `/saude` passa a dizer `"conectado": bool`.

## Fora
- Braço em outra máquina (pareamento só local por decisão de segurança).
