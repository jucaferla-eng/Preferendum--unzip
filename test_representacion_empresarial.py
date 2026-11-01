"""test_representacion_empresarial.py — OPCIÓN A.

Una organización (empresa, organismo público, ONG) no puede crear consultas
ni operar campañas sin un perfil APROBADO por un supervisor previamente
acreditado. Un ciudadano conserva su procedimiento intacto.

No construye otro sistema de registro: comprueba que los mecanismos que ya
existían —verificación de dominio, RUT, web, y acreditación por supervisor—
ahora CONDICIONAN el acceso, que es lo que antes no hacían.

Recorridos cubiertos, incluidos los intentos de suplantación:
  X.  El estado inicial del perfil, por tipo de organización
  Y.  Las dos puertas (consultas y campañas) con perfil ausente, pendiente,
      suspendido y aprobado
  Z.  La acreditación del supervisor: real, y los intentos de falsearla
"""
import json
import os
import tempfile
import unittest
import uuid

_TMP = tempfile.mkdtemp(prefix='prefy_repr_')
os.environ['DATABASE_URL'] = f'sqlite:///{os.path.join(_TMP, "repr.db")}'
os.environ.setdefault('ADMIN_SECRET', 'repr-solo-local')
os.environ.setdefault('JWT_SECRET', 'repr-solo-local')
os.environ.pop('ADMIN_SECRET_CANARY', None)

import bcrypt                                    # noqa: E402
from fastapi.testclient import TestClient        # noqa: E402

import main                                      # noqa: E402

ADMIN = os.environ['ADMIN_SECRET']


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

    def auth(self, uid, rol):
        h = _ip()
        h['Authorization'] = 'Bearer ' + main.make_token(uid, rol)
        return h

    def _usuario(self, rol, email=None, selfie=False):
        em = email or (_uniq('u') + '@empresa-ficticia.invalid')
        u = main.User(name='Representante', email=em, role=rol,
                      password=bcrypt.hashpw(b'x', bcrypt.gensalt()).decode(),
                      country='CL', email_verified=True, selfie_verified=selfie)
        self.db.add(u); self.db.commit(); self.db.refresh(u)
        return u

    def _perfil(self, Modelo, uid, org_type='company', status='pending',
                supervisor=False):
        p = Modelo(user_id=uid, org_type=org_type, status=status,
                   is_supervisor=supervisor, company_name='Empresa Ficticia')
        self.db.add(p); self.db.commit()
        return p

    def _cuerpo_consulta(self):
        return {
            'title': _uniq('Consulta'), 'context': 'Ficticia',
            'options': ['Opción A', 'Opción B'],
            'closes_at': '2027-06-30T23:59:59',
            'creator_type': 'company', 'scope': 'country',
            'scope_country': 'CL',
        }

    def _cuerpo_campana(self, email):
        return {
            'advertiser_email': email, 'advertiser_name': 'Empresa Ficticia',
            'campaign_title': _uniq('Campana'), 'budget_clp': 95000,
            'target_country': 'CL', 'start_date': '2026-11-10T00:00:00',
            'end_date': '2026-12-10T23:59:59',
            'ad_copy': 'Anuncio', 'link_url': 'https://example.invalid',
        }


# ═══════════════════════════════════════════════════════════════════════
# X. ESTADO INICIAL DEL PERFIL, POR TIPO
# ═══════════════════════════════════════════════════════════════════════

class TestX_EstadoInicial(Base):

    def test_X1_una_organizacion_nace_pendiente(self):
        """Empresa, organismo público y ONG: ninguna se autoaprueba."""
        for tipo in ('company', 'public', 'ngo', 'government', 'institution'):
            self.assertEqual(main._estado_inicial_de_perfil(tipo), 'pending',
                             f'{tipo!r} se autoaprobaría')
            self.assertTrue(main._es_organizacion(tipo))

    def test_X2_un_ciudadano_nace_aprobado(self):
        """Regla 7: los ciudadanos conservan su procedimiento."""
        for tipo in ('person', 'PERSON', ' person ', '', None):
            self.assertEqual(main._estado_inicial_de_perfil(tipo), 'approved',
                             f'{tipo!r} quedaría pendiente sin motivo')
            self.assertFalse(main._es_organizacion(tipo))

    def test_X3_la_regla_es_por_exclusion_no_lista_blanca(self):
        """Cualquier tipo futuro queda cubierto sin tocar el código."""
        self.assertTrue(main._es_organizacion('cooperativa-municipal-2030'))
        self.assertEqual(
            main._estado_inicial_de_perfil('cooperativa-municipal-2030'),
            'pending')

    def test_X4_el_alta_real_de_una_empresa_queda_pendiente(self):
        """Por la ruta real, con correo corporativo válido."""
        em = _uniq('rep') + '@empresa-ficticia.invalid'
        r = self.client.post('/organizer/register', json={
            'email': em, 'password': 'ClaveR123!', 'name': 'Representante',
            'org_type': 'company', 'company_name': 'Empresa Ficticia',
            'country': 'CL'}, headers=_ip())
        if r.status_code == 400 and 'mail' in r.text.lower():
            self.skipTest(f'el dominio ficticio no resuelve en este entorno: '
                          f'{r.text[:120]}')
        self.assertIn(r.status_code, (200, 201), r.text[:300])
        u = self.db.query(main.User).filter(
            main.func.lower(main.User.email) == em.lower()).first()
        p = self.db.query(main.OrganizerProfile).filter(
            main.OrganizerProfile.user_id == u.id).first()
        self.assertIsNotNone(p, 'el alta no creó perfil')
        self.assertEqual(p.status, 'pending',
                         'la empresa se autoaprobó al registrarse')

    def test_X5_un_correo_gratuito_no_sirve_para_una_organizacion(self):
        """La verificación de dominio que ya existía, ahora para TODA
        organización y no solo para 'company'."""
        for tipo in ('company', 'public'):
            r = self.client.post('/organizer/register', json={
                'email': _uniq('x') + '@gmail.com', 'password': 'ClaveR123!',
                'name': 'Representante', 'org_type': tipo,
                'company_name': 'Organismo Ficticio', 'country': 'CL'},
                headers=_ip())
            self.assertEqual(r.status_code, 400,
                             f'{tipo}: aceptó un correo gratuito')
            self.assertIn('gratuito', r.text.lower())

    def test_X6_un_ciudadano_puede_usar_correo_gratuito(self):
        """Regla 7: no se le exige representar a ninguna empresa."""
        r = self.client.post('/organizer/register', json={
            'email': _uniq('ciud') + '@gmail.com', 'password': 'ClaveR123!',
            'name': 'Ciudadana', 'org_type': 'person', 'country': 'CL'},
            headers=_ip())
        self.assertIn(r.status_code, (200, 201), r.text[:300])

    def test_X7_un_ciudadano_que_pasa_a_organizacion_NO_se_autoacredita(self):
        """Era el camino más corto para saltarse todo: la rama de usuario
        existente creaba el perfil 'approved' e is_supervisor=True."""
        em = _uniq('prev') + '@empresa-ficticia.invalid'
        u = self._usuario('voter', email=em)
        self.db.execute(main.text(
            'UPDATE users SET password=:p WHERE id=:i'),
            {'p': bcrypt.hashpw(b'ClaveR123!', bcrypt.gensalt()).decode(),
             'i': u.id})
        self.db.commit()
        r = self.client.post('/organizer/register', json={
            'email': em, 'password': 'ClaveR123!', 'name': 'Representante',
            'org_type': 'company', 'company_name': 'Empresa Ficticia',
            'country': 'CL'}, headers=_ip())
        self.assertIn(r.status_code, (200, 201), r.text[:300])
        p = self.db.query(main.OrganizerProfile).filter(
            main.OrganizerProfile.user_id == u.id).first()
        self.assertIsNotNone(p)
        self.assertEqual(p.status, 'pending',
                         'se autoaprobó por la rama de usuario existente')
        self.assertFalse(p.is_supervisor,
                         'se autoacreditó como supervisor, que es justo lo '
                         'que un supervisor o un admin deben decidir')


# ═══════════════════════════════════════════════════════════════════════
# Y. LAS DOS PUERTAS
# ═══════════════════════════════════════════════════════════════════════

class TestY_LasDosPuertas(Base):

    # ── consultas ────────────────────────────────────────────────────

    def test_Y1_sin_perfil_no_se_crean_consultas(self):
        """REGLA 5. Antes `if profile and …` dejaba pasar a quien no tenía
        perfil. En producción había 2 cuentas así."""
        u = self._usuario('organizer')
        r = self.client.post('/organizer/consultations',
                             json=self._cuerpo_consulta(),
                             headers=self.auth(u.id, 'organizer'))
        self.assertEqual(r.status_code, 403, r.text[:300])
        self.assertIn('perfil', r.text.lower())

    def test_Y2_con_perfil_pendiente_no_se_crean_consultas(self):
        u = self._usuario('organizer')
        self._perfil(main.OrganizerProfile, u.id, status='pending')
        r = self.client.post('/organizer/consultations',
                             json=self._cuerpo_consulta(),
                             headers=self.auth(u.id, 'organizer'))
        self.assertEqual(r.status_code, 403, r.text[:300])
        self.assertIn('pendiente', r.text.lower())

    def test_Y3_con_perfil_suspendido_tampoco(self):
        u = self._usuario('organizer')
        self._perfil(main.OrganizerProfile, u.id, status='suspended')
        r = self.client.post('/organizer/consultations',
                             json=self._cuerpo_consulta(),
                             headers=self.auth(u.id, 'organizer'))
        self.assertEqual(r.status_code, 403, r.text[:300])
        self.assertIn('suspendida', r.text.lower())

    def test_Y4_con_perfil_aprobado_SI_se_crean(self):
        """La puerta no puede quedar cerrada para quien sí está acreditado."""
        u = self._usuario('organizer')
        self._perfil(main.OrganizerProfile, u.id, status='approved')
        r = self.client.post('/organizer/consultations',
                             json=self._cuerpo_consulta(),
                             headers=self.auth(u.id, 'organizer'))
        self.assertEqual(r.status_code, 200, r.text[:400])

    def test_Y5_un_ciudadano_aprobado_sigue_creando_consultas(self):
        """Regla 7: su procedimiento no cambia."""
        u = self._usuario('organizer')
        self._perfil(main.OrganizerProfile, u.id, org_type='person',
                     status='approved')
        r = self.client.post('/organizer/consultations',
                             json=self._cuerpo_consulta(),
                             headers=self.auth(u.id, 'organizer'))
        self.assertEqual(r.status_code, 200, r.text[:400])

    def test_Y6_las_cuentas_sin_acreditar_SIGUEN_viendo_su_informacion(self):
        """REGLA 9. La puerta es solo para CREAR. Leer y listar lo que ya
        existe no puede romperse."""
        u = self._usuario('organizer')
        self._perfil(main.OrganizerProfile, u.id, status='pending')
        cab = self.auth(u.id, 'organizer')
        for ruta in ('/organizer/consultations', '/organizer/status',
                     '/organizers/me/debates'):
            r = self.client.get(ruta, headers=cab)
            self.assertNotEqual(r.status_code, 403,
                                f'{ruta} dejó sin acceso a su información')
            self.assertLess(r.status_code, 500, f'{ruta}: {r.text[:200]}')

    # ── campañas ─────────────────────────────────────────────────────

    def test_Y7_sin_perfil_no_se_operan_campanas(self):
        u = self._usuario('marketer')
        r = self.client.post('/marketer/campaigns',
                             json=self._cuerpo_campana(u.email),
                             headers=self.auth(u.id, 'marketer'))
        self.assertEqual(r.status_code, 403, r.text[:300])

    def test_Y8_con_perfil_pendiente_no_se_operan_campanas(self):
        u = self._usuario('marketer')
        self._perfil(main.MarketerProfile, u.id, status='pending')
        r = self.client.post('/marketer/campaigns',
                             json=self._cuerpo_campana(u.email),
                             headers=self.auth(u.id, 'marketer'))
        self.assertEqual(r.status_code, 403, r.text[:300])
        self.assertIn('pendiente', r.text.lower())

    def test_Y9_con_perfil_aprobado_SI_se_crea_la_campana(self):
        u = self._usuario('marketer')
        self._perfil(main.MarketerProfile, u.id, status='approved')
        r = self.client.post('/marketer/campaigns',
                             json=self._cuerpo_campana(u.email),
                             headers=self.auth(u.id, 'marketer'))
        self.assertEqual(r.status_code, 200, r.text[:400])

    def test_Y10_una_campana_ACTIVA_no_se_interrumpe_por_sorpresa(self):
        """REGLA 9. La entrega de una campaña ya activa no pasa por la
        puerta de autoridad: endurecer el alta no puede apagar lo que está
        corriendo."""
        u = self._usuario('marketer')
        self._perfil(main.MarketerProfile, u.id, status='approved')
        cr = self.client.post('/marketer/campaigns',
                              json=self._cuerpo_campana(u.email),
                              headers=self.auth(u.id, 'marketer'))
        self.assertEqual(cr.status_code, 200, cr.text[:300])
        cid = cr.json()['campaign_id']
        # el perfil pasa a pendiente DESPUES de tener la campaña activa
        p = self.db.query(main.MarketerProfile).filter(
            main.MarketerProfile.user_id == u.id).first()
        p.status = 'pending'
        self.db.commit()
        c = self.db.query(main.AdCampaign).filter(
            main.AdCampaign.id == cid).first()
        self.db.refresh(c)
        self.assertTrue(c.is_active,
                        'la campaña activa se apagó al cambiar el perfil')
        # y el anunciante sigue viendo sus datos
        r = self.client.get(f'/advertiser/campaigns?email={u.email}',
                            headers=self.auth(u.id, 'marketer'))
        self.assertNotEqual(r.status_code, 500, r.text[:200])


# ═══════════════════════════════════════════════════════════════════════
# Z. LA ACREDITACIÓN DEL SUPERVISOR, Y LOS INTENTOS DE FALSEARLA
# ═══════════════════════════════════════════════════════════════════════

class TestZ_AcreditacionDelSupervisor(Base):

    def _solicitud(self, Modelo, empleado_id, sup_email):
        tok = uuid.uuid4().hex[:32]
        self.db.add(Modelo(
            employee_user_id=empleado_id, employee_name='Empleado Ficticio',
            employee_email=f'emp-{empleado_id}@empresa-ficticia.invalid',
            supervisor_email=sup_email, token=tok))
        self.db.commit()
        return tok

    def test_Z1_un_supervisor_SIN_perfil_no_puede_acreditar(self):
        """REGLA 2/3: indicar un correo de jefe no acredita nada."""
        emp = self._usuario('organizer')
        self._perfil(main.OrganizerProfile, emp.id, status='pending')
        jefe = self._usuario('organizer', selfie=True)   # sin perfil
        tok = self._solicitud(main.AuthorizationRequest, emp.id, jefe.email)
        r = self.client.post(
            f'/organizer/authorize/{tok}?action=approved',
            headers=self.auth(jefe.id, 'organizer'))
        self.assertEqual(r.status_code, 403, r.text[:300])
        self._assert_sigue_pendiente(main.OrganizerProfile, emp.id)

    def test_Z2_un_supervisor_PENDIENTE_no_puede_acreditar(self):
        emp = self._usuario('organizer')
        self._perfil(main.OrganizerProfile, emp.id, status='pending')
        jefe = self._usuario('organizer', selfie=True)
        self._perfil(main.OrganizerProfile, jefe.id, status='pending',
                     supervisor=True)
        tok = self._solicitud(main.AuthorizationRequest, emp.id, jefe.email)
        r = self.client.post(
            f'/organizer/authorize/{tok}?action=approved',
            headers=self.auth(jefe.id, 'organizer'))
        self.assertEqual(r.status_code, 403, r.text[:300])
        self.assertIn('aprobada', r.text.lower())
        self._assert_sigue_pendiente(main.OrganizerProfile, emp.id)

    def test_Z3_un_aprobado_que_NO_es_supervisor_no_puede_acreditar(self):
        emp = self._usuario('organizer')
        self._perfil(main.OrganizerProfile, emp.id, status='pending')
        jefe = self._usuario('organizer', selfie=True)
        self._perfil(main.OrganizerProfile, jefe.id, status='approved',
                     supervisor=False)
        tok = self._solicitud(main.AuthorizationRequest, emp.id, jefe.email)
        r = self.client.post(
            f'/organizer/authorize/{tok}?action=approved',
            headers=self.auth(jefe.id, 'organizer'))
        self.assertEqual(r.status_code, 403, r.text[:300])
        self._assert_sigue_pendiente(main.OrganizerProfile, emp.id)

    def test_Z4_un_supervisor_SIN_selfie_propia_no_puede_acreditar(self):
        """El jefe tiene que poner su propia cara antes de avalar a otro."""
        emp = self._usuario('organizer')
        self._perfil(main.OrganizerProfile, emp.id, status='pending')
        jefe = self._usuario('organizer', selfie=False)
        self._perfil(main.OrganizerProfile, jefe.id, status='approved',
                     supervisor=True)
        tok = self._solicitud(main.AuthorizationRequest, emp.id, jefe.email)
        r = self.client.post(
            f'/organizer/authorize/{tok}?action=approved',
            headers=self.auth(jefe.id, 'organizer'))
        self.assertEqual(r.status_code, 403, r.text[:300])
        self.assertIn('selfie', r.text.lower())
        self._assert_sigue_pendiente(main.OrganizerProfile, emp.id)

    def test_Z5_un_supervisor_ACREDITADO_si_aprueba_y_habilita_la_puerta(self):
        """El recorrido completo: pendiente -> acreditado -> puede crear."""
        emp = self._usuario('organizer')
        self._perfil(main.OrganizerProfile, emp.id, status='pending')
        jefe = self._usuario('organizer', selfie=True)
        self._perfil(main.OrganizerProfile, jefe.id, status='approved',
                     supervisor=True)
        tok = self._solicitud(main.AuthorizationRequest, emp.id, jefe.email)

        # antes: la puerta está cerrada
        cerrada = self.client.post('/organizer/consultations',
                                   json=self._cuerpo_consulta(),
                                   headers=self.auth(emp.id, 'organizer'))
        self.assertEqual(cerrada.status_code, 403)

        r = self.client.post(f'/organizer/authorize/{tok}?action=approved',
                             headers=self.auth(jefe.id, 'organizer'))
        self.assertEqual(r.status_code, 200, r.text[:300])
        self.db.expire_all()
        p = self.db.query(main.OrganizerProfile).filter(
            main.OrganizerProfile.user_id == emp.id).first()
        self.assertEqual(p.status, 'approved')
        self.assertEqual(p.supervisor_user_id, jefe.id,
                         'no quedó registrado QUIÉN acreditó')

        # después: la puerta se abre
        abierta = self.client.post('/organizer/consultations',
                                   json=self._cuerpo_consulta(),
                                   headers=self.auth(emp.id, 'organizer'))
        self.assertEqual(abierta.status_code, 200, abierta.text[:400])

    def test_Z6_lo_mismo_en_CAMPANAS(self):
        """Paridad: el camino del anunciante exige lo mismo."""
        emp = self._usuario('marketer')
        self._perfil(main.MarketerProfile, emp.id, status='pending')
        # jefe sin selfie -> rechazado
        jefe = self._usuario('marketer', selfie=False)
        self._perfil(main.MarketerProfile, jefe.id, status='approved',
                     supervisor=True)
        tok = self._solicitud(main.MarketerAuthorizationRequest, emp.id,
                              jefe.email)
        r = self.client.post(f'/marketer/authorize/{tok}?action=approved',
                             headers=self.auth(jefe.id, 'marketer'))
        self.assertEqual(r.status_code, 403, r.text[:300])
        self._assert_sigue_pendiente(main.MarketerProfile, emp.id)
        # con selfie -> aprueba, y la puerta de campañas se abre
        self.db.execute(main.text(
            'UPDATE users SET selfie_verified=1 WHERE id=:i'), {'i': jefe.id})
        self.db.commit()
        r2 = self.client.post(f'/marketer/authorize/{tok}?action=approved',
                              headers=self.auth(jefe.id, 'marketer'))
        self.assertEqual(r2.status_code, 200, r2.text[:300])
        rc = self.client.post('/marketer/campaigns',
                              json=self._cuerpo_campana(emp.email),
                              headers=self.auth(emp.id, 'marketer'))
        self.assertEqual(rc.status_code, 200, rc.text[:400])

    def test_Z7_un_documento_cargado_NO_acredita(self):
        """REGLA 3: subir el documento de cargo no aprueba nada."""
        emp = self._usuario('organizer')
        self._perfil(main.OrganizerProfile, emp.id, status='pending')
        r = self.client.post(
            '/organizer/upload-cargo-doc',
            files={'file': ('cargo.pdf', b'%PDF-1.4 ficticio', 'application/pdf')},
            headers=self.auth(emp.id, 'organizer'))
        self.assertIn(r.status_code, (200, 201), r.text[:300])
        self.db.expire_all()
        p = self.db.query(main.OrganizerProfile).filter(
            main.OrganizerProfile.user_id == emp.id).first()
        self.assertEqual(p.status, 'pending',
                         'subir el documento aprobó el perfil')
        self.assertFalse(p.doc_verified,
                         'subir el documento marcó doc_verified sin revisión')
        # y la puerta sigue cerrada
        c = self.client.post('/organizer/consultations',
                             json=self._cuerpo_consulta(),
                             headers=self.auth(emp.id, 'organizer'))
        self.assertEqual(c.status_code, 403)

    def test_Z8_el_administrador_puede_acreditar_al_primer_supervisor(self):
        """Arranque: la primera organización no tiene supervisor acreditado
        todavía, así que la acredita un administrador por la ruta que ya
        existía. Sin esto, nadie podría empezar nunca."""
        u = self._usuario('organizer')
        self._perfil(main.OrganizerProfile, u.id, status='pending')
        r = self.client.post(
            f'/admin/organizer/{u.id}/status?secret={ADMIN}&status=approved',
            headers=_ip())
        self.assertEqual(r.status_code, 200, r.text[:300])
        self.db.expire_all()
        p = self.db.query(main.OrganizerProfile).filter(
            main.OrganizerProfile.user_id == u.id).first()
        self.assertEqual(p.status, 'approved')
        c = self.client.post('/organizer/consultations',
                             json=self._cuerpo_consulta(),
                             headers=self.auth(u.id, 'organizer'))
        self.assertEqual(c.status_code, 200, c.text[:400])

    def test_Z9_la_acreditacion_exige_credencial_de_administrador(self):
        u = self._usuario('organizer')
        self._perfil(main.OrganizerProfile, u.id, status='pending')
        r = self.client.post(
            f'/admin/organizer/{u.id}/status?status=approved', headers=_ip())
        self.assertIn(r.status_code, (401, 403, 422), r.text[:200])

    # ── ayudante ─────────────────────────────────────────────────────

    def _assert_sigue_pendiente(self, Modelo, uid):
        self.db.expire_all()
        p = self.db.query(Modelo).filter(Modelo.user_id == uid).first()
        self.assertEqual(p.status, 'pending',
                         'la solicitud se aprobó con un supervisor no '
                         'acreditado')


if __name__ == '__main__':
    unittest.main()


# ═══════════════════════════════════════════════════════════════════════
# W. LO QUE VE Y PUEDE HACER UNA PERSONA AL REGISTRARSE EN CAMPAÑAS
#
# El defecto que JC encontró probando el formulario publicado: el portal
# entraba al panel operativo con solo tener un token, sin mirar si la
# cuenta estaba habilitada. Entrar al portal y estar autorizado a operar
# son dos cosas distintas.
#
# Estas pruebas recorren el camino del PORTAL (las mismas llamadas, en el
# mismo orden, con los mismos cuerpos) y además comprueban que el servidor
# sigue bloqueando aunque alguien se salte la interfaz.
# ═══════════════════════════════════════════════════════════════════════

class TestW_RecorridoRealDelPortal(Base):

    PORTAL = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.PORTAL = open('marketer_portal.html', encoding='utf-8').read()

    def _registrar_por_el_portal(self, dominio='example.com'):
        """Exactamente lo que envía doRegister() del portal publicado."""
        em = _uniq('alta') + '@' + dominio
        r = self.client.post('/marketer/register', json={
            'name': 'Marca Ficticia', 'email': em, 'password': 'ClaveW123!',
            'country': 'CL', 'company_name': 'Marca Ficticia',
            'business_category': 'retail_comercio', 'lang': 'es'},
            headers=_ip())
        return em, r

    # ── el estado con el que nace ────────────────────────────────────

    def test_W1_al_registrarse_la_cuenta_NO_queda_habilitada(self):
        em, r = self._registrar_por_el_portal()
        self.assertIn(r.status_code, (200, 201), r.text[:300])
        self.assertTrue(r.json().get('token'),
                        'el registro no devuelve token: el portal se guiaba por él')
        u = self.db.query(main.User).filter(
            main.func.lower(main.User.email) == em.lower()).first()
        p = self.db.query(main.MarketerProfile).filter(
            main.MarketerProfile.user_id == u.id).first()
        self.assertEqual(u.role, 'marketer')
        self.assertFalse(u.email_verified, 'el correo quedó verificado sin confirmarlo')
        self.assertEqual(p.status, 'pending')
        self.assertFalse(p.is_supervisor,
                         'CORRECCION 4: nació supervisor sin acreditación')

    def test_W2_el_estado_que_consulta_el_portal_dice_la_verdad(self):
        """`/marketer/status` es lo que showApp() consulta ahora."""
        em, r = self._registrar_por_el_portal()
        tok = r.json()['token']
        h = _ip(); h['Authorization'] = 'Bearer ' + tok
        st = self.client.get('/marketer/status', headers=h)
        self.assertEqual(st.status_code, 200, st.text[:300])
        d = st.json()
        self.assertEqual(d['status'], 'pending')
        self.assertFalse(d['verifications']['email'])
        self.assertFalse(d['is_supervisor'])

    # ── CORRECCIÓN 1: el portal no muestra el panel ──────────────────

    def test_W3_showApp_consulta_el_estado_antes_de_revelar_el_panel(self):
        """CORRECCION 1. Antes revelaba el panel con solo tener token."""
        bloque = self.PORTAL[self.PORTAL.index('async function showApp'):]
        bloque = bloque[:bloque.index('\n// ── BALANCE')]
        self.assertIn('_estadoAnunciante()', bloque,
                      'showApp no consulta el estado real')
        self.assertIn("status === 'approved'", bloque,
                      'no comprueba la aprobación del perfil')
        self.assertIn('verifications.email', bloque,
                      'no comprueba la verificación del correo')
        # y el panel solo se revela DESPUÉS de las comprobaciones
        i_check = bloque.index('_mostrarPendiente')
        i_panel = bloque.index("classList.add('visible')")
        self.assertLess(i_check, i_panel,
                        'revela el panel antes de comprobar el estado')

    def test_W4_los_puntos_de_entrada_esperan_la_comprobacion(self):
        """showApp es asíncrono: si no se espera, el panel aparecería igual."""
        for fn in ('doLogin', 'doRegister'):
            bloque = self.PORTAL[self.PORTAL.index(f'async function {fn}'):]
            bloque = bloque[:bloque.index('\n}') + 2]
            # El prefijo, no la firma exacta: showApp recibe ahora el
            # origen de la llamada —showApp('login')— para distinguir una
            # sesión guardada de un registro recién hecho. Fijar la firma
            # rompia la prueba sin que nada funcionara peor.
            self.assertIn('await showApp(', bloque,
                          f'{fn} no espera la comprobación de estado')

    def test_W5_existe_el_aviso_y_no_es_un_panel_nuevo(self):
        self.assertIn('id="pending-notice"', self.PORTAL)
        self.assertIn('todavía no está habilitada', self.PORTAL,
                      'el aviso no dice con claridad que no está habilitada')
        # dentro de la tarjeta de acceso, no un panel aparte
        self.assertLess(self.PORTAL.index('id="pending-notice"'),
                        self.PORTAL.index('id="main-app"'))

    # ── CORRECCIONES 2 y 3: el servidor bloquea ──────────────────────

    def test_W6_una_cuenta_pendiente_NO_obtiene_creditos_demo(self):
        """CORRECCION 2. Antes devolvía 200 y acreditaba 500 DEMO."""
        em, r = self._registrar_por_el_portal()
        tok = r.json()['token']
        u = self.db.query(main.User).filter(
            main.func.lower(main.User.email) == em.lower()).first()
        h = _ip(); h['Authorization'] = 'Bearer ' + tok
        rc = self.client.post('/payments/demo-credits', json={}, headers=h)
        self.assertEqual(rc.status_code, 403, rc.text[:300])
        self.assertEqual(
            main._ledger_balance(self.db, main._ledger.USER_DEMO, u.id), 0.0,
            'se le acreditó saldo DEMO a una cuenta pendiente')

    def test_W7_una_cuenta_pendiente_NO_abre_sesion_de_pago(self):
        """CORRECCION 3. Ningún cobro real: se cierra antes de empezar."""
        em, r = self._registrar_por_el_portal()
        h = _ip(); h['Authorization'] = 'Bearer ' + r.json()['token']
        rp = self.client.post('/payments/stripe/create-session',
                              json={'package_id': 1,
                                    'success_url': 'https://e.invalid/ok',
                                    'cancel_url': 'https://e.invalid/no'},
                              headers=h)
        self.assertEqual(rp.status_code, 403, rp.text[:300])

    def test_W8_el_servidor_bloquea_aunque_se_salte_la_interfaz(self):
        """Lo que importa: la interfaz es una cortesía, no la seguridad.
        Con el token en la mano y sin pasar por el portal, nada operativo."""
        em, r = self._registrar_por_el_portal()
        tok = r.json()['token']
        def h():
            x = _ip(); x['Authorization'] = 'Bearer ' + tok; return x
        campana = {
            'advertiser_email': em, 'advertiser_name': 'Marca Ficticia',
            'campaign_title': _uniq('C'), 'budget_clp': 95000,
            'target_country': 'CL', 'start_date': '2026-11-20T00:00:00',
            'end_date': '2026-12-20T23:59:59', 'ad_copy': 'x',
            'link_url': 'https://e.invalid'}
        bloqueadas = [
            ('POST', '/marketer/campaigns', campana),
            ('POST', '/payments/demo-credits', {}),
            ('POST', '/payments/stripe/create-session',
             {'package_id': 1, 'success_url': 'https://e.invalid/a',
              'cancel_url': 'https://e.invalid/b'}),
            ('GET', f'/advertiser/campaigns?email={em}', None),
        ]
        for met, ruta, cuerpo in bloqueadas:
            rr = self.client.request(met, ruta, json=cuerpo, headers=h())
            self.assertEqual(rr.status_code, 403,
                             f'{met} {ruta.split("?")[0]} dio {rr.status_code}, '
                             f'deberia bloquear: {rr.text[:160]}')

    def test_W9_el_inicio_de_sesion_POSTERIOR_tampoco_habilita(self):
        """Pedido explícitamente: comprobar también el login posterior."""
        em, r = self._registrar_por_el_portal()
        li = self.client.post('/marketer/login',
                              json={'email': em, 'password': 'ClaveW123!'},
                              headers=_ip())
        self.assertEqual(li.status_code, 200, li.text[:300])
        tok = li.json().get('token')
        self.assertTrue(tok, 'el login no devolvió token')
        h = _ip(); h['Authorization'] = 'Bearer ' + tok
        # el estado que vera showApp sigue siendo pendiente
        st = self.client.get('/marketer/status', headers=h).json()
        self.assertEqual(st['status'], 'pending')
        self.assertFalse(st['verifications']['email'])
        # y el servidor sigue bloqueando
        rc = self.client.post('/payments/demo-credits', json={}, headers=h)
        self.assertEqual(rc.status_code, 403, rc.text[:200])

    # ── la contraparte: una cuenta habilitada SÍ opera ───────────────

    def test_W10_una_cuenta_aprobada_y_verificada_opera_con_normalidad(self):
        """Las correcciones no pueden cerrar la puerta a quien sí cumple."""
        em, r = self._registrar_por_el_portal()
        u = self.db.query(main.User).filter(
            main.func.lower(main.User.email) == em.lower()).first()
        # el recorrido real: verificar correo + acreditar por administrador
        self.db.execute(main.text(
            'UPDATE users SET email_verified=1 WHERE id=:i'), {'i': u.id})
        self.db.commit()
        ac = self.client.post(
            f'/admin/marketer/{u.id}/status?secret={ADMIN}&status=approved',
            headers=_ip())
        self.assertEqual(ac.status_code, 200, ac.text[:300])
        self.db.expire_all()

        tok = main.make_token(u.id, 'marketer')
        def h():
            x = _ip(); x['Authorization'] = 'Bearer ' + tok; return x
        st = self.client.get('/marketer/status', headers=h()).json()
        self.assertEqual(st['status'], 'approved')
        self.assertTrue(st['verifications']['email'])

        # créditos demo: ahora SI
        rc = self.client.post('/payments/demo-credits', json={}, headers=h())
        self.assertEqual(rc.status_code, 200, rc.text[:300])
        self.assertGreater(
            main._ledger_balance(self.db, main._ledger.USER_DEMO, u.id), 0,
            'una cuenta habilitada no pudo obtener saldo demo')
        # crear campaña: ahora SI
        campana = {
            'advertiser_email': em, 'advertiser_name': 'Marca Ficticia',
            'campaign_title': _uniq('C'), 'budget_clp': 95000,
            'target_country': 'CL', 'start_date': '2026-11-20T00:00:00',
            'end_date': '2026-12-20T23:59:59', 'ad_copy': 'x',
            'link_url': 'https://e.invalid'}
        rcam = self.client.post('/marketer/campaigns', json=campana, headers=h())
        self.assertEqual(rcam.status_code, 200, rcam.text[:400])
        # y ver sus campañas
        rl = self.client.get(f'/advertiser/campaigns?email={em}', headers=h())
        self.assertEqual(rl.status_code, 200, rl.text[:200])


# ═══════════════════════════════════════════════════════════════════════
# V. CLARIDAD DEL PORTAL — que la persona entienda qué pasó
#
# JC pulsó «Create Account» y "no ocurrió nada": aparecía un aviso de
# cuenta pendiente, sin saber si se había creado una cuenta, si ya tenía
# una, o si era una sesión anterior guardada en el navegador.
#
# Cinco causas sumadas, todas de claridad y ninguna del servidor.
# ═══════════════════════════════════════════════════════════════════════

class TestV_ClaridadDelPortal(Base):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.P = open('marketer_portal.html', encoding='utf-8').read()

    def _js_showApp(self):
        i = self.P.index('async function showApp(')
        return self.P[i:self.P.index('\n// ── BALANCE')]

    # ── 1. sesión anterior vs registro nuevo ─────────────────────────

    def test_V1_showApp_distingue_el_origen_de_la_llamada(self):
        """CORRECCION 1. `token` se lee de localStorage al cargar la página,
        así que el aviso aparecía sin haber pulsado nada."""
        js = self._js_showApp()
        self.assertIn('async function showApp(origen)', js,
                      'showApp no recibe el origen de la llamada')
        for origen in ('sesion-previa', 'cuenta-creada', 'cuenta-existente'):
            self.assertIn(origen, js, f'no contempla el origen {origen!r}')

    def test_V2_el_onload_declara_que_es_una_sesion_anterior(self):
        i = self.P.index('window.onload = () => {')
        bloque = self.P[i:i + 900]
        self.assertIn("showApp('sesion-previa')", bloque,
                      'el onload no distingue la sesión guardada')

    def test_V3_los_tres_textos_son_distintos_entre_si(self):
        """Si los mensajes coinciden, la distinción no sirve de nada."""
        js = self._js_showApp()
        self.assertIn('Cuenta creada', js)
        self.assertIn('Ya tenías una cuenta con este correo', js)
        self.assertIn('sesión anterior guardada en este navegador', js)
        self.assertIn('No se creó una nueva', js,
                      'no aclara que reintentar no creó otra cuenta')

    def test_V4_una_sesion_anterior_se_puede_cerrar(self):
        js = self._js_showApp()
        self.assertIn('ofrecerCerrar', js)
        bloque = self.P[self.P.index('function _mostrarPendiente'):
                        self.P.index('function _mostrarFormulario')]
        self.assertIn('doLogout()', bloque,
                      'el aviso no ofrece cerrar la sesión anterior')

    # ── 2. el aviso nombra la cuenta ─────────────────────────────────

    def test_V5_el_aviso_dice_a_que_cuenta_se_refiere(self):
        bloque = self.P[self.P.index('function _mostrarPendiente'):
                        self.P.index('function _mostrarFormulario')]
        self.assertIn('Cuenta:', bloque, 'el aviso no nombra la cuenta')
        self.assertIn('userEmail', bloque)
        self.assertIn('_escaparHtml(userEmail)', bloque,
                      'el correo se inyecta sin escapar en innerHTML')

    def test_V6_el_correo_se_escapa_antes_de_pintarlo(self):
        """Va a innerHTML: hay que escaparlo."""
        i = self.P.index('function _escaparHtml')
        bloque = self.P[i:i + 300]
        for ch in ('&amp;', '&lt;', '&gt;', '&quot;'):
            self.assertIn(ch, bloque, f'_escaparHtml no cubre {ch}')

    # ── 3. ningún retorno mudo ───────────────────────────────────────

    def _doRegister_sin_comentarios(self):
        """El cuerpo de doRegister con los comentarios quitados.

        Los comentarios CITAN el codigo antiguo para explicarlo, asi que una
        busqueda por substring lo encontraria ahi y daria un falso positivo
        (me paso al escribir esto)."""
        i = self.P.index('async function doRegister')
        j = self.P.index('\nfunction doLogout', i)
        return '\n'.join(l for l in self.P[i:j].split('\n')
                          if not l.strip().startswith('//'))

    def test_V7_el_boton_nunca_se_queda_callado(self):
        """CORRECCION 3. Era `if (!name || !email || !pass) return;`."""
        bloque = self._doRegister_sin_comentarios()
        self.assertNotIn('|| !pass) return;', bloque,
                         'volvió el retorno mudo')
        self.assertIn('faltantes.push', bloque)
        self.assertIn("showErr('reg-err', 'Falta '", bloque,
                      'no dice qué campo falta')
        for campo in ('el nombre de la empresa', 'el correo',
                      'la contraseña', 'la categoría de tu empresa'):
            self.assertIn(campo, bloque, f'no menciona {campo!r}')

    # ── 4. distinguir "ya tenías cuenta" ─────────────────────────────

    def test_V8_el_portal_usa_la_senal_que_el_servidor_ya_daba(self):
        """Un registro nuevo responde con `verifications`; un correo que ya
        tenía cuenta responde sin ella. Comprobado contra el servidor."""
        bloque = self._doRegister_sin_comentarios()
        self.assertIn('const yaExistia = !d.verifications;', bloque)
        self.assertIn("'cuenta-existente' : 'cuenta-creada'", bloque)

    def test_V9_el_servidor_de_verdad_distingue_los_dos_casos(self):
        """La señal en la que se apoya la corrección 4, medida."""
        em = _uniq('clar') + '@example.com'
        cuerpo = {'name': 'Marca', 'email': em, 'password': 'ClaveV123!',
                  'country': 'CL', 'company_name': 'Marca',
                  'business_category': 'retail_comercio'}
        antes = self.db.execute(main.text('SELECT count(*) FROM users')).scalar()
        r1 = self.client.post('/marketer/register', json=cuerpo, headers=_ip())
        self.assertIn(r1.status_code, (200, 201), r1.text[:200])
        medio = self.db.execute(main.text('SELECT count(*) FROM users')).scalar()
        r2 = self.client.post('/marketer/register', json=cuerpo, headers=_ip())
        despues = self.db.execute(main.text('SELECT count(*) FROM users')).scalar()

        self.assertEqual(medio, antes + 1, 'el primer registro no creó cuenta')
        self.assertEqual(despues, medio,
                         'el segundo intento creó una cuenta duplicada')
        self.assertIn('verifications', r1.json(),
                      'un registro NUEVO debe traer `verifications`')
        self.assertNotIn('verifications', r2.json(),
                         'una cuenta preexistente no debe traerla: es la '
                         'señal que usa el portal')
        self.assertTrue(r2.json().get('token'),
                        'sin token el portal no sabría que hay sesión')

    def test_V10_una_contrasena_distinta_da_un_error_claro(self):
        em = _uniq('clar2') + '@example.com'
        base = {'name': 'Marca', 'email': em, 'country': 'CL',
                'company_name': 'Marca', 'business_category': 'retail_comercio'}
        self.client.post('/marketer/register',
                         json={**base, 'password': 'ClaveV123!'}, headers=_ip())
        r = self.client.post('/marketer/register',
                             json={**base, 'password': 'OtraClave999!'},
                             headers=_ip())
        self.assertEqual(r.status_code, 400, r.text[:200])
        self.assertIn('Ya tienes cuenta', r.json().get('detail', ''),
                      'el mensaje no explica el problema')

    # ── 5. el formulario se oculta ───────────────────────────────────

    def test_V11_el_aviso_oculta_el_formulario_y_las_pestanas(self):
        """CORRECCION 5. El formulario quedaba visible con los datos
        escritos, así que parecía que el botón no había hecho nada."""
        bloque = self.P[self.P.index('function _mostrarPendiente'):
                        self.P.index('function _mostrarFormulario')]
        for id_ in ('tab-login', 'tab-register'):
            self.assertIn(id_, bloque, f'no oculta {id_}')
        self.assertIn("querySelector('#auth-screen .tabs')", bloque,
                      'no oculta las pestañas')

    def test_V12_el_aviso_limpia_los_errores_anteriores(self):
        bloque = self.P[self.P.index('function _mostrarPendiente'):
                        self.P.index('function _mostrarFormulario')]
        self.assertIn('login-err', bloque)
        self.assertIn('reg-err', bloque)

    def test_V13_una_cuenta_habilitada_recupera_el_formulario_oculto(self):
        """Si no se restaura, quien cierre sesión después se quedaría sin
        formulario para volver a entrar."""
        self.assertIn('function _mostrarFormulario', self.P)
        js = self._js_showApp()
        self.assertIn('_mostrarFormulario();', js,
                      'el camino aprobado no restaura el formulario')
        bloque = self.P[self.P.index('function _mostrarFormulario'):
                        self.P.index('// CORRECCION 1')]
        self.assertIn("switchTab('login')", bloque)

    # ── cierre de sesión ─────────────────────────────────────────────

    def test_V14_cerrar_sesion_borra_la_sesion_guardada(self):
        """Pedido explícitamente. Si no se limpia localStorage, al recargar
        reaparecería el aviso de sesión anterior."""
        i = self.P.index('function doLogout')
        bloque = self.P[i:i + 400]
        self.assertIn('localStorage.clear()', bloque,
                      'cerrar sesión no borra el token guardado')
        self.assertIn('location.reload()', bloque)

    def test_V15_el_servidor_sigue_bloqueando_igual(self):
        """Las cinco correcciones son de claridad: la seguridad no cambia."""
        em = _uniq('clar3') + '@example.com'
        r = self.client.post('/marketer/register', json={
            'name': 'Marca', 'email': em, 'password': 'ClaveV123!',
            'country': 'CL', 'company_name': 'Marca',
            'business_category': 'retail_comercio'}, headers=_ip())
        h = _ip(); h['Authorization'] = 'Bearer ' + r.json()['token']
        for met, ruta, cuerpo in (
                ('POST', '/payments/demo-credits', {}),
                ('POST', '/marketer/campaigns', {
                    'advertiser_email': em, 'advertiser_name': 'M',
                    'campaign_title': 'C', 'budget_clp': 95000,
                    'target_country': 'CL',
                    'start_date': '2026-11-20T00:00:00',
                    'end_date': '2026-12-20T23:59:59',
                    'ad_copy': 'x', 'link_url': 'https://e.invalid'})):
            rr = self.client.request(met, ruta, json=cuerpo, headers=h)
            self.assertEqual(rr.status_code, 403,
                             f'{met} {ruta} dio {rr.status_code}')

    def test_V16_el_formulario_de_acceso_tampoco_se_queda_callado(self):
        """El mismo retorno mudo estaba en doLogin: pulsar «Sign In» con un
        campo vacío no hacía nada. Encontrado al probar el inicio de sesión
        que JC pidió comprobar."""
        i = self.P.index('async function doLogin')
        j = self.P.index('\nfunction switchTab', i) if '\nfunction switchTab' in self.P[i:] else i + 1500
        bloque = '\n'.join(l for l in self.P[i:j].split('\n')
                           if not l.strip().startswith('//'))
        self.assertNotIn('if (!email || !pass) return;', bloque,
                         'volvió el retorno mudo del acceso')
        self.assertIn("showErr('login-err', 'Falta '", bloque,
                      'el acceso no dice qué campo falta')
