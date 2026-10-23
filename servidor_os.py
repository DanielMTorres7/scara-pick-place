"""Servidor HTTP do braço: o sistema EMR manda a OS (POST /os) e o braço a executa em segundo plano (job_os),
avisando o sistema a cada caixa em <emr>/api/robo/<os>. Uma OS por vez.

A conexão com o sistema é feita pela tela dele ("Conectar braço"): o sistema manda o token e o próprio endereço
para POST /conectar, que só é aceito da própria máquina, e o braço guarda em braco_conexao.json. O endereço do
sistema nunca vem do pedido da OS: o token não vai para uma URL escolhida por quem manda a OS.

  POST /conectar {token, emr_url}                   -> 200 | 400 inválido | 403 não é local
  POST /os     Authorization: Bearer <token>        -> 202 aceita | 400 inválida | 401 token | 409 ocupado
               (a mesma OS de novo com o job vivo = retomada: 202 sem novo job) | 503 braço não conectado
  GET  /saude  -> {"ocupado": bool, "os": str|null, "conectado": bool}

Uso: python servidor_os.py [--porta 8770]
"""
import argparse
import hmac
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from conexao import Conexao, eh_local, valida_conexao

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


def cria_servidor(porta, conexao, novo_job):
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
                return self._responde(200, {"ocupado": vivo, "os": estado["job"].os if vivo else None,
                                            "conectado": conexao.conectada})

        def _corpo(self):
            """JSON do corpo; levanta ValueError (vira 400) se o tamanho ou o JSON forem inválidos"""
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0:
                raise ValueError("Content-Length inválido")
            if n > MAX_CORPO:
                raise ValueError("corpo grande demais")
            return json.loads(self.rfile.read(n) or b"null")

        def _conectar(self):
            # Só o backend do sistema, na própria máquina, conecta o braço. Um navegador aberto aqui também fala
            # com 127.0.0.1, então: sem Origin (navegador sempre manda num POST de outra página), JSON obrigatório
            # (força preflight de CORS, que este servidor não responde) e Host local (bloqueia DNS rebinding).
            host = urllib.parse.urlsplit("//" + (self.headers.get("Host") or "")).hostname
            if not eh_local(self.client_address[0]) or self.headers.get("Origin") or not eh_local(host):
                return self._responde(403, {"erro": "conexão só pelo sistema na própria máquina"})
            if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
                return self._responde(415, {"erro": "use application/json"})
            try:
                token, emr_url = valida_conexao(self._corpo())
            except ValueError as e:
                return self._responde(400, {"erro": str(e)})
            with trava:
                conexao.salva(token, emr_url)
            print("braço conectado ao sistema em %s" % emr_url)
            return self._responde(200, {"conectado": True})

        def do_POST(self):
            if self.path == "/conectar":
                return self._conectar()
            if self.path != "/os":
                return self._responde(404, {"erro": "rota"})
            if not conexao.conectada:
                return self._responde(503, {"erro": "braço não conectado: use 'Conectar braço' no sistema"})
            auth = self.headers.get("Authorization", "")
            if not hmac.compare_digest(auth.encode(), ("Bearer " + conexao.token).encode()):
                return self._responde(401, {"erro": "token"})
            try:
                pedido = valida_pedido(self._corpo())
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

    from braco_persistente import BracoPersistente
    from job_os import JobOS
    from pick_place import PickPlace
    from progresso import Progresso
    from sistema import Sistema

    pasta = Path(__file__).resolve().parent
    progresso = Progresso(pasta / "os_progresso.json")
    conexao = Conexao(pasta / "braco_conexao.json")

    braco = BracoPersistente(PickPlace)    # só a primeira OS abre e referencia; as seguintes vão direto

    def novo_job(pedido):
        return JobOS(pedido, lambda: braco.executor(com_nomes=bool(pedido["itens"])),
                     Sistema(callback_de(conexao.emr_url, pedido["os"]), conexao.token), progresso)

    srv = cria_servidor(args.porta, conexao, novo_job)
    estado = "conectado a %s" % conexao.emr_url if conexao.conectada else "aguardando 'Conectar braço' no sistema"
    print("braço esperando OS em http://0.0.0.0:%d/os (%s)" % (args.porta, estado))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        braco.encerrar()


if __name__ == "__main__":
    main()
