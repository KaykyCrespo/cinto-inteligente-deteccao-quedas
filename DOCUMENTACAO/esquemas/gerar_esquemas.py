"""Gera os diagramas esquemáticos do cinto e da antena (PNG e SVG) a partir da pinagem do firmware.

Uso: python DOCUMENTACAO/esquemas/gerar_esquemas.py
"""
import os

import matplotlib
matplotlib.use("Agg")
import schemdraw
import schemdraw.elements as elm

PASTA = os.path.dirname(os.path.abspath(__file__))
schemdraw.config(fontsize=11, lw=1.4)

COR_5V = "#c62828"
COR_3V3 = "#ef6c00"
COR_GND = "#212121"
COR_SINAL = "#1565c0"


def cor_da_rede(nome):
    if nome.startswith("+5V"):
        return COR_5V
    if nome.startswith("+3V3"):
        return COR_3V3
    if nome == "GND":
        return COR_GND
    return COR_SINAL


def rede(d, ic, pino, lado, nome, comprimento=1.0):
    """Liga um pino a um rótulo de rede (net label)."""
    cor = cor_da_rede(nome)
    linha = elm.Line().at(ic.absanchors[pino]).color(cor)
    linha = linha.left(comprimento) if lado == "L" else linha.right(comprimento)
    d.add(linha)
    tag = elm.Tag(width=1.6, height=0.5).color(cor).label(nome, fontsize=9, color=cor)
    d.add(tag.left() if lado == "L" else tag.right())


def nc(d, ic, pino, lado):
    linha = elm.Line().at(ic.absanchors[pino])
    d.add(linha.left(0.4) if lado == "L" else linha.right(0.4))
    d.add(elm.NoConnect())


def modulo(d, titulo, subtitulo, esquerda, direita, pos, largura=3.2, cima=(), baixo=()):
    # a schemdraw empilha os pinos laterais de baixo para cima
    pinos = [elm.IcPin(name=n, side="L", anchorname=a) for n, a in reversed(esquerda)]
    pinos += [elm.IcPin(name=n, side="R", anchorname=a) for n, a in reversed(direita)]
    pinos += [elm.IcPin(name=n, side="T", anchorname=a) for n, a in cima]
    pinos += [elm.IcPin(name=n, side="B", anchorname=a) for n, a in baixo]
    altura = max(len(esquerda), len(direita), 2) * 0.75 + 0.6
    ic = elm.Ic(pins=pinos, size=(largura, altura), pinspacing=0.75, edgepadH=0.4, leadlen=0.4,
                lsize=10, plblsize=9).right().at(pos).anchor("center")
    d.add(ic)
    d.add(elm.Label().at((pos[0], pos[1] - altura / 2 - 0.55)).label(titulo, fontsize=11, halign="center")
          .color("#000000"))
    if subtitulo:
        d.add(elm.Label().at((pos[0], pos[1] - altura / 2 - 1.0)).label(subtitulo, fontsize=8, halign="center",
                                                                         color="#555555"))
    return ic


def fonte(d, origem, duas_celulas, nome_esp_5v):
    """Bateria(s) -> TP4056 -> chave -> MT3608 (5,0 V) -> rede +5V."""
    x0, y0 = origem

    tp = modulo(d, "U2 - TP4056 (c/ DW01A)", "carregador Li-ion 1 A, USB-C 5 V",
                [("B+", "Bp"), ("B-", "Bm")], [("OUT+", "OUTp"), ("OUT-", "OUTm")],
                (x0 + 4.0, y0), largura=3.0, cima=[("USB-C 5V", "USB")])

    # baterias em paralelo, à esquerda do TP4056
    bp, bm = tp.absanchors["Bp"], tp.absanchors["Bm"]
    xr = bp[0] - 1.0
    y_base = bm[1] - 1.2
    n = 2 if duas_celulas else 1
    for i in range(n):
        x = x0 - i * 2.2
        bat = elm.Battery().at((x, y_base + 0.4)).up().label(f"BT{i + 1}\n18650\n3,7 V", loc="bottom",
                                                            fontsize=8)
        d.add(bat)
        y_topo = bat.end[1] + 0.4
        d.add(elm.Label().at((x - 0.35, bat.end[1] - 0.15)).label("+", fontsize=10, color=COR_5V))
        d.add(elm.Line().at(bat.end).toy(y_topo).color(COR_5V))
        d.add(elm.Line().at(bat.start).toy(y_base).color(COR_GND))
        if i:
            d.add(elm.Line().at((x, y_topo)).tox(x0).color(COR_5V))
            d.add(elm.Line().at((x, y_base)).tox(x0).color(COR_GND))
            d.add(elm.Dot().at((x0, y_topo)).color(COR_5V))
            d.add(elm.Dot().at((x0, y_base)).color(COR_GND))
    d.add(elm.Line().at((x0, y_topo)).tox(xr).color(COR_5V))
    d.add(elm.Wire("|-").at((xr, y_topo)).to(bp).color(COR_5V))
    d.add(elm.Line().at((x0, y_base)).tox(xr).color(COR_GND))
    d.add(elm.Wire("|-").at((xr, y_base)).to(bm).color(COR_GND))
    if duas_celulas:
        d.add(elm.Label().at((x0 - 1.1, y_topo + 0.45))
              .label("células em paralelo (mesma tensão antes de ligar)", fontsize=7, halign="center",
                     color="#555555"))

    # chave e MT3608
    mt = modulo(d, "U3 - MT3608", "step-up, trimpot ajustado p/ 5,0 V",
                [("VIN+", "VINp"), ("VIN-", "VINm")], [("VOUT+", "VOUTp"), ("VOUT-", "VOUTm")],
                (x0 + 11.0, y0), largura=3.0)
    sw = elm.Switch().at(tp.absanchors["OUTp"]).right(2.0).color(COR_5V).label("SW1\nchave gangorra",
                                                                                  loc="top", fontsize=8)
    d.add(sw)
    d.add(elm.Wire("-|").at(sw.end).to(mt.absanchors["VINp"]).color(COR_5V))
    d.add(elm.Line().at(tp.absanchors["OUTm"]).to(mt.absanchors["VINm"]).color(COR_GND))

    # saída 5 V com capacitor de reserva
    p5 = mt.absanchors["VOUTp"]
    g5 = mt.absanchors["VOUTm"]
    d.add(elm.Line().at(p5).right(1.2).color(COR_5V))
    d.add(elm.Dot().color(COR_5V))
    no_5v = d.here
    d.add(elm.Line().right(3.0).color(COR_5V))
    d.add(elm.Tag(width=1.6, height=0.5).right().color(COR_5V).label(nome_esp_5v, fontsize=9, color=COR_5V))
    d.add(elm.Line().at(g5).right(1.2).color(COR_GND))
    d.add(elm.Dot().color(COR_GND))
    no_gnd = d.here
    d.add(elm.Line().right(3.0).color(COR_GND))
    d.add(elm.Tag(width=1.6, height=0.5).right().color(COR_GND).label("GND", fontsize=9, color=COR_GND))
    d.add(elm.Capacitor(polar=True).at(no_5v).to(no_gnd).linestyle("--")
          .label("C1 470 µF/10 V\n(recomendado)", loc="bottom", ofst=0.15, fontsize=7))
    return tp, mt


def titulo(d, texto, sub, pos):
    d.add(elm.Label().at(pos).label(texto, fontsize=15, halign="left"))
    d.add(elm.Label().at((pos[0], pos[1] - 0.6)).label(sub, fontsize=9, halign="left", color="#555555"))


def legenda(d, pos):
    x, y = pos
    itens = [(COR_5V, "+5 V (saída do MT3608)"), (COR_3V3, "+3,3 V (regulador da placa ESP32)"),
             (COR_GND, "GND (terra comum)"), (COR_SINAL, "sinais")]
    d.add(elm.Label().at((x, y)).label("Legenda: rótulos com o mesmo nome estão ligados entre si.",
                                         fontsize=8, halign="left"))
    for i, (cor, txt) in enumerate(itens):
        yy = y - 0.5 * (i + 1)
        d.add(elm.Line().at((x, yy)).right(0.8).color(cor).linewidth(2.5))
        d.add(elm.Label().at((x + 1.0, yy)).label(txt, fontsize=8, halign="left"))


def esquema_cinto():
    with schemdraw.Drawing(show=False) as d:
        d.config(unit=2.0)
        titulo(d, "Esquema elétrico — Cinto inteligente (cinto_mvp_v1)",
               "ESP32-C3 Super Mini + MPU6050 (GY-521) + AD8232 · alimentação 2× 18650 → TP4056 → MT3608 (5 V)",
               (-4, 7.2))
        fonte(d, (0, 4.2), duas_celulas=True, nome_esp_5v="+5V")

        esp = modulo(d, "U1 - ESP32-C3 Super Mini", "I²C 400 kHz · ADC 12 bits · BLE 5 (+9 dBm)",
                     [("5V", "p5V"), ("GND", "GND"), ("3V3", "p3V3"),
                      ("GPIO2", "G2"), ("GPIO3", "G3"), ("GPIO4/ADC", "G4")],
                     [("GPIO8 SDA", "G8"), ("GPIO9 SCL", "G9"), ("GPIO10", "G10")],
                     (4.0, -3.0), largura=4.4)
        rede(d, esp, "p5V", "L", "+5V")
        rede(d, esp, "GND", "L", "GND")
        rede(d, esp, "p3V3", "L", "+3V3")
        rede(d, esp, "G2", "L", "LO-")
        rede(d, esp, "G3", "L", "LO+")
        rede(d, esp, "G4", "L", "ECG_OUT")
        rede(d, esp, "G8", "R", "SDA")
        rede(d, esp, "G9", "R", "SCL")

        # LED de eletrodo solto
        d.add(elm.Line().at(esp.absanchors["G10"]).right(1.0).color(COR_SINAL))
        d.add(elm.Resistor().right(2.0).label("R1 330 Ω", loc="bottom", fontsize=8))
        d.add(elm.LED().down(1.6).label("D1\neletrodo\nsolto", loc="bottom", fontsize=8))
        d.add(elm.Ground())

        mpu = modulo(d, "U4 - MPU6050 (GY-521)", "endereço I²C 0x68 · ±8 g / ±2000 °/s",
                     [("VCC", "VCC"), ("GND", "GND"), ("SCL", "SCL"), ("SDA", "SDA")],
                     [("AD0", "AD0"), ("INT", "INT"), ("XDA", "XDA"), ("XCL", "XCL")],
                     (17.0, -3.0), largura=3.2)
        rede(d, mpu, "VCC", "L", "+3V3")
        rede(d, mpu, "GND", "L", "GND")
        rede(d, mpu, "SCL", "L", "SCL")
        rede(d, mpu, "SDA", "L", "SDA")
        rede(d, mpu, "AD0", "R", "GND", comprimento=0.6)
        for p in ("INT", "XDA", "XCL"):
            nc(d, mpu, p, "R")
        d.add(elm.Label().at((17.0, -6.4)).label("pull-ups de SDA/SCL e desacoplamento\njá integrados ao GY-521",
                                                  fontsize=7, halign="center", color="#555555"))

        ad = modulo(d, "U5 - AD8232", "front-end de ECG de uma derivação",
                    [("3.3V", "V33"), ("GND", "GND"), ("OUTPUT", "OUT"), ("LO-", "LOm"), ("LO+", "LOp"),
                     ("SDN", "SDN")],
                    [("RA", "RA"), ("LA", "LA"), ("RL", "RL")],
                    (4.0, -11.0), largura=3.2)
        rede(d, ad, "V33", "L", "+3V3")
        rede(d, ad, "GND", "L", "GND")
        rede(d, ad, "OUT", "L", "ECG_OUT")
        rede(d, ad, "LOm", "L", "LO-")
        rede(d, ad, "LOp", "L", "LO+")
        nc(d, ad, "SDN", "L")

        # conector P2 e eletrodos
        jx = 10.0
        for pino, texto in (("RA", "RA - braço direito"), ("LA", "LA - braço esquerdo"),
                            ("RL", "RL - referência (perna direita)")):
            y = ad.absanchors[pino][1]
            d.add(elm.Line().at(ad.absanchors[pino]).tox(jx).color(COR_SINAL))
            d.add(elm.Dot(open=True))
            d.add(elm.Label().at((jx + 0.3, y)).label(f"eletrodo {texto}", fontsize=8, halign="left"))
        d.add(elm.Label().at((jx - 1.6, ad.absanchors["RA"][1] + 0.7))
              .label("J1 - conector P2 3,5 mm", fontsize=8, halign="center", color="#555555"))

        legenda(d, (18.0, -8.8))
        d.add(elm.Label().at((18.0, -12.6)).label(
            "Notas:\n"
            "• Ajuste o MT3608 para 5,0 V antes de ligar o ESP32-C3.\n"
            "• Desligue SW1 antes de conectar o USB-C do ESP32-C3 (gravação).\n"
            "• SDN do AD8232 fica aberto (pull-up no módulo = ligado).\n"
            "• INT, XDA e XCL do MPU6050 não são usados.\n"
            "• Pinos conforme Arduino/cinto_mvp_v1/cinto_mvp_v1.ino.",
            fontsize=8, halign="left"))
        for ext in ("png", "svg"):
            d.save(os.path.join(PASTA, f"esquema_cinto.{ext}"), dpi=200)


def esquema_antena():
    with schemdraw.Drawing(show=False) as d:
        d.config(unit=2.0)
        titulo(d, "Esquema elétrico — Antena (anchor_mvp_v1)",
               "ESP32 DevKit V1 (ESP32-WROOM-32) · alimentação 1× 18650 → TP4056 → MT3608 (5 V)",
               (-4, 7.2))
        fonte(d, (0, 4.2), duas_celulas=False, nome_esp_5v="+5V")

        esp = modulo(d, "U1 - ESP32 DevKit V1", "Wi-Fi 2,4 GHz + BLE · USB-serial CP2102 (Micro-USB)",
                     [("VIN", "VIN"), ("GND", "GND")],
                     [("3V3", "p3V3"), ("EN", "EN")],
                     (4.0, -2.8), largura=4.4, cima=[("Micro-USB", "USB")])
        rede(d, esp, "VIN", "L", "+5V")
        rede(d, esp, "GND", "L", "GND")
        nc(d, esp, "p3V3", "R")
        nc(d, esp, "EN", "R")

        legenda(d, (11.0, -1.4))
        d.add(elm.Label().at((-4.0, -6.2)).label(
            "Notas:\n"
            "• A antena não tem sensores: só alimentação; BLE e Wi-Fi usam a antena interna do módulo.\n"
            "• Ajuste o MT3608 para 5,0 V antes de ligar o ESP32.\n"
            "• Desligue SW1 antes de conectar o Micro-USB (gravação), para não ligar\n"
            "  a saída do MT3608 em paralelo com o 5 V do USB.\n"
            "• Configuração (Wi-Fi, broker MQTT, ID_ANTENA) em Arduino/anchor_mvp_v1/anchor_mvp_v1.ino.",
            fontsize=8, halign="left"))
        for ext in ("png", "svg"):
            d.save(os.path.join(PASTA, f"esquema_antena.{ext}"), dpi=200)


if __name__ == "__main__":
    esquema_cinto()
    esquema_antena()
    print("Esquemas gerados em", PASTA)
