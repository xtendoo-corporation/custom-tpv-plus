"""Checks the card-reader entry points of the kiosk in a real browser (selenium + chrome, running server).

Usage: e2e_nfc.py URL/feria
Imitates the TPVPlus Android app: an injected NDEFReader polyfill (+ __nfcTriggerRead) and the global
window.handleNfcScan. Expects customers "Estres" (card STRESS01) and "Estela Prueba" (card ESTELA01).
"""
import sys
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

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
    return d.find_element(By.ID, 'app').text.replace('\n', ' | ')


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
    check('UID tag opens the customer (COBRAR -> amount screen)', 'Estres' in screen(d) and 'Saldo actual' in screen(d), screen(d)[:90])
    d.find_element(By.CSS_SELECTOR, '[data-act="home"]').click()
    start(d, 'SALDO')
    d.execute_script("window.__nfcTriggerText('ESTELA01', '04:aa:bb:cc')")  # NDEF text wins over the UID
    time.sleep(1.2)
    check('NDEF text record is used instead of the UID', 'Estela Prueba' in screen(d), screen(d)[:90])
    d.find_element(By.CSS_SELECTOR, '[data-act="home"]').click()
    d.execute_script("window.__nfcTriggerRead('stress01')")  # tag while on the home screen
    time.sleep(1)
    check('a tag on the home screen is ignored', 'COBRAR' in screen(d) and 'Saldo actual' not in screen(d))
    start(d, 'SALDO')
    d.execute_script("window.__nfcTriggerRead('nope9999')")
    time.sleep(1.2)
    check('unknown tag shows "Cliente no encontrado"', 'Cliente no encontrado' in screen(d), screen(d)[:100])
finally:
    d.quit()

# B. Native bridge fallback and keyboard-wedge reader, no NDEFReader available
d = driver(polyfill=False)
try:
    start(d, 'SALDO')
    d.execute_script("window.handleNfcScan('estela01')")
    time.sleep(1.2)
    check('window.handleNfcScan opens the customer', 'Estela Prueba' in screen(d), screen(d)[:90])
    d.find_element(By.CSS_SELECTOR, '[data-act="home"]').click()
    start(d, 'SALDO')
    d.execute_script("window.handleNfcScan('estela01'); window.handleNfcScan('estela01');")
    time.sleep(1.5)
    check('a repeated read within 2 s is ignored (no double lookup)', 'Estela Prueba' in screen(d))
    d.find_element(By.CSS_SELECTOR, '[data-act="home"]').click()
    start(d, 'SALDO')
    field = d.find_element(By.ID, 'query')
    for ch in '04:AA-BB':  # a wedge reader types the code character by character, then Enter
        field.send_keys(ch)
    field.send_keys('')
    time.sleep(1.2)
    check('keyboard-wedge reader text is normalised and not found when unknown', 'Cliente no encontrado' in screen(d))
finally:
    d.quit()

print('RESULT:', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
