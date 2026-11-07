import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

BASE = Path(r"c:\Users\User\Documents\Repositório\cinto-inteligente-deteccao-quedas")
ORIGINAIS = BASE / "DOCUMENTACAO" / "APOIO" / "IMAGENS" / "prints" / "originais"
DESTINO = BASE / "DOCUMENTACAO" / "APOIO" / "IMAGENS" / "prints"
JSON_PATH = BASE / "DOCUMENTACAO" / "esquemas" / "prints_anotacoes.json"
RED = (198, 40, 40)


def carregar_json():
    if not JSON_PATH.exists():
        return {}
    with JSON_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def desenhar_numero(imagem, x, y, numero, raio=18):
    draw = ImageDraw.Draw(imagem)
    draw.ellipse((x - raio, y - raio, x + raio, y + raio), outline=RED, width=2)
    draw.ellipse((x - raio + 2, y - raio + 2, x + raio - 2, y + raio - 2), outline=RED, width=2)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", int(raio + 4))
    except OSError:
        font = ImageFont.load_default()
    txt = str(numero)
    bbox = draw.textbbox((0, 0), txt, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((x - tw / 2, y - th / 2), txt, fill="white", font=font, anchor="mm")
    return imagem


def anotar_imagem(nome, marcacoes):
    origem = ORIGINAIS / f"{nome}.png"
    if not origem.exists():
        return
    img = Image.open(origem).convert("RGBA")
    for item in marcacoes:
        x = int(item["x"])
        y = int(item["y"])
        desenhar_numero(img, x, y, int(item["numero"]))
    img.save(DESTINO / f"{nome}.png")


def gerar_json_automatico():
    if ORIGINAIS.exists():
        itens = [
            "barra_lateral",
            "monitoramento_normal",
            "detalhes_status",
            "detalhes_mapa",
            "detalhes_sinais_ecg",
            "detalhes_exportacao",
        ]
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=1)
            page.goto("http://localhost:8501", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector("text=Monitoramento", timeout=60000)
            page.wait_for_timeout(5000)

            dados = {}

            sidebar = page.locator('[data-testid="stSidebar"]')
            box = sidebar.bounding_box()
            if box:
                cx = int(box["x"] + box["width"] / 2)
                dados["barra_lateral"] = [
                    {"numero": 1, "x": cx, "y": int(box["y"] + 120)},
                    {"numero": 2, "x": cx, "y": int(box["y"] + 240)},
                    {"numero": 3, "x": cx, "y": int(box["y"] + 450)},
                    {"numero": 4, "x": cx, "y": int(box["y"] + 560)},
                    {"numero": 5, "x": cx, "y": int(box["y"] + 660)},
                    {"numero": 6, "x": cx, "y": int(box["y"] + 750)},
                    {"numero": 7, "x": cx, "y": int(box["y"] + 840)},
                ]

            page.get_by_role("tab", name="Monitoramento").click()
            page.wait_for_timeout(2000)
            dados["monitoramento_normal"] = [
                {"numero": 1, "x": 430, "y": 180},
                {"numero": 2, "x": 570, "y": 270},
                {"numero": 3, "x": 690, "y": 270},
                {"numero": 4, "x": 860, "y": 270},
                {"numero": 5, "x": 1060, "y": 270},
                {"numero": 6, "x": 540, "y": 650},
                {"numero": 7, "x": 1120, "y": 670},
            ]

            page.get_by_role("tab", name="Detalhes").click()
            page.wait_for_timeout(1500)
            dados["detalhes_status"] = [
                {"numero": 1, "x": 520, "y": 180},
                {"numero": 2, "x": 760, "y": 195},
                {"numero": 3, "x": 1000, "y": 195},
                {"numero": 4, "x": 300, "y": 370},
                {"numero": 5, "x": 760, "y": 370},
                {"numero": 6, "x": 1180, "y": 370},
            ]

            page.get_by_text("Ambiente e posição das antenas").first.click()
            page.wait_for_timeout(1000)
            dados["detalhes_mapa"] = [
                {"numero": 1, "x": 300, "y": 160},
                {"numero": 2, "x": 560, "y": 170},
                {"numero": 3, "x": 910, "y": 170},
                {"numero": 4, "x": 430, "y": 470},
                {"numero": 5, "x": 960, "y": 460},
                {"numero": 6, "x": 1150, "y": 550},
            ]

            dados["detalhes_sinais_ecg"] = [
                {"numero": 1, "x": 350, "y": 165},
                {"numero": 2, "x": 980, "y": 165},
                {"numero": 3, "x": 1180, "y": 470},
            ]

            dados["detalhes_exportacao"] = [
                {"numero": 1, "x": 300, "y": 200},
                {"numero": 2, "x": 710, "y": 200},
                {"numero": 3, "x": 1060, "y": 200},
            ]

            browser.close()
            with JSON_PATH.open("w", encoding="utf-8") as f:
                json.dump(dados, f, ensure_ascii=False, indent=2)


def main():
    dados = carregar_json()
    if not dados:
        gerar_json_automatico()
        dados = carregar_json()
    for nome, marcacoes in dados.items():
        anotar_imagem(nome, marcacoes)
    print(f"Anotações salvas em {DESTINO}")


if __name__ == "__main__":
    main()
