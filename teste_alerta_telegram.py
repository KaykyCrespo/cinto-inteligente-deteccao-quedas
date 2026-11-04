import ast
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import URLError

import alerta_telegram as tg


class TestControleTelegram(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        caminho = Path(__file__).with_name("app.py")
        arvore = ast.parse(caminho.read_text(encoding="utf-8-sig"))
        classe = next(node for node in arvore.body
                      if isinstance(node, ast.ClassDef) and node.name == "Conexao")
        contexto = {"threading": threading, "tg": tg}
        exec(compile(ast.Module(body=[classe], type_ignores=[]), str(caminho), "exec"), contexto)
        cls.classe_conexao = contexto["Conexao"]

    def setUp(self):
        self.conexao = self.classe_conexao.__new__(self.classe_conexao)
        self.conexao.lock = threading.Lock()
        self.conexao.telegram_ativo = False
        self.conexao.telegram_geracao = 0
        self.conexao.fechada = False
        self.conexao.detectar = True
        configurado = patch.object(tg, "configurado", return_value=True)
        configurado.start()
        self.addCleanup(configurado.stop)
        self.conexao.configurar_telegram(True)
        self.geracao = self.conexao.telegram_geracao

    def permitido(self):
        return self.conexao._telegram_permitido(self.geracao)

    def test_envio_ativo(self):
        with patch.object(tg, "_post", return_value=True) as post:
            self.assertEqual(tg.enviar_sincrono("teste", permitido=self.permitido), (True, None))
            post.assert_called_once_with("teste")

    def test_desativar_bloqueia_envio(self):
        self.conexao.configurar_telegram(False)
        with patch.object(tg, "_post") as post:
            ok, erro = tg.enviar_sincrono("teste", permitido=self.permitido)
            self.assertFalse(ok)
            self.assertIn("cancelado", erro)
            post.assert_not_called()

    def test_reativar_nao_libera_mensagem_antiga(self):
        self.conexao.configurar_telegram(False)
        self.conexao.configurar_telegram(True)
        self.assertFalse(self.permitido())
        self.assertTrue(self.conexao._telegram_permitido(self.conexao.telegram_geracao))

    def test_desativar_cancela_thread_pendente(self):
        tarefas = []
        resultados = []

        def thread_adiada(*, target, daemon):
            tarefas.append(target)
            return SimpleNamespace(start=lambda: None)

        with patch.object(tg.threading, "Thread", side_effect=thread_adiada), patch.object(tg, "_post") as post:
            tg.enviar("teste", callback=lambda *resultado: resultados.append(resultado),
                      permitido=self.permitido)
            self.conexao.configurar_telegram(False)
            tarefas[0]()
            post.assert_not_called()
        self.assertFalse(resultados[0][0])
        self.assertIn("cancelado", resultados[0][1])

    def test_desativar_impede_nova_tentativa(self):
        def falhar_e_desativar(texto):
            self.conexao.configurar_telegram(False)
            raise URLError("rede indisponivel")

        with patch.object(tg, "_post", side_effect=falhar_e_desativar) as post:
            ok, erro = tg.enviar_sincrono("teste", permitido=self.permitido)
            post.assert_called_once()
        self.assertFalse(ok)
        self.assertIn("cancelado", erro)

    def test_fechar_bloqueia_envios_da_conexao_antiga(self):
        self.conexao.parar_gravacao = lambda: None
        self.conexao.client = SimpleNamespace(loop_stop=lambda: None, disconnect=lambda: None)
        self.conexao.fechar()
        self.assertFalse(self.permitido())

    def test_deteccao_desligada_bloqueia_alerta_automatico(self):
        self.conexao.detectar = False
        self.assertFalse(self.permitido())

    def test_teste_manual_independe_do_controle_automatico(self):
        self.conexao.configurar_telegram(False)
        with patch.object(tg, "_post", return_value=True) as post:
            self.assertEqual(tg.enviar_sincrono("teste manual"), (True, None))
            post.assert_called_once_with("teste manual")


if __name__ == "__main__":
    unittest.main()