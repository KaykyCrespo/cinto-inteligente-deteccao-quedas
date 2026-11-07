from pathlib import Path
from time import sleep
from playwright.sync_api import sync_playwright

base = Path(r"c:\Users\User\Documents\Repositório\cinto-inteligente-deteccao-quedas")
out = base / "DOCUMENTACAO" / "APOIO" / "IMAGENS" / "prints" / "originais"
out.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=1)
    print('navigating...')
    page.goto('http://localhost:8501', wait_until='domcontentloaded', timeout=60000)
    page.wait_for_selector('text=Monitoramento', timeout=60000)
    print('loaded')
    sleep(5)
    page.locator('[data-testid="stSidebar"]').screenshot(path=str(out / 'barra_lateral_test.png'), animations='disabled')
    print('sidebar saved')
    page.get_by_role('tab', name='Monitoramento').click()
    sleep(2)
    page.locator('main').screenshot(path=str(out / 'monitoramento_test.png'), animations='disabled')
    print('main saved')
    browser.close()
    print('done')
