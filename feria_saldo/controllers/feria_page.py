import os

from odoo import SUPERUSER_ID, http
from odoo.http import request
from odoo.tools import file_open, file_path

from ..feria_tools import FeriaError
from .feria_api import check_network

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'"
)


class FeriaPage(http.Controller):

    @staticmethod
    def _assets_version():
        """Changes whenever app.js/app.css change, so a browser never keeps serving an old screen."""
        stamps = [int(os.stat(file_path(f'feria_saldo/static/app/{name}')).st_mtime) for name in ('app.js', 'app.css')]
        return str(max(stamps))

    @http.route(['/feria', '/feria/'], type='http', auth='none', methods=['GET'], save_session=False, readonly=False)
    def page(self):
        """The one-page cash desk used by operators; Odoo forms stay for back office work."""
        try:
            check_network(request.env(user=SUPERUSER_ID))
        except FeriaError as error:
            return request.make_response(error.message, status=403, headers=[('Content-Type', 'text/plain; charset=utf-8')])
        with file_open('feria_saldo/static/app/index.html') as handle:
            html = handle.read().replace('__V__', self._assets_version())
        return request.make_response(html, headers=[
            ('Content-Type', 'text/html; charset=utf-8'),
            ('Cache-Control', 'no-store'),
            ('Content-Security-Policy', CSP),
            ('X-Content-Type-Options', 'nosniff'),
        ])
