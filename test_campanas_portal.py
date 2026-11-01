"""test_campanas_portal.py — CAMPAÑAS desde la perspectiva del anunciante.

Lo que NINGUNA prueba de API detectaba: que los formularios y botones del
portal llamen a rutas que existen, con el método correcto, con la cabecera de
autorización cuando hace falta, y con los campos que el backend exige.

Dos defectos reales se encontraron así, y estas pruebas los fijan:

  1. El alta del portal llamaba a `/auth/register`, que crea un usuario con
     rol 'voter' y SIN MarketerProfile. Reproducido de punta a punta: el
     anunciante se daba de alta, verificaba su correo y al crear su primera
     campaña recibía 403 'Marketer role required'. Ningún anunciante nuevo
     podía usar CAMPAÑAS desde la interfaz.
  2. El POST de creación de campaña no enviaba la cabecera de autorización,
     mientras la rama de EDICIÓN sí la enviaba. La ruta exige
     `get_verified_user`, así que crear campaña fallaba siempre con 403.

El recorrido se ejecuta con los payloads EXACTOS que construye el portal,
extraídos del propio HTML cuando es posible, para que la prueba no pueda
pasar con un payload inventado por mí que el portal nunca enviaría.

Datos ficticios: dominio .invalid. Ningún pago real.
"""
import json
import os
import re
import tempfile
import unittest
import uuid

_TMP = tempfile.mkdtemp(prefix='prefy_camp_')
os.environ['DATABASE_URL'] = f'sqlite:///{os.path.join(_TMP, "camp.db")}'
os.environ.setdefault('ADMIN_SECRET', 'camp-solo-local')
os.environ.setdefault('JWT_SECRET', 'camp-solo-local')
os.environ.pop('ADMIN_SECRET_CANARY', None)

import bcrypt                                    # noqa: E402
from fastapi.testclient import TestClient        # noqa: E402

import main                                      # noqa: E402

ADMIN = os.environ['ADMIN_SECRET']
PORTAL = open('marketer_portal.html', encoding='utf-8').read()


def _ip():
    _ip.n = getattr(_ip, 'n', 0) + 1
    return {'X-Forwarded-For': f'203.0.113.{_ip.n % 250 + 1}'}


def _uniq(p):
    return f'{p}-{uuid.uuid4().hex[:10]}'


# ═══════════════════════════════════════════════════════════════════════
# P. EL PORTAL CONTRA EL BACKEND — desajustes que la API no revela
# ═══════════════════════════════════════════════════════════════════════

class TestP_PortalContraBackend(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.rutas = {}
        for r in main.app.routes:
            if hasattr(r, 'path') and hasattr(r, 'methods'):
                cls.rutas.setdefault(r.path, set()).update(r.methods)
        # qué dependencia de usuario exige cada ruta, leída del código real
        import ast
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
        cls.llamadas = cls._llamadas_del_portal()

    @staticmethod
    def _llamadas_del_portal():
        """(metodo, ruta_normalizada, envia_token) por cada fetch del portal."""
        out = []
        for m in re.finditer(r"fetch\(\s*[`'\"]([^`'\"]+)", PORTAL):
            url = m.group(1)
            cola = PORTAL[m.end():m.end() + 400]
            met = re.search(r"method\s*:\s*['\"](\w+)", cola)
            met = met.group(1).upper() if met else 'GET'
            # el prefijo PRIMERO: si no, ${API} se convierte en X
            p = url.replace('${API}', '')
            p = re.sub(r'\$\{[^}]*\}', 'X', p).split('?')[0]
            if not p.startswith('/'):
                p = '/' + p
            out.append((met, p, 'Authorization' in cola))
        return out

    def _plantilla(self, p):
        for real in self.rutas:
            if re.match('^' + re.sub(r'\{[^}]+\}', '[^/]+', real) + '$', p):
                return real
        return None

    def test_P1_el_portal_hace_llamadas(self):
        self.assertGreater(len(self.llamadas), 15,
                           f'solo se detectaron {len(self.llamadas)} llamadas: '
                           f'revisar el extractor antes de creer el resultado')

    def test_P2_cada_llamada_del_portal_apunta_a_una_ruta_real(self):
        """Una ruta inexistente es un botón que no hace nada. Ya no hay
        exclusiones: el recuadro de verificación, que era la única, pasó a
        usar la ruta canónica (ver test_portales_y_verificacion, T6-T7)."""
        roto = []
        for met, p, _ in sorted(set(self.llamadas)):
            t = self._plantilla(p)
            if t is None:
                roto.append(f'{met} {p} -> la ruta no existe')
            elif met not in self.rutas[t]:
                roto.append(f'{met} {p} -> solo acepta '
                            f'{sorted(self.rutas[t] - {"HEAD", "OPTIONS"})}')
        self.assertEqual(roto, [], '\n'.join(roto))

    def test_P3_el_verificador_de_voto_del_portal_quedo_conectado(self):
        """Antes esta prueba fijaba el defecto como conocido y pedia
        retirarse si cambiaba el comportamiento. Se corrigio: el recuadro
        llamaba a GET /verify/{codigo}, que no existe, y ahora usa la ruta
        canonica POST /debates/{id}/verify, la misma que usa el portal del
        votante. El detalle esta en test_portales_y_verificacion (T6, T7).
        """
        self.assertNotIn('${API}/verify/${vcode}', PORTAL,
                         'volvio la ruta inexistente')
        self.assertIsNone(self._plantilla('/verify/X'),
                          'si esa ruta existe ahora, revisar que no afirme '
                          'anclaje cuando la cadena no esta en vivo')

    def test_P4_toda_llamada_que_exige_sesion_envia_el_token(self):
        """EL DEFECTO 2. La creación de campaña no enviaba la cabecera, y la
        ruta exige `get_verified_user`: crear campaña fallaba siempre."""
        faltan = []
        for met, p, envia in sorted(set(self.llamadas)):
            t = self._plantilla(p)
            if t is None:
                continue
            dep = self.exige.get((met, t))
            if dep in ('get_verified_user', 'get_current_user') and not envia:
                faltan.append(f'{met} {p} exige {dep} y no envía Authorization')
        self.assertEqual(faltan, [], '\n'.join(faltan))

    def test_P5_el_alta_del_portal_usa_la_ruta_de_ANUNCIANTE(self):
        """EL DEFECTO 1. `/auth/register` crea rol 'voter' sin
        MarketerProfile; `/marketer/register` crea el anunciante aprobado."""
        self.assertIn('/marketer/register', PORTAL,
                      'el alta del portal no llama a la ruta de anunciante')
        bloque = PORTAL[PORTAL.index('async function doRegister'):]
        bloque = bloque[:bloque.index('async function') + 1] if 'async function' in bloque[20:] else bloque[:2000]
        self.assertNotIn('/auth/register', bloque,
                         'el alta volvió a /auth/register, que no crea un '
                         'anunciante')

    def test_P6_las_categorias_del_formulario_son_las_del_servidor(self):
        """La lista del formulario está duplicada en el HTML por necesidad
        (ninguna ruta la publica). Esta prueba falla si las dos se separan,
        que es la única forma de que la duplicación sea segura."""
        bloque = PORTAL[PORTAL.index('id="reg-category"'):]
        bloque = bloque[:bloque.index('</select>')]
        en_html = set(re.findall(r'value="([a-z_]+)"', bloque)) - {''}
        self.assertEqual(en_html, set(main.MARKETER_BUSINESS_CATEGORIES),
                         f'el formulario y el servidor divergen.\n'
                         f'  solo en el HTML: {en_html - set(main.MARKETER_BUSINESS_CATEGORIES)}\n'
                         f'  solo en el servidor: {set(main.MARKETER_BUSINESS_CATEGORIES) - en_html}')

    def test_P7_ninguna_categoria_prohibida_aparece_en_el_formulario(self):
        bloque = PORTAL[PORTAL.index('id="reg-category"'):]
        bloque = bloque[:bloque.index('</select>')]
        for mala in main.MARKETER_PROHIBITED_CATEGORIES:
            self.assertNotIn(f'value="{mala}"', bloque,
                             f'el formulario ofrece una categoría prohibida: {mala}')


# ═══════════════════════════════════════════════════════════════════════
# Q. EL RECORRIDO COMPLETO DEL ANUNCIANTE
# ═══════════════════════════════════════════════════════════════════════

class TestQ_RecorridoDelAnunciante(unittest.TestCase):
    """De cero a campaña entregada y medida, con los payloads del portal."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        cls.db = main.SessionLocal()
        for commune, tier, idx in (('Las Condes', 'A', 95.0), ('Conchalí', 'C', 45.0)):
            if not cls.db.query(main.CommuneMarketData).filter(
                    main.CommuneMarketData.commune == commune).first():
                cls.db.add(main.CommuneMarketData(
                    country='CL', commune=commune, se_tier=tier,
                    income_index=idx, price_m2_avg=idx, cpm_usd=6.0))
        cls.db.commit()
        # el alta real, por la MISMA ruta y con los MISMOS campos que el portal
        cls.email = _uniq('anunciante') + '@test.invalid'
        r = cls.client.post('/marketer/register', json={
            'name': 'Marca Ficticia', 'email': cls.email, 'password': 'ClaveP123!',
            'country': 'CL', 'company_name': 'Marca Ficticia',
            'business_category': 'retail_comercio', 'lang': 'es'}, headers=_ip())
        assert r.status_code in (200, 201), f'el alta falló: {r.status_code} {r.text[:300]}'
        cls.u = cls.db.query(main.User).filter(
            main.func.lower(main.User.email) == cls.email.lower()).first()
        # verificar el correo: en producción llega (comprobado), aquí se marca
        cls.db.execute(main.text('UPDATE users SET email_verified=1 WHERE id=:i'),
                       {'i': cls.u.id})
        cls.db.commit()

        # OPCION A — el recorrido real del anunciante tiene ahora un paso mas.
        # El alta de una ORGANIZACION nace 'pending': ya no se autoaprueba.
        # Para operar campanas hace falta que la acredite un supervisor ya
        # acreditado o, en el arranque -cuando la empresa todavia no tiene
        # ninguno-, un administrador por la ruta que ya existia.
        #
        # Se hace aqui, por esa MISMA ruta, para que el resto de la suite
        # pruebe lo que de verdad le ocurre a un anunciante acreditado. Que
        # sin acreditar la puerta este cerrada se comprueba aparte, en
        # test_representacion_empresarial.
        _p = cls.db.query(main.MarketerProfile).filter(
            main.MarketerProfile.user_id == cls.u.id).first()
        assert _p is not None, 'el alta no creo perfil de anunciante'
        assert _p.status == 'pending', (
            f'el alta deberia nacer pendiente y nacio {_p.status!r}')
        _acred = cls.client.post(
            f'/admin/marketer/{cls.u.id}/status?secret={ADMIN}&status=approved',
            headers=_ip())
        assert _acred.status_code == 200, (
            f'la acreditacion fallo: {_acred.status_code} {_acred.text[:200]}')
        cls.db.expire_all()
        cls.token = main.make_token(cls.u.id, 'marketer')

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def auth(self):
        h = _ip()
        h['Authorization'] = 'Bearer ' + self.token
        return h

    def _cuerpo_campana(self, **cambios):
        """El cuerpo EXACTO que arma el portal en createCampaign()."""
        cuerpo = {
            'advertiser_email': self.email, 'advertiser_name': 'Marca Ficticia',
            'campaign_title': _uniq('Campana'), 'budget_clp': 95000,
            'ad_type': 'banner', 'target_country': 'CL',
            'target_communes': 'Las Condes', 'target_gender': 'all',
            'target_age_min': 18, 'target_age_max': 99,
            'target_age_ranges': '18-99', 'target_age_weights': '',
            'target_company_sizes': '', 'target_se_tiers': 'A,B,C,D',
            'min_per_capita_usd': 0, 'target_categories': '',
            'excluded_categories': '', 'blocked_competitors': '',
            'logo_url': '', 'ad_image_url': '', 'video_url': '',
            'start_date': '2026-11-05T00:00:00',
            'end_date': '2026-12-05T23:59:59',
            'ad_copy': 'Anuncio ficticio', 'link_url': 'https://example.invalid',
        }
        cuerpo.update(cambios)
        return cuerpo

    def _votante(self, commune='Las Condes'):
        em = _uniq('v') + '@test.invalid'
        r = self.client.post('/voter/register', json={
            'name': 'Votante', 'email': em, 'password': 'ClaveV123!',
            'country': 'CL', 'profession': 'Ingeniero Industrial',
            'cargo': 'empleado', 'commune': commune, 'gender': 'M',
            'dob': '1990-05-05',
            'national_id': f'99{uuid.uuid4().int % 10**6:06d}-9'}, headers=_ip())
        self.assertIn(r.status_code, (200, 201), r.text[:200])
        u = self.db.query(main.User).filter(
            main.func.lower(main.User.email) == em.lower()).first()
        self.db.execute(main.text('UPDATE users SET email_verified=1 WHERE id=:i'),
                        {'i': u.id})
        self.db.commit()
        h = _ip()
        h['Authorization'] = 'Bearer ' + main.make_token(u.id, 'voter')
        return u, h

    # ── 1. acceso ────────────────────────────────────────────────────

    def test_Q1_el_alta_crea_un_anunciante_con_perfil_aprobado(self):
        self.assertEqual(self.u.role, 'marketer',
                         f'el alta dejó el rol en {self.u.role!r}')
        perfil = self.db.query(main.MarketerProfile).filter(
            main.MarketerProfile.user_id == self.u.id).first()
        self.assertIsNotNone(perfil, 'el alta no creó MarketerProfile')
        self.assertEqual(perfil.status, 'approved')

    def test_Q2_el_acceso_funciona_con_la_ruta_del_portal(self):
        r = self.client.post('/marketer/login',
                             json={'email': self.email, 'password': 'ClaveP123!'},
                             headers=_ip())
        self.assertEqual(r.status_code, 200, r.text[:300])
        self.assertTrue(r.json().get('token'), 'el acceso no devolvió token')

    def test_Q3_una_clave_equivocada_no_entra(self):
        r = self.client.post('/marketer/login',
                             json={'email': self.email, 'password': 'incorrecta'},
                             headers=_ip())
        self.assertNotEqual(r.status_code, 200)

    # ── 2. crear, editar, pausar ─────────────────────────────────────

    def test_Q4_crear_campana_con_el_payload_del_portal(self):
        r = self.client.post('/marketer/campaigns',
                             json=self._cuerpo_campana(), headers=self.auth())
        self.assertEqual(r.status_code, 200, r.text[:400])
        d = r.json()
        self.assertTrue(d.get('campaign_id'), f'no devolvió id: {d}')
        c = self.db.query(main.AdCampaign).filter(
            main.AdCampaign.id == d['campaign_id']).first()
        self.assertEqual(c.target_country, 'CL')
        self.assertEqual(c.budget_clp, 95000)
        self.assertEqual(c.target_communes, 'Las Condes')

    def test_Q5_el_anunciante_ve_sus_campanas(self):
        self.client.post('/marketer/campaigns', json=self._cuerpo_campana(),
                         headers=self.auth())
        r = self.client.get(f'/advertiser/campaigns?email={self.email}',
                            headers=self.auth())
        self.assertEqual(r.status_code, 200, r.text[:300])
        self.assertIn('Marca Ficticia', r.text)

    def test_Q6_editar_y_pausar_su_propia_campana(self):
        cr = self.client.post('/marketer/campaigns', json=self._cuerpo_campana(),
                              headers=self.auth())
        cid = cr.json()['campaign_id']
        r = self.client.patch(f'/advertiser/campaigns/{cid}',
                              json=self._cuerpo_campana(budget_clp=120000),
                              headers=self.auth())
        self.assertEqual(r.status_code, 200, r.text[:300])
        self.db.expire_all()
        c = self.db.query(main.AdCampaign).filter(main.AdCampaign.id == cid).first()
        self.assertEqual(c.budget_clp, 120000, 'la edición no se guardó')
        # La campana nace pausada, asi que primero se enciende: lo que se
        # comprueba aqui es que la pausa apaga.
        self._activar(cid)
        r2 = self.client.put(f'/advertiser/campaigns/{cid}/pause',
                             headers=self.auth())
        self.assertEqual(r2.status_code, 200, r2.text[:300])
        self.db.expire_all()
        c = self.db.query(main.AdCampaign).filter(main.AdCampaign.id == cid).first()
        self.assertFalse(c.is_active, 'la pausa no desactivó la campaña')

    def _activar(self, cid):
        """Enciende una campana recien creada.

        Desde el cambio de noviembre de 2026 una campana NACE PAUSADA:
        antes quedaba servible en el instante de crearla. Lo que estas
        pruebas comprueban -entrega, cobro, segmentacion- solo ocurre con
        la campana encendida, asi que ahora la encienden, igual que tiene
        que hacerlo el anunciante.
        """
        self.db.expire_all()
        c = self.db.query(main.AdCampaign).filter(main.AdCampaign.id == cid).first()
        c.is_active = True
        self.db.commit()
        return cid

    def test_Q6b_una_campana_nueva_NACE_PAUSADA(self):
        """Antes quedaba servible en el instante de crearla: el anunciante
        pulsaba Crear y ya se estaba publicando, sin encenderla nadie."""
        for ruta in ('/marketer/campaigns', '/advertiser/campaigns'):
            cr = self.client.post(ruta, json=self._cuerpo_campana(),
                                  headers=self.auth())
            self.assertEqual(cr.status_code, 200, f'{ruta}: {cr.text[:200]}')
            cid = cr.json()['campaign_id']
            self.db.expire_all()
            c = self.db.query(main.AdCampaign).filter(
                main.AdCampaign.id == cid).first()
            self.assertFalse(c.is_active,
                             f'{ruta} dejo la campana activa al crearla')

    def test_Q6c_solo_el_dueno_la_activa_expresamente(self):
        cr = self.client.post('/marketer/campaigns', json=self._cuerpo_campana(),
                              headers=self.auth())
        cid = cr.json()['campaign_id']
        sin_sesion = self.client.put(f'/advertiser/campaigns/{cid}/pause')
        self.assertIn(sin_sesion.status_code, (401, 403),
                      'un extrano no puede encender la campana')
        self.db.expire_all()
        c = self.db.query(main.AdCampaign).filter(main.AdCampaign.id == cid).first()
        self.assertFalse(c.is_active, 'sigue pausada')
        propia = self.client.put(f'/advertiser/campaigns/{cid}/pause',
                                 headers=self.auth())
        self.assertEqual(propia.status_code, 200, propia.text[:200])
        self.assertTrue(propia.json()['is_active'],
                        'el dueno si puede activarla')

    def test_Q6d_el_saldo_DEMO_se_ve_y_no_se_mezcla_con_el_real(self):
        """El portal mostraba solo el saldo real, asi que tras recibir
        creditos de demostracion la pantalla decia 0."""
        # El importe lo fija el servidor, no el cuerpo de la peticion.
        g = self.client.post('/payments/demo-credits', headers=self.auth())
        self.assertEqual(g.status_code, 200, g.text[:200])
        concedido = g.json()['demo_balance']
        self.assertGreater(concedido, 0)
        r = self.client.get('/payments/balance', headers=self.auth())
        self.assertEqual(r.status_code, 200, r.text[:200])
        d = r.json()
        self.assertIn('demo_credits', d, 'el saldo DEMO no se expone')
        self.assertEqual(d['demo_credits'], concedido, d)
        self.assertEqual(d['balance_credits'], 0.0,
                         'los creditos DEMO no pueden sumarse al saldo real')

    def test_Q7_un_anunciante_ajeno_no_toca_la_campana(self):
        cr = self.client.post('/marketer/campaigns', json=self._cuerpo_campana(),
                              headers=self.auth())
        cid = cr.json()['campaign_id']
        otro = main.User(name='Otro', email=_uniq('o') + '@test.invalid',
                         password=bcrypt.hashpw(b'x', bcrypt.gensalt()).decode(),
                         country='CL', role='marketer', email_verified=True)
        self.db.add(otro); self.db.commit(); self.db.refresh(otro)
        self.db.add(main.MarketerProfile(user_id=otro.id, company_name='Otra',
                                         status='approved'))
        self.db.commit()
        h = _ip(); h['Authorization'] = 'Bearer ' + main.make_token(otro.id, 'marketer')
        for met, ruta in (('PATCH', f'/advertiser/campaigns/{cid}'),
                          ('PUT', f'/advertiser/campaigns/{cid}/pause'),
                          ('GET', f'/marketer/campaigns/{cid}/metrics')):
            r = self.client.request(met, ruta,
                                    json=self._cuerpo_campana() if met == 'PATCH' else None,
                                    headers=h)
            self.assertIn(r.status_code, (403, 404),
                          f'{met} {ruta} lo permitió a un ajeno: {r.status_code}')

    # ── 3. segmentación efectiva ─────────────────────────────────────

    def test_Q8_la_segmentacion_elige_al_publico_correcto(self):
        marca = _uniq('MarcaSeg')
        _cr = self.client.post('/marketer/campaigns',
                               json=self._cuerpo_campana(advertiser_name=marca,
                                                         target_communes='Las Condes'),
                               headers=self.auth())
        self._activar(_cr.json()['campaign_id'])
        _, cab_ok = self._votante(commune='Las Condes')
        _, cab_no = self._votante(commune='Conchalí')
        dentro = [a.get('brand') for a in
                  self.client.get('/ads/featured', headers=cab_ok).json().get('ads', [])]
        fuera = [a.get('brand') for a in
                 self.client.get('/ads/featured', headers=cab_no).json().get('ads', [])]
        self.assertIn(marca, dentro, f'no llegó a quien cumple: {dentro}')
        self.assertNotIn(marca, fuera, 'llegó a quien NO cumple el objetivo')

    # ── 4. presupuesto, entrega, impresiones, contabilidad ───────────

    def test_Q9_presupuesto_entrega_impresion_y_gasto(self):
        """El ciclo comercial completo con dinero de clase DEMO: acreditar,
        asignar a la campaña, entregar, cobrar y medir."""
        cr = self.client.post('/marketer/campaigns', json=self._cuerpo_campana(),
                              headers=self.auth())
        cid = self._activar(cr.json()['campaign_id'])
        c = self.db.query(main.AdCampaign).filter(main.AdCampaign.id == cid).first()
        c.value_class = main._ledger.DEMO
        self.db.commit()

        f = main._ledger_fund(self.db, main._ledger.DEMO, self.u.id, 20.0,
                              method='camp_demo', idempotency_key=_uniq('f'),
                              description='Fondeo ficticio')
        self.assertTrue(f['ok'], f)
        res = main._ledger_reserve(self.db, c, self.u.id, 10.0,
                                   idempotency_key=_uniq('r'))
        self.assertTrue(res['ok'], res)
        self.db.refresh(c)
        self.assertEqual(c.ledger_status, 'LEDGER_MANAGED')

        _, cab = self._votante()
        clave = _uniq('imp')
        r = self.client.post(f'/ads/impression?campaign_id={cid}&debate_id=0'
                             f'&idempotency_key={clave}', headers=cab)
        self.assertEqual(r.status_code, 200, r.text[:300])
        self.assertTrue(r.json().get('ok'), r.text[:300])

        # el reintento con la MISMA clave no cobra dos veces
        r2 = self.client.post(f'/ads/impression?campaign_id={cid}&debate_id=0'
                              f'&idempotency_key={clave}', headers=cab)
        self.assertTrue(r2.json().get('idempotent'), r2.text[:300])

        # impresiones y ledger concilian (CHANGE-006)
        posteado = float(self.db.query(
            main.func.sum(main.AdImpressionLog.cost_credits_posted)).filter(
            main.AdImpressionLog.campaign_id == cid).scalar() or 0)
        self.assertGreater(posteado, 0,
                           'la impresión cobrada no anotó el importe asentado')

        # métricas visibles para el anunciante
        m = self.client.get(f'/marketer/campaigns/{cid}/metrics', headers=self.auth())
        self.assertEqual(m.status_code, 200, m.text[:300])
        datos = m.json()
        contador = next((datos[k] for k in ('impressions', 'impressions_count',
                                            'total_impressions', 'views')
                         if isinstance(datos.get(k), (int, float))), None)
        self.assertEqual(contador, 1,
                         f'las métricas no reflejan la impresión: {datos}')

    def test_Q10_al_agotarse_el_presupuesto_la_campana_se_detiene(self):
        cr = self.client.post('/marketer/campaigns', json=self._cuerpo_campana(),
                              headers=self.auth())
        cid = self._activar(cr.json()['campaign_id'])
        c = self.db.query(main.AdCampaign).filter(main.AdCampaign.id == cid).first()
        c.value_class = main._ledger.DEMO
        self.db.commit()
        coste = main._ledger.round_amount(main.COST_PER_VIEW / main.USD_TO_CLP)
        main._ledger_fund(self.db, main._ledger.DEMO, self.u.id, coste,
                          method='camp_demo', idempotency_key=_uniq('f'),
                          description='Fondeo minimo')
        main._ledger_reserve(self.db, c, self.u.id, coste,
                             idempotency_key=_uniq('r'))
        _, cab = self._votante()
        r1 = self.client.post(f'/ads/impression?campaign_id={cid}&debate_id=0'
                              f'&idempotency_key={_uniq("i")}', headers=cab)
        self.assertTrue(r1.json().get('ok'), r1.text[:300])
        r2 = self.client.post(f'/ads/impression?campaign_id={cid}&debate_id=0'
                              f'&idempotency_key={_uniq("i")}', headers=cab)
        self.assertTrue(r2.json().get('budget_exhausted'), r2.text[:300])
        self.db.expire_all()
        c = self.db.query(main.AdCampaign).filter(main.AdCampaign.id == cid).first()
        self.assertFalse(c.is_active, 'la campaña sin saldo siguió activa')

    # ── 5. estimación, saldo y medios de pago ────────────────────────

    def test_Q11_la_estimacion_de_alcance_responde(self):
        r = self.client.post('/marketer/estimate', json={
            'advertiser_email': self.email, 'advertiser_name': 'Marca Ficticia',
            'campaign_title': 'Estimacion', 'budget_clp': 95000,
            'target_country': 'CL', 'target_communes': 'Las Condes',
            'start_date': '2026-11-05', 'end_date': '2026-12-05'},
            headers=self.auth())
        self.assertEqual(r.status_code, 200, r.text[:300])

    def test_Q12_saldo_paquetes_e_historial_responden(self):
        for ruta in ('/payments/balance', '/payments/history'):
            r = self.client.get(ruta, headers=self.auth())
            self.assertEqual(r.status_code, 200, f'{ruta}: {r.text[:200]}')
        r = self.client.get('/payments/packages', headers=_ip())
        self.assertEqual(r.status_code, 200, r.text[:200])

    def test_Q13_el_webhook_de_pago_exige_firma(self):
        """No se ejecuta ningún pago. Lo que se comprueba es que una carga
        sin firma válida NO acredita saldo, que es lo que lo protege."""
        r = self.client.post('/payments/stripe/webhook',
                             content=json.dumps({'type': 'checkout.session.completed'}),
                             headers={**_ip(), 'Content-Type': 'application/json'})
        self.assertNotEqual(r.status_code, 200)


# ═══════════════════════════════════════════════════════════════════════
# R. LO QUE NO SE PUEDE COMPROBAR AQUÍ — declarado
# ═══════════════════════════════════════════════════════════════════════

class TestR_LimitesDeCampanas(unittest.TestCase):

    def test_R1_los_cobros_reales_no_se_ejercitan(self):
        """Stripe y cripto solo se comprueban en su rechazo: no hay
        credenciales y no se ejecuta ningún cargo. Un cobro real de punta a
        punta queda NO COMPROBADO."""
        self.assertIsNone(os.environ.get('STRIPE_SECRET_KEY'))

    def test_R2_el_portal_es_responsive_en_movil(self):
        """Las dos apps son un envoltorio WebView del portal, así que el
        viewport y las reglas móviles son lo que decide si se puede usar
        desde el teléfono. El comportamiento en un dispositivo físico queda
        NO COMPROBADO."""
        self.assertIn('name="viewport"', PORTAL,
                      'el portal no declara viewport: no sería usable en móvil')
        self.assertRegex(PORTAL, r'@media[^{]*max-width',
                         'el portal no tiene ninguna regla responsive')


if __name__ == '__main__':
    unittest.main()
