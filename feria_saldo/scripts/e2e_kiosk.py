"""Browser walk-through of the kiosk (needs selenium + chrome and a running server).

Usage: e2e_kiosk.py OUT_DIR URL/feria WIDTH HEIGHT TAG   (screenshots go to OUT_DIR)
Expects a contact "Estres" with card STRESS01 and a second customer "Estela Prueba" (card ESTELA01).
There is no search box: a reader "types" the code and presses Enter, which is what the script simulates.
"""
import sys
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys

OUT, URL, W, H, TAG = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
options = Options()
for arg in ('--headless=new', '--no-sandbox', '--disable-gpu', '--hide-scrollbars'):
    options.add_argument(arg)
d = webdriver.Chrome(options=options)
d.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {'width': W, 'height': H, 'deviceScaleFactor': 1, 'mobile': W < 700})
d.implicitly_wait(5)


def shot(name):
    d.save_screenshot(f'{OUT}/{TAG}_{name}.png')


def click(act, **kw):
    d.find_element(By.CSS_SELECTOR, f'[data-act="{act}"]' + ''.join(f'[data-{k}="{v}"]' for k, v in kw.items())).click()


def text():
    return d.find_element(By.ID, 'app').text.replace('\n', ' | ')


def scan(code):
    """What a keyboard-wedge reader does: a fast burst of characters and Enter."""
    ActionChains(d).send_keys(code).send_keys(Keys.ENTER).perform()
    time.sleep(1.4)


def ask(action, code):
    click('start', a=action)
    time.sleep(0.6)
    scan(code)


try:
    d.get(URL)
    time.sleep(1)
    print('HOME:', text())
    shot('1_home')
    print('BIG BUTTONS:', [(b.size['width'], b.size['height']) for b in d.find_elements(By.CSS_SELECTOR, '.big')])
    click('start', a='CONSULTA')
    time.sleep(0.5)
    shot('2_escanear')
    print('SCAN SCREEN:', text())
    print('NO TEXT FIELD:', not d.find_elements(By.CSS_SELECTOR, 'input'))
    scan('nope9999')
    print('UNKNOWN CARD:', text())
    scan('stress01')
    print('SALDO (card):', text())
    shot('3_saldo')
    click('home')
    ask('CONSULTA', 'estela01')
    print('SALDO (other card):', text())
    click('home')
    ask('CONSULTA', 'stress01')
    print('PEDIDOS:', text())
    shot('4_pedidos')
    click('home')
    ask('COBRAR', 'stress01')
    for k in '1.5':
        click('key', k=k)
    shot('5_importe')
    click('confirm')
    time.sleep(1.5)
    print('COBRO:', text())
    shot('6_resultado')
    click('home')
    ask('RECARGAR', 'stress01')
    for v in (10, 5, 5):  # coins and notes, no keypad
        click('denom', v=v)
    shot('7_recargar')
    print('RECARGA pide como paga:', [b.text for b in d.find_elements(By.CSS_SELECTOR, '[data-act="confirm"]')])
    click('confirm', pay='cash')
    time.sleep(1.5)
    print('RECARGA:', text())
    print('CONSOLE ERRORS:', [m for m in d.get_log('browser') if m['level'] == 'SEVERE'])
finally:
    d.quit()
