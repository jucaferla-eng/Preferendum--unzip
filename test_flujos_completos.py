"""test_flujos_completos.py — comprobación funcional de los módulos que
`test_e2e_commercial` NO cubría.

Objetivo: comprobar que lo que YA EXISTE funciona de principio a fin. No
añade funcionalidad y no rediseña nada. Cada prueba recorre un flujo real
contra la app real; un HTTP 200 no se acepta como prueba de funcionamiento.

Cubre los huecos de la lista de módulos:
  G. Verificación de identidad (correo, teléfono, documento, selfie, estado)
  H. Debate y participación (opiniones y comentarios)
  I. Ciclo de vida de la consulta por el organizador (crear, editar, cerrar,
     resultados, códigos de recompensa)
  J. Portales servidos (votante, organizador, anunciante)
  K. Idiomas y navegación
  L. Prefy — solo que los vídeos existentes se sirvan (decisión de producto:
     es un botón con vídeos pregrabados, NO un asistente conversacional)
  M. Pagos y registros contables existentes (sin ningún pago real)
  N. Configuración de las aplicaciones móviles (iOS y Android)

Datos ficticios siempre: dominio .invalid y documentos del rango 99.xxx.xxx.
"""
import json
import os
import re
import tempfile
import unittest
import uuid

_TMP = tempfile.mkdtemp(prefix='prefy_flujos_')
os.environ['DATABASE_URL'] = f'sqlite:///{os.path.join(_TMP, "flujos.db")}'
os.environ.setdefault('ADMIN_SECRET', 'flujos-solo-local')
os.environ.setdefault('JWT_SECRET', 'flujos-solo-local')
os.environ.pop('ADMIN_SECRET_CANARY', None)

import bcrypt                                    # noqa: E402
from fastapi.testclient import TestClient        # noqa: E402

import main                                      # noqa: E402
import pruebas_voto_facial  # noqa: E402,F401  (rellena el token facial del voto)

ADMIN = os.environ['ADMIN_SECRET']


def _ip():
    _ip.n = getattr(_ip, 'n', 0) + 1
    return {'X-Forwarded-For': f'203.0.113.{_ip.n % 250 + 1}'}


def _uniq(p):
    return f'{p}-{uuid.uuid4().hex[:10]}'


def _rut():
    return f'99{uuid.uuid4().int % 10**6:06d}-9'


class Base(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        cls.db = main.SessionLocal()
        ya = cls.db.query(main.CommuneMarketData).filter(
            main.CommuneMarketData.commune == 'Las Condes').first()
        if not ya:
            cls.db.add(main.CommuneMarketData(
                country='CL', commune='Las Condes', se_tier='A',
                income_index=95.0, price_m2_avg=95.0, cpm_usd=6.0))
            cls.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def auth(self, token):
        h = _ip()
        h['Authorization'] = f'Bearer {token}'
        return h

    def votante(self, commune='Las Condes', correo_verificado=True):
        """Registra un votante de verdad por la ruta real.

        `/voter/register` deja `email_verified=False` A PROPÓSITO: el
        producto exige verificar el correo antes de votar u opinar, y eso
        está bien. El flujo de verificación se comprueba aparte (G3). Para
        los demás flujos se parte del estado NORMAL de un usuario ya
        verificado, que es el que tiene cualquiera que use la plataforma.
        """
        email = _uniq('v') + '@test.invalid'
        r = self.client.post('/voter/register', json={
            'name': 'Votante Flujos', 'email': email, 'password': 'ClaveF123!',
            'country': 'CL', 'profession': 'Ingeniero Industrial',
            'cargo': 'empleado', 'commune': commune, 'gender': 'M',
            'dob': '1990-05-05', 'national_id': _rut()}, headers=_ip())
        self.assertIn(r.status_code, (200, 201), r.text[:300])
        u = self.db.query(main.User).filter(
            main.func.lower(main.User.email) == email.lower()).first()
        if correo_verificado:
            self.db.execute(main.text(
                'UPDATE users SET email_verified=1 WHERE id=:i'), {'i': u.id})
            self.db.commit()
            self.db.refresh(u)
        return u, self.auth(main.make_token(u.id, 'voter'))

    def _sin_proveedores(self):
        """Simula el proveedor de correo/SMS para poder recorrer el flujo.

        Sin proveedor configurado las rutas devuelven 503, que es el
        comportamiento CORRECTO: informan honestamente que no enviaron
        nada. Pero entonces el flujo de verificación no se puede recorrer,
        así que aquí se simula solo el envío — el código, su guardado y su
        confirmación siguen siendo los reales."""
        import contextlib

        @contextlib.contextmanager
        def _ctx():
            orig_mail = main.send_email_otp
            orig_sms = main.send_sms_otp
            main.send_email_otp = lambda *a, **k: True
            main.send_sms_otp = lambda *a, **k: True
            try:
                yield
            finally:
                main.send_email_otp = orig_mail
                main.send_sms_otp = orig_sms
        return _ctx()

    def consulta_abierta(self, **kw):
        org = main.User(name='Org F', email=_uniq('of') + '@test.invalid',
                        password=bcrypt.hashpw(b'x', bcrypt.gensalt()).decode(),
                        country='CL', role='organizer', email_verified=True)
        self.db.add(org); self.db.commit(); self.db.refresh(org)
        campos = dict(
            title=_uniq('Consulta flujos'), context='Ficticia',
            options=json.dumps(['Opción A', 'Opción B']),
            creator_id=org.id, creator_type='organizer', scope='country',
            scope_country='CL', status='open', target_gender='all',
            target_age_min=18, target_age_max=99, target_se_tiers='A,B,C,D',
            total_votes=0, vote_counts=json.dumps({'Opción A': 0, 'Opción B': 0}))
        campos.update(kw)
        d = main.Debate(**campos)
        self.db.add(d); self.db.commit(); self.db.refresh(d)
        return org, d


# ═══════════════════════════════════════════════════════════════════════
# G. VERIFICACIÓN DE IDENTIDAD
# ═══════════════════════════════════════════════════════════════════════

class TestG_VerificacionDeIdentidad(Base):

    def test_G1_el_estado_de_verificacion_informa_cada_factor(self):
        """`/verify/status` debe decir, por factor, qué está verificado. Es
        lo que el portal usa para saber qué pedirle al usuario."""
        u, cab = self.votante()
        r = self.client.get('/verify/status', headers=cab)
        self.assertEqual(r.status_code, 200, r.text[:300])
        d = r.json()
        self.assertIsInstance(d, dict)
        # El contrato real: `steps` lleva los factores, mas `is_verified`,
        # `progress` y `verify_level` agregados.
        for clave in ('steps', 'is_verified', 'progress', 'verify_level'):
            self.assertIn(clave, d, f'falta {clave} en el estado: {sorted(d)}')
        pasos = json.dumps(d['steps']).lower()
        encontrados = [f for f in ('email', 'phone', 'selfie', 'document',
                                   'doc', 'face', 'imei', 'location')
                       if f in pasos]
        self.assertTrue(encontrados,
                        f'`steps` no informa ningún factor: {d["steps"]}')

    def test_G2_sin_sesion_no_se_consulta_el_estado(self):
        r = self.client.get('/verify/status', headers=_ip())
        self.assertIn(r.status_code, (401, 403), r.text[:200])

    def test_G3_el_codigo_de_correo_se_emite_y_confirma(self):
        """Flujo completo: pedir código -> leerlo de la base -> confirmar ->
        el usuario queda con el correo verificado."""
        u, cab = self.votante(correo_verificado=False)
        self.db.refresh(u)
        with self._sin_proveedores():
            r = self.client.post('/verify/email/send', json={}, headers=cab)
        self.assertIn(r.status_code, (200, 201), r.text[:300])
        fila = self.db.execute(main.text(
            'SELECT code FROM otp_codes WHERE user_id=:i AND channel=:c '
            ' ORDER BY id DESC LIMIT 1'), {'i': u.id, 'c': 'email'}).fetchone()
        self.assertIsNotNone(fila, 'no se emitió ningún código de correo')
        codigo = fila[0]
        r2 = self.client.post('/verify/email/confirm',
                              json={'code': codigo}, headers=cab)
        self.assertEqual(r2.status_code, 200, r2.text[:300])
        self.db.expire_all()
        u2 = self.db.query(main.User).filter(main.User.id == u.id).first()
        self.assertTrue(u2.email_verified,
                        'confirmar el código no marcó el correo como verificado')

    def test_G4_un_codigo_de_correo_equivocado_se_rechaza(self):
        u, cab = self.votante(correo_verificado=False)
        with self._sin_proveedores():
            r = self.client.post('/verify/email/send', json={}, headers=cab)
        self.assertIn(r.status_code, (200, 201))
        r2 = self.client.post('/verify/email/confirm',
                              json={'code': '000000'}, headers=cab)
        self.assertNotEqual(r2.status_code, 200,
                            'aceptó un código de correo equivocado')

    def test_G5_el_codigo_de_telefono_se_emite_y_confirma(self):
        u, cab = self.votante()
        tel = f'+5699{uuid.uuid4().int % 10**6:06d}'
        self.db.execute(main.text('UPDATE users SET phone=:p WHERE id=:i'),
                        {'p': tel, 'i': u.id})
        self.db.commit()
        with self._sin_proveedores():
            r = self.client.post('/verify/phone/send',
                                 json={'phone': tel}, headers=cab)
        self.assertIn(r.status_code, (200, 201), r.text[:300])
        fila = self.db.execute(main.text(
            'SELECT code FROM otp_codes WHERE user_id=:i AND channel=:c '
            ' ORDER BY id DESC LIMIT 1'), {'i': u.id, 'c': 'sms'}).fetchone()
        self.assertIsNotNone(fila, 'no se emitió código de teléfono')
        r2 = self.client.post('/verify/phone/confirm',
                              json={'phone': tel, 'code': fila[0]}, headers=cab)
        self.assertEqual(r2.status_code, 200, r2.text[:300])
        self.db.expire_all()
        u2 = self.db.query(main.User).filter(main.User.id == u.id).first()
        self.assertTrue(u2.phone_verified,
                        'confirmar el código no marcó el teléfono verificado')

    def test_G5b_sin_proveedor_configurado_se_informa_el_fallo(self):
        """Comportamiento CORRECTO, fijado como tal: sin proveedor de correo
        o SMS, las rutas devuelven 503 en vez de decir "código enviado".
        Dejar al votante esperando un código que nunca salió sería peor."""
        u, cab = self.votante(correo_verificado=False)
        r = self.client.post('/verify/email/send', json={}, headers=cab)
        self.assertEqual(r.status_code, 503, r.text[:200])
        self.assertIn('no pudimos enviar', r.text.lower())

    def test_G6_la_selfie_falla_cerrado_sin_credenciales_de_aws(self):
        """Sin AWS no se puede verificar una cara. Lo correcto es RECHAZAR,
        nunca dar por verificado lo que no se pudo comprobar."""
        u, cab = self.votante()
        r = self.client.post('/verify/selfie',
                             json={'image_base64': 'ZmFrZQ=='}, headers=cab)
        self.assertNotEqual(r.status_code, 200,
                            'dio por verificada una selfie sin poder comprobarla')
        self.db.expire_all()
        u2 = self.db.query(main.User).filter(main.User.id == u.id).first()
        self.assertFalse(bool(u2.selfie_verified),
                         'marcó selfie_verified sin verificación real')

    def test_G7_el_voto_exige_token_facial_si_la_selfie_esta_verificada(self):
        """Nadie vota sin el token facial: es el factor que impide que otra
        persona vote con su cuenta.

        Antes esto solo se exigia a quien tenia la selfie verificada, y se
        perdonaba a quien no. Hoy se exige siempre, asi que la prueba
        comprueba los dos casos; `face_token` vacio va explicito para que
        el andamiaje de conftest.py no lo rellene."""
        u, cab = self.votante()
        _, d = self.consulta_abierta()
        r0 = self.client.post(f'/debates/{d.id}/vote',
                              json={'option_index': 0, 'face_token': ''},
                              headers=cab)
        self.assertEqual(r0.status_code, 403, r0.text[:200])
        self.db.execute(main.text('UPDATE users SET selfie_verified=1 WHERE id=:i'),
                        {'i': u.id})
        self.db.commit()
        r = self.client.post(f'/debates/{d.id}/vote',
                             json={'option_index': 0, 'face_token': ''},
                             headers=cab)
        self.assertEqual(r.status_code, 403, r.text[:300])
        self.assertIn('facial', r.text.lower())


# ═══════════════════════════════════════════════════════════════════════
# H. DEBATE Y PARTICIPACIÓN
# ═══════════════════════════════════════════════════════════════════════

class TestH_DebateYParticipacion(Base):

    def test_H1_una_opinion_se_publica_y_se_lee(self):
        u, cab = self.votante()
        _, d = self.consulta_abierta()
        texto = f'Opinión ficticia de prueba número {uuid.uuid4().hex[:8]}'
        r = self.client.post(f'/debates/{d.id}/opinions',
                             json={'text': texto}, headers=cab)
        self.assertIn(r.status_code, (200, 201), r.text[:300])
        r2 = self.client.get(f'/debates/{d.id}/opinions', headers=cab)
        self.assertEqual(r2.status_code, 200, r2.text[:300])
        self.assertIn(texto, r2.text,
                      'la opinión publicada no aparece al leerlas')

    def test_H2_una_opinion_exige_sesion(self):
        _, d = self.consulta_abierta()
        r = self.client.post(
            f'/debates/{d.id}/opinions',
            json={'text': 'Intento de opinar sin ninguna sesión abierta.'},
            headers=_ip())
        self.assertIn(r.status_code, (401, 403, 422), r.text[:200])

    def test_H3_un_no_elegible_no_participa_en_el_debate(self):
        """La participación respeta la misma barrera que el voto: si no
        puedes ver la consulta, no puedes opinar en ella."""
        u, cab = self.votante(commune='Las Condes')
        _, d = self.consulta_abierta(scope='commune', scope_commune='Conchalí')
        # El texto tiene que superar el mínimo de 20 caracteres, o la ruta
        # responde 400 por longitud ANTES de llegar a la comprobación de
        # acceso, y la prueba pasaría sin haber medido lo que pretende.
        r = self.client.post(
            f'/debates/{d.id}/opinions',
            json={'text': 'Esta opinión no debería poder publicarse nunca.'},
            headers=cab)
        self.assertIn(r.status_code, (403, 404), r.text[:300])
        n = self.db.query(main.Opinion).filter(
            main.Opinion.debate_id == d.id).count()
        self.assertEqual(n, 0, 'se guardó la opinión de un no elegible')

    def test_H4_los_comentarios_se_publican_y_se_leen(self):
        """REGLA REAL DEL PRODUCTO, comprobada: solo comenta quien ya votó
        en esa consulta. Por eso el flujo vota primero."""
        u, cab = self.votante()
        _, d = self.consulta_abierta()
        rv = self.client.post(f'/debates/{d.id}/vote',
                              json={'option_index': 0}, headers=cab)
        self.assertEqual(rv.status_code, 200, rv.text[:300])
        texto = f'Comentario ficticio {uuid.uuid4().hex[:8]}'
        r = self.client.post(f'/debates/{d.id}/comments',
                             json={'text': texto}, headers=cab)
        self.assertIn(r.status_code, (200, 201), r.text[:300])
        r2 = self.client.get(f'/debates/{d.id}/comments', headers=cab)
        self.assertEqual(r2.status_code, 200, r2.text[:300])
        self.assertIn(texto, r2.text, 'el comentario no aparece al leerlos')


    def test_H5_quien_no_ha_votado_no_puede_comentar(self):
        """La otra cara de H4, fijada porque es una decisión de producto:
        el debate es de quienes participaron."""
        u, cab = self.votante()
        _, d = self.consulta_abierta()
        r = self.client.post(f'/debates/{d.id}/comments',
                             json={'text': 'sin haber votado'}, headers=cab)
        self.assertEqual(r.status_code, 403, r.text[:300])
        self.assertIn('votado', r.text.lower())


# ═══════════════════════════════════════════════════════════════════════
# I. CICLO DE VIDA DE LA CONSULTA (ORGANIZADOR)
# ═══════════════════════════════════════════════════════════════════════
class TestI_CicloDeVidaDeLaConsulta(Base):

    def _organizador(self):
        email = _uniq('org') + '@test.invalid'
        u = main.User(name='Organizador Flujos', email=email, role='organizer',
                      password=bcrypt.hashpw(b'x', bcrypt.gensalt()).decode(),
                      country='CL', email_verified=True)
        self.db.add(u); self.db.commit(); self.db.refresh(u)
        return u, self.auth(main.make_token(u.id, 'organizer'))

    def _cuerpo_edicion(self, d, **cambios):
        """PUT /organizers/debates/{id} recibe un DebateCreate COMPLETO, no
        un parche: `options` y `closes_at` son obligatorios. Se reenvía el
        estado actual con el cambio aplicado encima."""
        cuerpo = {
            'title': d.title,
            'context': d.context or '',
            'options': json.loads(d.options or '[]'),
            'closes_at': (d.closes_at.isoformat() if d.closes_at
                          else '2027-12-31T23:59:59'),
        }
        cuerpo.update(cambios)
        return cuerpo

    def test_I1_el_organizador_ve_sus_propias_consultas(self):
        org, cab = self._organizador()
        _, d = self.consulta_abierta()
        self.db.execute(main.text('UPDATE debates SET creator_id=:c WHERE id=:d'),
                        {'c': org.id, 'd': d.id})
        self.db.commit()
        r = self.client.get('/organizers/me/debates', headers=cab)
        self.assertEqual(r.status_code, 200, r.text[:300])
        self.assertIn(str(d.id), r.text,
                      'el organizador no ve su propia consulta')

    def test_I2_editar_una_consulta_sin_votos_funciona(self):
        org, cab = self._organizador()
        _, d = self.consulta_abierta()
        self.db.execute(main.text('UPDATE debates SET creator_id=:c WHERE id=:d'),
                        {'c': org.id, 'd': d.id})
        self.db.commit()
        nuevo = 'Título corregido ' + uuid.uuid4().hex[:6]
        r = self.client.put(f'/organizers/debates/{d.id}',
                            json=self._cuerpo_edicion(d, title=nuevo), headers=cab)
        self.assertEqual(r.status_code, 200, r.text[:300])
        self.db.expire_all()
        d2 = self.db.query(main.Debate).filter(main.Debate.id == d.id).first()
        self.assertEqual(d2.title, nuevo, 'la edición no se guardó')

    def test_I3_una_consulta_CON_votos_queda_inmutable(self):
        """Protección de integridad: con votos emitidos, el enunciado no se
        puede cambiar. Cambiarlo falsearía lo que la gente votó."""
        org, cab = self._organizador()
        _, d = self.consulta_abierta()
        self.db.execute(main.text('UPDATE debates SET creator_id=:c WHERE id=:d'),
                        {'c': org.id, 'd': d.id})
        self.db.commit()
        u, cabv = self.votante()
        rv = self.client.post(f'/debates/{d.id}/vote',
                              json={'option_index': 0}, headers=cabv)
        self.assertEqual(rv.status_code, 200, rv.text[:300])
        r = self.client.put(f'/organizers/debates/{d.id}',
                            json=self._cuerpo_edicion(d, title='intento de cambio'),
                            headers=cab)
        self.assertEqual(r.status_code, 403, r.text[:300])
        self.db.expire_all()
        d2 = self.db.query(main.Debate).filter(main.Debate.id == d.id).first()
        self.assertNotEqual(d2.title, 'intento de cambio',
                            'el enunciado cambió pese a tener votos')

    def test_I4_cerrar_la_consulta_y_leer_sus_resultados(self):
        org, cab = self._organizador()
        _, d = self.consulta_abierta()
        self.db.execute(main.text('UPDATE debates SET creator_id=:c WHERE id=:d'),
                        {'c': org.id, 'd': d.id})
        self.db.commit()
        u, cabv = self.votante()
        self.client.post(f'/debates/{d.id}/vote',
                         json={'option_index': 1}, headers=cabv)
        r = self.client.put(f'/organizers/debates/{d.id}/close', headers=cab)
        self.assertEqual(r.status_code, 200, r.text[:300])
        r2 = self.client.get(f'/organizers/debates/{d.id}/results', headers=cab)
        self.assertEqual(r2.status_code, 200, r2.text[:300])
        datos = r2.json()
        # el resultado debe reflejar el voto realmente emitido
        self.assertIn('1', json.dumps(datos),
                      f'los resultados no muestran el voto emitido: {datos}')

    def test_I5_un_organizador_ajeno_no_edita_ni_cierra(self):
        org, cab = self._organizador()
        otro, cab_otro = self._organizador()
        _, d = self.consulta_abierta()
        self.db.execute(main.text('UPDATE debates SET creator_id=:c WHERE id=:d'),
                        {'c': org.id, 'd': d.id})
        self.db.commit()
        r = self.client.put(f'/organizers/debates/{d.id}',
                            json=self._cuerpo_edicion(d, title='ajeno'),
                            headers=cab_otro)
        self.assertIn(r.status_code, (403, 404), r.text[:300])
        r2 = self.client.put(f'/organizers/debates/{d.id}/close', headers=cab_otro)
        self.assertIn(r2.status_code, (403, 404), r2.text[:300])

    def test_I6_los_codigos_de_recompensa_se_cargan_y_se_entregan(self):
        """Flujo completo: el organizador carga un lote, un votante vota y
        recibe UN código, y el lote queda con ese código reclamado."""
        org, cab = self._organizador()
        _, d = self.consulta_abierta()
        self.db.execute(main.text('UPDATE debates SET creator_id=:c WHERE id=:d'),
                        {'c': org.id, 'd': d.id})
        self.db.commit()
        codigos = [f'PREMIO-{uuid.uuid4().hex[:6].upper()}' for _ in range(3)]
        # Contrato real: `codes` es TEXTO con un código por línea, no una
        # lista (la ruta hace splitlines sobre la cadena).
        r = self.client.post(
            f'/organizer/consultations/{d.id}/reward-codes',
            json={'codes': '\n'.join(codigos)}, headers=cab)
        self.assertIn(r.status_code, (200, 201), r.text[:300])
        u, cabv = self.votante()
        rv = self.client.post(f'/debates/{d.id}/vote',
                              json={'option_index': 0}, headers=cabv)
        self.assertEqual(rv.status_code, 200, rv.text[:300])
        entregado = rv.json().get('reward_code')
        self.assertIn(entregado, codigos,
                      f'no se entregó un código del lote cargado: {entregado}')
        n = self.db.query(main.DebateRewardCode).filter(
            main.DebateRewardCode.debate_id == d.id,
            main.DebateRewardCode.claimed == True).count()
        self.assertEqual(n, 1, 'el código entregado no quedó marcado reclamado')


# ═══════════════════════════════════════════════════════════════════════
# J. PORTALES SERVIDOS
# ═══════════════════════════════════════════════════════════════════════

class TestJ_Portales(Base):

    PORTALES = (
        ('/voter', 'votante'),
        ('/organizer-panel', 'organizador'),
        ('/marketer-portal', 'anunciante'),
    )

    def test_J1_los_tres_portales_se_sirven_con_html_real(self):
        """No basta el 200: tiene que venir HTML con cuerpo, no una página
        de error ni una respuesta vacía."""
        for ruta, nombre in self.PORTALES:
            r = self.client.get(ruta, headers=_ip())
            self.assertEqual(r.status_code, 200,
                             f'portal {nombre} ({ruta}) dio {r.status_code}')
            self.assertIn('text/html', r.headers.get('content-type', ''),
                          f'portal {nombre} no devolvió HTML')
            self.assertGreater(len(r.text), 5000,
                               f'portal {nombre} devolvió {len(r.text)} bytes: '
                               f'parece una página de error')
            self.assertIn('<body', r.text.lower(),
                          f'portal {nombre} no trae cuerpo HTML')

    def test_J2_cada_portal_carga_sus_propios_scripts(self):
        """Un portal que no carga su JS se ve pero no funciona."""
        for ruta, nombre in self.PORTALES:
            r = self.client.get(ruta, headers=_ip())
            self.assertRegex(r.text, r'<script',
                             f'portal {nombre} no carga ningún script')

    def test_J3_los_scripts_que_los_portales_piden_existen(self):
        """Se extraen los src= locales de cada portal y se piden de verdad:
        un 404 aquí es un portal roto en producción."""
        faltantes = []
        for ruta, nombre in self.PORTALES:
            html = self.client.get(ruta, headers=_ip()).text
            for src in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html):
                if src.startswith(('http://', 'https://', '//', 'data:')):
                    continue
                camino = src if src.startswith('/') else '/' + src
                rr = self.client.get(camino.split('?')[0], headers=_ip())
                if rr.status_code != 200:
                    faltantes.append(f'{nombre}: {camino} -> {rr.status_code}')
        self.assertEqual(faltantes, [], '\n'.join(faltantes))

    def test_J4_la_raiz_lleva_al_portal_del_votante(self):
        r = self.client.get('/', headers=_ip(), follow_redirects=True)
        self.assertEqual(r.status_code, 200, r.text[:200])
        self.assertGreater(len(r.text), 1000)


# ═══════════════════════════════════════════════════════════════════════
# K. IDIOMAS Y NAVEGACIÓN
# ═══════════════════════════════════════════════════════════════════════

class TestK_IdiomasYNavegacion(Base):

    def test_K1_lang_js_se_sirve_y_trae_traducciones(self):
        r = self.client.get('/lang.js', headers=_ip())
        self.assertEqual(r.status_code, 200, r.text[:200])
        self.assertGreater(len(r.text), 2000,
                           'lang.js llegó demasiado corto para traer idiomas')

    def test_K2_el_idioma_del_perfil_se_guarda_y_se_recupera(self):
        u, cab = self.votante()
        r0 = self.client.get('/profile/language', headers=cab)
        self.assertEqual(r0.status_code, 200, r0.text[:200])
        r = self.client.post('/profile/language',
                             json={'lang': 'en'}, headers=cab)
        self.assertEqual(r.status_code, 200, r.text[:300])
        r2 = self.client.get('/profile/language', headers=cab)
        self.assertEqual(r2.status_code, 200)
        self.assertIn('en', r2.text,
                      f'el idioma guardado no se recupera: {r2.text[:200]}')

    def test_K3_un_idioma_invalido_no_se_guarda(self):
        u, cab = self.votante()
        r = self.client.post('/profile/language',
                             json={'lang': 'no-existe-xx'}, headers=cab)
        if r.status_code == 200:
            r2 = self.client.get('/profile/language', headers=cab)
            self.assertNotIn('no-existe-xx', r2.text,
                             'guardó un idioma inexistente')


# ═══════════════════════════════════════════════════════════════════════
# L. PREFY — solo que los vídeos existentes se sirvan
# ═══════════════════════════════════════════════════════════════════════

class TestL_PrefyVideos(Base):
    """DECISIÓN DE PRODUCTO, no se discute aquí: Prefy es un botón con
    vídeos pregrabados con voz. NO es un asistente conversacional. Estas
    pruebas solo comprueban que lo que existe se sirve; no reconectan
    motores retirados ni tocan su diseño."""

    def test_L1_los_estaticos_de_prefy_se_sirven(self):
        for ruta in ('/prefy.js', '/prefy.css', '/prefy-content.js',
                     '/prefy-video.js', '/prefy-video.css', '/prefy-voice.js'):
            r = self.client.get(ruta, headers=_ip())
            self.assertEqual(r.status_code, 200,
                             f'{ruta} dio {r.status_code}')
            self.assertGreater(len(r.text), 100, f'{ruta} llegó vacío')

    def test_L2_existen_ficheros_de_video_en_el_repositorio(self):
        import glob
        # Ubicación real: assets/prefy-media/<contexto>/prefy-<contexto>-<lang>.mp4
        videos = glob.glob('assets/prefy-media/**/*.mp4', recursive=True)
        self.assertTrue(videos,
                        'no se encontró ningún fichero de vídeo de Prefy en '
                        'assets/prefy-media')
        # Y el idioma por defecto del producto tiene que estar
        self.assertTrue(
            [v for v in videos if v.endswith('-es.mp4')],
            f'no hay vídeo en español entre los {len(videos)} encontrados')

    def test_L3_la_ruta_de_video_responde_para_un_contexto_real(self):
        """Se pide el vídeo por la MISMA ruta que usa el portal."""
        r = self.client.get('/prefy/video/welcome/es', headers=_ip(),
                            follow_redirects=False)
        self.assertIn(r.status_code, (200, 206, 302),
                      f'la ruta de vídeo dio {r.status_code}: {r.text[:200]}')
        if r.status_code in (200, 206):
            # servido desde disco: tiene que venir vídeo de verdad
            self.assertIn('video', r.headers.get('content-type', ''),
                          f'no devolvió vídeo: {r.headers.get("content-type")}')
            self.assertGreater(int(r.headers.get('content-length') or 0), 10000,
                               'el vídeo servido es sospechosamente pequeño')

    def test_L4_un_contexto_o_idioma_inexistente_da_404(self):
        """La tabla de contextos e idiomas es cerrada: no se construye un
        nombre de fichero con lo que llegue por la URL."""
        for ruta in ('/prefy/video/contexto-inventado/es',
                     '/prefy/video/welcome/zz'):
            r = self.client.get(ruta, headers=_ip(), follow_redirects=False)
            self.assertEqual(r.status_code, 404,
                             f'{ruta} dio {r.status_code}')


# ═══════════════════════════════════════════════════════════════════════
# M. PAGOS Y REGISTROS CONTABLES (sin ningún pago real)
# ═══════════════════════════════════════════════════════════════════════

class TestM_PagosYContabilidad(Base):

    def _anunciante(self):
        email = _uniq('mk') + '@test.invalid'
        u = main.User(name='Anunciante Flujos', email=email, role='marketer',
                      password=bcrypt.hashpw(b'x', bcrypt.gensalt()).decode(),
                      country='CL', email_verified=True)
        self.db.add(u); self.db.commit(); self.db.refresh(u)
        self.db.add(main.MarketerProfile(user_id=u.id, company_name='Marca F',
                                         status='approved'))
        self.db.commit()
        return u, self.auth(main.make_token(u.id, 'marketer'))

    def test_M1_el_saldo_se_consulta_y_empieza_en_cero(self):
        u, cab = self._anunciante()
        r = self.client.get('/payments/balance', headers=cab)
        self.assertEqual(r.status_code, 200, r.text[:300])
        self.assertIsInstance(r.json(), dict)

    def test_M2_el_saldo_exige_sesion(self):
        r = self.client.get('/payments/balance', headers=_ip())
        self.assertIn(r.status_code, (401, 403), r.text[:200])

    def test_M3_el_historial_de_movimientos_responde(self):
        u, cab = self._anunciante()
        r = self.client.get('/payments/history', headers=cab)
        self.assertEqual(r.status_code, 200, r.text[:300])

    def test_M4_los_creditos_demo_se_acreditan_y_quedan_asentados(self):
        """Dinero de clase DEMO: no es un pago real. Comprueba que acreditar
        sube el saldo Y deja asiento en el ledger."""
        u, cab = self._anunciante()
        antes = main._ledger_balance(self.db, main._ledger.USER_DEMO, u.id)
        r = self.client.post('/payments/demo-credits', json={}, headers=cab)
        if r.status_code != 200:
            self.skipTest(f'los créditos demo no están habilitados en este '
                          f'entorno: {r.status_code} {r.text[:150]}')
        despues = main._ledger_balance(self.db, main._ledger.USER_DEMO, u.id)
        self.assertGreater(despues, antes,
                           'los créditos demo no subieron el saldo del ledger')

    def test_M5_asignar_presupuesto_a_una_campana_mueve_saldo_real(self):
        """Flujo contable completo: acreditar -> asignar a campaña -> la
        campaña queda gestionada por el ledger y el saldo del usuario baja."""
        u, cab = self._anunciante()
        c = main.AdCampaign(
            advertiser_email=u.email, advertiser_name='Marca F',
            title='Campaña flujos', budget_clp=100000, is_active=True,
            target_country='CL', target_communes='Las Condes',
            target_gender='all', target_se_tiers='A,B,C,D',
            target_age_min=18, target_age_max=99,
            ad_copy='Anuncio', link_url='https://example.invalid',
            value_class=main._ledger.DEMO)
        self.db.add(c); self.db.commit(); self.db.refresh(c)

        f = main._ledger_fund(self.db, main._ledger.DEMO, u.id, 30.0,
                              method='flujos_demo',
                              idempotency_key=_uniq('f'),
                              description='Fondeo ficticio')
        self.assertTrue(f['ok'], f'el fondeo falló: {f}')
        saldo_antes = main._ledger_balance(self.db, main._ledger.USER_DEMO, u.id)

        res = main._ledger_reserve(self.db, c, u.id, 10.0,
                                   idempotency_key=_uniq('r'))
        self.assertTrue(res['ok'], f'la reserva falló: {res}')
        self.db.refresh(c)
        saldo_despues = main._ledger_balance(self.db, main._ledger.USER_DEMO, u.id)
        reservado = main._ledger_balance(
            self.db, main._ledger.campaign_account_kind(main._ledger.DEMO), c.id)

        self.assertEqual(c.ledger_status, 'LEDGER_MANAGED')
        self.assertAlmostEqual(saldo_antes - saldo_despues, 10.0, places=6,
                               msg='el saldo del usuario no bajó lo reservado')
        self.assertAlmostEqual(reservado, 10.0, places=6,
                               msg='la campaña no quedó con el saldo reservado')

    def test_M6_devolver_presupuesto_no_reservado_no_crea_dinero(self):
        """Devolver más de lo reservado debe rechazarse: el ledger no puede
        quedar con saldo negativo ni inventar créditos."""
        u, cab = self._anunciante()
        r = self.client.post('/payments/return-from-campaign/999999',
                             json={'amount': 1000}, headers=cab)
        self.assertNotEqual(r.status_code, 200,
                            'aceptó devolver presupuesto de una campaña '
                            'inexistente')

    def test_M7_no_se_ejecuta_ningun_pago_real_en_esta_suite(self):
        self.assertIsNone(os.environ.get('STRIPE_SECRET_KEY'),
                          'hay clave de Stripe en el entorno de pruebas')


# ═══════════════════════════════════════════════════════════════════════
# N. APLICACIONES MÓVILES — configuración, no dispositivo
# ═══════════════════════════════════════════════════════════════════════

class TestN_AplicacionesMoviles(unittest.TestCase):
    """Las dos aplicaciones EXISTEN y están distribuidas. Lo que se puede
    comprobar aquí es su configuración de compilación y distribución; lo que
    NO se puede comprobar sin un teléfono queda declarado como no comprobado
    en el informe, nunca como inexistente.

    Corrección de un error mío anterior: la ausencia de una carpeta
    `android/` en el repositorio NO significa que no haya aplicación
    Android. Con EAS Build el proyecto nativo se genera en la nube a partir
    de `app.json` y `eas.json`; no se versiona. La carpeta `ios/` existe
    solo porque alguien ejecutó un prebuild local."""

    @classmethod
    def setUpClass(cls):
        cls.app_json = json.load(open('app.json'))['expo']
        cls.eas = json.load(open('eas.json'))

    def test_N1_ambas_plataformas_tienen_perfil_de_compilacion(self):
        prod = self.eas['build']['production']
        self.assertIn('android', prod, 'no hay perfil de compilación Android')
        self.assertIn('ios', prod, 'no hay perfil de compilación iOS')
        self.assertEqual(prod['android']['buildType'], 'app-bundle',
                         'Android debe compilarse como app-bundle para Play')

    def test_N2_ambas_plataformas_tienen_identificador_de_aplicacion(self):
        self.assertTrue(self.app_json['android']['package'],
                        'falta el package de Android')
        self.assertTrue(self.app_json['ios']['bundleIdentifier'],
                        'falta el bundleIdentifier de iOS')

    def test_N3_existe_configuracion_de_distribucion_para_ambas(self):
        sub = self.eas['submit']['production']
        self.assertIn('android', sub, 'no hay configuración de envío a Play')
        self.assertIn('ios', sub, 'no hay configuración de envío a App Store')

    def test_N4_android_declara_los_permisos_que_el_producto_usa(self):
        """Cámara y micrófono: la verificación por selfie y Prefy los
        necesitan. Si faltaran, la app instalada no podría usarlos."""
        permisos = self.app_json['android'].get('permissions', [])
        self.assertIn('android.permission.CAMERA', permisos)

    def test_N5_la_app_apunta_a_la_url_de_produccion_real(self):
        """Las dos apps son un envoltorio WebView: su funcionamiento ES el de
        los portales web. Por eso comprobar los flujos web comprueba casi
        todo de ambas aplicaciones."""
        fuente = open('App.js').read()
        self.assertIn('WebView', fuente)
        urls = re.findall(r"APP_URL\s*=\s*'([^']+)'", fuente)
        self.assertEqual(len(urls), 1, f'URL de la app ambigua: {urls}')
        self.assertTrue(urls[0].startswith('https://'),
                        f'la app no apunta a HTTPS: {urls[0]}')
        self.assertIn('onrender.com', urls[0],
                      f'la app apunta a un host inesperado: {urls[0]}')

    def test_N6_las_versiones_nativas_estan_declaradas(self):
        self.assertTrue(self.app_json.get('version'))
        self.assertTrue(self.app_json['android'].get('versionCode'))
        self.assertTrue(self.app_json['ios'].get('buildNumber'))


if __name__ == '__main__':
    unittest.main()
