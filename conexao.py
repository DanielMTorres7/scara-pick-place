"""Com qual sistema EMR o braço está conectado: token compartilhado e endereço do EMR, gravados quando o operador
clica "Conectar braço" na tela do sistema (POST /conectar). Fica em disco para valer depois de reiniciar."""
import ipaddress
import json
import os
import urllib.parse
from pathlib import Path

TOKEN_MIN = 16


def eh_local(host):
    """"localhost" ou IP de loopback (inclui IPv4 mapeado em IPv6)"""
    if host is None:
        return False
    if host.lower() == "localhost":
        return True
    try:
        a = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped:
        a = a.ipv4_mapped
    return a.is_loopback


def valida_conexao(corpo):
    """confere o pedido de conexão e devolve (token, emr_url sem barra no fim)"""
    if not isinstance(corpo, dict):
        raise ValueError("corpo deve ser um objeto JSON")
    token, url = corpo.get("token"), corpo.get("emr_url")
    if not isinstance(token, str) or len(token) < TOKEN_MIN:
        raise ValueError("token: texto com %d+ caracteres" % TOKEN_MIN)
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise ValueError("emr_url: URL http(s)")
    partes = urllib.parse.urlsplit(url)
    # sistema e braço na mesma máquina: o token só vai para um endereço local, sem usuário/senha na URL
    if partes.username or partes.password or not eh_local(partes.hostname):
        raise ValueError("emr_url: só o sistema da própria máquina (localhost)")
    return token, url.rstrip("/")


class Conexao:
    def __init__(self, caminho):
        self.caminho = Path(caminho)
        self.token, self.emr_url = "", ""
        try:
            d = json.loads(self.caminho.read_text(encoding="utf-8"))
            self.token, self.emr_url = valida_conexao(d)
        except (FileNotFoundError, ValueError):
            pass

    @property
    def conectada(self):
        return bool(self.token and self.emr_url)

    def salva(self, token, emr_url):
        tmp = self.caminho.with_suffix(".tmp")
        tmp.write_text(json.dumps({"token": token, "emr_url": emr_url}), encoding="utf-8")
        os.chmod(tmp, 0o600)     # o token dá acesso ao /api/robo do sistema
        os.replace(tmp, self.caminho)
        self.token, self.emr_url = token, emr_url
