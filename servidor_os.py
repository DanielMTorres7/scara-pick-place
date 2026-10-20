"""Servidor HTTP do braço: o sistema EMR manda a OS (POST /os) e o braço a executa em segundo plano (job_os),
avisando o sistema a cada caixa em EMR_URL/api/robo/<os>. Uma OS por vez. O endereço do sistema vem da
configuração do braço, nunca do pedido: o token não vai para uma URL escolhida por quem manda a OS.

  POST /os     Authorization: Bearer <ROBO_TOKEN>    -> 202 aceita | 400 inválida | 401 token | 409 ocupado
               (a mesma OS de novo com o job vivo = retomada: 202 sem novo job)
  GET  /saude  -> {"ocupado": bool, "os": str|null}

Uso: ROBO_TOKEN=... EMR_URL=http://<emr>:8765 python servidor_os.py [--porta 8770]
"""
import argparse
import hmac
import json
import os
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_CORPO = 64 * 1024
ESPERA_ENCERRAR = 20.0   # s que um job já encerrando (estacionando) tem para liberar o braço a uma OS nova


def _int(v, minimo, campo):
    if not isinstance(v, int) or isinstance(v, bool) or v < minimo:
        raise ValueError("%s: inteiro >= %d" % (campo, minimo))
    return v


def valida_pedido(corpo):
    """confere o JSON da OS e devolve só o que o job usa"""
    if not isinstance(corpo, dict):
        raise ValueError("corpo deve ser um objeto JSON")
    os_ = corpo.get("os")
    if not isinstance(os_, str) or not os_.strip():
        raise ValueError("os: texto não vazio")
    itens = corpo.get("itens", [])
    if not isinstance(itens, list):
        raise ValueError("itens: lista")
    limpos = {}     # a visão só lê o nome: dosagens diferentes do mesmo remédio viram um item só
    for it in itens:
        if not isinstance(it, dict) or not isinstance(it.get("nome"), str) or not it["nome"].strip():
            raise ValueError("itens[].nome: texto não vazio")
        nome = it["nome"].strip().lower()
        q = _int(it.get("quantidade"), 1, "itens[].quantidade")
        limpos[nome] = limpos.get(nome, 0) + q
    limpos = [{"nome": n, "quantidade": q} for n, q in limpos.items()]
    return {"os": os_.strip(), "cliente": str(corpo.get("cliente", "")), "itens": limpos,
            "quantidade": _int(corpo.get("quantidade", 0), 0, "quantidade"),
            "separadas": _int(corpo.get("separadas", 0), 0, "separadas")}


def callback_de(emr_url, os_):
    """endpoint do sistema para os eventos desta OS"""
    return "%s/api/robo/%s" % (emr_url.rstrip("/"), urllib.parse.quote(os_, safe=""))


def cria_servidor(porta, token, novo_job):
    estado = {"job": None, "thread": None}
    trava = threading.Lock()

    def ocupado():
        t = estado["thread"]
        return t is not None and t.is_alive()

    def espera_encerrar():
        """job que já decidiu sair (cancelada/concluída/erro) só falta estacionar: espera fora da trava"""
        with trava:
            t, job = estado["thread"], estado["job"]
        if t is not None and t.is_alive() and getattr(job, "encerrando", False):
            t.join(ESPERA_ENCERRAR)

    class Handler(BaseHTTPRequestHandler):
        def _responde(self, status, corpo):
            b = json.dumps(corpo, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if self.path != "/saude":
                return self._responde(404, {"erro": "rota"})
            with trava:
                vivo = ocupado()
                return self._responde(200, {"ocupado": vivo, "os": estado["job"].os if vivo else None})

        def do_POST(self):
            if self.path != "/os":
                return self._responde(404, {"erro": "rota"})
            auth = self.headers.get("Authorization", "")
            if not hmac.compare_digest(auth.encode(), ("Bearer " + token).encode()):
                return self._responde(401, {"erro": "token"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0:
                return self._responde(400, {"erro": "Content-Length inválido"})
            if n > MAX_CORPO:
                return self._responde(413, {"erro": "corpo grande demais"})
            try:
                pedido = valida_pedido(json.loads(self.rfile.read(n) or b"null"))
            except ValueError as e:      # JSONDecodeError também é ValueError
                return self._responde(400, {"erro": str(e)})
            espera_encerrar()
            with trava:
                if ocupado():
                    if estado["job"].os == pedido["os"]:
                        return self._responde(202, {"aceito": True, "retomada": True})
                    return self._responde(409, {"erro": "braço ocupado com a OS %s" % estado["job"].os})
                job = novo_job(pedido)
                t = threading.Thread(target=job.rodar, daemon=True, name="os-" + pedido["os"])
                estado.update(job=job, thread=t)
                t.start()
            print("OS %s recebida: %s" % (pedido["os"], pedido["itens"] or "%d caixas" % pedido["quantidade"]))
            return self._responde(202, {"aceito": True, "retomada": False})

        def log_message(self, fmt, *args):
            pass

    return ThreadingHTTPServer(("0.0.0.0", porta), Handler)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--porta", type=int, default=8770)
    args = ap.parse_args()
    token = os.environ.get("ROBO_TOKEN", "").strip()
    if not token:
        sys.exit("defina ROBO_TOKEN (o mesmo valor de EMR_ROBO_TOKEN no sistema)")
    emr_url = os.environ.get("EMR_URL", "").strip()
    if not emr_url.startswith(("http://", "https://")):
        sys.exit("defina EMR_URL (endereço do sistema EMR, ex.: http://127.0.0.1:8765)")

    from job_os import JobOS
    from pick_place import PickPlace
    from progresso import Progresso
    from sistema import Sistema

    progresso = Progresso(Path(__file__).resolve().parent / "os_progresso.json")

    def novo_job(pedido):
        return JobOS(pedido, lambda: PickPlace(com_nomes=bool(pedido["itens"])),
                     Sistema(callback_de(emr_url, pedido["os"]), token), progresso)

    srv = cria_servidor(args.porta, token, novo_job)
    print("braço esperando OS em http://0.0.0.0:%d/os" % args.porta)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
