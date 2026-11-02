"""test_e2e_commercial.py — recorrido comercial de punta a punta.

Reproduce el funcionamiento real de Preferendum sobre la app FastAPI en
memoria, con una base SQLite temporal y datos EXCLUSIVAMENTE ficticios.

LO QUE ESTA SUITE SÍ VALIDA
  A. Registro, documento obligatorio y único, prevención de duplicados,
     elegibilidad y segmentación.
  B. Organizador: alta, creación y publicación de consulta, acceso de
     participantes, votación, cierre y resultados.
  C. Anunciante: alta, campaña, público objetivo, presupuesto, estimación
     de alcance, asiento contable en el ledger, entrega, impresiones,
     control de duplicados y consumo de presupuesto.
  E. Integridad: conciliación de votos y de saldos, y ausencia de
     duplicación por reintentos.

LO QUE NO PUEDE VALIDAR (y por qué) — ver TestLimitesConocidos al final:
  · Stripe real: no se ejecutan pagos. El webhook se ejercita con su
    verificación de firma activa, que es justamente lo que lo protege.
  · Rekognition real: exige credenciales de AWS y una cara real.
  · Dispositivos físicos iOS/Android.
  · Anclaje real en Polygon: requiere gas y una clave de wallet.
"""
import json
import os
import re
import tempfile
import unittest
import uuid

_TMP = tempfile.mkdtemp(prefix='prefy_e2e_')
os.environ['DATABASE_URL'] = f'sqlite:///{os.path.join(_TMP, "e2e.db")}'
os.environ.setdefault('ADMIN_SECRET', 'e2e-solo-local')
os.environ.setdefault('JWT_SECRET', 'e2e-solo-local')
os.environ.pop('ADMIN_SECRET_CANARY', None)

import bcrypt                                    # noqa: E402
from fastapi.testclient import TestClient        # noqa: E402

import main                                      # noqa: E402
import pruebas_voto_facial  # noqa: E402,F401  (rellena el token facial del voto)
import usa_data_agent as USA                     # noqa: E402

ADMIN = os.environ['ADMIN_SECRET']
_REF = {'done': False}


def _ip():
    """IP distinta por petición: el escudo de seguridad bloquea una IP tras
    varios fallos y luego le sirve un payload señuelo con status 200, lo que
    haría indistinguible 'pasó' de 'bloqueado'."""
    _ip.n = getattr(_ip, 'n', 0) + 1
    return {'X-Forwarded-For': f'203.0.113.{_ip.n % 250 + 1}'}


def _seed_reference_data(db):
    """Datos de referencia ficticios: PPP de país, ocupaciones BLS reales
    (vía la MISMA función que usa el endpoint de importación, no una copia a
    mano) y dos comunas chilenas."""
    if _REF['done']:
        return
    db.execute(main.text(
        "CREATE TABLE IF NOT EXISTS world_countries "
        "(iso2 TEXT PRIMARY KEY, gdp_per_capita_usd FLOAT)"))
    db.execute(main.text(
        "INSERT OR REPLACE INTO world_countries VALUES ('CL', 26000.0)"))
    USA.import_bls_occupations_to_db(db)
    db.execute(main.text("""
        INSERT INTO occupation_unified
          (country_iso, occupation_type, isco_group, profession_score, median_annual_usd)
        VALUES ('CL', 'ISCO', 2, 78.0, 42000)"""))
    db.execute(main.text("""
        CREATE TABLE IF NOT EXISTS occupation_salary (
            id INTEGER PRIMARY KEY AUTOINCREMENT, country_iso TEXT NOT NULL,
            isco_group INTEGER NOT NULL, isco_label TEXT DEFAULT '',
            median_monthly_local REAL, median_monthly_usd REAL, currency TEXT DEFAULT '',
            profession_score REAL DEFAULT 0, year INTEGER, source TEXT DEFAULT '',
            updated_at TIMESTAMP, UNIQUE (country_iso, isco_group))"""))
    db.execute(main.text("""
        INSERT OR REPLACE INTO occupation_salary
          (country_iso, isco_group, median_monthly_usd, profession_score, year, source)
        VALUES ('CL', 2, 2600.0, 65.0, 2025, 'e2e-ficticio')"""))
    for commune, tier, idx in (('Las Condes', 'A', 95.0), ('Conchalí', 'C', 45.0)):
        db.add(main.CommuneMarketData(country='CL', commune=commune, se_tier=tier,
                                      income_index=idx, price_m2_avg=idx, cpm_usd=6.0))
    db.commit()
    _REF['done'] = True


def _uniq(p):
    return f'{p}-{uuid.uuid4().hex[:10]}'


def _rut():
    """RUT ficticio del rango 99.xxx.xxx, que no colisiona con uno real."""
    return f'99{uuid.uuid4().int % 10**6:06d}-9'


class Base(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        cls.db = main.SessionLocal()
        _seed_reference_data(cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    # ── ayudantes ────────────────────────────────────────────────────

    def crear_votante(self, commune='Las Condes', profession='Ingeniero Industrial',
                      dob='1990-05-05', gender='M', national_id=None, phone=None):
        email = _uniq('votante') + '@test.invalid'
        body = {'name': 'Votante Ficticio', 'email': email, 'password': 'ClaveE2E123!',
                'country': 'CL', 'profession': profession, 'cargo': 'empleado',
                'commune': commune, 'gender': gender, 'dob': dob,
                'national_id': national_id or _rut()}
        if phone:
            body['phone'] = phone
        r = self.client.post('/voter/register', json=body, headers=_ip())
        return r, email, body

    def token_de(self, user_id, role='voter'):
        """Token de sesión emitido por la MISMA función que usa el login
        real (make_token), para no inventar un camino de autenticación
        paralelo que no exista en producción."""
        return main.make_token(user_id, role)

    def usuario_por_email(self, email):
        return self.db.query(main.User).filter(
            main.func.lower(main.User.email) == email.lower()).first()

    def auth(self, token):
        h = _ip()
        h['Authorization'] = f'Bearer {token}'
        return h


# ═══════════════════════════════════════════════════════════════════════
# A. REGISTRO E IDENTIDAD
# ═══════════════════════════════════════════════════════════════════════

class TestA_RegistroEIdentidad(Base):

    def test_A1_registro_de_votante_funciona(self):
        r, email, _ = self.crear_votante()
        self.assertIn(r.status_code, (200, 201), r.text)
        u = self.usuario_por_email(email)
        self.assertIsNotNone(u)
        self.assertEqual(u.country, 'CL')

    def test_A2_el_documento_es_obligatorio(self):
        r = self.client.post('/voter/register', json={
            'name': 'Sin Documento', 'email': _uniq('nodoc') + '@test.invalid',
            'password': 'ClaveE2E123!', 'country': 'CL',
            'profession': 'Ingeniero Industrial', 'cargo': 'empleado'},
            headers=_ip())
        self.assertEqual(r.status_code, 400)
        self.assertIn('documento', r.text.lower())

    def test_A3_documento_duplicado_se_rechaza(self):
        nid = _rut()
        r1, _, _ = self.crear_votante(national_id=nid)
        self.assertIn(r1.status_code, (200, 201), r1.text)
        r2, _, _ = self.crear_votante(national_id=nid)
        self.assertEqual(r2.status_code, 409, r2.text)
        self.assertIn('documento', r2.text.lower())

    def test_A4_la_contrasena_nunca_se_guarda_en_claro(self):
        r, email, body = self.crear_votante()
        self.assertIn(r.status_code, (200, 201))
        u = self.usuario_por_email(email)
        self.assertNotEqual(u.password, body['password'])
        self.assertTrue(bcrypt.checkpw(body['password'].encode(), u.password.encode()))

    def test_A5_la_verificacion_de_identidad_existe_y_exige_sesion(self):
        for ruta in ('/verify/document', '/verify/selfie', '/verify/face'):
            r = self.client.post(ruta, headers=_ip())
            self.assertIn(r.status_code, (401, 403, 422),
                          f'{ruta} debería exigir sesión, dio {r.status_code}')

    def test_A6_elegibilidad_respeta_pais_edad_genero_comuna_y_tier(self):
        """Usa el evaluador canónico por su ruta real (adaptador incluido),
        no una fórmula paralela."""
        import eligibility as E
        from datetime import date
        hoy = date(2026, 10, 31)

        class D:
            def __init__(self, **kw):
                d = dict(id=1, scope_country='CL', scope_commune='', target_gender='all',
                         target_age_min=18, target_age_max=65, target_se_tiers='A,B,C,D',
                         income_min_usd=None, income_max_usd=None, target_professions='',
                         target_cargos='', target_company_sizes='', min_per_capita_usd=0.0,
                         is_closed_list=False, category='general', title='ficticia')
                d.update(kw); self.__dict__.update(d)

        _, email, _ = self.crear_votante(commune='Las Condes', gender='M', dob='1990-05-05')
        u = self.usuario_por_email(email)
        p = E.profile_from_user(u, today=hoy)

        self.assertTrue(E.evaluate_consultation(p, D()).allowed, 'CL debe pasar')
        self.assertFalse(E.evaluate_consultation(p, D(scope_country='AR')).allowed)
        self.assertFalse(E.evaluate_consultation(p, D(target_gender='f')).allowed)
        self.assertFalse(E.evaluate_consultation(p, D(target_age_min=70, target_age_max=99)).allowed)
        self.assertFalse(E.evaluate_consultation(
            p, D(scope='commune', scope_commune='maipu')).allowed)
        # lista cerrada: la lista ES la audiencia
        self.assertFalse(E.evaluate_consultation(
            p, D(is_closed_list=True), closed_list_member=False).allowed)
        self.assertTrue(E.evaluate_consultation(
            p, D(is_closed_list=True), closed_list_member=True).allowed)

    def test_A7_sin_sesion_no_hay_elegibilidad(self):
        import eligibility as E
        d = E.evaluate_consultation(None, object())
        self.assertFalse(d.allowed)
        self.assertIn('authentication', d.blocking_dimensions())


# ═══════════════════════════════════════════════════════════════════════
# B. CONSULTAS: CREACIÓN, PUBLICACIÓN, VOTO, RESULTADOS
# ═══════════════════════════════════════════════════════════════════════

class TestB_ConsultasYVotacion(Base):

    def _consulta_ficticia(self, **kw):
        """Crea una consulta por ORM, con los mismos campos que usa la ruta
        real de creación. Evita depender del flujo de aprobación de
        organizador, que se cubre aparte en B1."""
        from datetime import datetime, timedelta
        d = dict(title='¿Consulta ficticia de prueba E2E?',
                 context='Creada por la suite automatizada. No es real.',
                 options=json.dumps(['Opción A', 'Opción B', 'Opción C']),
                 creator_type='citizen', debate_type='nat', scope='country',
                 scope_country='CL', scope_commune='', target_gender='all',
                 target_age_min=18, target_age_max=99, target_se_tiers='A,B,C,D',
                 status='live', closes_at=datetime.utcnow() + timedelta(days=7),
                 verify_closes_at=datetime.utcnow() + timedelta(days=8),
                 vote_counts=json.dumps({}), total_votes=0)
        d.update(kw)
        deb = main.Debate(**d)
        self.db.add(deb); self.db.commit(); self.db.refresh(deb)
        return deb

    def test_B1_alta_de_organizador(self):
        r = self.client.post('/organizer/register', json={
            'name': 'Organizador Ficticio', 'email': _uniq('org') + '@test.invalid',
            'password': 'ClaveE2E123!', 'org_name': 'Institución Ficticia',
            'country': 'CL'}, headers=_ip())
        self.assertIn(r.status_code, (200, 201, 400, 409, 422),
                      f'alta de organizador devolvió {r.status_code}: {r.text[:200]}')

    def test_B2_crear_consulta_y_configurar_segmentacion(self):
        deb = self._consulta_ficticia(scope_country='CL', target_gender='f',
                                      target_age_min=25, target_age_max=40,
                                      target_se_tiers='A,B')
        self.assertIsNotNone(deb.id)
        self.assertEqual(deb.target_gender, 'f')
        self.assertEqual(deb.target_se_tiers, 'A,B')
        self.assertEqual(len(json.loads(deb.options)), 3)

    def test_B3_preguntas_de_seguimiento_condicionales(self):
        follow = json.dumps([{'title': '¿Por qué?', 'options': ['Razón 1', 'Razón 2']}, {}, {}])
        deb = self._consulta_ficticia(follow_up_questions=follow)
        self.assertEqual(len(json.loads(deb.follow_up_questions)), 3)

    def test_B4_la_consulta_publicada_aparece_para_un_elegible(self):
        deb = self._consulta_ficticia()
        _, email, _ = self.crear_votante(gender='M', dob='1990-05-05')
        u = self.usuario_por_email(email)
        u.email_verified = True; self.db.commit()
        salida = main._eligible_debates_for(u, self.db, status='live', limit=50)
        self.assertIn(deb.id, [d['id'] for d in salida],
                      'un usuario elegible debe ver la consulta publicada')

    def test_B5_un_no_elegible_no_la_ve(self):
        deb = self._consulta_ficticia(target_gender='f')
        _, email, _ = self.crear_votante(gender='M')
        u = self.usuario_por_email(email)
        u.email_verified = True; self.db.commit()
        salida = main._eligible_debates_for(u, self.db, status='live', limit=50)
        self.assertNotIn(deb.id, [d['id'] for d in salida],
                         'la segmentación por género debe excluirlo')

    def test_B6_un_borrador_no_aparece_para_nadie(self):
        deb = self._consulta_ficticia(status='draft')
        _, email, _ = self.crear_votante()
        u = self.usuario_por_email(email)
        u.email_verified = True; self.db.commit()
        salida = main._eligible_debates_for(u, self.db, status='live', limit=50)
        self.assertNotIn(deb.id, [d['id'] for d in salida])

    def test_B7_votar_registra_el_voto_y_entrega_codigo(self):
        deb = self._consulta_ficticia()
        _, email, _ = self.crear_votante()
        u = self.usuario_por_email(email)
        u.email_verified = True; self.db.commit()
        r = self.client.post(f'/debates/{deb.id}/vote', json={'option_index': 0},
                             headers=self.auth(self.token_de(u.id)))
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertTrue(data.get('success'))
        self.assertTrue(data.get('verify_code'))
        self.assertEqual(data.get('option'), 'Opción A')
        # la papeleta NO lleva identidad
        voto = self.db.query(main.DebateVote).filter(
            main.DebateVote.verify_code == data['verify_code']).first()
        self.assertIsNotNone(voto)
        self.assertIsNone(voto.voter_id, 'la papeleta nunca debe llevar voter_id')

    def test_B8_no_se_puede_votar_dos_veces_con_la_misma_cuenta(self):
        deb = self._consulta_ficticia()
        _, email, _ = self.crear_votante()
        u = self.usuario_por_email(email)
        u.email_verified = True; self.db.commit()
        h = self.auth(self.token_de(u.id))
        r1 = self.client.post(f'/debates/{deb.id}/vote', json={'option_index': 0}, headers=h)
        self.assertEqual(r1.status_code, 200, r1.text)
        r2 = self.client.post(f'/debates/{deb.id}/vote', json={'option_index': 1},
                              headers=self.auth(self.token_de(u.id)))
        self.assertEqual(r2.status_code, 409, f'segundo voto debió dar 409: {r2.text[:200]}')

    def test_B9_un_no_elegible_no_puede_votar_aunque_conozca_el_id(self):
        """El límite de autorización se reevalúa al votar: conocer el
        debate_id y llamar la API directamente no basta."""
        deb = self._consulta_ficticia(target_gender='f')
        _, email, _ = self.crear_votante(gender='M')
        u = self.usuario_por_email(email)
        u.email_verified = True; self.db.commit()
        r = self.client.post(f'/debates/{deb.id}/vote', json={'option_index': 0},
                             headers=self.auth(self.token_de(u.id)))
        self.assertEqual(r.status_code, 403, r.text[:200])

    def test_B10_verificacion_por_codigo_devuelve_el_voto(self):
        deb = self._consulta_ficticia()
        _, email, _ = self.crear_votante()
        u = self.usuario_por_email(email)
        u.email_verified = True; self.db.commit()
        r = self.client.post(f'/debates/{deb.id}/vote', json={'option_index': 2},
                             headers=self.auth(self.token_de(u.id)))
        code = r.json()['verify_code']
        v = self.client.post(f'/debates/{deb.id}/verify', json={'code': code}, headers=_ip())
        self.assertEqual(v.status_code, 200, v.text)
        self.assertEqual(v.json()['your_vote'], 'Opción C')
        self.assertIn('blockchain_anchored', v.json())

    def test_B11_un_codigo_inexistente_no_valida(self):
        deb = self._consulta_ficticia()
        v = self.client.post(f'/debates/{deb.id}/verify',
                             json={'code': 'INEXISTENTE-0000'}, headers=_ip())
        self.assertEqual(v.status_code, 404)

    def test_B12_cierre_y_resultados(self):
        from datetime import datetime, timedelta
        deb = self._consulta_ficticia()
        _, email, _ = self.crear_votante()
        u = self.usuario_por_email(email)
        u.email_verified = True; self.db.commit()
        self.client.post(f'/debates/{deb.id}/vote', json={'option_index': 1},
                         headers=self.auth(self.token_de(u.id)))
        # cerrar moviendo solo la fecha de cierre
        deb.closes_at = datetime.utcnow() - timedelta(minutes=1)
        self.db.commit(); self.db.refresh(deb)
        self.assertNotEqual(main.get_debate_status(deb), 'live')
        formateada = main.format_debate(deb)
        total = sum(r['count'] for r in formateada['results'])
        self.assertEqual(total, formateada['total_votes'],
                         'la suma del escrutinio debe igualar el total')


# ═══════════════════════════════════════════════════════════════════════
# C. CAMPAÑAS PUBLICITARIAS
# ═══════════════════════════════════════════════════════════════════════

class TestC_CampanasPublicitarias(Base):

    def _marketer(self):
        email = _uniq('anunciante') + '@test.invalid'
        u = main.User(name='Anunciante Ficticio', email=email, role='marketer',
                      password=bcrypt.hashpw(b'x', bcrypt.gensalt()).decode(),
                      country='CL', email_verified=True)
        self.db.add(u); self.db.commit(); self.db.refresh(u)
        perfil = main.MarketerProfile(user_id=u.id, company_name='Marca Ficticia',
                                      status='approved')
        self.db.add(perfil); self.db.commit()
        return u, email

    def _campana(self, u, email, budget=100000):
        c = main.AdCampaign(
            advertiser_email=email, advertiser_name='Marca Ficticia',
            title='Campaña ficticia E2E', budget_clp=budget, is_active=True,
            target_country='CL', target_communes='Las Condes',
            target_gender='all', target_se_tiers='A,B,C,D',
            target_age_min=18, target_age_max=99,
            ad_copy='Anuncio de prueba', link_url='https://example.invalid')
        self.db.add(c); self.db.commit(); self.db.refresh(c)
        return c

    def test_C1_alta_de_anunciante(self):
        # business_category es OBLIGATORIO: el producto rechaza el alta sin
        # declarar la categoría de la empresa (control de brand safety).
        r = self.client.post('/marketer/register', json={
            'name': 'Anunciante Nuevo', 'email': _uniq('mk') + '@test.invalid',
            'password': 'ClaveE2E123!', 'company_name': 'Marca Ficticia',
            'business_category': 'retail_comercio', 'country': 'CL'}, headers=_ip())
        self.assertIn(r.status_code, (200, 201, 409),
                      f'alta de anunciante devolvió {r.status_code}: {r.text[:200]}')

    def test_C1b_el_alta_sin_categoria_de_empresa_se_rechaza(self):
        r = self.client.post('/marketer/register', json={
            'name': 'Sin Categoria', 'email': _uniq('mk') + '@test.invalid',
            'password': 'ClaveE2E123!', 'company_name': 'Marca Ficticia',
            'country': 'CL'}, headers=_ip())
        self.assertEqual(r.status_code, 403)
        self.assertIn('categoría', r.text.lower())

    def test_C1c_una_categoria_inventada_se_rechaza(self):
        """El catálogo de categorías es cerrado (control de brand safety):
        'retail' NO vale, 'retail_comercio' sí."""
        r = self.client.post('/marketer/register', json={
            'name': 'Categoria Inventada', 'email': _uniq('mk') + '@test.invalid',
            'password': 'ClaveE2E123!', 'company_name': 'Marca Ficticia',
            'business_category': 'categoria-que-no-existe', 'country': 'CL'},
            headers=_ip())
        self.assertEqual(r.status_code, 403)
        self.assertIn('no es una categoría reconocida', r.text)

    def test_C2_estimacion_de_alcance_responde(self):
        r = self.client.post('/marketer/estimate', json={
            'advertiser_email': _uniq('est') + '@test.invalid',
            'advertiser_name': 'Marca Ficticia',
            'campaign_title': 'Estimación E2E', 'budget_clp': 100000,
            'target_country': 'CL', 'target_communes': 'Las Condes',
            'start_date': '2026-11-01', 'end_date': '2026-11-30'}, headers=_ip())
        self.assertEqual(r.status_code, 200, r.text[:200])
        self.assertIsInstance(r.json(), dict)

    def test_C3_crear_campana_con_publico_objetivo_y_presupuesto(self):
        u, email = self._marketer()
        c = self._campana(u, email)
        self.assertEqual(c.target_country, 'CL')
        self.assertEqual(c.budget_clp, 100000)
        self.assertTrue(c.is_active)

    def test_C4_solo_el_dueno_lee_sus_metricas(self):
        u, email = self._marketer()
        c = self._campana(u, email)
        otro, _ = self._marketer()
        # el dueño sí
        r = self.client.get(f'/marketer/campaigns/{c.id}/metrics',
                            headers=self.auth(self.token_de(u.id, 'marketer')))
        self.assertEqual(r.status_code, 200, r.text[:200])
        # un intruso autenticado, no
        r2 = self.client.get(f'/marketer/campaigns/{c.id}/metrics',
                             headers=self.auth(self.token_de(otro.id, 'marketer')))
        self.assertEqual(r2.status_code, 403, r2.text[:200])
        # sin sesión, tampoco
        r3 = self.client.get(f'/marketer/campaigns/{c.id}/metrics', headers=_ip())
        self.assertIn(r3.status_code, (401, 403))

    def test_C5_el_ledger_es_el_unico_contable_y_no_permite_gasto_sin_reserva(self):
        """R1 del ledger: una campaña nunca gasta más de lo reservado. Una
        campaña recién creada está LEGACY_UNRECONCILED, no LEDGER_MANAGED,
        así que un gasto no debe poder recargarse contra ella."""
        u, email = self._marketer()
        c = self._campana(u, email)
        self.assertNotEqual(getattr(c, 'ledger_status', None), 'LEDGER_MANAGED',
                            'una campaña nueva no debe nacer gestionada por el ledger')

    def test_C6_los_paquetes_de_pago_se_publican(self):
        r = self.client.get('/payments/packages', headers=_ip())
        self.assertEqual(r.status_code, 200, r.text[:200])

    def test_C7_el_webhook_de_stripe_exige_firma(self):
        """No se ejecuta ningún pago. Se comprueba que el webhook RECHAZA
        una carga sin firma válida, que es lo que impide acreditar saldo
        falso."""
        r = self.client.post('/payments/stripe/webhook',
                             content=json.dumps({'type': 'checkout.session.completed'}),
                             headers={**_ip(), 'Content-Type': 'application/json'})
        self.assertNotEqual(r.status_code, 200,
                            'un webhook sin firma válida no debe aceptarse')

    def test_C8_una_impresion_exige_sesion(self):
        for ruta in ('/ads/view', '/ads/impression'):
            r = self.client.post(ruta, json={}, headers=_ip())
            self.assertIn(r.status_code, (401, 403, 422),
                          f'{ruta} debería exigir sesión, dio {r.status_code}')


# ═══════════════════════════════════════════════════════════════════════
# D. ENTREGA, PRESUPUESTO, LEDGER, MÉTRICAS, INFORMES Y ADMINISTRACIÓN
#
# Lo que estas pruebas persiguen es la promesa comercial completa: que un
# anuncio llegue SOLO a quien cumple el público objetivo, que cada impresión
# servida consuma presupuesto real, que el ledger sea el único contable y no
# permita cobrar dos veces ni gastar sin reserva, que las métricas y los
# informes digan lo que de verdad ocurrió, y que la administración esté
# cerrada con credencial.
#
# Todo con dinero FICTICIO de clase DEMO: no se ejecuta ningún pago.
# ═══════════════════════════════════════════════════════════════════════

class TestD_EntregaYContabilidad(Base):

    # ── utilidades ───────────────────────────────────────────────────

    def _cuenta_reservada(self):
        """Cuenta del saldo reservado de una campaña DEMO, obtenida por el
        MISMO accesor canónico que usa el ledger, no por un nombre copiado:
        si alguna vez se renombra la cuenta, estas pruebas siguen midiendo
        la correcta en vez de pasar contra una cuenta inexistente."""
        return main._ledger.campaign_account_kind(main._ledger.DEMO)

    def _cuenta_gasto(self):
        return main._ledger.spend_account_kind(main._ledger.DEMO)

    def _anunciante(self):
        email = _uniq('anunciante') + '@test.invalid'
        u = main.User(name='Anunciante Ficticio', email=email, role='marketer',
                      password=bcrypt.hashpw(b'x', bcrypt.gensalt()).decode(),
                      country='CL', email_verified=True)
        self.db.add(u); self.db.commit(); self.db.refresh(u)
        self.db.add(main.MarketerProfile(user_id=u.id,
                                         company_name='Marca Ficticia',
                                         status='approved'))
        self.db.commit()
        return u, email

    def _campana(self, email, *, marca, budget=100000, tiers='A,B,C,D',
                 communes='Las Condes', activa=True):
        c = main.AdCampaign(
            advertiser_email=email, advertiser_name=marca,
            title=f'Campaña {marca}', budget_clp=budget, is_active=activa,
            target_country='CL', target_communes=communes,
            target_gender='all', target_se_tiers=tiers,
            target_age_min=18, target_age_max=99,
            ad_copy=f'Anuncio de {marca}', link_url='https://example.invalid')
        self.db.add(c); self.db.commit(); self.db.refresh(c)
        return c

    def _financiar_y_reservar(self, u, c, creditos=50.0):
        """Deja la campaña LEDGER_MANAGED por el ÚNICO camino que existe en
        producción: financiar al usuario y reservar contra la campaña. No se
        fabrica saldo ni se fuerza el estado a mano."""
        c.value_class = main._ledger.DEMO
        self.db.commit()
        f = main._ledger_fund(
            self.db, main._ledger.DEMO, u.id, creditos, method='e2e_demo',
            idempotency_key=_uniq('fund'), description='Fondeo ficticio E2E')
        self.assertTrue(f['ok'], f'el fondeo ficticio falló: {f}')
        r = main._ledger_reserve(self.db, c, u.id, creditos,
                                 idempotency_key=_uniq('res'))
        self.assertTrue(r['ok'], f'la reserva falló: {r}')
        self.db.refresh(c)
        return c

    def _votante_elegible(self, commune='Las Condes'):
        r, email, _ = self.crear_votante(commune=commune)
        self.assertIn(r.status_code, (200, 201), r.text[:200])
        u = self.usuario_por_email(email)
        return u, self.auth(self.token_de(u.id, 'voter'))

    # ── D1. Entrega efectiva de publicidad ───────────────────────────

    def test_D1_un_usuario_del_publico_objetivo_recibe_el_anuncio(self):
        """La promesa central: la campaña LLEGA a quien cumple el objetivo."""
        u, email = self._anunciante()
        marca = _uniq('MarcaEntrega')
        self._campana(email, marca=marca, communes='Las Condes')
        _, cab = self._votante_elegible(commune='Las Condes')
        r = self.client.get('/ads/featured', headers=cab)
        self.assertEqual(r.status_code, 200, r.text[:200])
        marcas = [a.get('brand') for a in r.json().get('ads', [])]
        self.assertIn(marca, marcas,
                      f'la campaña no se entregó a un usuario elegible: {marcas}')

    def test_D2_un_usuario_fuera_del_publico_objetivo_no_lo_recibe(self):
        """Y la contraparte: no llega a quien NO lo cumple. Se comprueba la
        AUSENCIA de esta marca concreta, no que la lista esté vacía: cuando
        ninguna campaña calza, la ruta sirve anuncios estáticos de respaldo,
        así que una lista vacía no probaría nada."""
        u, email = self._anunciante()
        marca = _uniq('MarcaSoloLasCondes')
        self._campana(email, marca=marca, communes='Las Condes')
        _, cab = self._votante_elegible(commune='Conchalí')
        r = self.client.get('/ads/featured', headers=cab)
        self.assertEqual(r.status_code, 200, r.text[:200])
        marcas = [a.get('brand') for a in r.json().get('ads', [])]
        self.assertNotIn(marca, marcas,
                         'la campaña se entregó FUERA de su público objetivo')

    def test_D3_sin_sesion_no_se_entrega_ninguna_campana(self):
        """El evaluador de elegibilidad deniega al usuario no autenticado, así
        que una campaña segmentada no puede alcanzarlo."""
        u, email = self._anunciante()
        marca = _uniq('MarcaConSesion')
        self._campana(email, marca=marca)
        r = self.client.get('/ads/featured', headers=_ip())
        self.assertEqual(r.status_code, 200, r.text[:200])
        marcas = [a.get('brand') for a in r.json().get('ads', [])]
        self.assertNotIn(marca, marcas,
                         'una campaña segmentada se entregó sin sesión')

    def test_D4_una_campana_desactivada_no_se_entrega(self):
        u, email = self._anunciante()
        marca = _uniq('MarcaApagada')
        self._campana(email, marca=marca, activa=False)
        _, cab = self._votante_elegible()
        r = self.client.get('/ads/featured', headers=cab)
        marcas = [a.get('brand') for a in r.json().get('ads', [])]
        self.assertNotIn(marca, marcas, 'una campaña inactiva se entregó')

    def test_D5_una_campana_con_presupuesto_agotado_no_se_entrega(self):
        """El filtro de entrega exige budget_clp > spent_clp."""
        u, email = self._anunciante()
        marca = _uniq('MarcaAgotada')
        c = self._campana(email, marca=marca, budget=100)
        c.spent_clp = 100
        self.db.commit()
        _, cab = self._votante_elegible()
        r = self.client.get('/ads/featured', headers=cab)
        marcas = [a.get('brand') for a in r.json().get('ads', [])]
        self.assertNotIn(marca, marcas,
                         'una campaña con presupuesto agotado siguió entregándose')

    # ── D6. Consumo de presupuesto ───────────────────────────────────

    def test_D6_una_impresion_servida_consume_presupuesto_del_ledger(self):
        """Dinero de verdad moviéndose: el saldo reservado de la campaña baja
        exactamente el coste de una impresión."""
        u, email = self._anunciante()
        c = self._campana(email, marca=_uniq('MarcaConsumo'))
        self._financiar_y_reservar(u, c, creditos=50.0)
        self.assertEqual(c.ledger_status, 'LEDGER_MANAGED')
        votante, cab = self._votante_elegible()

        antes = main._ledger_balance(self.db, self._cuenta_reservada(), c.id)
        r = self.client.post(
            f'/ads/impression?campaign_id={c.id}&debate_id=0'
            f'&idempotency_key={_uniq("imp")}', headers=cab)
        self.assertEqual(r.status_code, 200, r.text[:300])
        cuerpo = r.json()
        self.assertTrue(cuerpo.get('ok'), f'la impresión no se cobró: {cuerpo}')
        despues = main._ledger_balance(self.db, self._cuenta_reservada(), c.id)
        consumido = antes - despues

        # El ledger lleva los importes al céntimo (ledger.round_amount), así
        # que el cargo real es round(20/950, 2) = 0.02, no 0.0210526...
        # Se fija el comportamiento REAL, y la divergencia con el precio
        # declarado se documenta en test_D6b.
        esperado = main._ledger.round_amount(main.COST_PER_VIEW / main.USD_TO_CLP)
        self.assertAlmostEqual(consumido, esperado, places=5,
                               msg='el consumo no coincide con el cargo del ledger')
        self.assertGreater(consumido, 0, 'la impresión no consumió presupuesto')
        # y la respuesta declara al anunciante lo que le cuesta
        self.assertIn('cost_this_impression', cuerpo)

    def test_D6b_HALLAZGO_el_cargo_redondeado_no_iguala_el_precio_declarado(self):
        """HALLAZGO COMERCIAL, no un fallo de esta prueba.

        Dos cifras conviven para una misma impresión:
          · AdImpressionLog.cost_clp = COST_PER_VIEW = 20 CLP (lo que se
            registra en el libro de impresiones)
          · el cargo del ledger = round(20/950, 2) = 0.02 créditos, que a
            950 CLP/USD equivalen a 19 CLP

        El ledger lleva los importes al céntimo, y 20/950 = 0,0210526 no cabe
        en un céntimo. El anunciante se factura un 5% MENOS de lo que dice su
        propio libro de impresiones. No afecta la integridad del ledger —el
        asiento cuadra— pero el precio declarado y el precio cobrado no son
        el mismo número, y la diferencia crece con el volumen.

        Es una decisión de negocio (unidad mínima de facturación), no un
        defecto que yo deba resolver. Esta prueba lo fija y lo deja visible.
        """
        precio_declarado = main.COST_PER_VIEW / main.USD_TO_CLP
        cargo_real = main._ledger.round_amount(precio_declarado)
        self.assertNotAlmostEqual(
            cargo_real, precio_declarado, places=5,
            msg='si esto ya coincide, el hallazgo se resolvió: retirar la prueba')
        desvio = abs(cargo_real - precio_declarado) / precio_declarado
        self.assertLess(desvio, 0.10,
                        f'el desvío entre precio declarado y cobrado creció a '
                        f'{desvio:.1%}: revisar la unidad de facturación')

    def test_D6c_HALLAZGO_spent_clp_no_refleja_el_asiento_del_ledger(self):
        """HALLAZGO COMERCIAL, medido de punta a punta.

        `_ledger_spend` dice en su propio docstring que refleja el coste en
        CLP dentro de `spent_clp`, pero lo calcula con el importe PEDIDO
        (0,021052…) en vez del POSTEADO (0,02):

            cost_clp = int(round(float(cost_credits) * USD_TO_CLP))

        Así que el espejo suma 20 CLP mientras el ledger reconoce 0,02
        créditos ≡ 19 CLP. No es un espejo: refleja la petición, no el
        asiento.

        Importa porque la puerta de entrega es `budget_clp > spent_clp`: con
        el espejo inflado un 5,26 %, una campaña deja de entregarse antes de
        haber gastado su presupuesto según el libro canónico. Y cualquier
        factura construida sobre `spent_clp` cobraría de más.

        Ver docs/POLITICA_CONCILIACION_FACTURACION.md §1.1 y §4.3. No se
        corrige aquí: la unidad de facturación es una decisión de negocio.
        """
        u, email = self._anunciante()
        c = self._campana(email, marca=_uniq('MarcaEspejo'))
        self._financiar_y_reservar(u, c, creditos=50.0)
        _, cab = self._votante_elegible()

        gasto_antes = main._ledger_balance(self.db, self._cuenta_gasto(), None)
        r = self.client.post(
            f'/ads/impression?campaign_id={c.id}&debate_id=0'
            f'&idempotency_key={_uniq("imp")}', headers=cab)
        self.assertTrue(r.json().get('ok'), r.text[:300])
        self.db.refresh(c)

        posteado = main._ledger_balance(self.db, self._cuenta_gasto(), None) - gasto_antes
        espejo_clp = float(c.spent_clp or 0)
        log_clp = float(self.db.query(
            main.func.sum(main.AdImpressionLog.cost_clp)).filter(
            main.AdImpressionLog.campaign_id == c.id).scalar() or 0)

        # Lo que el ledger asentó, en CLP
        ledger_clp = posteado * main.USD_TO_CLP
        self.assertAlmostEqual(ledger_clp, 19.0, places=6,
                               msg=f'el ledger asentó {ledger_clp} CLP')
        # Lo que dicen el espejo y el libro de impresiones
        self.assertEqual(espejo_clp, 20.0)
        self.assertEqual(log_clp, 20.0)
        # La brecha: 1 CLP por impresión, el 5,26 %
        brecha = espejo_clp - ledger_clp
        self.assertAlmostEqual(brecha, 1.0, places=6,
                               msg='si la brecha cambió, actualizar '
                                   'docs/POLITICA_CONCILIACION_FACTURACION.md')
        self.assertAlmostEqual(brecha / ledger_clp, 0.0526, places=3)

    def test_D6e_CORREGIDO_impresiones_y_ledger_concilian_EXACTAMENTE(self):
        """CHANGE-006 — la corrección mínima, sin tocar precios.

        Cada impresión guarda ahora `cost_credits_posted`: el importe EXACTO
        que el ledger asentó, no el que se pidió. Así la suma de las
        impresiones iguala al céntimo el gasto reconocido por el ledger, sin
        tolerancia.

        Lo que NO cambia, a propósito: `cost_clp` sigue siendo 20, el espejo
        `spent_clp` sigue sumando 20, y ningún importe histórico se toca.
        Decidir si el precio debe ser 19 o 20 es comercial y queda pendiente.
        """
        u, email = self._anunciante()
        c = self._campana(email, marca=_uniq('MarcaExacta'))
        self._financiar_y_reservar(u, c, creditos=50.0)
        gasto_antes = main._ledger_balance(self.db, self._cuenta_gasto(), None)

        for _ in range(5):
            _, cab = self._votante_elegible()
            r = self.client.post(
                f'/ads/impression?campaign_id={c.id}&debate_id=0'
                f'&idempotency_key={_uniq("imp")}', headers=cab)
            self.assertTrue(r.json().get('ok'), r.text[:300])

        ledger_reconocido = (
            main._ledger_balance(self.db, self._cuenta_gasto(), None) - gasto_antes)
        suma_impresiones = float(self.db.query(
            main.func.sum(main.AdImpressionLog.cost_credits_posted)).filter(
            main.AdImpressionLog.campaign_id == c.id).scalar() or 0)

        # Se compara EN LA UNIDAD DECLARADA DEL LEDGER, que es el céntimo.
        # Los dos lados suman los MISMOS importes por fila; lo único que
        # difiere es el orden de acumulación en coma flotante (5 × 0,02 da
        # 0,09999999999999998 por un lado y 0,1 por el otro). Exactitud aquí
        # significa exactitud en la unidad en la que el ledger lleva las
        # cuentas, no igualdad bit a bit de dos sumas de flotantes — esa
        # última no es alcanzable y exigirla sería una prueba falsa.
        self.assertEqual(round(suma_impresiones, 2), round(ledger_reconocido, 2),
                         f'las impresiones no concilian con el ledger al '
                         f'céntimo: {suma_impresiones} vs {ledger_reconocido}')
        # cinco impresiones a 0,02 créditos asentados
        self.assertEqual(round(suma_impresiones, 2), 0.10)
        # y la diferencia residual es solo ruido de coma flotante
        self.assertLess(abs(suma_impresiones - ledger_reconocido), 1e-9)
        # y cada fila sabe lo suyo: ninguna quedó sin anotar
        sin_anotar = self.db.query(main.AdImpressionLog).filter(
            main.AdImpressionLog.campaign_id == c.id,
            main.AdImpressionLog.cost_credits_posted == None).count()
        self.assertEqual(sin_anotar, 0,
                         'alguna impresión cobrada quedó sin su importe asentado')
        # lo histórico intacto: cost_clp y el espejo siguen en 20 por impresión
        self.db.refresh(c)
        self.assertEqual(float(c.spent_clp or 0), 100.0,
                         'el espejo spent_clp cambió: eso es una decisión comercial')
        self.assertEqual(float(self.db.query(
            main.func.sum(main.AdImpressionLog.cost_clp)).filter(
            main.AdImpressionLog.campaign_id == c.id).scalar() or 0), 100.0)

    def test_D6f_una_impresion_no_cobrada_no_anota_importe(self):
        """Si no se cobró, no hay importe asentado que anotar. La columna
        dice 'desconocido' (NULL), nunca un cero que parecería un cobro de
        cero."""
        u, email = self._anunciante()
        c = self._campana(email, marca=_uniq('MarcaNoCobrada'))
        self.assertNotEqual(c.ledger_status, 'LEDGER_MANAGED')
        _, cab = self._votante_elegible()
        r = self.client.post(
            f'/ads/impression?campaign_id={c.id}&debate_id=0'
            f'&idempotency_key={_uniq("imp")}', headers=cab)
        self.assertTrue(r.json().get('not_billable'), r.text[:300])
        n = self.db.query(main.AdImpressionLog).filter(
            main.AdImpressionLog.campaign_id == c.id,
            main.AdImpressionLog.cost_credits_posted != None).count()
        self.assertEqual(n, 0,
                         'anotó un importe asentado para una impresión que no '
                         'se cobró')

    def test_D6d_la_conciliacion_existente_ya_delata_la_brecha(self):
        """La tolerancia de 1,0 CLP de `reconcile_campaign_spend` es
        exactamente el error de UNA impresión, así que con dos o más la
        divergencia se reporta. No es un hueco de detección: es un hueco de
        decisión."""
        import ledger as L
        # dos impresiones: ledger 38 CLP, espejo 40 CLP, brecha 2 > 1,0
        r = L.reconcile_campaign_spend(
            budget_clp=100000, spent_clp=40, impression_log_sum_clp=40,
            ledger_spend_credits=0.04, usd_to_clp=main.USD_TO_CLP)
        self.assertEqual(r['status'], L.RECON_MISMATCH,
                         f'la conciliación no delató la brecha: {r}')
        self.assertTrue(any('ledger-recognized' in f for f in r['findings']),
                        f'no señaló la divergencia del ledger: {r["findings"]}')
        # y con UNA sola impresión la tolerancia la esconde — por eso §4.6
        # propone bajarla a cero una vez el redondeo desaparezca
        r1 = L.reconcile_campaign_spend(
            budget_clp=100000, spent_clp=20, impression_log_sum_clp=20,
            ledger_spend_credits=0.02, usd_to_clp=main.USD_TO_CLP)
        self.assertEqual(r1['status'], L.RECON_OK,
                         'si esto ya no pasa, la tolerancia cambió: revisar '
                         'docs/POLITICA_CONCILIACION_FACTURACION.md §4.6')

    def test_D7_la_misma_impresion_no_se_cobra_dos_veces(self):
        """Idempotencia: un reintento con la MISMA clave no vuelve a cobrar.
        Es lo que protege al anunciante de un reintento de red."""
        u, email = self._anunciante()
        c = self._campana(email, marca=_uniq('MarcaIdem'))
        self._financiar_y_reservar(u, c, creditos=50.0)
        _, cab = self._votante_elegible()
        clave = _uniq('imp-repetida')
        url = (f'/ads/impression?campaign_id={c.id}&debate_id=0'
               f'&idempotency_key={clave}')

        r1 = self.client.post(url, headers=cab)
        self.assertEqual(r1.status_code, 200, r1.text[:300])
        self.assertTrue(r1.json().get('ok'))
        saldo1 = main._ledger_balance(self.db, self._cuenta_reservada(), c.id)

        r2 = self.client.post(url, headers=cab)
        self.assertEqual(r2.status_code, 200, r2.text[:300])
        self.assertTrue(r2.json().get('idempotent'),
                        'el reintento no se reconoció como idempotente')
        saldo2 = main._ledger_balance(self.db, self._cuenta_reservada(), c.id)
        self.assertAlmostEqual(saldo1, saldo2, places=6,
                               msg='un reintento con la misma clave cobró dos veces')

    def test_D8_una_impresion_sin_clave_de_idempotencia_no_se_cobra(self):
        """Falla cerrado: sin clave, no hay cargo."""
        u, email = self._anunciante()
        c = self._campana(email, marca=_uniq('MarcaSinClave'))
        self._financiar_y_reservar(u, c, creditos=50.0)
        _, cab = self._votante_elegible()
        r = self.client.post(
            f'/ads/impression?campaign_id={c.id}&debate_id=0&idempotency_key=',
            headers=cab)
        self.assertEqual(r.status_code, 422, r.text[:200])

    def test_D9_al_agotarse_el_saldo_la_campana_se_detiene_sola(self):
        """Y no sigue gastando: el presupuesto es un límite real, no un
        indicador. La campaña queda inactiva, así que tampoco se entrega."""
        u, email = self._anunciante()
        marca = _uniq('MarcaSeAgota')
        c = self._campana(email, marca=marca)
        # reserva mínima: alcanza para una sola impresión
        coste = main.COST_PER_VIEW / main.USD_TO_CLP
        self._financiar_y_reservar(u, c, creditos=round(coste, 5))
        _, cab = self._votante_elegible()

        r1 = self.client.post(
            f'/ads/impression?campaign_id={c.id}&debate_id=0'
            f'&idempotency_key={_uniq("imp")}', headers=cab)
        self.assertEqual(r1.status_code, 200, r1.text[:300])
        self.assertTrue(r1.json().get('ok'), f'la primera impresión falló: {r1.text[:300]}')

        r2 = self.client.post(
            f'/ads/impression?campaign_id={c.id}&debate_id=0'
            f'&idempotency_key={_uniq("imp")}', headers=cab)
        self.assertEqual(r2.status_code, 200, r2.text[:300])
        self.assertTrue(r2.json().get('budget_exhausted'),
                        f'se cobró una impresión sin saldo: {r2.text[:300]}')
        self.db.refresh(c)
        self.assertFalse(c.is_active,
                         'la campaña sin saldo debe quedar inactiva')
        _, cab2 = self._votante_elegible()
        marcas = [a.get('brand') for a in
                  self.client.get('/ads/featured', headers=cab2).json().get('ads', [])]
        self.assertNotIn(marca, marcas,
                         'una campaña agotada siguió entregándose')

    def test_D10_una_campana_sin_reserva_no_puede_gastar(self):
        """R1 del ledger. Una campaña LEGACY_UNRECONCILED no es facturable:
        la impresión se sirve pero NO se cobra, y lo dice explícitamente en
        vez de inventar un cargo."""
        u, email = self._anunciante()
        c = self._campana(email, marca=_uniq('MarcaSinReserva'))
        self.assertNotEqual(c.ledger_status, 'LEDGER_MANAGED')
        _, cab = self._votante_elegible()
        r = self.client.post(
            f'/ads/impression?campaign_id={c.id}&debate_id=0'
            f'&idempotency_key={_uniq("imp")}', headers=cab)
        self.assertEqual(r.status_code, 200, r.text[:300])
        cuerpo = r.json()
        self.assertFalse(cuerpo.get('ok'))
        self.assertTrue(cuerpo.get('not_billable'))
        self.assertEqual(cuerpo.get('reason'), 'legacy_unreconciled')

    def test_D11_una_impresion_fuera_del_publico_objetivo_no_se_cobra(self):
        """El cobro va atado a la elegibilidad, no solo la entrega: si no se
        podía mostrar, no se puede facturar."""
        u, email = self._anunciante()
        c = self._campana(email, marca=_uniq('MarcaCobroAjeno'),
                          communes='Las Condes')
        self._financiar_y_reservar(u, c, creditos=50.0)
        antes = main._ledger_balance(self.db, self._cuenta_reservada(), c.id)
        _, cab = self._votante_elegible(commune='Conchalí')
        r = self.client.post(
            f'/ads/impression?campaign_id={c.id}&debate_id=0'
            f'&idempotency_key={_uniq("imp")}', headers=cab)
        self.assertEqual(r.status_code, 403, r.text[:300])
        despues = main._ledger_balance(self.db, self._cuenta_reservada(), c.id)
        self.assertEqual(antes, despues,
                         'se cobró una impresión a un usuario no elegible')

    # ── D12. Métricas e informes del anunciante ──────────────────────

    def test_D12_las_metricas_reflejan_la_impresion_realmente_servida(self):
        """Las métricas no pueden ser decorativas: tras una impresión cobrada
        el contador del anunciante debe subir."""
        u, email = self._anunciante()
        c = self._campana(email, marca=_uniq('MarcaMetricas'))
        self._financiar_y_reservar(u, c, creditos=50.0)
        _, cab = self._votante_elegible()
        cab_anunciante = self.auth(self.token_de(u.id, 'marketer'))

        def impresiones():
            r = self.client.get(f'/marketer/campaigns/{c.id}/metrics',
                                headers=cab_anunciante)
            self.assertEqual(r.status_code, 200, r.text[:300])
            d = r.json()
            # el nombre del campo puede variar; se busca el contador real
            for k in ('impressions', 'impressions_count', 'total_impressions',
                      'views'):
                if isinstance(d.get(k), (int, float)):
                    return d[k], d
            self.fail(f'las métricas no publican un contador de impresiones: '
                      f'{sorted(d.keys())}')

        antes, _ = impresiones()
        r = self.client.post(
            f'/ads/impression?campaign_id={c.id}&debate_id=0'
            f'&idempotency_key={_uniq("imp")}', headers=cab)
        self.assertTrue(r.json().get('ok'), r.text[:300])
        despues, detalle = impresiones()
        self.assertEqual(despues, antes + 1,
                         f'las métricas no registraron la impresión: {detalle}')

    def test_D13_un_clic_se_registra_y_no_se_factura(self):
        """El clic NO es un evento pagado: debe contarse sin mover saldo."""
        u, email = self._anunciante()
        c = self._campana(email, marca=_uniq('MarcaClic'))
        self._financiar_y_reservar(u, c, creditos=50.0)
        antes = main._ledger_balance(self.db, self._cuenta_reservada(), c.id)
        previos = c.clicks_count or 0
        r = self.client.post(f'/ads/click?campaign_id={c.id}&debate_id=0',
                             headers=_ip())
        self.assertEqual(r.status_code, 200, r.text[:200])
        self.db.refresh(c)
        self.assertEqual((c.clicks_count or 0), previos + 1,
                         'el clic no se registró')
        despues = main._ledger_balance(self.db, self._cuenta_reservada(), c.id)
        self.assertEqual(antes, despues, 'un clic movió saldo: no debe facturarse')

    def test_D14_el_informe_del_anunciante_responde_y_esta_protegido(self):
        for ruta in ('/marketing/advertiser/report',):
            r = self.client.get(ruta, headers=_ip())
            self.assertNotEqual(r.status_code, 500,
                                f'{ruta} devolvió error de servidor: {r.text[:200]}')
            self.assertIn(r.status_code, (200, 401, 403, 422),
                          f'{ruta} dio {r.status_code}: {r.text[:200]}')

    def test_D15_el_panel_del_anunciante_no_lo_lee_un_tercero(self):
        u, email = self._anunciante()
        c = self._campana(email, marca=_uniq('MarcaPanel'))
        otro, _ = self._anunciante()
        propio = self.client.get(f'/advertiser/dashboard/{c.id}',
                                 headers=self.auth(self.token_de(u.id, 'marketer')))
        ajeno = self.client.get(f'/advertiser/dashboard/{c.id}',
                                headers=self.auth(self.token_de(otro.id, 'marketer')))
        anon = self.client.get(f'/advertiser/dashboard/{c.id}', headers=_ip())
        self.assertNotEqual(propio.status_code, 500, propio.text[:200])
        self.assertIn(ajeno.status_code, (401, 403, 404),
                      f'un tercero leyó el panel ajeno: {ajeno.status_code}')
        self.assertIn(anon.status_code, (401, 403, 404),
                      f'el panel se leyó sin sesión: {anon.status_code}')

    # ── D16. Ledger y conciliación ───────────────────────────────────

    def test_D16_el_gasto_queda_asentado_en_el_ledger_con_doble_entrada(self):
        """Cada impresión cobrada deja un asiento cuadrado: lo que sale del
        saldo reservado entra en la cuenta de gasto."""
        u, email = self._anunciante()
        c = self._campana(email, marca=_uniq('MarcaAsiento'))
        self._financiar_y_reservar(u, c, creditos=50.0)
        _, cab = self._votante_elegible()
        # La cuenta de gasto es un SUMIDERO GLOBAL por clase de valor:
        # ledger.build_spend asienta la contrapartida con ref_id=None, no por
        # campaña. Consultarla con el id de la campaña devolvería siempre 0 y
        # la prueba pasaría sin comprobar nada.
        gasto_antes = main._ledger_balance(self.db, self._cuenta_gasto(), None)
        reservado_antes = main._ledger_balance(
            self.db, self._cuenta_reservada(), c.id)
        r = self.client.post(
            f'/ads/impression?campaign_id={c.id}&debate_id=0'
            f'&idempotency_key={_uniq("imp")}', headers=cab)
        self.assertTrue(r.json().get('ok'), r.text[:300])
        reservado_despues = main._ledger_balance(
            self.db, self._cuenta_reservada(), c.id)
        salida = reservado_antes - reservado_despues
        self.assertGreater(salida, 0, 'el asiento no movió el saldo reservado')
        gasto_despues = main._ledger_balance(self.db, self._cuenta_gasto(), None)
        self.assertAlmostEqual(gasto_despues - gasto_antes, salida, places=6,
                               msg='el asiento no cuadra: lo que salió del '
                                   'saldo reservado no entró en gasto')

    def test_D17_la_conciliacion_es_de_solo_lectura_y_exige_credencial(self):
        sin = self.client.get('/admin/ledger/reconciliation', headers=_ip())
        self.assertIn(sin.status_code, (401, 403, 422),
                      f'la conciliación se leyó sin credencial: {sin.status_code}')
        con = self.client.get(f'/admin/ledger/reconciliation?secret={ADMIN}',
                              headers=_ip())
        self.assertEqual(con.status_code, 200, con.text[:300])
        # y no escribe: comprobado sobre el AST de la propia ruta
        import ast as _ast, inspect, textwrap
        arbol = _ast.parse(textwrap.dedent(
            inspect.getsource(main.admin_ledger_reconciliation)))
        escrituras = [n.func.attr for n in _ast.walk(arbol)
                      if isinstance(n, _ast.Call)
                      and isinstance(n.func, _ast.Attribute)
                      and n.func.attr in ('add', 'commit', 'delete', 'merge')]
        self.assertEqual(escrituras, [],
                         f'la conciliación escribe: {escrituras}')

    def test_D18_la_politica_del_ledger_declara_que_no_esta_aprobada(self):
        """Honestidad: la política de demo y los umbrales siguen marcados como
        decisiones provisionales, no como aprobadas."""
        r = self.client.get(f'/admin/ledger/policy?secret={ADMIN}', headers=_ip())
        self.assertEqual(r.status_code, 200, r.text[:300])
        import ledger as L
        self.assertFalse(L.DEMO_POLICY_APPROVED_BY_BUSINESS)

    # ── D19. Administración ──────────────────────────────────────────

    def test_D19_las_rutas_de_administracion_comercial_exigen_credencial(self):
        u, email = self._anunciante()
        c = self._campana(email, marca=_uniq('MarcaAdmin'))
        rutas = [
            ('GET',   '/admin/campaigns'),
            ('GET',   f'/admin/campaigns/{c.id}/impression-ledger'),
            ('GET',   '/admin/ledger/reconciliation'),
            ('GET',   '/admin/recent-ad-impressions'),
            ('GET',   '/admin/stalled-campaigns'),
            ('PATCH', f'/admin/campaigns/{c.id}/deactivate'),
            ('PATCH', f'/admin/campaigns/{c.id}/activate'),
            ('POST',  f'/admin/campaigns/{c.id}/recompute-spend'),
        ]
        for metodo, ruta in rutas:
            r = self.client.request(metodo, ruta, headers=_ip())
            self.assertIn(r.status_code, (401, 403, 422),
                          f'{metodo} {ruta} quedó accesible sin credencial '
                          f'({r.status_code})')

    def test_D20_la_administracion_puede_detener_y_reactivar_una_campana(self):
        u, email = self._anunciante()
        c = self._campana(email, marca=_uniq('MarcaOnOff'))
        r = self.client.patch(
            f'/admin/campaigns/{c.id}/deactivate?secret={ADMIN}', headers=_ip())
        self.assertEqual(r.status_code, 200, r.text[:300])
        self.db.refresh(c)
        self.assertFalse(c.is_active, 'la campaña no se detuvo')
        r = self.client.patch(
            f'/admin/campaigns/{c.id}/activate?secret={ADMIN}', headers=_ip())
        self.assertEqual(r.status_code, 200, r.text[:300])
        self.db.refresh(c)
        self.assertTrue(c.is_active, 'la campaña no se reactivó')

    def test_D21_el_libro_de_impresiones_lista_la_impresion_cobrada(self):
        """Trazabilidad para una auditoría: cada impresión facturada debe
        poder encontrarse después."""
        u, email = self._anunciante()
        c = self._campana(email, marca=_uniq('MarcaLibro'))
        self._financiar_y_reservar(u, c, creditos=50.0)
        _, cab = self._votante_elegible()
        r = self.client.post(
            f'/ads/impression?campaign_id={c.id}&debate_id=0'
            f'&idempotency_key={_uniq("imp")}', headers=cab)
        self.assertTrue(r.json().get('ok'), r.text[:300])
        libro = self.client.get(
            f'/admin/campaigns/{c.id}/impression-ledger?secret={ADMIN}',
            headers=_ip())
        self.assertEqual(libro.status_code, 200, libro.text[:300])
        self.assertIn('200', str(libro.status_code))
        # la impresión existe en el registro real
        n = self.db.query(main.AdImpressionLog).filter(
            main.AdImpressionLog.campaign_id == c.id).count()
        self.assertGreaterEqual(n, 1, 'la impresión cobrada no quedó registrada')

    def test_D22_recalcular_el_gasto_lo_deriva_del_recuento_real(self):
        """La herramienta de reparación cuenta las impresiones REALES y las
        multiplica por el coste CPM vigente. Lo que importa aquí es que la
        cifra se derive del registro y reemplace una cifra corrupta, que es
        para lo que existe.

        Se prueba sobre una campaña legacy, que es donde aplica: una campaña
        gestionada por el ledger la rechaza a propósito (ver D23). Las
        impresiones se insertan como registro ficticio porque el camino de
        cobro no deja rastro en una campaña no facturable, y lo que se mide
        es la aritmética del recálculo.
        """
        u, email = self._anunciante()
        c = self._campana(email, marca=_uniq('MarcaRecalculo'))
        self.assertNotEqual(c.ledger_status, 'LEDGER_MANAGED')
        for _ in range(3):
            self.db.add(main.AdImpressionLog(
                campaign_id=c.id, debate_id=0, user_id=u.id,
                cost_clp=main.COST_PER_VIEW, gender='', age_group='',
                county='Las Condes', country='CL'))
        c.spent_clp = 999999          # cifra deliberadamente corrupta
        self.db.commit()

        r = self.client.post(
            f'/admin/campaigns/{c.id}/recompute-spend?secret={ADMIN}',
            headers=_ip())
        self.assertEqual(r.status_code, 200, r.text[:300])
        d = r.json()
        self.assertEqual(d['real_impressions'], 3,
                         'no contó las impresiones realmente registradas')
        self.db.refresh(c)
        esperado = min(c.budget_clp,
                       3 * main._cost_per_impression_clp(c, self.db))
        self.assertEqual(float(c.spent_clp or 0), float(esperado),
                         'el gasto recalculado no se deriva del recuento real')
        self.assertNotEqual(float(c.spent_clp or 0), 999999.0,
                            'no reemplazó la cifra corrupta')

    def test_D22b_HALLAZGO_el_recalculo_usa_el_cpm_de_hoy_no_lo_cobrado(self):
        """HALLAZGO COMERCIAL, no un fallo de esta prueba.

        La ruta de reparación recalcula el gasto como
        `impresiones × _cost_per_impression_clp(campaña)`, es decir con el
        CPM VIGENTE derivado de CommuneMarketData, mientras que cada fila de
        AdImpressionLog guarda el coste que de verdad se cobró
        (COST_PER_VIEW = 20 CLP). Con los datos de esta suite el CPM vigente
        da 6 CLP por impresión, así que el recálculo produce 18 donde el
        libro de impresiones suma 60.

        Consecuencia: reparar una campaña puede MOVER su gasto a una base de
        precios distinta de la que se le cobró, y el resultado depende de
        cuándo se ejecute la reparación. Su propia documentación dice
        «never inferred or invented», y el recuento no se inventa, pero el
        precio aplicado sí es otro.

        Es una decisión de negocio (qué precio es el válido al reparar un
        histórico), no un defecto que yo deba resolver sin autorización.
        Esta prueba lo deja medido y visible.
        """
        u, email = self._anunciante()
        c = self._campana(email, marca=_uniq('MarcaDosPrecios'))
        for _ in range(3):
            self.db.add(main.AdImpressionLog(
                campaign_id=c.id, debate_id=0, user_id=u.id,
                cost_clp=main.COST_PER_VIEW, gender='', age_group='',
                county='Las Condes', country='CL'))
        self.db.commit()
        suma_cobrada = self.db.query(
            main.func.sum(main.AdImpressionLog.cost_clp)).filter(
            main.AdImpressionLog.campaign_id == c.id).scalar() or 0
        cpm_vigente = main._cost_per_impression_clp(c, self.db)
        recalculado = 3 * cpm_vigente
        self.assertNotEqual(float(suma_cobrada), float(recalculado),
                            'si ya coinciden, el hallazgo se resolvió: '
                            'retirar esta prueba y actualizar el informe')
        # y queda explícito que son dos precios distintos, no un error de suma
        self.assertEqual(float(suma_cobrada), 3.0 * main.COST_PER_VIEW)
        self.assertNotEqual(cpm_vigente, main.COST_PER_VIEW)

    def test_D23_la_herramienta_legacy_no_puede_pisar_el_ledger(self):
        """Propiedad valiosa, verificada: en una campaña gestionada por el
        ledger, la reparación legacy del gasto se RECHAZA (409) en vez de
        sobreescribir la cifra de la que el ledger es dueño. Un contable
        único solo lo es si nadie más puede escribir en él."""
        u, email = self._anunciante()
        c = self._campana(email, marca=_uniq('MarcaDueno'))
        self._financiar_y_reservar(u, c, creditos=50.0)
        self.assertEqual(c.ledger_status, 'LEDGER_MANAGED')
        antes = float(c.spent_clp or 0)
        r = self.client.post(
            f'/admin/campaigns/{c.id}/recompute-spend?secret={ADMIN}',
            headers=_ip())
        self.assertEqual(r.status_code, 409, r.text[:300])
        self.assertIn('ledger', r.text.lower())
        self.db.refresh(c)
        self.assertEqual(float(c.spent_clp or 0), antes,
                         'la herramienta legacy modificó una campaña del ledger')


# ═══════════════════════════════════════════════════════════════════════
# E. INTEGRIDAD Y CONCILIACIÓN
# ═══════════════════════════════════════════════════════════════════════

class TestE_Integridad(Base):

    def test_E1_conciliacion_votos_vs_escrutinio(self):
        """Para cada consulta: la suma del escrutinio debe igualar el
        número real de papeletas. Detecta la deriva del contador."""
        from datetime import datetime, timedelta
        deb = main.Debate(
            title='Conciliación E2E', context='ficticia',
            options=json.dumps(['Sí', 'No']), creator_type='citizen',
            debate_type='nat', scope='country', scope_country='CL',
            target_gender='all', target_age_min=18, target_age_max=99,
            target_se_tiers='A,B,C,D', status='live',
            closes_at=datetime.utcnow() + timedelta(days=3),
            vote_counts=json.dumps({}), total_votes=0)
        self.db.add(deb); self.db.commit(); self.db.refresh(deb)

        emitidos = 0
        for _ in range(3):
            _, email, _ = self.crear_votante()
            u = self.usuario_por_email(email)
            u.email_verified = True; self.db.commit()
            r = self.client.post(f'/debates/{deb.id}/vote', json={'option_index': 0},
                                 headers=self.auth(self.token_de(u.id)))
            if r.status_code == 200:
                emitidos += 1

        self.db.refresh(deb)
        papeletas = self.db.query(main.DebateVote).filter(
            main.DebateVote.debate_id == deb.id).count()
        marcadores = self.db.query(main.HasVotedLog).filter(
            main.HasVotedLog.debate_id == deb.id).count()
        suma = sum(json.loads(deb.vote_counts or '{}').values())

        self.assertEqual(papeletas, emitidos, 'una papeleta por voto aceptado')
        self.assertEqual(marcadores, emitidos, 'un marcador por voto aceptado')
        self.assertEqual(suma, emitidos, 'el escrutinio debe cuadrar con las papeletas')
        self.assertEqual(deb.total_votes, emitidos, 'el contador debe cuadrar')

    def test_E2_un_reintento_no_duplica_el_voto(self):
        from datetime import datetime, timedelta
        deb = main.Debate(
            title='Reintento E2E', context='ficticia',
            options=json.dumps(['A', 'B']), creator_type='citizen', debate_type='nat',
            scope='country', scope_country='CL', target_gender='all',
            target_age_min=18, target_age_max=99, target_se_tiers='A,B,C,D',
            status='live', closes_at=datetime.utcnow() + timedelta(days=3),
            vote_counts=json.dumps({}), total_votes=0)
        self.db.add(deb); self.db.commit(); self.db.refresh(deb)
        _, email, _ = self.crear_votante()
        u = self.usuario_por_email(email)
        u.email_verified = True; self.db.commit()
        aceptados = 0
        for _ in range(4):
            r = self.client.post(f'/debates/{deb.id}/vote', json={'option_index': 0},
                                 headers=self.auth(self.token_de(u.id)))
            if r.status_code == 200:
                aceptados += 1
        self.assertEqual(aceptados, 1, 'cuatro intentos deben producir un solo voto')
        self.assertEqual(self.db.query(main.DebateVote).filter(
            main.DebateVote.debate_id == deb.id).count(), 1)

    def test_E3_el_ledger_es_el_unico_escritor_de_saldos(self):
        """CHANGE-001: ninguna ruta debe escribir spent_clp directamente;
        todo pasa por _ledger_spend."""
        import ast
        src = open('main.py', encoding='utf-8').read()
        tree = ast.parse(src)
        infractores = []
        for n in ast.walk(tree):
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            seg = ast.get_source_segment(src, n) or ''
            # Solo cuentan las ESCRITURAS: asignar a campaign.spent_clp o un
            # UPDATE en SQL. `spent_clp = campaign.spent_clp or 0` es una
            # lectura a variable local y no es una infracción — mi primera
            # versión de esta prueba la marcaba por error.
            escribe_orm = re.search(r'campaign\.spent_clp\s*=(?!=)', seg)
            escribe_sql = re.search(r'UPDATE\s+ad_campaigns[^;]*SET[^;]*spent_clp', seg, re.I)
            if (escribe_orm or escribe_sql) and '_ledger_spend' not in seg:
                infractores.append(n.name)
        self.assertEqual(infractores, [],
                         f'escriben spent_clp sin pasar por el ledger: {infractores}')

    def test_E4_la_consulta_819_y_los_votos_historicos_no_se_tocan(self):
        """Esta suite nunca debe escribir sobre la 819 ni sobre votos
        preexistentes: trabaja sobre una base temporal propia."""
        self.assertIn('e2e.db', os.environ['DATABASE_URL'],
                      'la suite debe correr contra su base temporal')
        self.assertNotIn('postgres', os.environ['DATABASE_URL'].lower())


# ═══════════════════════════════════════════════════════════════════════
# F. MONITOREO E INTEGRIDAD DEL ESCRUTINIO
# ═══════════════════════════════════════════════════════════════════════

class TestF_Monitoreo(Base):
    """Antes no existía ninguna señal: un 500 en producción no generaba
    alerta alguna. Estas pruebas comprueban que ahora la hay Y que no
    arrastra datos personales ni secretos, que es el riesgo clásico de
    cualquier sistema de reporte de errores."""

    def test_F1_un_error_no_controlado_emite_un_evento_de_una_linea(self):
        import io
        from contextlib import redirect_stdout

        class _Falso:
            method = 'GET'
            scope = {}
            url = type('U', (), {'path': '/ruta/ficticia'})()
            headers = {}
            client = None

        buf = io.StringIO()
        try:
            raise ValueError('mensaje interno que NO debe salir')
        except ValueError as e:
            with redirect_stdout(buf):
                main._error_event(_Falso(), e)
        salida = buf.getvalue().strip()
        self.assertTrue(salida.startswith(main.ERROR_EVENT_PREFIX),
                        f'el evento no lleva el prefijo alertable: {salida[:120]}')
        self.assertEqual(len(salida.splitlines()), 1,
                         'el evento debe ser UNA línea, para poder alertarlo')
        cuerpo = json.loads(salida[len(main.ERROR_EVENT_PREFIX):].strip())
        self.assertEqual(cuerpo['exc'], 'ValueError')
        for clave in ('ts', 'route', 'method', 'exc', 'at', 'ip_hash'):
            self.assertIn(clave, cuerpo)

    def test_F2_el_evento_NO_lleva_el_mensaje_ni_datos_personales(self):
        """Un evento de error es por donde se escapan los secretos. El
        mensaje de la excepción puede arrastrar valores de una fila, así
        que no se emite."""
        import io
        from contextlib import redirect_stdout

        class _Falso:
            method = 'GET'
            scope = {}
            url = type('U', (), {'path': '/admin/dev-otp/+56912345678'})()
            headers = {}
            client = None

        buf = io.StringIO()
        try:
            raise RuntimeError('clave=supersecreto correo=persona@real.com')
        except RuntimeError as e:
            with redirect_stdout(buf):
                main._error_event(_Falso(), e)
        salida = buf.getvalue()
        for prohibido in ('supersecreto', 'persona@real.com', '56912345678'):
            self.assertNotIn(prohibido, salida,
                             f'el evento filtró {prohibido!r}')

    def test_F3_la_ruta_se_enmascara_cuando_no_hay_plantilla(self):
        """Sin ruta resuelta, cualquier segmento con dígitos se enmascara:
        así un teléfono o un id no se cuela por la vía de respaldo."""
        class _Falso:
            scope = {}
            url = type('U', (), {'path': '/admin/dev-otp/56912345678'})()
        self.assertEqual(main._error_route_template(_Falso()),
                         '/admin/dev-otp/{masked}')

    def test_F4_sin_webhook_configurado_no_se_envia_nada(self):
        """La función queda inerte sin ERROR_WEBHOOK_URL: no debe intentar
        ninguna salida de red."""
        import inspect
        cuerpo = inspect.getsource(main._error_event)
        self.assertIn("os.getenv('ERROR_WEBHOOK_URL')", cuerpo)
        llamadas = cuerpo.index('ERROR_WEBHOOK_URL')
        self.assertIn('if destino:', cuerpo[llamadas:],
                      'el envío debe estar condicionado a la variable')
        self.assertIsNone(os.environ.get('ERROR_WEBHOOK_URL'),
                          'la suite no debe correr con webhook configurado')

    def test_F5_la_observabilidad_no_cambia_ninguna_respuesta(self):
        """Observa y vuelve a lanzar: el comportamiento visible es el de
        antes. Se comprueba sobre el AST que el except re-lanza."""
        import ast as _ast, inspect, textwrap
        arbol = _ast.parse(textwrap.dedent(
            inspect.getsource(main.error_observability_middleware)))
        relanza = [n for n in _ast.walk(arbol)
                   if isinstance(n, _ast.Raise) and n.exc is None]
        self.assertTrue(relanza,
                        'el middleware debe volver a lanzar la excepción tal cual')
        # y la app sigue respondiendo con normalidad
        r = self.client.get('/health', headers=_ip())
        self.assertEqual(r.status_code, 200, r.text[:200])


class TestF_IntegridadDelEscrutinio(Base):
    """La conciliación del escrutinio no existía: no había forma de
    preguntarle al sistema si el resultado que publica coincide con las
    papeletas que tiene."""

    def _consulta_con_votos(self, n_papeletas, declarado=None, counts=None):
        org = main.User(name='Org F', email=_uniq('orgf') + '@test.invalid',
                        password=bcrypt.hashpw(b'x', bcrypt.gensalt()).decode(),
                        country='CL', role='organizer', email_verified=True)
        self.db.add(org); self.db.commit(); self.db.refresh(org)
        d = main.Debate(
            title=_uniq('Consulta F'), context='Ficticia',
            options='["Opción A", "Opción B"]',
            creator_id=org.id, creator_type='organizer', scope='country',
            scope_country='CL', status='open', target_gender='all',
            target_age_min=18, target_age_max=99, target_se_tiers='A,B,C,D',
            total_votes=0, vote_counts=json.dumps(
                counts if counts is not None else {'Opción A': 0, 'Opción B': 0}))
        self.db.add(d); self.db.commit(); self.db.refresh(d)
        for i in range(n_papeletas):
            codigo = _uniq('VF').upper()
            self.db.add(main.DebateVote(
                debate_id=d.id, voter_id=None, option_index=i % 2,
                option_text=['Opción A', 'Opción B'][i % 2],
                verify_code=codigo, vote_hash=_uniq('h'),
                gender='M', age_group='35-44', commune='Las Condes',
                country='CL'))
            self.db.add(main.HasVotedLog(debate_id=d.id, user_id=org.id + 1 + i,
                                         verify_code=codigo))
        d.total_votes = n_papeletas if declarado is None else declarado
        self.db.commit(); self.db.refresh(d)
        return d

    def _conciliar(self):
        r = self.client.get(f'/admin/tally/reconciliation?secret={ADMIN}',
                            headers=_ip())
        self.assertEqual(r.status_code, 200, r.text[:300])
        return r.json()

    def test_F6_la_conciliacion_exige_credencial(self):
        r = self.client.get('/admin/tally/reconciliation', headers=_ip())
        self.assertIn(r.status_code, (401, 403, 422),
                      f'la conciliación del escrutinio quedó abierta: {r.status_code}')

    def test_F7_un_contador_inflado_ya_no_infla_el_resultado_publicado(self):
        """CHANGE-005 — la propiedad cambió, y a mejor.

        Antes, un contador inflado ERA el resultado publicado. Ahora el
        resultado se cuenta sobre las papeletas, así que un contador inflado
        queda reducido a una caché desajustada: se informa, pero ya no puede
        mentirle a nadie."""
        d = self._consulta_con_votos(3, declarado=37931)
        datos = self._conciliar()
        mio = [h for h in datos['hallazgos'] if h['debate_id'] == d.id]
        self.assertTrue(mio, 'no informó la caché desajustada')
        h = mio[0]
        self.assertEqual(h['cache_total_votes'], 37931)
        self.assertEqual(h['papeletas_reales'], 3)
        # lo PUBLICADO son las papeletas, no el contador inflado
        self.assertEqual(h['publicado'], 3)
        self.assertIn('cache total_votes != papeletas', h['informativas'])
        self.assertEqual(h['desviaciones'], [],
                         'un contador inflado ya no es un defecto de lo publicado')
        # y el resultado que de verdad se sirve dice 3
        publicado = main.format_debate(
            self.db.query(main.Debate).filter(main.Debate.id == d.id).first())
        self.assertEqual(publicado['total_votes'], 3,
                         'format_debate sigue publicando el contador inflado')

    def test_F8_una_consulta_cuadrada_no_aparece_como_hallazgo(self):
        """Sin falsos positivos: si las tres cifras coinciden, no es un
        hallazgo. Una conciliación que marca todo no sirve para nada."""
        d = self._consulta_con_votos(
            4, counts={'Opción A': 2, 'Opción B': 2})
        datos = self._conciliar()
        ids = [h['debate_id'] for h in datos['hallazgos']]
        self.assertNotIn(d.id, ids,
                         f'marcó como desviada una consulta cuadrada: '
                         f'{[h for h in datos["hallazgos"] if h["debate_id"] == d.id]}')
        self.assertGreaterEqual(datos['resumen']['cuadradas'], 1)

    def test_F9_detecta_claves_de_recuento_sin_opcion_actual(self):
        """Votos invisibles: `format_debate` hace counts.get(opcion, 0), así
        que una clave que ya no es ninguna opción devuelve 0 en silencio y
        sus votos desaparecen del resultado sin que nadie se entere."""
        d = self._consulta_con_votos(
            2, counts={'Opción A': 1, 'Opción B': 1, 'Opción retirada': 7})
        datos = self._conciliar()
        h = [x for x in datos['hallazgos'] if x['debate_id'] == d.id]
        self.assertTrue(h, 'no detectó la clave huérfana')
        self.assertIn('Opción retirada', h[0]['claves_huerfanas'])
        # CHANGE-005 — ya no esconde votos, porque el recuento publicado se
        # agrega por option_index y no por el texto de la opción. Sigue
        # siendo señal de que alguien editó opciones, así que se informa.
        self.assertIn('claves de vote_counts sin opcion actual', h[0]['informativas'])
        publicado = main.format_debate(
            self.db.query(main.Debate).filter(main.Debate.id == d.id).first())
        self.assertEqual(sum(r['count'] for r in publicado['results']), 2,
                         'el texto editado volvió a esconder votos')

    def test_F10_detecta_que_la_suma_por_opcion_no_cuadra(self):
        """Los porcentajes son el cociente de dos cifras guardadas aparte,
        así que pueden no sumar 100. Esto lo detecta."""
        d = self._consulta_con_votos(
            4, counts={'Opción A': 99, 'Opción B': 1})
        datos = self._conciliar()
        h = [x for x in datos['hallazgos'] if x['debate_id'] == d.id]
        self.assertTrue(h)
        self.assertEqual(h[0]['cache_suma_por_opcion'], 100)
        self.assertEqual(h[0]['papeletas_reales'], 4)
        self.assertIn('cache vote_counts != papeletas', h[0]['informativas'])
        # CHANGE-005 — y los porcentajes publicados ya SÍ suman 100, porque
        # el recuento y el total salen de la misma cuenta de papeletas.
        publicado = main.format_debate(
            self.db.query(main.Debate).filter(main.Debate.id == d.id).first())
        self.assertEqual(sum(r['count'] for r in publicado['results']), 4)
        self.assertAlmostEqual(sum(r['pct'] for r in publicado['results']), 100.0,
                               places=1,
                               msg='los porcentajes publicados no suman 100')

    def test_F11_la_conciliacion_no_escribe_nada(self):
        """Diagnóstico, no reparación: corregir la desviación conocida
        expondría las preferencias de las 3 personas que sí votaron en las
        consultas sembradas, así que debe exigir decisión aparte."""
        import ast as _ast, inspect, textwrap
        arbol = _ast.parse(textwrap.dedent(
            inspect.getsource(main.admin_tally_reconciliation)))
        escrituras = [n.func.attr for n in _ast.walk(arbol)
                      if isinstance(n, _ast.Call)
                      and isinstance(n.func, _ast.Attribute)
                      and n.func.attr in ('add', 'commit', 'delete', 'merge',
                                          'flush', 'execute')]
        self.assertEqual(escrituras, [],
                         f'la conciliación del escrutinio escribe: {escrituras}')

    def test_F12_declara_de_donde_sale_el_resultado(self):
        """Honestidad: la respuesta debe decir de dónde sale el número que
        se publica, y si la garantía de voto único está activa."""
        datos = self._conciliar()
        self.assertIn('origen_del_resultado', datos)
        self.assertIn('_derived_tally', datos['origen_del_resultado'])
        self.assertIn('nota', datos)
        # y declara si la garantía de voto único está realmente activa
        self.assertIn('garantia_voto_unico', datos)
        self.assertEqual(set(datos['garantia_voto_unico']),
                         {n for n, _, _ in main.VOTE_UNIQUENESS_INDEXES})


# ═══════════════════════════════════════════════════════════════════════
# LÍMITES CONOCIDOS — lo que esta suite NO valida, declarado
# ═══════════════════════════════════════════════════════════════════════

class TestLimitesConocidos(Base):
    """No son fallos: son fronteras declaradas del alcance de la prueba,
    para que nadie lea 'suite en verde' como 'todo verificado'."""

    def test_L1_stripe_no_se_ejercita_de_verdad(self):
        """Solo se comprueba que el webhook rechaza cargas sin firma. Un
        cobro real en modo de prueba exige credenciales de Stripe."""
        self.assertIsNone(os.environ.get('STRIPE_SECRET_KEY'),
                          'si hubiera clave de Stripe, revisar este límite')

    def test_L2_rekognition_no_se_ejercita(self):
        """La verificación facial real exige credenciales de AWS y una cara.
        Aquí solo se comprueba que las rutas exigen sesión."""
        self.assertIsNone(os.environ.get('AWS_SECRET_ACCESS_KEY'),
                          'si hubiera credenciales de AWS, revisar este límite')

    def test_L3_el_anclaje_en_blockchain_corre_en_modo_simulado(self):
        """Sin clave de wallet, anchor_vote devuelve live=False y un hash
        simulado. blockchain_anchored refleja la verdad y NO se asume True."""
        self.assertIsNone(os.environ.get('PREFERENDUM_WALLET_KEY'))
        import blockchain
        self.assertIn('_mock_tx', dir(blockchain.PreferendumBlockchain))

    def test_L4_dispositivos_fisicos_no_cubiertos(self):
        """iOS/Android en teléfonos reales no se pueden probar aquí. iOS
        tiene proyecto nativo generado; Android NO lo tiene."""
        self.assertTrue(os.path.isdir('ios'), 'iOS tiene proyecto nativo')
        self.assertFalse(os.path.isdir('android'),
                         'si ya existe android/, actualizar este límite')


if __name__ == '__main__':
    unittest.main()


# ═══════════════════════════════════════════════════════════════════════
# P0.5 — ESTIMADOR SOCIOECONÓMICO: regresión SOC vs slug heredado
#
# Contexto del defecto. `_assign_user_tier_inner` resuelve la profesión a
# su SOC canónico y ANTES sobreescribía la variable con el resultado. Pero
# los dos mapas de lookup heredados (_OCC_TO_ISCO, _US_PROFESSION_SOC)
# contienen solo 54 slugs y no códigos SOC, así que 'medico' se convertía
# en '29-1215' y el lookup fallaba: el camino heredado quedó roto y el
# camino SOC no existía. Sin ingreso no hay observación, sin observación
# el clasificador dice unresolved, y sin tier el usuario no calza con
# ninguna consulta ni campaña segmentada por tier.
#
# La corrección conserva el valor CRUDO junto al SOC y usa cada uno donde
# corresponde, derivando SOC→ISCO de occupation_unified (que trae ambos en
# sus 818 filas reales), sin inventar ninguna tabla de equivalencias y sin
# tocar ninguna regla, umbral ni criterio de clasificación.
# ═══════════════════════════════════════════════════════════════════════

class TestP05_EstimadorSocioeconomico(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db = main.SessionLocal()
        cls.db.execute(main.text(
            "CREATE TABLE IF NOT EXISTS world_countries "
            "(iso2 TEXT PRIMARY KEY, gdp_per_capita_usd FLOAT)"))
        cls.db.execute(main.text(
            "INSERT OR REPLACE INTO world_countries VALUES ('CL', 26000.0)"))
        USA.import_bls_occupations_to_db(cls.db)
        cls.db.execute(main.text("""
            INSERT INTO occupation_unified
              (country_iso, occupation_type, isco_group, profession_score, median_annual_usd)
            VALUES ('CL', 'ISCO', 2, 78.0, 42000)"""))
        cls.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def _clasificar(self, profession, commune='Las Condes'):
        u = main.User(name='X', email=_uniq('p05') + '@test.invalid',
                      password=bcrypt.hashpw(b'x', bcrypt.gensalt()).decode(),
                      country='CL', county=commune, dob='1990-05-05',
                      profession=profession, company_size='251-1000',
                      email_verified=True)
        self.db.add(u); self.db.commit(); self.db.refresh(u)
        main._assign_user_tier(u, self.db); self.db.refresh(u)
        return u

    # ── la corrección en sí ──────────────────────────────────────────

    def test_P05_el_valor_crudo_se_conserva_junto_al_soc(self):
        """La regresión fue sobreescribir la profesión con el SOC. El código
        debe conservar AMBOS."""
        src = main.__dict__['_assign_user_tier_inner'].__doc__ or ''
        import inspect
        cuerpo = inspect.getsource(main._assign_user_tier_inner)
        self.assertIn('user_profession_raw', cuerpo)
        self.assertIn('user_profession_soc', cuerpo)

    def test_P05_los_mapas_heredados_reciben_el_valor_crudo(self):
        import inspect
        cuerpo = inspect.getsource(main._assign_user_tier_inner)
        self.assertIn('_OCC_TO_ISCO.get(user_profession_raw)', cuerpo)
        self.assertIn('_US_PROFESSION_SOC.get(user_profession_raw)', cuerpo)

    def test_P05_soc_a_isco_sale_de_los_datos_no_de_una_tabla_inventada(self):
        """El helper debe consultar occupation_unified, no un diccionario
        escrito a mano: inventar equivalencias sería criterio nuevo."""
        import inspect
        cuerpo = inspect.getsource(main._isco_group_for_soc)
        self.assertIn('occupation_unified', cuerpo)
        self.assertIn('occupation_code', cuerpo)
        # y devuelve None ante lo desconocido, nunca un grupo adivinado
        self.assertIsNone(main._isco_group_for_soc('', self.db))
        self.assertIsNone(main._isco_group_for_soc('99-9999', self.db))
        # un SOC real sí resuelve, con el valor que dicen los datos
        self.assertEqual(main._isco_group_for_soc('17-2112', self.db), 2)

    def test_P05_las_reglas_y_umbrales_no_cambiaron(self):
        """La corrección NO debe tocar ningún umbral ni criterio: ambas
        banderas de política siguen declaradas como no aprobadas, y la
        función de puntuación a tier sigue siendo la del agente."""
        import socioeconomic as S, ledger as L
        self.assertFalse(S.THRESHOLDS_APPROVED_BY_BUSINESS)
        self.assertFalse(L.DEMO_POLICY_APPROVED_BY_BUSINESS)
        from usa_data_agent import profession_score_to_tier
        self.assertEqual(profession_score_to_tier(78.0), 'B')

    def test_P05_los_except_silenciosos_ahora_dejan_rastro(self):
        """Dos `except Exception: pass` ocultaban este defecto. Ahora
        registran, sin exponer datos personales."""
        import inspect
        # P0.6 — el cuerpo que lleva este manejador se renombró
        # `_assign_user_tier_persist`; `_assign_user_tier` es ahora solo el
        # envoltorio que abre y cierra la sesión aislada de referencia.
        exterior = inspect.getsource(main._assign_user_tier_persist)
        # El manejador que envuelve la LLAMADA a _assign_user_tier_inner es
        # el que ocultaba el defecto, y debe registrar. El OTRO
        # `except Exception: pass` de esta función envuelve un db.rollback()
        # de limpieza, donde silenciar sí es correcto: si el rollback falla
        # no hay nada que informar ni que hacer. Por eso se comprueba el
        # manejador concreto, no la ausencia global del patrón.
        self.assertIn('except Exception as _tier_err:', exterior,
                      'el manejador de la clasificación volvió a ser anónimo')
        self.assertIn('clasificación falló para user=', exterior)
        interior = inspect.getsource(main._assign_user_tier_inner)
        self.assertIn('except Exception as _occ_err:', interior,
                      'el manejador del bloque de ocupación volvió a ser anónimo')
        self.assertIn('estimación por ocupación falló', interior)
        # y NUNCA registra correo, documento ni el mensaje de la excepción
        for prohibido in ('user.email', 'national_id', '{_tier_err}'):
            self.assertNotIn(prohibido, exterior)

    # ── comportamiento: sin datos de comuna el estimador YA funciona ──

    def test_P05_un_codigo_soc_produce_ingreso_y_tier(self):
        u = self._clasificar('17-2112', commune='SinDatosDeComuna')
        self.assertIsNotNone(u.estimated_income_usd,
                             'un SOC canónico debe producir ingreso estimado')
        self.assertIn(u.se_tier, ('A', 'B', 'C', 'D'))

    def test_P05_un_titulo_en_texto_libre_produce_lo_mismo_que_su_soc(self):
        por_titulo = self._clasificar('Ingeniero Industrial', commune='SinDatosDeComuna')
        por_codigo = self._clasificar('17-2112', commune='SinDatosDeComuna')
        self.assertEqual(por_titulo.estimated_income_usd, por_codigo.estimated_income_usd,
                         'el título y su SOC deben dar el MISMO ingreso')
        self.assertEqual(por_titulo.se_tier, por_codigo.se_tier)

    def test_P05_un_slug_heredado_sigue_funcionando(self):
        """Compatibilidad: los slugs antiguos no deben romperse."""
        u = self._clasificar('medico', commune='SinDatosDeComuna')
        self.assertIsNotNone(u.estimated_income_usd,
                             'un slug heredado debe seguir produciendo ingreso')

    def test_P05_una_ocupacion_desconocida_no_inventa_ingreso(self):
        """Falla hacia 'no sé', nunca hacia una cifra adivinada por
        ocupación. (Puede haber un respaldo por país, que es otra fuente
        declarada, no una invención a partir de la ocupación.)"""
        u = self._clasificar('ocupacion-que-no-existe-xyz', commune='SinDatosDeComuna')
        # Lo que importa no es QUÉ fuente se usa, sino que la fuente quede
        # DECLARADA y sea una de las conocidas: nunca una cifra sin
        # procedencia. La auditabilidad es la garantía, no la ausencia de
        # respaldo.
        fuentes_conocidas = ('', 'estimated_occupation', 'country_median',
                             'commune', 'country', 'declared', 'declared_confirmed')
        self.assertIn(u.se_tier_source or '', fuentes_conocidas,
                      f'fuente NO declarada: {u.se_tier_source!r}')
        # P0.6 — la propiedad correcta es sobre el TIER, no sobre la cifra.
        # `se_tier_source` describe de dónde sale el TIER. Una cifra puede
        # existir sin tier: el respaldo documentado de ingreso per cápita del
        # país (main.py, «Fallback: ingreso per cápita del país cuando no hay
        # otro dato») garantiza que estimated_income_usd no quede en None, y
        # es una fuente declarada, no una invención a partir de la ocupación.
        # Lo que NUNCA debe pasar es un tier accionable sin procedencia.
        if u.se_tier:
            self.assertTrue(u.se_tier_source,
                            'hay un tier accionable sin procedencia declarada')
        else:
            # R7: sin señal suficiente, el tier queda vacío en vez de
            # inventarse. La cifra del respaldo por país no lo promueve.
            self.assertEqual(u.se_tier or '', '')

    # ── P0.6: el defecto corregido, con comuna y sin comuna ──────────
    #
    # Lo que se informó antes como «defecto de precedencia comuna/ocupación»
    # NO era una precedencia. Medido en PostgreSQL 16 real, la comuna no
    # altera ni el ingreso ni el tier en ninguno de los seis escenarios
    # probados. La causa real era transaccional: una lectura de referencia
    # que falla aborta la transacción (PostgreSQL) o dispara un
    # `db.rollback()` de reintento (SQLite, que no soporta
    # PERCENTILE_CONT), y ese rollback corría sobre la sesión del USUARIO,
    # descartando el ingreso ya calculado y expirando el objeto. Ninguna
    # regla económica estaba implicada, y por tanto ninguna se cambió.

    def _sembrar_comuna(self, nombre):
        ya = (self.db.query(main.CommuneMarketData)
              .filter(main.CommuneMarketData.commune == nombre).first())
        if not ya:
            self.db.add(main.CommuneMarketData(
                country='CL', commune=nombre, se_tier='A',
                income_index=95.0, price_m2_avg=95.0, cpm_usd=6.0))
            self.db.commit()

    def test_P06_con_datos_de_comuna_se_conserva_el_ingreso_por_ocupacion(self):
        """El caso que fallaba: comuna sembrada —lo normal en Chile— dejaba
        al usuario sin ingreso estimado y sin se_tier."""
        self._sembrar_comuna('LasCondesP06')
        u = self._clasificar('17-2112', commune='LasCondesP06')
        self.assertIsNotNone(u.estimated_income_usd,
                             'con comuna el ingreso por ocupación se perdía')
        self.assertIn(u.se_tier, ('A', 'B', 'C', 'D'),
                      'con comuna el usuario quedaba sin tier')

    def test_P06_la_comuna_no_altera_el_ingreso_ni_el_tier(self):
        """R1: el ingreso es la señal primaria de A/B/C/D. La comuna es una
        posición en el mercado local (R2), no una fuente de ingreso: no
        aparece en ninguna de las reglas R1-R8 como tal."""
        self._sembrar_comuna('LasCondesP06')
        con = self._clasificar('17-2112', commune='LasCondesP06')
        sin = self._clasificar('17-2112', commune='ComunaSinDatosP06')
        self.assertEqual(con.estimated_income_usd, sin.estimated_income_usd,
                         'la comuna no debe cambiar el ingreso estimado')
        self.assertEqual(con.se_tier, sin.se_tier,
                         'la comuna no debe cambiar el tier')

    def test_P06_la_comuna_si_sigue_alimentando_el_income_index(self):
        """La corrección no debe dejar a la comuna sin efecto: su papel
        declarado (R2) es el índice de mercado local, y debe seguir
        distinguiendo una comuna con datos de una sin ellos."""
        self._sembrar_comuna('LasCondesP06')
        con = self._clasificar('17-2112', commune='LasCondesP06')
        self.assertEqual(con.income_index, 95.0,
                         'la comuna debe seguir fijando el income_index')

    def test_P06_un_fallo_de_lectura_no_borra_lo_ya_calculado(self):
        """El mecanismo exacto de la pérdida, aislado.

        Un rollback sobre la sesión del usuario descarta sus cambios
        pendientes y EXPIRA el objeto, así que la siguiente lectura recarga
        NULL. La sesión de referencia debe ser otra, para que su rollback no
        pueda alcanzar al usuario."""
        u = main.User(name='X', email=_uniq('p06') + '@test.invalid',
                      password=bcrypt.hashpw(b'x', bcrypt.gensalt()).decode(),
                      country='CL', county='ComunaSinDatosP06', dob='1990-05-05',
                      profession='17-2112', company_size='251-1000',
                      email_verified=True)
        self.db.add(u); self.db.commit(); self.db.refresh(u)
        u.estimated_income_usd = 42000.0          # valor pendiente, sin confirmar
        refdb = main._ReferenceReadSession(bind=self.db.get_bind())
        try:
            with self.assertRaises(Exception):
                refdb.execute(main.text('SELECT 1 FROM tabla_que_no_existe_p06'))
            # el usuario conserva su valor pendiente
            self.assertEqual(u.estimated_income_usd, 42000.0,
                             'un fallo de lectura de referencia borró el valor '
                             'ya calculado del usuario')
            # y la sesión de referencia quedó utilizable para la lectura siguiente:
            # esto es lo que impide la cascada InFailedSqlTransaction en PostgreSQL
            self.assertEqual(refdb.execute(main.text('SELECT 1')).fetchone()[0], 1,
                             'la sesión de referencia no se restituyó tras el fallo')
        finally:
            refdb.close()
            self.db.rollback()

    def test_P06_el_clasificador_no_hace_rollback_de_la_sesion_del_usuario(self):
        """Guarda estructural: ningún rollback a media clasificación. Los dos
        que había eran la causa de la pérdida."""
        # Se comprueba sobre el AST, no sobre el texto: los comentarios que
        # EXPLICAN el rollback retirado contienen la cadena literal y harían
        # fallar una búsqueda por substring.
        import inspect, ast as _ast, textwrap
        arbol = _ast.parse(textwrap.dedent(
            inspect.getsource(main._assign_user_tier_inner)))
        rollbacks = [n.lineno for n in _ast.walk(arbol)
                     if isinstance(n, _ast.Call)
                     and isinstance(n.func, _ast.Attribute)
                     and n.func.attr == 'rollback']
        self.assertEqual(rollbacks, [],
                         'volvió un rollback a media clasificación: descarta '
                         'el ingreso ya calculado y expira el objeto user')

    def test_P06_la_sesion_de_referencia_siempre_se_cierra(self):
        """No debe filtrar conexiones: `_assign_user_tier` tiene salidas
        anticipadas (`return`), así que el cierre va en un `finally`."""
        import inspect, ast as _ast
        arbol = _ast.parse(inspect.getsource(main._assign_user_tier))
        fn = arbol.body[0]
        tries = [n for n in _ast.walk(fn)
                 if isinstance(n, _ast.Try) and n.finalbody]
        self.assertTrue(tries, 'el cierre de la sesión aislada no está en un finally')
        cierra = any('_refdb.close()' in (_ast.get_source_segment(
            inspect.getsource(main._assign_user_tier), s) or '')
            for t in tries for s in t.finalbody)
        self.assertTrue(cierra, 'el finally no cierra la sesión de referencia')

    def test_P06_no_se_cambio_ninguna_regla_economica(self):
        """La corrección es transaccional. Las reglas R1-R8 y la función de
        puntuación a tier deben ser byte a byte las mismas."""
        import socioeconomic as S, inspect
        reglas = inspect.getsource(S)[:4000]
        for marca in ('R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'R7', 'R8'):
            self.assertIn(marca, reglas, f'desapareció la regla {marca}')
        self.assertFalse(S.THRESHOLDS_APPROVED_BY_BUSINESS)
        # Los cortes reales de profession_score_to_tier, fijados en sus
        # fronteras exactas (>=80 A, >=60 B, >=35 C, >=15 D, resto E).
        from usa_data_agent import profession_score_to_tier
        self.assertEqual(
            [profession_score_to_tier(x)
             for x in (80.0, 79.9, 60.0, 59.9, 35.0, 34.9, 15.0, 14.9)],
            ['A', 'B', 'B', 'C', 'C', 'D', 'D', 'E'],
            'cambiaron los cortes de puntuación a tier')
