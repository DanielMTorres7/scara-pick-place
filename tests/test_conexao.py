import pytest

from conexao import Conexao, valida_conexao

TOKEN = "a" * 32


def test_sem_arquivo_nao_conectada(tmp_path):
    c = Conexao(tmp_path / "c.json")
    assert (c.conectada, c.token, c.emr_url) == (False, "", "")


def test_salva_e_recarrega(tmp_path):
    Conexao(tmp_path / "c.json").salva(TOKEN, "http://127.0.0.1:8765")
    c = Conexao(tmp_path / "c.json")
    assert (c.conectada, c.token, c.emr_url) == (True, TOKEN, "http://127.0.0.1:8765")


def test_arquivo_corrompido_nao_conectada(tmp_path):
    (tmp_path / "c.json").write_text("{lixo")
    assert Conexao(tmp_path / "c.json").conectada is False


def test_valida_conexao_ok():
    assert valida_conexao({"token": TOKEN, "emr_url": "http://127.0.0.1:8765/"}) == (TOKEN, "http://127.0.0.1:8765")


@pytest.mark.parametrize("ruim", [
    None, [], {"token": "curto", "emr_url": "http://x"}, {"token": TOKEN, "emr_url": "ftp://x"},
    {"token": TOKEN}, {"token": 5, "emr_url": "http://x"},
])
def test_valida_conexao_recusa(ruim):
    with pytest.raises(ValueError):
        valida_conexao(ruim)


@pytest.mark.parametrize("url", ["http://192.168.0.10:8765", "http://evil.com", "http://u:p@127.0.0.1:8765",
                                 "http://127.0.0.1.evil.com:8765"])
def test_emr_url_so_na_propria_maquina(url):
    with pytest.raises(ValueError):
        valida_conexao({"token": TOKEN, "emr_url": url})


@pytest.mark.parametrize("url", ["http://localhost:8765", "http://[::1]:8765", "https://127.0.0.1"])
def test_emr_url_local_aceita(url):
    assert valida_conexao({"token": TOKEN, "emr_url": url})[1] == url
