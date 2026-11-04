import math
import unittest

import localizacao as loc


class TestLocalizacao(unittest.TestCase):
    def setUp(self):
        self.tracker = loc.Localizador()
        self.inicial = (loc.LADO_M * 0.2, loc.LADO_M * 0.2)
        self.destino = (loc.LADO_M * 0.8, loc.LADO_M * 0.8)

    def alimentar(self, instante, ponto=None, rssi_fixo=None, cinto=1, antenas=None):
        ponto = self.inicial if ponto is None else ponto
        for antena, coordenadas in loc.ANCHORS.items():
            if antenas is not None and antena not in antenas:
                continue
            distancia = math.dist(ponto, coordenadas)
            rssi = loc.RSSI_1M - 10 * loc.N_PERDA * math.log10(distancia)
            self.tracker.atualizar(cinto, antena, rssi if rssi_fixo is None else rssi_fixo, instante)

    def test_posicao_consistente(self):
        self.alimentar(0)
        pos = self.tracker.estimar(1, 0)
        self.assertEqual(pos["quadrante"], "IE")
        self.assertEqual(pos["confianca"], "boa")
        self.assertFalse(pos["retida"])
        self.assertAlmostEqual(pos["x"], self.inicial[0], places=3)
        self.assertAlmostEqual(pos["y"], self.inicial[1], places=3)

    def test_mediana_rejeita_pico_isolado(self):
        for instante in (0, 0.1, 0.2):
            self.alimentar(instante)
        esperado = self.tracker.rssi_suavizado(1, 0.2)
        self.alimentar(0.3, rssi_fixo=-110)
        self.assertEqual(self.tracker.rssi_suavizado(1, 0.3), esperado)

    def test_oscilacao_breve_nao_troca_quadrante(self):
        self.alimentar(0)
        self.tracker.estimar(1, 0)
        for passo in range(1, 21):
            instante = passo / 10
            self.alimentar(instante, self.destino if instante <= 0.5 else self.inicial)
            pos = self.tracker.estimar(1, instante)
            self.assertIsNotNone(pos)
            self.assertEqual(pos["quadrante"], "IE")

    def test_mudanca_persistente_exige_confirmacao(self):
        self.alimentar(0)
        self.tracker.estimar(1, 0)
        houve_incerteza = False
        confirmado_em = None
        for passo in range(1, 81):
            instante = passo / 10
            self.alimentar(instante, self.destino)
            pos = self.tracker.estimar(1, instante)
            houve_incerteza |= pos is not None and pos["confianca"] == "baixa"
            if pos and pos["quadrante"] == "SD" and pos["confianca"] == "boa":
                confirmado_em = instante
                break
        self.assertTrue(houve_incerteza)
        self.assertIsNotNone(confirmado_em)
        self.assertGreaterEqual(confirmado_em, loc.CONFIRMACAO_S)

    def test_reter_e_expirar_sem_dados(self):
        self.alimentar(0)
        inicial = self.tracker.estimar(1, 0)
        pos = self.tracker.estimar(1, loc.FRESCOR_S + 0.1)
        self.assertEqual(pos["confianca"], "baixa")
        self.assertTrue(pos["retida"])
        self.assertEqual((pos["x"], pos["y"]), (inicial["x"], inicial["y"]))
        for instante in (3, 4, 5, loc.RETENCAO_S + 0.1):
            pos = self.tracker.estimar(1, instante)
        self.assertIsNone(pos)

    def test_leitura_repetida_nao_confirma_mudanca(self):
        self.alimentar(0)
        self.tracker.estimar(1, 0)
        for historico in self.tracker.hist[1].values():
            historico.clear()
        self.alimentar(1, self.destino)
        for instante in (1, 1.5, 2, 3, 4.1):
            pos = self.tracker.estimar(1, instante)
            self.assertEqual(pos["quadrante"], "IE")
            self.assertEqual(pos["confianca"], "baixa")

    def test_sinal_incompativel_expira_posicao(self):
        self.alimentar(0)
        self.tracker.estimar(1, 0)
        for passo in range(1, 101):
            instante = passo / 10
            self.alimentar(instante, rssi_fixo=-110)
            pos = self.tracker.estimar(1, instante)
        self.assertIsNone(pos)

    def test_residuo_alto_retem_posicao(self):
        self.alimentar(0)
        self.tracker.estimar(1, 0)
        for historico in self.tracker.hist[1].values():
            historico.clear()
        rssi = loc.RSSI_1M - 10 * loc.N_PERDA * math.log10(loc.LADO_M * 1.4)
        self.alimentar(1, rssi_fixo=rssi)
        pos = self.tracker.estimar(1, 1)
        self.assertTrue(pos["retida"])
        self.assertEqual(pos["confianca"], "baixa")

    def test_duas_antenas_nao_confirmam_e_retomada_recupera(self):
        self.alimentar(0, antenas=(1, 2))
        self.assertIsNone(self.tracker.estimar(1, 0))
        self.alimentar(1)
        self.assertEqual(self.tracker.estimar(1, 1)["confianca"], "boa")
        self.alimentar(4, antenas=(1, 2))
        self.assertEqual(self.tracker.estimar(1, 4)["confianca"], "baixa")
        self.assertIsNone(self.tracker.estimar(1, 8))
        self.alimentar(9, self.destino)
        pos = self.tracker.estimar(1, 9)
        self.assertEqual(pos["confianca"], "boa")
        self.assertEqual(pos["quadrante"], "SD")

    def test_cintos_independentes(self):
        self.alimentar(0, cinto=1)
        self.alimentar(0, self.destino, cinto=2)
        self.assertEqual(self.tracker.estimar(1, 0)["quadrante"], "IE")
        self.assertEqual(self.tracker.estimar(2, 0)["quadrante"], "SD")

    def test_histerese_proxima_da_divisa(self):
        self.assertEqual(loc.quadrante(loc.LADO_M / 2 + 0.1, 1, "IE"), "IE")
        self.assertEqual(loc.quadrante(loc.LADO_M / 2 + loc.HISTERESE_M + 0.1, 1, "IE"), "ID")

    def test_rssi_nao_finito_ignorado(self):
        self.alimentar(0, rssi_fixo=float("nan"))
        self.assertIsNone(self.tracker.estimar(1, 0))


if __name__ == "__main__":
    unittest.main()