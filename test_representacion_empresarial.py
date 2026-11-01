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
