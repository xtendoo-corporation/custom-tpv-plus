"""Checks the card-reader entry points of the kiosk in a real browser (selenium + chrome, running server).

Usage: e2e_nfc.py URL/feria
Imitates the TPVPlus Android app: an injected NDEFReader polyfill (+ __nfcTriggerRead) and the global
window.handleNfcScan. Expects customers "Estres" (card STRESS01) and "Estela Prueba" (card ESTELA01).
"""
import sys
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

URL = sys.argv[1]

POLYFILL = """
(() => {
    let active = null;
    class Reader {
        constructor() { this._l = {}; }
        addEventListener(t, f) { (this._l[t] = this._l[t] || []).push(f); }
        removeEventListener() {}
        async scan() { active = this; window.__scans = (window.__scans || 0) + 1; }
        _emit(ev) { (this._l.reading || []).forEach((f) => f(ev)); }
    }
    window.NDEFReader = Reader;
    // what MainActivity.onNewIntent calls: UID as lowercase hex, or the NDEF text
    window.__nfcTriggerRead = (id) => {
        if (!active) { return false; }
        active._emit({ serialNumber: id.toUpperCase(), message: { records: [] } });
        return true;
    };
    window.__nfcTriggerText = (text, uid) => active && active._emit({
        serialNumber: uid, message: { records: [{ recordType: 'text', encoding: 'utf-8', data: new TextEncoder().encode(text) }] },
    });
})();
"""


def driver(polyfill):
    options = Options()
    for arg in ('--headless=new', '--no-sandbox', '--disable-gpu'):
        options.add_argument(arg)
    d = webdriver.Chrome(options=options)
    d.implicitly_wait(5)
    if polyfill:
        d.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': POLYFILL})
    d.get(URL)
    time.sleep(1)
    return d


def screen(d):
    # lower case: the design shows some labels in capitals through CSS
    return d.find_element(By.ID, 'app').text.replace('\n', ' | ').lower()


def start(d, action):
    d.find_element(By.CSS_SELECTOR, f'[data-act="start"][data-a="{action}"]').click()
    time.sleep(0.4)


ok = True


def check(name, passed, detail=''):
    global ok
    ok &= bool(passed)
    print(f'[{"OK" if passed else "FAIL"}] {name} {detail}')


# A. Android app: injected NDEFReader, tag delivered through __nfcTriggerRead
d = driver(polyfill=True)
try:
    check('NFC reader started on its own', d.execute_script('return window.__scans') >= 1)
    start(d, 'COBRAR')
    d.execute_script("window.__nfcTriggerRead('stress01')")  # UID as the app sends it
    time.sleep(1.2)
    check('UID tag opens the customer (COBRAR -> amount screen)', 'estres' in screen(d) and 'importe a cobrar' in screen(d), screen(d)[:90])
    d.find_element(By.CSS_SELECTOR, '[data-act="home"]').click()
    start(d, 'CONSULTA')
    d.execute_script("window.__nfcTriggerText('ESTELA01', '04:aa:bb:cc')")  # NDEF text wins over the UID
    time.sleep(1.2)
    check('NDEF text record is used instead of the UID', 'estela prueba' in screen(d), screen(d)[:90])
    d.find_element(By.CSS_SELECTOR, '[data-act="home"]').click()
    d.execute_script("window.__nfcTriggerRead('stress01')")  # tag while on the home screen
    time.sleep(1)
    check('a tag on the home screen is ignored', 'cobrar' in screen(d) and 'importe a cobrar' not in screen(d))
    start(d, 'CONSULTA')
    d.execute_script("window.__nfcTriggerRead('nope9999')")
    time.sleep(1.2)
    check('unknown tag shows "no reconocida"', 'no reconocida' in screen(d), screen(d)[:100])
finally:
    d.quit()

# B. Native bridge fallback and keyboard-wedge reader, no NDEFReader available
d = driver(polyfill=False)
try:
    start(d, 'CONSULTA')
    d.execute_script("window.handleNfcScan('estela01')")
    time.sleep(1.2)
    check('window.handleNfcScan opens the customer', 'estela prueba' in screen(d), screen(d)[:90])
    d.find_element(By.CSS_SELECTOR, '[data-act="home"]').click()
    start(d, 'CONSULTA')
    d.execute_script("window.handleNfcScan('estela01'); window.handleNfcScan('estela01');")
    time.sleep(1.5)
    check('a repeated read within 2 s is ignored (no double lookup)', 'estela prueba' in screen(d))
    d.find_element(By.CSS_SELECTOR, '[data-act="home"]').click()
    start(d, 'CONSULTA')
    ActionChains(d).send_keys('04:AA-BB').send_keys(Keys.ENTER).perform()  # a wedge reader types the code, then Enter
    time.sleep(1.2)
    check('keyboard-wedge reader text is captured (no field) and unknown cards are refused', 'no reconocida' in screen(d))
    d.find_element(By.CSS_SELECTOR, '[data-act="home"]').click()
    start(d, 'CONSULTA')
    ActionChains(d).send_keys('ESTELA01').perform()  # readers without the Enter suffix: the end of the burst is enough
    time.sleep(1.6)
    check('a fast burst without Enter is also read', 'estela prueba' in screen(d), screen(d)[:80])
    check('there is no search field on the screen', not d.find_elements(By.CSS_SELECTOR, 'input'))
finally:
    d.quit()

print('RESULT:', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
