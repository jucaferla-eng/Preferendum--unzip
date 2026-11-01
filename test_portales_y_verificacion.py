"""test_portales_y_verificacion.py — las conexiones que faltaban por demostrar.

Dos cosas, ambas señaladas como no demostradas:

  S. El MISMO barrido que destapó los dos defectos de CAMPAÑAS, aplicado a
     los TRES portales: que cada formulario y cada botón llamen a una ruta
     que existe, con el método correcto, y con la cabecera de autorización
     cuando la ruta exige sesión. Una ruta inexistente es un botón que no
     hace nada; una ruta autenticada sin token es un botón que falla
     siempre. Ninguna prueba de API detecta ni lo uno ni lo otro.

  T. El recorrido completo del voto y su verificación por código, incluido
     el recuadro del portal que devolvía «Code not found».

Reutiliza los ayudantes de test_flujos_completos (registro real por la ruta
real, consulta abierta, etc.) para no duplicar ese andamiaje.
"""
import re
import unittest

# Fija DATABASE_URL a su base temporal propia al importarse, y expone los
# ayudantes del recorrido real.
from test_flujos_completos import Base, _ip, _uniq        # noqa: E402
import main                                              # noqa: E402


# ═══════════════════════════════════════════════════════════════════════
# S. LOS TRES PORTALES CONTRA EL BACKEND
# ═══════════════════════════════════════════════════════════════════════

class TestS_BarridoDeLosTresPortales(unittest.TestCase):

    PORTALES = {
        'votante':     'voter_portal.html',
        'organizador': 'preferendum_organizer.html',
        'anunciante':  'marketer_portal.html',
    }

    @classmethod
    def setUpClass(cls):
        import ast
        cls.rutas = {}
        for r in main.app.routes:
            if hasattr(r, 'path') and hasattr(r, 'methods'):
                cls.rutas.setdefault(r.path, set()).update(r.methods)
        src = open('main.py', encoding='utf-8').read()
        cls.exige = {}
        for n in ast.walk(ast.parse(src)):
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            seg = ast.get_source_segment(src, n) or ''
            dep = None
            for d in ('get_verified_user', 'get_current_user', 'get_optional_user'):
                if d in seg:
                    dep = d
                    break
            for d in n.decorator_list:
                if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                        and d.args and isinstance(d.args[0], ast.Constant)):
                    cls.exige[(d.func.attr.upper(), d.args[0].value)] = dep

    def _plantilla(self, p):
        for real in self.rutas:
            if re.match('^' + re.sub(r'\{[^}]+\}', '[^/]+', real) + '$', p):
                return real
        return None

    def _llamadas(self, fichero):
        """(metodo, ruta_normalizada, envia_token) por cada fetch del fichero.

        DOS TRAMPAS QUE ME COMÍ AL ESCRIBIR ESTO, y por las que el detector
        es así de explícito:

        1. El prefijo `${API}` se quita ANTES de enmascarar el resto de las
           interpolaciones. Al revés, `${API}` se convierte en X y TODAS las
           rutas parecen inexistentes.

        2. La cabecera no siempre está escrita literalmente junto al fetch:
           el portal del votante pasa `headers: voteHeaders` y
           `headers: authHeaders`, variables definidas más arriba. Buscar
           sólo el texto 'Authorization' cerca de la llamada daba tres
           falsos positivos, es decir, habría denunciado como roto un
           portal que funciona. Si las cabeceras son un identificador, se
           resuelve su definición en el propio fichero.
        """
        html = open(fichero, encoding='utf-8').read()

        def _identificador_lleva_token(nombre):
            for m in re.finditer(
                    r'(?:const|let|var)\s+' + re.escape(nombre) + r'\s*=\s*(.{0,400})',
                    html, re.S):
                if 'Authorization' in m.group(1):
                    return True
            return False

        out = []
        for m in re.finditer(r'fetch\(\s*[`\'"]([^`\'"]+)', html):
            cola = html[m.end():m.end() + 400]
            met = re.search(r'method\s*:\s*[\'"](\w+)', cola)
            met = met.group(1).upper() if met else 'GET'
            envia = 'Authorization' in cola
            if not envia:
                ref = re.search(r'headers\s*:\s*([A-Za-z_$][\w$]*)', cola)
                if ref and _identificador_lleva_token(ref.group(1)):
                    envia = True
            p = m.group(1).replace('${API}', '')
            p = re.sub(r'\$\{[^}]*\}', 'X', p).split('?')[0]
            if not p.startswith('/'):
                p = '/' + p
            out.append((met, p, envia))
        return out

    def test_S1_cada_portal_hace_llamadas_detectables(self):
        for nombre, f in self.PORTALES.items():
            self.assertGreater(
                len(self._llamadas(f)), 5,
                f'portal {nombre}: el extractor no encontró llamadas; '
                f'revisar el extractor antes de creer cualquier resultado')

    def test_S2_ninguna_llamada_apunta_a_una_ruta_inexistente(self):
        roto = []
        for nombre, f in self.PORTALES.items():
            for met, p, _ in sorted(set(self._llamadas(f))):
                t = self._plantilla(p)
                if t is None:
                    roto.append(f'{nombre}: {met} {p} -> la ruta no existe')
                elif met not in self.rutas[t]:
                    roto.append(f'{nombre}: {met} {p} -> solo acepta '
                                f'{sorted(self.rutas[t] - {"HEAD", "OPTIONS"})}')
        self.assertEqual(roto, [], '\n'.join(roto))

    def test_S3_toda_llamada_que_exige_sesion_envia_el_token(self):
        """Éste era el defecto de CAMPAÑAS: la ruta exigía sesión y la
        llamada no mandaba la cabecera, así que fallaba siempre."""
        faltan = []
        for nombre, f in self.PORTALES.items():
            for met, p, envia in sorted(set(self._llamadas(f))):
                t = self._plantilla(p)
                if t is None:
                    continue
                dep = self.exige.get((met, t))
                if dep in ('get_verified_user', 'get_current_user') and not envia:
                    faltan.append(f'{nombre}: {met} {p} exige {dep} sin token')
        self.assertEqual(faltan, [], '\n'.join(faltan))


# ═══════════════════════════════════════════════════════════════════════
# T. VOTO, CÓDIGO Y VERIFICACIÓN
# ═══════════════════════════════════════════════════════════════════════

class TestT_VotoYVerificacion(Base):

    def test_T1_votar_entrega_un_codigo_que_resuelve_a_su_voto(self):
        u, cab = self.votante()
        _, d = self.consulta_abierta()
        rv = self.client.post(f'/debates/{d.id}/vote',
                              json={'option_index': 1}, headers=cab)
        self.assertEqual(rv.status_code, 200, rv.text[:300])
        codigo = rv.json().get('verify_code')
        self.assertTrue(codigo, 'votar no entregó código de verificación')
        r = self.client.post(f'/debates/{d.id}/verify',
                             json={'code': codigo}, headers=_ip())
        self.assertEqual(r.status_code, 200, r.text[:300])
        v = r.json()
        self.assertTrue(v.get('found'))
        self.assertEqual(v.get('your_vote'), 'Opción B',
                         f'el código no devolvió el voto emitido: {v}')

    def test_T2_el_estado_de_anclaje_se_declara_con_honestidad(self):
        """Sin clave de wallet el anclaje es simulado, y el servidor debe
        decirlo: `blockchain_anchored` no puede ser True sin anclaje real."""
        u, cab = self.votante()
        _, d = self.consulta_abierta()
        rv = self.client.post(f'/debates/{d.id}/vote',
                              json={'option_index': 0}, headers=cab)
        self.assertFalse(rv.json().get('blockchain_anchored'),
                         'declaró anclaje real sin clave de wallet')
        r = self.client.post(f'/debates/{d.id}/verify',
                             json={'code': rv.json()['verify_code']},
                             headers=_ip())
        self.assertIn(r.json().get('blockchain_anchored'), (False, None),
                      'la verificación afirmó un anclaje que no ocurrió')

    def test_T3_un_codigo_de_otra_consulta_no_valida(self):
        u, cab = self.votante()
        _, d1 = self.consulta_abierta()
        _, d2 = self.consulta_abierta()
        rv = self.client.post(f'/debates/{d1.id}/vote',
                              json={'option_index': 0}, headers=cab)
        r = self.client.post(f'/debates/{d2.id}/verify',
                             json={'code': rv.json()['verify_code']},
                             headers=_ip())
        self.assertEqual(r.status_code, 404, r.text[:200])

    def test_T4_un_codigo_inventado_no_valida(self):
        _, d = self.consulta_abierta()
        r = self.client.post(f'/debates/{d.id}/verify',
                             json={'code': 'NO-EXISTE-XYZ'}, headers=_ip())
        self.assertEqual(r.status_code, 404, r.text[:200])

    def test_T5_la_verificacion_no_revela_la_identidad_del_votante(self):
        """Separación identidad/preferencia: el código devuelve el voto a
        quien lo tiene, pero nunca de QUIÉN es."""
        u, cab = self.votante()
        _, d = self.consulta_abierta()
        rv = self.client.post(f'/debates/{d.id}/vote',
                              json={'option_index': 0}, headers=cab)
        r = self.client.post(f'/debates/{d.id}/verify',
                             json={'code': rv.json()['verify_code']},
                             headers=_ip())
        cuerpo = r.text
        for prohibido in (u.email, u.name, str(u.national_id or 'sin-documento')):
            self.assertNotIn(prohibido, cuerpo,
                             f'la verificación filtró {prohibido!r}')
        for campo in ('voter_id', 'user_id'):
            self.assertNotIn(campo, cuerpo,
                             f'la verificación expuso {campo}')

    def test_T6_el_recuadro_del_portal_usa_la_ruta_canonica(self):
        """DEFECTO CORREGIDO — llamaba a GET /verify/{codigo}, inexistente,
        así que respondía siempre «Code not found»."""
        html = open('marketer_portal.html', encoding='utf-8').read()
        bloque = html[html.index('async function verifyVote'):]
        bloque = bloque[:bloque.index('// ── NAVIGATION')]
        self.assertIn('/verify', bloque)
        self.assertIn('debates/', bloque,
                      'el recuadro no usa la ruta canónica de verificación')
        self.assertNotIn('${API}/verify/${vcode}', bloque,
                         'volvió la ruta inexistente')
        self.assertIn('blockchain_anchored', bloque,
                      'el recuadro no mira el estado real de anclaje')

    def test_T7_el_recuadro_no_afirma_anclaje_sin_comprobarlo(self):
        """Antes mostraba «Vote verified on Polygon» en cuanto la respuesta
        traía cualquier cosa. Ahora distingue tres estados."""
        html = open('marketer_portal.html', encoding='utf-8').read()
        bloque = html[html.index('async function verifyVote'):]
        bloque = bloque[:bloque.index('// ── NAVIGATION')]
        self.assertIn('blockchain_anchored === true', bloque)
        self.assertIn('blockchain_anchored === false', bloque)
        self.assertIn('unknown', bloque.lower(),
                      'no contempla el caso de anclaje desconocido (NULL)')


# ═══════════════════════════════════════════════════════════════════════
# U. BLOCKCHAIN — qué está implementado y qué no se puede demostrar
# ═══════════════════════════════════════════════════════════════════════

class TestU_BlockchainImplementado(unittest.TestCase):

    def test_U1_el_modulo_existe_y_declara_su_modo(self):
        import blockchain
        bc = main._blockchain
        est = bc.status()
        self.assertIn('live', est,
                      'el estado de blockchain no declara si está en vivo')

    def test_U2_sin_clave_de_wallet_el_anclaje_NO_se_declara_en_vivo(self):
        """Lo importante no es que ancle, es que no MIENTA cuando no puede."""
        r = main._blockchain.anchor_vote(999999, 'h' * 64, 'CODIGO-FICTICIO',
                                         debate_title='Ficticia')
        self.assertIn('live', r)
        self.assertFalse(r['live'],
                         'declaró un anclaje en vivo sin clave de wallet')
        self.assertTrue(r.get('tx_hash'),
                        'devolvió un hash vacío en vez de uno simulado')

    def test_U3_verify_by_code_existe_pero_NO_se_usa_desde_el_servidor(self):
        """HECHO DECLARADO, no corregido: blockchain.verify_by_code consulta
        el contrato, pero main.py no la llama desde ninguna ruta. La
        verificación que se ofrece al votante resuelve el código contra la
        BASE DE DATOS, no contra la cadena.

        No se conecta porque, cuando el anclaje no está en vivo,
        verify_by_code devuelve `exists: True` con un hash FABRICADO
        (sha256 del propio código): enchufarla afirmaría «verificado en
        Polygon» para cualquier texto. Eso sería peor que no tenerla.

        Por tanto NO existe verificación independiente de la cadena, y esta
        prueba impide que alguien lo afirme sin cambiar el código.
        """
        import blockchain, inspect
        self.assertTrue(hasattr(blockchain.PreferendumBlockchain, 'verify_by_code'))
        src = open('main.py', encoding='utf-8').read()
        self.assertEqual(src.count('verify_by_code'), 0,
                         'verify_by_code ya se usa desde main.py: revisar que '
                         'no afirme anclaje cuando live=False, y actualizar '
                         'esta prueba y el informe')
        # y el motivo, medido: en modo simulado afirma que existe
        fuente = inspect.getsource(blockchain.PreferendumBlockchain.verify_by_code)
        self.assertIn("'exists':    True", fuente,
                      'si ya no fabrica exists=True, reconsiderar conectarla')


if __name__ == '__main__':
    unittest.main()


# ═══════════════════════════════════════════════════════════════════════
# V. ANCLAJE EN POLYGON — el defecto de intermitencia, corregido
# ═══════════════════════════════════════════════════════════════════════

class TestV_AnclajeHonesto(unittest.TestCase):
    """Ninguna de estas pruebas envía transacciones ni gasta fondos: sin
    clave de wallet el cliente no está en vivo, y eso se comprueba primero."""

    def setUp(self):
        import blockchain
        self.bc = blockchain.PreferendumBlockchain()

    def test_V0_el_entorno_de_prueba_no_puede_gastar_fondos(self):
        self.assertFalse(self.bc.live)
        self.assertEqual(self.bc.private_key, '',
                         'hay clave de wallet en el entorno de pruebas: '
                         'estas pruebas NO deben poder firmar transacciones')

    def test_V1_un_hash_simulado_NO_se_declara_exito(self):
        """DEFECTO CORREGIDO. Devolvía `success: True` con un hash simulado."""
        r = self.bc.anchor_vote(999999, 'ab' * 32, 'CODIGO-FICTICIO',
                                debate_title='Ficticia')
        self.assertFalse(r['live'])
        self.assertFalse(r['success'],
                         'un hash simulado se sigue declarando como exito')
        self.assertTrue(r.get('reason'),
                        'no explica por que no se ancló')
        self.assertTrue(r['tx_hash'], 'no devolvió ningún hash')

    def test_V2_el_estado_que_se_guarda_es_el_verdadero(self):
        """`blockchain_anchored` = success AND live. Con un simulado debe
        quedar False, nunca True."""
        r = self.bc.anchor_vote(999999, 'cd' * 32, 'OTRO-FICTICIO')
        anclado = bool(r.get('success')) and bool(r.get('live'))
        self.assertFalse(anclado)

    def test_V3_el_modo_simulado_ya_NO_se_queda_pegado_para_siempre(self):
        """ÉSTA ERA LA CAUSA DE LA INTERMITENCIA.

        Antes, tras tres intentos fallidos se marcaba `_initialized = True`
        y el proceso no volvía a intentar la conexión NUNCA: todos sus votos
        salían simulados hasta el siguiente reinicio. Eso explica los tramos
        contiguos de votos simulados medidos en producción.
        """
        self.bc._initialized   = True
        self.bc._init_attempts = 3
        self.bc._gave_up_at    = 0.0      # hace mucho: la espera ya pasó
        intentos = {'n': 0}
        orig = self.bc._init
        def _contar():
            intentos['n'] += 1
            orig()
        self.bc._init = _contar
        self.bc._ensure_init()
        self.assertEqual(intentos['n'], 1,
                         'no reintentó la conexión pasada la espera: el modo '
                         'simulado sigue siendo permanente')

    def test_V4_dentro_de_la_espera_NO_reintenta(self):
        """El reintento está acotado: el anclaje ocurre dentro del camino de
        voto, así que no puede reintentar en cada voto o un RPC caído
        penalizaría a todos los votantes."""
        import time as _t
        self.bc._initialized   = True
        self.bc._init_attempts = 3
        self.bc._gave_up_at    = _t.time()   # acaba de rendirse
        intentos = {'n': 0}
        self.bc._init = lambda: intentos.__setitem__('n', intentos['n'] + 1)
        self.bc._ensure_init()
        self.assertEqual(intentos['n'], 0,
                         'reintentó dentro de la ventana de espera')

    def test_V5_una_transaccion_revertida_NO_cuenta_como_anclaje(self):
        """DEFECTO CORREGIDO. El recibo se descartaba con `except: pass`, así
        que una transacción minada pero REVERTIDA (status 0) se devolvía como
        éxito. Su hash existe en la cadena, pero no ancló nada."""
        import ast, inspect, textwrap
        arbol = ast.parse(textwrap.dedent(
            inspect.getsource(type(self.bc)._send_transaction)))
        fn = arbol.body[0]
        # Se quita la documentación: cita el código ANTIGUO para explicarlo,
        # y buscar por substring encontraría ahí el patrón ya retirado.
        cuerpo = fn.body[1:] if (isinstance(fn.body[0], ast.Expr)
                                 and isinstance(fn.body[0].value, ast.Constant)
                                 ) else fn.body
        codigo = '\n'.join(ast.unparse(n) for n in cuerpo)
        self.assertIn('status', codigo,
                      '_send_transaction no mira el status del recibo')
        self.assertIn('return None', codigo)
        # el recibo ya NO se descarta: su resultado se asigna y se evalúa
        self.assertIn('receipt = ', codigo,
                      'el recibo se sigue descartando sin mirarlo')

    def test_V6_sin_recibo_no_se_declara_anclado(self):
        import inspect
        fuente = inspect.getsource(type(self.bc)._send_transaction)
        self.assertIn('sin recibo', fuente,
                      'un timeout de recibo no se trata como no-anclado')

    def test_V7_si_la_consulta_no_se_abre_no_se_envia_la_transaccion(self):
        """DEFECTO CORREGIDO. El resultado de _ensure_debate_open se
        ignoraba: se gastaba gas en una transacción que el contrato iba a
        revertir."""
        import inspect
        fuente = inspect.getsource(type(self.bc).anchor_vote)
        self.assertIn('if not self._ensure_debate_open(', fuente,
                      'sigue ignorando si la consulta se pudo abrir')

    def test_V8_open_y_close_no_declaran_live_sin_confirmacion(self):
        import inspect
        for m in ('open_debate', 'close_debate'):
            fuente = inspect.getsource(getattr(type(self.bc), m))
            self.assertIn('if tx_hash:', fuente,
                          f'{m} declara live sin confirmar la transacción')


class TestW_FalloDePolygonNoAfectaElVoto(Base):
    """Punto 5: un fallo de Polygon no puede perder ni duplicar un voto, y
    lo que se le comunica al votante tiene que ser verdad."""

    def test_W1_con_polygon_caido_el_voto_se_registra_una_sola_vez(self):
        u, cab = self.votante()
        _, d = self.consulta_abierta()

        # Se simula un fallo DURO de la cadena: anchor_vote lanza.
        orig = main._blockchain.anchor_vote
        def _explota(*a, **k):
            raise RuntimeError('Polygon caido (simulado)')
        main._blockchain.anchor_vote = _explota
        try:
            r = self.client.post(f'/debates/{d.id}/vote',
                                 json={'option_index': 0}, headers=cab)
        finally:
            main._blockchain.anchor_vote = orig

        # El voto NO debe perderse por un fallo de la cadena...
        self.assertEqual(r.status_code, 200,
                         f'un fallo de Polygon tumbó el voto: {r.text[:300]}')
        # ...ni duplicarse.
        self.db.rollback()
        n = self.db.execute(main.text(
            'SELECT count(*) FROM debate_votes WHERE debate_id=:d'),
            {'d': d.id}).scalar()
        self.assertEqual(n, 1, f'quedaron {n} papeletas para un solo voto')
        # ...y el estado comunicado debe ser VERDADERO: no anclado.
        self.assertFalse(r.json().get('blockchain_anchored'),
                         'declaró anclaje con Polygon caído')
        fila = self.db.execute(main.text(
            'SELECT blockchain_anchored FROM debate_votes WHERE debate_id=:d'),
            {'d': d.id}).fetchone()
        self.assertIn(fila[0], (False, 0, None),
                      'guardó anclaje True con Polygon caído')

    def test_W2_y_el_votante_sigue_sin_poder_votar_dos_veces(self):
        """La protección de voto único no depende de la cadena."""
        u, cab = self.votante()
        _, d = self.consulta_abierta()
        orig = main._blockchain.anchor_vote
        main._blockchain.anchor_vote = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError('Polygon caido'))
        try:
            r1 = self.client.post(f'/debates/{d.id}/vote',
                                  json={'option_index': 0}, headers=cab)
            self.assertEqual(r1.status_code, 200, r1.text[:200])
            r2 = self.client.post(f'/debates/{d.id}/vote',
                                  json={'option_index': 1}, headers=cab)
        finally:
            main._blockchain.anchor_vote = orig
        self.assertEqual(r2.status_code, 409, r2.text[:200])
        self.db.rollback()
        n = self.db.execute(main.text(
            'SELECT count(*) FROM debate_votes WHERE debate_id=:d'),
            {'d': d.id}).scalar()
        self.assertEqual(n, 1)

    def test_W3_el_codigo_de_verificacion_sigue_sirviendo_sin_cadena(self):
        """El voto queda verificable contra el registro de Preferendum
        aunque no se haya anclado."""
        u, cab = self.votante()
        _, d = self.consulta_abierta()
        orig = main._blockchain.anchor_vote
        main._blockchain.anchor_vote = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError('Polygon caido'))
        try:
            rv = self.client.post(f'/debates/{d.id}/vote',
                                  json={'option_index': 1}, headers=cab)
        finally:
            main._blockchain.anchor_vote = orig
        codigo = rv.json()['verify_code']
        r = self.client.post(f'/debates/{d.id}/verify',
                             json={'code': codigo}, headers=_ip())
        self.assertEqual(r.status_code, 200, r.text[:300])
        self.assertTrue(r.json().get('found'))
        self.assertIn(r.json().get('blockchain_anchored'), (False, None),
                      'la verificación afirmó un anclaje que no ocurrió')
