"""test_cuenta_de_prueba.py — voto SIMULADO para una cuenta designada.

Una cuenta designada en PREFY_TEST_VOTE_ACCOUNTS puede entrar y recorrer la
votacion sin reconocimiento facial, y en cambio su voto no se guarda.

LA INVARIANTE que hace que esto sea seguro: la exencion de camara y la
simulacion del voto cuelgan del MISMO predicado. No hay forma de quedar
exento de la camara y emitir un voto real. Eso es lo primero que se
comprueba aqui, sobre el codigo mismo.

Lo demas es lo que no debe quedar: ni papeleta, ni codigo valido, ni suma a
resultados, ni consumo del derecho a votar.
"""
import json
import os
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta

_TMP = tempfile.mkdtemp(prefix='prefy_prueba_')
os.environ['DATABASE_URL'] = f'sqlite:///{os.path.join(_TMP, "p.db")}'
os.environ.setdefault('ADMIN_SECRET', 'prueba-solo-local')
os.environ.setdefault('JWT_SECRET', 'prueba-solo-local')
os.environ.pop('ADMIN_SECRET_CANARY', None)

CUENTA = 'cuenta.de.prueba@test.invalid'
os.environ['PREFY_TEST_VOTE_ACCOUNTS'] = CUENTA

import bcrypt                                    # noqa: E402
import jwt as _jwt                                # noqa: E402
from fastapi.testclient import TestClient        # noqa: E402

import main                                      # noqa: E402


def _ip():
    _ip.n = getattr(_ip, 'n', 0) + 1
    return {'X-Forwarded-For': f'198.51.100.{_ip.n % 250 + 1}'}


def _uniq(p):
    return f'{p}-{uuid.uuid4().hex[:10]}'


class Base(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        cls.db = main.SessionLocal()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def _usuario(self, email=None, selfie=True, phone='+56900000000'):
        u = main.User(name='Votante', email=email or (_uniq('v') + '@test.invalid'),
                      password=bcrypt.hashpw(b'Clave-de-prueba-2026',
                                             bcrypt.gensalt()).decode(),
                      country='CL', county='Vitacura', gender='M',
                      dob='1980-01-01', se_tier='B', role='voter',
                      phone=phone, email_verified=True, phone_verified=True,
                      selfie_verified=selfie, verify_level=3, is_verified=True)
        self.db.add(u); self.db.commit(); self.db.refresh(u)
        h = _ip()
        h['Authorization'] = 'Bearer ' + main.make_token(u.id, 'voter')
        return u, h

    def _consulta(self):
        d = main.Debate(
            title=_uniq('Consulta'), context='Ficticia',
            options=json.dumps(['Alternativa A', 'Alternativa B']),
            status='live', creator_id=1,
            closes_at=datetime.utcnow() + timedelta(days=30),
            scope='country', scope_country='CL', target_gender='all',
            target_age_min=18, target_age_max=99, target_se_tiers='A,B,C,D',
            results_visibility='public')
        self.db.add(d); self.db.commit(); self.db.refresh(d)
        return d

    def _votar(self, debate, cab, face=''):
        return self.client.post(
            f'/debates/{debate.id}/vote',
            json={'option_index': 0, 'vote_chain': [], 'device_fp': 'fp',
                  'face_token': face}, headers=cab)

    def _verificacion(self, user, debate):
        jti = uuid.uuid4().hex
        self.db.add(main.OTPCode(user_id=user.id, email=user.email, code=jti,
                                 channel='face_vote', used=False,
                                 expires_at=datetime.utcnow() + timedelta(minutes=5)))
        self.db.commit()
        return _jwt.encode({'sub': user.id, 'debate_id': debate.id,
                            'type': 'face_vote', 'jti': jti,
                            'exp': datetime.utcnow() + timedelta(minutes=5)},
                           main.SECRET, algorithm='HS256')


class TestLaInvariante(Base):
    """Exencion de camara y voto simulado son la MISMA condicion."""

    def test_las_dos_ramas_usan_el_mismo_predicado(self):
        import inspect
        src = inspect.getsource(main._cast_vote_inner)
        exencion = "if not _es_cuenta_de_prueba_de_voto(user.email):"
        simulado = "if _es_cuenta_de_prueba_de_voto(user.email):"
        self.assertIn(exencion, src,
                      'la exencion de camara debe usar el predicado unico')
        self.assertIn(simulado, src,
                      'la rama simulada debe usar el MISMO predicado')
        # Y no puede quedar ninguna exencion colgada de otro predicado.
        self.assertNotIn('if not _is_google_full_review_account(user.email):', src)

    def test_sin_la_variable_de_entorno_no_hay_ninguna_exencion(self):
        previo = os.environ.get('PREFY_TEST_VOTE_ACCOUNTS', '')
        try:
            os.environ['PREFY_TEST_VOTE_ACCOUNTS'] = ''
            self.assertFalse(main._es_cuenta_de_prueba_de_voto(CUENTA))
            u, cab = self._usuario(email=CUENTA + '.x')
            d = self._consulta()
            r = self._votar(d, cab)
            self.assertEqual(r.status_code, 403,
                             'sin la variable, nadie queda exento')
        finally:
            os.environ['PREFY_TEST_VOTE_ACCOUNTS'] = previo

    def test_el_correo_no_decide_nada_en_el_navegador(self):
        portal = open('voter_portal.html', encoding='utf-8').read()
        self.assertIn('data.voto_de_prueba === true', portal,
                      'el aviso tiene que venir del servidor')
        self.assertNotIn('joss0525agreda', portal,
                         'ningun correo personal en el navegador')
        self.assertNotIn(CUENTA, portal)

    def test_el_correo_de_JC_ya_no_esta_escrito_en_el_codigo(self):
        """Condicion 5. El repositorio es publico.

        La cuenta, su rol y sus permisos no cambian: lo unico que cambia es
        de donde se lee su identificador. Sin la variable configurada la
        cuenta pierde su autoridad elevada, asi que la variable tiene que
        estar puesta ANTES de desplegar -eso se comprueba en Render, no
        aqui-.
        """
        fuente = open('main.py', encoding='utf-8').read()
        self.assertNotIn('jucaferla24649', fuente,
                         'el correo personal sigue escrito en el fuente')
        self.assertIn("os.getenv('PREFY_DEMO_ACCOUNT'", fuente)
        # Sin la variable, el predicado no casa con NADIE. Se sustituye el
        # valor del modulo en vez de recargarlo: recargar `main` recrea la
        # aplicacion, los modelos y la sesion, y deja invalidas las de las
        # demas pruebas. Me paso: dieciseis fallos de golpe.
        previo = main.JC_FULL_DEMO_EMAIL
        try:
            main.JC_FULL_DEMO_EMAIL = ''
            for valor in ('', '   ', None, 'cualquiera@test.invalid'):
                self.assertFalse(main._is_jc_full_demo_account(valor),
                                 f'sin variable, {valor!r} no puede casar')
        finally:
            main.JC_FULL_DEMO_EMAIL = previo

    def test_la_cuenta_designada_por_la_variable_conserva_su_autoridad(self):
        """Con la variable puesta, el comportamiento es el de siempre."""
        previo = main.JC_FULL_DEMO_EMAIL
        try:
            main.JC_FULL_DEMO_EMAIL = 'demo.designada@test.invalid'
            self.assertTrue(main._is_jc_full_demo_account('demo.designada@test.invalid'))
            self.assertTrue(main._is_jc_full_demo_account('  DEMO.Designada@TEST.invalid '))
            self.assertTrue(main._is_full_demo_account('demo.designada@test.invalid'))
            # Y NO vota en modo simulado: esa cuenta vota de verdad.
            self.assertFalse(main._es_cuenta_de_prueba_de_voto('demo.designada@test.invalid'))
        finally:
            main.JC_FULL_DEMO_EMAIL = previo

    def test_ningun_correo_personal_nuevo_en_el_codigo(self):
        """El repositorio es publico."""
        fuente = open('main.py', encoding='utf-8').read()
        self.assertNotIn('joss0525agreda', fuente)
        self.assertIn("os.getenv('PREFY_TEST_VOTE_ACCOUNTS'", fuente)


class TestElVotoDePruebaNoDejaNada(Base):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # El correo es unico en la tabla: la cuenta se crea UNA vez.
        cls._u = main.User(
            name='Cuenta de prueba', email=CUENTA,
            password=bcrypt.hashpw(b'x', bcrypt.gensalt()).decode(),
            country='CL', county='Vitacura', gender='M', dob='1980-01-01',
            se_tier='B', role='voter', phone='+56900000000',
            email_verified=True, phone_verified=True, selfie_verified=True,
            verify_level=3, is_verified=True)
        cls.db.add(cls._u); cls.db.commit(); cls.db.refresh(cls._u)

    def setUp(self):
        self.u = self._u
        self.cab = _ip()
        self.cab['Authorization'] = 'Bearer ' + main.make_token(self.u.id, 'voter')
        self.d = self._consulta()

    def _recuento(self):
        return {
            'papeletas': self.db.query(main.DebateVote).filter(
                main.DebateVote.debate_id == self.d.id).count(),
            'ya_voto': self.db.query(main.HasVotedLog).filter(
                main.HasVotedLog.debate_id == self.d.id).count(),
            'sim': self.db.query(main.SimVoteLog).filter(
                main.SimVoteLog.debate_id == self.d.id).count(),
            'documento': self.db.query(main.NationalIdVoteLog).filter(
                main.NationalIdVoteLog.debate_id == self.d.id).count(),
        }

    def test_vota_sin_camara(self):
        r = self._votar(self.d, self.cab)
        self.assertEqual(r.status_code, 200, r.text[:300])
        self.assertTrue(r.json()['voto_de_prueba'])
        self.assertEqual(r.json()['aviso'], 'VOTO DE PRUEBA — NO CONTABILIZADO')

    def test_no_crea_papeleta_ni_rastro_alguno(self):
        antes = self._recuento()
        self.assertEqual(self._votar(self.d, self.cab).status_code, 200)
        self.db.expire_all()
        self.assertEqual(self._recuento(), antes,
                         'un voto de prueba no puede dejar ningun registro')

    def test_no_suma_al_escrutinio(self):
        antes = self.db.query(main.Debate).filter(
            main.Debate.id == self.d.id).first().total_votes or 0
        self._votar(self.d, self.cab)
        self.db.expire_all()
        d = self.db.query(main.Debate).filter(main.Debate.id == self.d.id).first()
        self.assertEqual(d.total_votes or 0, antes)
        res = self.client.get(f'/debates/{self.d.id}/results',
                              headers=self.cab)
        # Sin voto registrado, el escrutinio no se le abre: eso tambien
        # demuestra que no quedo constancia de que votara.
        self.assertEqual(res.status_code, 403, res.text[:200])

    def test_su_codigo_NO_verifica_nada(self):
        r = self._votar(self.d, self.cab)
        codigo = r.json()['verify_code']
        self.assertTrue(codigo.startswith('DEMO-'))
        v = self.client.post(f'/debates/{self.d.id}/verify',
                             json={'code': codigo}, headers=self.cab)
        self.assertNotEqual(v.status_code, 200,
                            'un codigo de prueba no puede verificar un voto')

    def test_no_consume_el_derecho_a_votar(self):
        for i in range(3):
            r = self._votar(self.d, self.cab)
            self.assertEqual(r.status_code, 200,
                             f'intento {i + 1}: {r.text[:200]}')
        self.db.expire_all()
        self.assertEqual(self._recuento()['papeletas'], 0)

    def test_sigue_respetando_la_elegibilidad(self):
        """Ser cuenta de prueba no abre consultas que no le corresponden."""
        d2 = self._consulta()
        d2.scope_country = 'AR'
        self.db.commit()
        r = self._votar(d2, self.cab)
        self.assertEqual(r.status_code, 403, r.text[:200])

    def test_tampoco_vota_en_una_consulta_cerrada(self):
        self.d.status = 'closed'
        self.d.closes_at = datetime.utcnow() - timedelta(days=1)
        self.db.commit()
        r = self._votar(self.d, self.cab)
        self.assertEqual(r.status_code, 400, r.text[:200])


class TestLosDemasSiguenObligados(Base):

    def test_otra_cuenta_sigue_necesitando_la_camara(self):
        u, cab = self._usuario()
        d = self._consulta()
        r = self._votar(d, cab)
        self.assertEqual(r.status_code, 403, r.text[:200])
        self.assertIn('facial', r.json()['detail'].lower())

    def test_y_su_voto_con_camara_SI_se_registra(self):
        u, cab = self._usuario()
        d = self._consulta()
        tk = self._verificacion(u, d)
        r = self._votar(d, cab, tk)
        self.assertEqual(r.status_code, 200, r.text[:300])
        self.assertNotIn('voto_de_prueba', r.json(),
                         'un voto real no puede marcarse como de prueba')
        self.assertFalse(r.json()['verify_code'].startswith('DEMO-'))
        self.assertEqual(self.db.query(main.DebateVote).filter(
            main.DebateVote.debate_id == d.id).count(), 1)

    def test_un_correo_parecido_no_cuela(self):
        for parecido in (CUENTA.upper().replace('@', '@x'),
                         'x' + CUENTA, CUENTA + 'x'):
            self.assertFalse(main._es_cuenta_de_prueba_de_voto(parecido),
                             f'{parecido} no esta designado')

    def test_mayusculas_y_espacios_no_importan(self):
        self.assertTrue(main._es_cuenta_de_prueba_de_voto('  ' + CUENTA.upper() + ' '))

    def test_la_cuenta_de_demostracion_vota_de_verdad(self):
        """El correo ya no esta en el fuente -condicion 5-, asi que lo que
        se fija es la REGLA: la cuenta de demostracion, sea cual sea, vota
        por el camino real y nunca en modo simulado."""
        previo = main.JC_FULL_DEMO_EMAIL
        try:
            main.JC_FULL_DEMO_EMAIL = 'demo.designada@test.invalid'
            self.assertFalse(
                main._es_cuenta_de_prueba_de_voto(main.JC_FULL_DEMO_EMAIL),
                'la cuenta de demostracion vota de verdad, no en modo prueba')
        finally:
            main.JC_FULL_DEMO_EMAIL = previo


class TestElIngresoSinCamara(Base):
    """Correo Y SMS, los dos obligatorios, en vez de la cara."""

    def _codigos(self, user):
        return {c.channel: c.code for c in self.db.query(main.OTPCode).filter(
            main.OTPCode.user_id == user.id,
            main.OTPCode.used == False).all()}

    def _pre_auth(self, user):
        return _jwt.encode({'sub': user.id, 'type': 'pre_auth',
                            'exp': datetime.utcnow() + timedelta(minutes=10)},
                           main.SECRET, algorithm='HS256')

    def _sembrar(self, user, canal):
        c = str(100000 + (user.id % 900000))
        self.db.add(main.OTPCode(user_id=user.id, email=user.email, code=c,
                                 channel=canal, used=False,
                                 expires_at=datetime.utcnow() + timedelta(minutes=10)))
        self.db.commit()
        return c

    def test_entra_con_los_dos_codigos_y_sin_cara(self):
        os.environ['TWILIO_ACCOUNT_SID'] = 'sid-de-prueba'
        os.environ['TWILIO_AUTH_TOKEN'] = 'token-de-prueba'
        try:
            u, _ = self._usuario(email=_uniq('p') + '@test.invalid')
            os.environ['PREFY_TEST_VOTE_ACCOUNTS'] = u.email
            ce = self._sembrar(u, 'email')
            cs = self._sembrar(u, 'sms')
            r = self.client.post('/auth/complete-login', headers=_ip(), json={
                'pre_auth_token': self._pre_auth(u),
                'email_code': ce, 'sms_code': cs, 'face_token': ''})
            self.assertEqual(r.status_code, 200, r.text[:300])
            self.assertTrue(r.json().get('token'))
        finally:
            os.environ['PREFY_TEST_VOTE_ACCOUNTS'] = CUENTA
            os.environ.pop('TWILIO_ACCOUNT_SID', None)
            os.environ.pop('TWILIO_AUTH_TOKEN', None)

    def test_sin_el_codigo_de_SMS_no_entra(self):
        os.environ['TWILIO_ACCOUNT_SID'] = 'sid-de-prueba'
        os.environ['TWILIO_AUTH_TOKEN'] = 'token-de-prueba'
        try:
            u, _ = self._usuario(email=_uniq('p') + '@test.invalid')
            os.environ['PREFY_TEST_VOTE_ACCOUNTS'] = u.email
            ce = self._sembrar(u, 'email')
            self._sembrar(u, 'sms')
            r = self.client.post('/auth/complete-login', headers=_ip(), json={
                'pre_auth_token': self._pre_auth(u),
                'email_code': ce, 'sms_code': '', 'face_token': ''})
            self.assertEqual(r.status_code, 400, r.text[:200])
            self.assertIn('SMS', r.text)
        finally:
            os.environ['PREFY_TEST_VOTE_ACCOUNTS'] = CUENTA
            os.environ.pop('TWILIO_ACCOUNT_SID', None)
            os.environ.pop('TWILIO_AUTH_TOKEN', None)

    def test_sin_telefono_verificado_no_se_concede_la_exencion(self):
        u, _ = self._usuario(email=_uniq('p') + '@test.invalid')
        u.phone_verified = False
        self.db.commit()
        os.environ['PREFY_TEST_VOTE_ACCOUNTS'] = u.email
        os.environ['TWILIO_ACCOUNT_SID'] = 'sid-de-prueba'
        os.environ['TWILIO_AUTH_TOKEN'] = 'token-de-prueba'
        try:
            r = self.client.post('/auth/complete-login', headers=_ip(), json={
                'pre_auth_token': self._pre_auth(u),
                'email_code': self._sembrar(u, 'email'),
                'sms_code': '', 'face_token': ''})
            self.assertEqual(r.status_code, 403, r.text[:200])
            self.assertIn('verificados', r.text)
        finally:
            os.environ['PREFY_TEST_VOTE_ACCOUNTS'] = CUENTA
            os.environ.pop('TWILIO_ACCOUNT_SID', None)
            os.environ.pop('TWILIO_AUTH_TOKEN', None)

    def test_sin_SMS_disponible_no_se_concede_la_exencion(self):
        u, _ = self._usuario(email=_uniq('p') + '@test.invalid')
        os.environ['PREFY_TEST_VOTE_ACCOUNTS'] = u.email
        os.environ.pop('TWILIO_ACCOUNT_SID', None)
        os.environ.pop('TWILIO_AUTH_TOKEN', None)
        try:
            r = self.client.post('/auth/complete-login', headers=_ip(), json={
                'pre_auth_token': self._pre_auth(u),
                'email_code': self._sembrar(u, 'email'),
                'sms_code': '', 'face_token': ''})
            self.assertEqual(r.status_code, 503, r.text[:200])
        finally:
            os.environ['PREFY_TEST_VOTE_ACCOUNTS'] = CUENTA

    def test_una_cuenta_normal_sigue_necesitando_la_cara_para_entrar(self):
        u, _ = self._usuario()
        r = self.client.post('/auth/complete-login', headers=_ip(), json={
            'pre_auth_token': self._pre_auth(u),
            'email_code': self._sembrar(u, 'email'),
            'sms_code': '', 'face_token': ''})
        self.assertEqual(r.status_code, 400, r.text[:200])
        self.assertIn('facial', r.text.lower())


class TestLaPantallaDeIngresoNoPideLaCamara(Base):
    """EL FALLO REAL, reproducido.

    La exencion se habia aplicado en /auth/complete-login -el endpoint que
    VALIDA-, pero la pantalla del portal se construye con el `requires` que
    devuelve /auth/login -el que ANUNCIA-. Ese seguia diciendo
    `face: true`, asi que el portal pedia la camara y se negaba a seguir
    sin token facial: la peticion a complete-login NO se hacia nunca y la
    exencion no se alcanzaba.

    Resultado para el usuario: «todavia me exige reconocimiento facial».
    """

    def _login(self, user, clave='Clave-de-prueba-2026'):
        return self.client.post('/auth/login', headers=_ip(),
                                json={'email': user.email, 'password': clave})

    def _con_entrega(self):
        """Simula que los codigos SALEN, que es lo que ocurre en produccion.

        Sin proveedor de correo ni SMS, /auth/login responde 503 -y hace
        bien: para una cuenta exenta de camara, un fallo de envio es un
        bloqueo real-. Aqui lo que se mide es la exencion, no el proveedor.
        """
        previos = (main.send_email_otp, main.send_sms_otp)
        main.send_email_otp = lambda *a, **k: True
        main.send_sms_otp = lambda *a, **k: True
        return previos

    def _restaurar(self, previos):
        main.send_email_otp, main.send_sms_otp = previos

    def test_a_la_cuenta_designada_NO_se_le_anuncia_la_camara(self):
        os.environ['TWILIO_ACCOUNT_SID'] = 'sid-de-prueba'
        os.environ['TWILIO_AUTH_TOKEN'] = 'token-de-prueba'
        u, _ = self._usuario(email=_uniq('designada') + '@test.invalid')
        os.environ['PREFY_TEST_VOTE_ACCOUNTS'] = u.email
        _envio = self._con_entrega()
        try:
            self.assertTrue(u.selfie_verified,
                            'la cuenta tiene selfie verificada: es el caso real')
            r = self._login(u)
            self.assertEqual(r.status_code, 200, r.text[:200])
            d = r.json()
            self.assertTrue(d.get('pending_2fa'))
            req = d['requires']
            self.assertFalse(req['face'],
                             'se le sigue anunciando la camara: el portal la '
                             'pedira y no llegara a complete-login')
            # `requires.email` informa si el codigo SALIO de verdad, y en
            # el entorno de pruebas no hay proveedor de correo. Lo que se
            # comprueba es que el codigo SE GENERO: en produccion, donde el
            # proveedor funciona, ademas se anuncia.
            self.assertTrue(
                self.db.query(main.OTPCode).filter(
                    main.OTPCode.user_id == u.id,
                    main.OTPCode.channel == 'email',
                    main.OTPCode.used == False).count(),
                'no se genero el codigo de correo')
        finally:
            self._restaurar(_envio)
            os.environ['PREFY_TEST_VOTE_ACCOUNTS'] = CUENTA
            os.environ.pop('TWILIO_ACCOUNT_SID', None)
            os.environ.pop('TWILIO_AUTH_TOKEN', None)

    def test_a_cualquier_otra_cuenta_SI_se_le_anuncia(self):
        u, _ = self._usuario()
        r = self._login(u)
        self.assertEqual(r.status_code, 200, r.text[:200])
        self.assertTrue(r.json()['requires']['face'],
                        'los demas tienen que seguir pasando por la camara')

    def test_el_recorrido_completo_de_ingreso_sin_camara(self):
        """De punta a punta: login -> los dos codigos -> sesion. Sin cara."""
        os.environ['TWILIO_ACCOUNT_SID'] = 'sid-de-prueba'
        os.environ['TWILIO_AUTH_TOKEN'] = 'token-de-prueba'
        u, _ = self._usuario(email=_uniq('completa') + '@test.invalid')
        os.environ['PREFY_TEST_VOTE_ACCOUNTS'] = u.email
        _envio = self._con_entrega()
        try:
            r = self._login(u)
            self.assertEqual(r.status_code, 200, r.text[:200])
            d = r.json()
            self.assertFalse(d['requires']['face'])
            pre = d['pre_auth_token']
            codigos = {c.channel: c.code for c in self.db.query(main.OTPCode).filter(
                main.OTPCode.user_id == u.id, main.OTPCode.used == False).all()}
            self.assertIn('email', codigos, 'no se genero codigo de correo')
            # El SMS puede no haberse enviado en el entorno de pruebas; se
            # siembra para poder recorrer el paso que el usuario SI vera.
            if 'sms' not in codigos:
                self.db.add(main.OTPCode(
                    user_id=u.id, email=u.email, code='654321', channel='sms',
                    used=False,
                    expires_at=datetime.utcnow() + timedelta(minutes=10)))
                self.db.commit()
                codigos['sms'] = '654321'
            fin = self.client.post('/auth/complete-login', headers=_ip(), json={
                'pre_auth_token': pre, 'email_code': codigos['email'],
                'sms_code': codigos['sms'], 'face_token': ''})
            self.assertEqual(fin.status_code, 200, fin.text[:300])
            self.assertTrue(fin.json().get('token'), 'no devolvio sesion')
        finally:
            self._restaurar(_envio)
            os.environ['PREFY_TEST_VOTE_ACCOUNTS'] = CUENTA
            os.environ.pop('TWILIO_ACCOUNT_SID', None)
            os.environ.pop('TWILIO_AUTH_TOKEN', None)

    def test_si_no_sale_ningun_codigo_se_dice_claramente(self):
        """Sin camara como salida, un fallo de envio tiene que fallar
        claro en vez de dejarla en una pantalla sin nada que rellenar."""
        u, _ = self._usuario(email=_uniq('sinenvio') + '@test.invalid')
        os.environ['PREFY_TEST_VOTE_ACCOUNTS'] = u.email
        try:
            r = self._login(u)
            self.assertEqual(r.status_code, 503, r.text[:200])
            self.assertIn('ningún canal', r.text)
        finally:
            os.environ['PREFY_TEST_VOTE_ACCOUNTS'] = CUENTA

    def test_una_cuenta_normal_conserva_la_cara_como_salida(self):
        """La misma situacion, para otra cuenta, NO es un bloqueo: le queda
        la camara."""
        u, _ = self._usuario()
        r = self._login(u)
        self.assertEqual(r.status_code, 200, r.text[:200])
        self.assertTrue(r.json()['requires']['face'])

    def test_el_portal_obedece_a_requires_face(self):
        """Por que `requires.face` era decisivo: el portal se niega a
        continuar sin token facial cuando viene en true."""
        portal = open('voter_portal.html', encoding='utf-8').read()
        self.assertIn("if (req.face  && !_loginFaceToken)", portal)
        self.assertIn('req.face', portal)


class TestElAvisoEnPantalla(Base):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.portal = open('voter_portal.html', encoding='utf-8').read()

    def test_muestra_el_texto_exacto(self):
        self.assertIn('VOTO DE PRUEBA — NO CONTABILIZADO', self.portal)

    def test_no_ofrece_nada_operativo_en_modo_prueba(self):
        self.assertIn("const esPrueba = data.voto_de_prueba === true", self.portal)
        self.assertIn("${esPrueba ? '' : rewardHtml}", self.portal)
        self.assertIn('NO es un comprobante', self.portal)


if __name__ == '__main__':
    unittest.main(verbosity=2)
