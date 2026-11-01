"""test_acreditacion_empresarial.py — UN SOLO procedimiento de acreditación.

CREAR CONSULTA y CAMPAÑAS comparten identidad de empresa, estados y guardas.
La identidad de una empresa es (país, identificación tributaria normalizada),
nunca su nombre ni el dominio de su correo: los dos son texto que cualquiera
escribe.

Lo que se comprueba, en este orden:

  A. La identidad de la empresa: resolución, reutilización, normalización y
     ausencia de identificación verificable.
  B. Los perfiles históricos: siguen aprobados y siguen SIN vincular.
  C. Las autorizaciones fraudulentas, que es el punto del encargo:
       · autoaprobación
       · supervisor distinto del designado en la solicitud (poseer el token
         no basta)
       · supervisor de OTRA empresa
       · supervisor sin empresa vinculada
       · reutilización del token ya resuelto
     Las cinco, en los DOS portales.
  D. El panel de revisión: el secreto viaja por cabecera y nunca por la URL,
     el listado no lleva documentos, y cada decisión registra quién, cuándo
     y con qué resultado.
  E. Los dos formularios publicados: que envíen de verdad lo que el servidor
     ya verificaba y que consulten el estado antes de ofrecer operar.
"""
import json
import os
import re
import tempfile
import unittest
import uuid

_TMP = tempfile.mkdtemp(prefix='prefy_acred_')
os.environ['DATABASE_URL'] = f'sqlite:///{os.path.join(_TMP, "acred.db")}'
os.environ.setdefault('ADMIN_SECRET', 'acred-solo-local')
os.environ.setdefault('JWT_SECRET', 'acred-solo-local')
os.environ.pop('ADMIN_SECRET_CANARY', None)

import bcrypt                                    # noqa: E402
from fastapi.testclient import TestClient        # noqa: E402

import main                                      # noqa: E402

ADMIN = os.environ['ADMIN_SECRET']


def _ip():
    _ip.n = getattr(_ip, 'n', 0) + 1
    return {'X-Forwarded-For': f'203.0.113.{_ip.n % 250 + 1}'}


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

    def _usuario(self, rol, email=None, selfie=True):
        em = email or (_uniq('u') + '@empresa-ficticia.invalid')
        u = main.User(name='Representante', email=em, role=rol,
                      password=bcrypt.hashpw(b'x', bcrypt.gensalt()).decode(),
                      country='CL', email_verified=True, selfie_verified=selfie)
        self.db.add(u); self.db.commit(); self.db.refresh(u)
        return u

    def _empresa(self, tax_id=None, country='CL', name='Empresa Ficticia'):
        emp, _ = main._resolver_empresa(
            self.db, country=country, tax_id=tax_id or _uniq('76'),
            name=name, verified_tax_id=True)
        return emp

    def _perfil(self, Modelo, uid, company_id=None, status='pending',
                supervisor=False, org_type='company'):
        p = Modelo(user_id=uid, org_type=org_type, status=status,
                   is_supervisor=supervisor, company_name='Empresa Ficticia',
                   company_id=company_id)
        self.db.add(p); self.db.commit()
        return p


# ══════════════════════════════════════════════════════════════════
# A. LA IDENTIDAD DE LA EMPRESA
# ══════════════════════════════════════════════════════════════════

class TestIdentidadDeEmpresa(Base):

    def test_normaliza_puntos_guiones_y_mayusculas(self):
        self.assertEqual(main._norm_tax_id('76.123.456-7'), '761234567')
        self.assertEqual(main._norm_tax_id(' 76123456-K '), '76123456K')
        self.assertEqual(main._norm_tax_id('76123456-k'), '76123456K')

    def test_mismo_rut_escrito_distinto_es_la_misma_empresa(self):
        a, creada_a = main._resolver_empresa(
            self.db, country='CL', tax_id='77.111.222-3', name='Alfa SpA',
            verified_tax_id=True)
        b, creada_b = main._resolver_empresa(
            self.db, country='cl', tax_id='771112223', name='ALFA SPA',
            verified_tax_id=True)
        self.assertTrue(creada_a)
        self.assertFalse(creada_b)
        self.assertEqual(a.id, b.id)

    def test_mismo_rut_en_otro_pais_es_otra_empresa(self):
        a, _ = main._resolver_empresa(self.db, country='CL', tax_id='77.999.888-1',
                                      name='Beta', verified_tax_id=True)
        b, _ = main._resolver_empresa(self.db, country='AR', tax_id='77.999.888-1',
                                      name='Beta', verified_tax_id=True)
        self.assertNotEqual(a.id, b.id)

    def test_el_nombre_NO_identifica_a_la_empresa(self):
        a, _ = main._resolver_empresa(self.db, country='CL', tax_id='77.555.111-1',
                                      name='Gamma Ltda', verified_tax_id=True)
        b, _ = main._resolver_empresa(self.db, country='CL', tax_id='77.555.222-2',
                                      name='Gamma Ltda', verified_tax_id=True)
        self.assertNotEqual(a.id, b.id,
                            'dos RUT distintos con el mismo nombre no pueden '
                            'resolver a la misma empresa')

    def test_sin_identificacion_no_hay_empresa(self):
        for basura in ('', '   ', '-', '...'):
            emp, creada = main._resolver_empresa(
                self.db, country='CL', tax_id=basura, name='Sin RUT SpA')
            self.assertIsNone(emp, f'{basura!r} no identifica a nadie')
            self.assertFalse(creada)

    def test_sin_pais_no_hay_empresa(self):
        emp, _ = main._resolver_empresa(self.db, country='', tax_id='77.333.444-5',
                                        name='Sin país SpA')
        self.assertIsNone(emp)

    def test_el_indice_unico_existe_en_el_modelo(self):
        nombres = {i.name for i in main.Company.__table__.indexes}
        self.assertIn('ux_companies_country_taxid', nombres)
        ix = next(i for i in main.Company.__table__.indexes
                  if i.name == 'ux_companies_country_taxid')
        self.assertTrue(ix.unique)
        self.assertEqual([c.name for c in ix.columns], ['country', 'tax_id_norm'])

    def test_los_dos_perfiles_tienen_company_id(self):
        for Modelo in (main.OrganizerProfile, main.MarketerProfile):
            self.assertIn('company_id', Modelo.__table__.c,
                          f'{Modelo.__name__} debe poder vincularse a una empresa')
            self.assertTrue(Modelo.__table__.c['company_id'].nullable,
                            'los perfiles históricos quedan en NULL')


# ══════════════════════════════════════════════════════════════════
# B. LOS PERFILES HISTÓRICOS
# ══════════════════════════════════════════════════════════════════

class TestPerfilesHistoricos(Base):

    def test_un_perfil_aprobado_sin_company_id_conserva_su_acceso(self):
        u = self._usuario('organizer')
        self._perfil(main.OrganizerProfile, u.id, company_id=None,
                     status='approved', supervisor=True)
        r = self.client.post('/organizer/consultations',
                             json={'title': _uniq('C'), 'context': 'Ficticia',
                                   'options': ['A', 'B'],
                                   'closes_at': '2027-06-30T23:59:59',
                                   'creator_type': 'company', 'scope': 'country',
                                   'scope_country': 'CL'},
                             headers=self.auth(u.id, 'organizer'))
        self.assertEqual(r.status_code, 200,
                         'un perfil histórico aprobado no pierde acceso por no '
                         f'estar vinculado: {r.text[:200]}')

    def test_la_migracion_no_vincula_ningun_perfil(self):
        cuerpo = _migracion()
        self.assertNotRegex(
            cuerpo, r'UPDATE\s+organizer_profiles\s+SET\s+company_id',
            'la migración nunca asigna company_id a un perfil existente')
        self.assertNotRegex(
            cuerpo, r'UPDATE\s+marketer_profiles\s+SET\s+company_id',
            'la migración nunca asigna company_id a un perfil existente')

    def test_la_migracion_de_company_id_es_aditiva(self):
        cuerpo = _migracion()
        self.assertIn('ADD COLUMN company_id INTEGER', cuerpo)
        self.assertNotIn('DROP COLUMN', cuerpo.upper())
        self.assertNotIn('NOT NULL', cuerpo.split('company_id INTEGER')[1][:80],
                         'la columna tiene que admitir NULL: los perfiles '
                         'históricos quedan sin vincular')


def _migracion():
    """El cuerpo de _migrate(), sin sus comentarios.

    Sin quitar los comentarios, cualquier aserción tropieza con el código
    viejo citado en las explicaciones; ya ha pasado varias veces.
    """
    import inspect
    fuente = inspect.getsource(main._migrate)
    return '\n'.join(l for l in fuente.splitlines()
                      if not l.strip().startswith('#'))


# ══════════════════════════════════════════════════════════════════
# C. AUTORIZACIONES FRAUDULENTAS — LAS CINCO, EN LOS DOS PORTALES
# ══════════════════════════════════════════════════════════════════

class _Fraude:
    """Las mismas cinco pruebas para los dos portales.

    `PORTAL` fija el modelo de perfil, el de solicitud y la ruta.
    """

    def _solicitud(self, empleado, supervisor_email, estado='pending'):
        req = self.SOLICITUD(
            employee_user_id=empleado.id, employee_name=empleado.name,
            employee_email=empleado.email, supervisor_email=supervisor_email,
            token=_uniq('tok'), status=estado)
        self.db.add(req); self.db.commit(); self.db.refresh(req)
        return req

    def _aprobar(self, req, supervisor, accion='approved'):
        return self.client.post(f'{self.RUTA}/{req.token}?action={accion}',
                                headers=self.auth(supervisor.id, self.ROL))

    # ── 1. Nadie se aprueba a sí mismo ────────────────────────────
    def test_autoaprobacion_rechazada(self):
        emp = self._empresa()
        u = self._usuario(self.ROL)
        self._perfil(self.PERFIL, u.id, company_id=emp.id,
                     status='approved', supervisor=True)
        req = self._solicitud(u, u.email)
        r = self._aprobar(req, u)
        self.assertEqual(r.status_code, 403, r.text[:200])
        self.assertIn('propia solicitud', r.json()['detail'])
        self.db.refresh(req)
        self.assertEqual(req.status, 'pending', 'la solicitud sigue sin resolver')

    # ── 2. Poseer el token no basta: hay que ser el designado ─────
    def test_supervisor_distinto_del_designado_rechazado(self):
        emp = self._empresa()
        jefe_real = self._usuario(self.ROL)
        otro_jefe = self._usuario(self.ROL)
        empleado = self._usuario(self.ROL)
        for jefe in (jefe_real, otro_jefe):
            self._perfil(self.PERFIL, jefe.id, company_id=emp.id,
                         status='approved', supervisor=True)
        self._perfil(self.PERFIL, empleado.id, company_id=emp.id)
        req = self._solicitud(empleado, jefe_real.email)
        r = self._aprobar(req, otro_jefe)
        self.assertEqual(r.status_code, 403, r.text[:200])
        self.assertIn('otro supervisor', r.json()['detail'])

    # ── 3. Supervisor de OTRA empresa ─────────────────────────────
    def test_supervisor_de_otra_empresa_rechazado(self):
        emp_a = self._empresa(name='Empresa A')
        emp_b = self._empresa(name='Empresa B')
        self.assertNotEqual(emp_a.id, emp_b.id)
        jefe_b = self._usuario(self.ROL)
        empleado_a = self._usuario(self.ROL)
        self._perfil(self.PERFIL, jefe_b.id, company_id=emp_b.id,
                     status='approved', supervisor=True)
        self._perfil(self.PERFIL, empleado_a.id, company_id=emp_a.id)
        # La solicitud va dirigida al jefe de la otra empresa: aunque el
        # destinatario coincida, la empresa no.
        req = self._solicitud(empleado_a, jefe_b.email)
        r = self._aprobar(req, jefe_b)
        self.assertEqual(r.status_code, 403, r.text[:200])
        self.assertIn('misma empresa', r.json()['detail'])
        perfil = self.db.query(self.PERFIL).filter(
            self.PERFIL.user_id == empleado_a.id).first()
        self.assertEqual(perfil.status, 'pending',
                         'el empleado de la otra empresa sigue pendiente')

    def test_empleado_sin_empresa_vinculada_rechazado(self):
        emp = self._empresa()
        jefe = self._usuario(self.ROL)
        empleado = self._usuario(self.ROL)
        self._perfil(self.PERFIL, jefe.id, company_id=emp.id,
                     status='approved', supervisor=True)
        self._perfil(self.PERFIL, empleado.id, company_id=None)
        req = self._solicitud(empleado, jefe.email)
        r = self._aprobar(req, jefe)
        self.assertEqual(r.status_code, 403, r.text[:200])
        self.assertIn('misma empresa', r.json()['detail'])

    # ── 4. Supervisor sin empresa vinculada (los 21 históricos) ───
    def test_supervisor_historico_sin_vincular_no_puede_acreditar(self):
        emp = self._empresa()
        jefe = self._usuario(self.ROL)
        empleado = self._usuario(self.ROL)
        self._perfil(self.PERFIL, jefe.id, company_id=None,
                     status='approved', supervisor=True)
        self._perfil(self.PERFIL, empleado.id, company_id=emp.id)
        req = self._solicitud(empleado, jefe.email)
        r = self._aprobar(req, jefe)
        self.assertEqual(r.status_code, 403, r.text[:200])
        self.assertIn('revision manual', r.json()['detail'])

    # ── 5. El token no se reutiliza ───────────────────────────────
    def test_token_ya_resuelto_no_se_reutiliza(self):
        emp = self._empresa()
        jefe = self._usuario(self.ROL)
        empleado = self._usuario(self.ROL)
        self._perfil(self.PERFIL, jefe.id, company_id=emp.id,
                     status='approved', supervisor=True)
        self._perfil(self.PERFIL, empleado.id, company_id=emp.id)
        req = self._solicitud(empleado, jefe.email)

        primera = self._aprobar(req, jefe)
        self.assertEqual(primera.status_code, 200, primera.text[:300])
        perfil = self.db.query(self.PERFIL).filter(
            self.PERFIL.user_id == empleado.id).first()
        self.db.refresh(perfil)
        self.assertEqual(perfil.status, 'approved',
                         'la autorización legítima sí funciona')

        segunda = self._aprobar(req, jefe)
        self.assertEqual(segunda.status_code, 404,
                         'un token ya resuelto no vuelve a servir')

    def test_token_inventado_no_sirve(self):
        emp = self._empresa()
        jefe = self._usuario(self.ROL)
        self._perfil(self.PERFIL, jefe.id, company_id=emp.id,
                     status='approved', supervisor=True)
        r = self.client.post(f'{self.RUTA}/{_uniq("inventado")}?action=approved',
                             headers=self.auth(jefe.id, self.ROL))
        self.assertEqual(r.status_code, 404)

    def test_la_autorizacion_legitima_registra_quien_aprobo(self):
        emp = self._empresa()
        jefe = self._usuario(self.ROL)
        empleado = self._usuario(self.ROL)
        self._perfil(self.PERFIL, jefe.id, company_id=emp.id,
                     status='approved', supervisor=True)
        self._perfil(self.PERFIL, empleado.id, company_id=emp.id)
        req = self._solicitud(empleado, jefe.email)
        r = self._aprobar(req, jefe)
        self.assertEqual(r.status_code, 200, r.text[:300])
        self.db.refresh(req)
        self.assertEqual(req.status, 'approved')
        self.assertEqual(req.supervisor_user_id, jefe.id)
        self.assertIsNotNone(req.resolved_at)


class TestFraudeOrganizador(_Fraude, Base):
    PERFIL = main.OrganizerProfile
    SOLICITUD = main.AuthorizationRequest
    RUTA = '/organizer/authorize'
    ROL = 'organizer'


class TestFraudeAnunciante(_Fraude, Base):
    PERFIL = main.MarketerProfile
    SOLICITUD = main.MarketerAuthorizationRequest
    RUTA = '/marketer/authorize'
    ROL = 'marketer'


# ══════════════════════════════════════════════════════════════════
# D. EL PANEL DE REVISIÓN
# ══════════════════════════════════════════════════════════════════

class TestPanelDeRevision(Base):

    def test_sin_cabecera_no_se_entra(self):
        r = self.client.get('/admin/accreditation/pending', headers=_ip())
        self.assertEqual(r.status_code, 403)

    def test_el_secreto_en_la_URL_no_sirve(self):
        r = self.client.get(f'/admin/accreditation/pending?secret={ADMIN}',
                            headers=_ip())
        self.assertEqual(r.status_code, 403,
                         'el secreto por query string queda en el historial, '
                         'en los logs y en el Referer: no se acepta')

    def test_secreto_equivocado_rechazado(self):
        h = _ip(); h['X-Admin-Secret'] = ADMIN + 'x'
        r = self.client.get('/admin/accreditation/pending', headers=h)
        self.assertEqual(r.status_code, 403)

    def test_ninguna_ruta_de_acreditacion_declara_secret_en_la_firma(self):
        import inspect
        for fn in (main.admin_acreditaciones_pendientes,
                   main.admin_acreditacion_documento,
                   main.admin_acreditacion_decidir):
            params = inspect.signature(fn).parameters
            self.assertNotIn('secret', params,
                             f'{fn.__name__} no puede recibir el secreto por URL')

    def _admin(self):
        h = _ip(); h['X-Admin-Secret'] = ADMIN
        return h

    def test_el_listado_no_lleva_documentos_ni_datos_personales(self):
        u = self._usuario('organizer')
        emp = self._empresa()
        p = self._perfil(main.OrganizerProfile, u.id, company_id=emp.id)
        p.cargo_doc_hash = 'a' * 64
        p.cargo_doc_bytes = 'ZmFrZQ=='
        self.db.commit()

        r = self.client.get('/admin/accreditation/pending', headers=self._admin())
        self.assertEqual(r.status_code, 200, r.text[:200])
        cuerpo = r.text
        self.assertNotIn('ZmFrZQ==', cuerpo, 'el documento no viaja en el listado')
        self.assertNotIn(u.email, cuerpo, 'el correo del solicitante no va aquí')
        fila = next(f for f in r.json()['pendientes']
                    if f['user_id'] == u.id and f['tipo'] == 'organizador')
        self.assertTrue(fila['tiene_documento_de_cargo'])
        self.assertEqual(fila['identificacion'], emp.tax_id_norm)

    def test_el_documento_se_consulta_de_uno_en_uno_y_autenticado(self):
        u = self._usuario('marketer')
        p = self._perfil(main.MarketerProfile, u.id, company_id=self._empresa().id)
        p.cargo_doc_hash = 'b' * 64
        p.cargo_doc_bytes = 'ZG9jdW1lbnRv'
        self.db.commit()

        sin = self.client.get(
            f'/admin/accreditation/document?tipo=anunciante&user_id={u.id}',
            headers=_ip())
        self.assertEqual(sin.status_code, 403)

        con = self.client.get(
            f'/admin/accreditation/document?tipo=anunciante&user_id={u.id}',
            headers=self._admin())
        self.assertEqual(con.status_code, 200, con.text[:200])
        self.assertEqual(con.json()['contenido_base64'], 'ZG9jdW1lbnRv')
        self.assertEqual(con.json()['sha256'], 'b' * 64)

    def test_aprobar_vincula_y_registra_la_decision(self):
        u = self._usuario('organizer')
        emp = self._empresa()
        self._perfil(main.OrganizerProfile, u.id, company_id=emp.id)
        r = self.client.post('/admin/accreditation/decide',
                             json={'tipo': 'organizador', 'user_id': u.id,
                                   'decision': 'approved',
                                   'decidido_por': 'JC'},
                             headers=self._admin())
        self.assertEqual(r.status_code, 200, r.text[:300])
        d = r.json()
        self.assertEqual(d['estado'], 'approved')
        self.assertEqual(d['decidido_por'], 'JC')
        self.assertTrue(d['decidido_en'])
        p = self.db.query(main.OrganizerProfile).filter(
            main.OrganizerProfile.user_id == u.id).first()
        self.db.refresh(p)
        self.assertEqual(p.status, 'approved')
        self.assertIsNotNone(p.approved_at)

    def test_no_se_aprueba_una_organizacion_sin_empresa_identificada(self):
        u = self._usuario('marketer')
        self._perfil(main.MarketerProfile, u.id, company_id=None)
        r = self.client.post('/admin/accreditation/decide',
                             json={'tipo': 'anunciante', 'user_id': u.id,
                                   'decision': 'approved', 'decidido_por': 'JC'},
                             headers=self._admin())
        self.assertEqual(r.status_code, 409, r.text[:300])
        self.assertIn('vincular_company_id', r.json()['detail'])

    def test_se_puede_vincular_y_aprobar_en_la_misma_decision(self):
        u = self._usuario('marketer')
        emp = self._empresa()
        self._perfil(main.MarketerProfile, u.id, company_id=None)
        r = self.client.post('/admin/accreditation/decide',
                             json={'tipo': 'anunciante', 'user_id': u.id,
                                   'decision': 'approved', 'decidido_por': 'JC',
                                   'vincular_company_id': emp.id},
                             headers=self._admin())
        self.assertEqual(r.status_code, 200, r.text[:300])
        self.assertEqual(r.json()['company_id'], emp.id)

    def test_no_se_vincula_a_una_empresa_inexistente(self):
        u = self._usuario('marketer')
        self._perfil(main.MarketerProfile, u.id, company_id=None)
        r = self.client.post('/admin/accreditation/decide',
                             json={'tipo': 'anunciante', 'user_id': u.id,
                                   'decision': 'approved', 'decidido_por': 'JC',
                                   'vincular_company_id': 99999999},
                             headers=self._admin())
        self.assertEqual(r.status_code, 404)

    def test_rechazar_guarda_el_motivo(self):
        u = self._usuario('organizer')
        self._perfil(main.OrganizerProfile, u.id, company_id=self._empresa().id)
        r = self.client.post('/admin/accreditation/decide',
                             json={'tipo': 'organizador', 'user_id': u.id,
                                   'decision': 'rejected',
                                   'motivo': 'El cargo no coincide con el poder',
                                   'decidido_por': 'JC'},
                             headers=self._admin())
        self.assertEqual(r.status_code, 200, r.text[:300])
        self.assertEqual(r.json()['estado'], 'rejected')
        self.assertIn('no coincide', r.json()['motivo'])

    def test_pedir_antecedentes_mantiene_la_cuenta_pendiente(self):
        u = self._usuario('organizer')
        self._perfil(main.OrganizerProfile, u.id, company_id=self._empresa().id)
        r = self.client.post('/admin/accreditation/decide',
                             json={'tipo': 'organizador', 'user_id': u.id,
                                   'decision': 'more_info',
                                   'motivo': 'Falta el certificado de vigencia',
                                   'decidido_por': 'JC'},
                             headers=self._admin())
        self.assertEqual(r.status_code, 200, r.text[:300])
        self.assertEqual(r.json()['estado'], 'pending')
        self.assertIn('certificado', r.json()['motivo'])

    def test_decision_invalida_rechazada(self):
        u = self._usuario('organizer')
        self._perfil(main.OrganizerProfile, u.id, company_id=self._empresa().id)
        r = self.client.post('/admin/accreditation/decide',
                             json={'tipo': 'organizador', 'user_id': u.id,
                                   'decision': 'aprobadisimo'},
                             headers=self._admin())
        self.assertEqual(r.status_code, 422)

    def test_tipo_invalido_rechazado(self):
        r = self.client.post('/admin/accreditation/decide',
                             json={'tipo': 'presidente', 'user_id': 1,
                                   'decision': 'approved'},
                             headers=self._admin())
        self.assertEqual(r.status_code, 422)


# ══════════════════════════════════════════════════════════════════
# E. EL AVISO AL REVISOR NO LLEVA DATOS PERSONALES NI DOCUMENTOS
# ══════════════════════════════════════════════════════════════════

class TestAvisoDeRevision(Base):

    def test_el_aviso_no_lleva_documentos_ni_credenciales(self):
        import inspect
        cuerpo = inspect.getsource(main._notificar_revision_acreditacion)
        for prohibido in ('cargo_doc_bytes', 'cargo_doc_hash', 'password',
                          'make_token', 'ADMIN_SECRET'):
            self.assertNotIn(prohibido, cuerpo,
                             f'el correo de revisión no puede llevar {prohibido}')

    def test_el_aviso_nunca_lanza(self):
        # Sin proveedor de correo la solicitud sigue existiendo igual: la
        # notificación es un aviso, no la autorización.
        ok = main._notificar_revision_acreditacion(
            perfil_tipo='organizador', user_id=1, company_id=None,
            company_name='X', country='CL', tax_id_norm='',
            cargo='Gerente', tiene_documento=False, motivo='prueba')
        self.assertIn(ok, (True, False))


# ══════════════════════════════════════════════════════════════════
# F. LOS DOS FORMULARIOS PUBLICADOS
# ══════════════════════════════════════════════════════════════════

def _js(ruta):
    s = open(ruta, encoding='utf-8').read()
    bloques = re.findall(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', s, re.S)
    return s, '\n'.join(bloques)


class TestFormularioCrearConsulta(Base):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.html, cls.js = _js('preferendum_organizer.html')

    def test_pregunta_a_quien_representa(self):
        self.assertIn('id="r-org-type"', self.html)
        for valor in ('value="person"', 'value="company"', 'value="public"'):
            self.assertIn(valor, self.html)

    def test_pide_identificacion_tributaria_cargo_y_web(self):
        for campo in ('id="r-tax-id"', 'id="r-cargo"', 'id="r-web"',
                      'id="r-country"'):
            self.assertIn(campo, self.html)

    def test_el_registro_envia_org_type(self):
        self.assertIn('org_type: tipo', self.js,
                      'sin org_type todo perfil nacía person y se aprobaba solo')

    def test_el_registro_envia_los_datos_que_el_servidor_verifica(self):
        for clave in ('cuerpo.company_name', 'cuerpo.company_rut',
                      'cuerpo.company_web', 'cuerpo.cargo'):
            self.assertIn(clave, self.js)

    def test_el_registro_ofrece_la_via_del_supervisor(self):
        self.assertIn('id="r-tiene-supervisor"', self.html)
        self.assertIn('cuerpo.is_supervisor', self.js)
        self.assertIn('cuerpo.supervisor_email', self.js)

    def test_ya_no_envia_el_campo_inexistente_organization(self):
        self.assertNotIn('organization:org', self.js.replace(' ', ''),
                         'el servidor descartaba ese campo en silencio')

    def test_consulta_el_estado_de_acreditacion(self):
        self.assertIn('/organizer/status', self.js)
        self.assertIn('_estadoOrganizador', self.js)

    def test_oculta_nueva_consulta_cuando_no_puede_publicar(self):
        self.assertIn('can_create_consultations', self.js)
        self.assertRegex(self.js, r"nueva-consulta-cta")

    def test_conecta_la_subida_del_documento_de_cargo(self):
        self.assertIn('/organizer/upload-cargo-doc', self.js)
        self.assertIn('subirDocCargo', self.js)
        self.assertIn('id="acred-subir-doc"', self.html)

    def test_escapa_el_html_del_estado(self):
        self.assertIn('_escaparHtml(est.status', self.js)

    def test_el_campo_requerido_no_falla_en_silencio(self):
        # Un retorno mudo en un botón es indistinguible de "no pasó nada".
        self.assertIn("err.textContent = 'Indica la razón social", self.js)
        self.assertIn("err.textContent = 'Indica tu cargo", self.js)


class TestFormularioCampanas(Base):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.html, cls.js = _js('marketer_portal.html')

    def test_pide_identificacion_tributaria_web_y_cargo(self):
        for campo in ('id="reg-tax-id"', 'id="reg-web"', 'id="reg-cargo"'):
            self.assertIn(campo, self.html)

    def test_el_registro_envia_esos_datos(self):
        for clave in ('company_rut: taxId', 'company_web: web', 'cargo: cargo'):
            self.assertIn(clave, self.js)

    def test_el_registro_ofrece_la_via_del_supervisor(self):
        self.assertIn('id="reg-tiene-supervisor"', self.html)
        self.assertIn('id="reg-sup-email"', self.html)
        self.assertIn('is_supervisor: !tieneSup', self.js)
        self.assertIn('supervisor_email: tieneSup', self.js)

    def test_el_aviso_dice_a_quien_se_pidio_la_autorizacion(self):
        self.assertIn('supervisorSolicitado', self.js)
        self.assertIn('_escaparHtml(supervisorSolicitado)', self.js)

    def test_sigue_consultando_el_estado_antes_de_abrir_el_panel(self):
        self.assertIn('/marketer/status', self.js)
        self.assertIn('_estadoAnunciante', self.js)

    def test_los_dos_portales_piden_la_misma_identidad(self):
        _, js_org = _js('preferendum_organizer.html')
        for texto in ('Identificación tributaria o registral',):
            self.assertIn(texto, self.html)
            self.assertIn(texto, open('preferendum_organizer.html',
                                      encoding='utf-8').read())


# ══════════════════════════════════════════════════════════════════
# G. LOS RECORRIDOS REALES DE REGISTRO, EN LOS DOS PORTALES
# ══════════════════════════════════════════════════════════════════

# RUT con dígito verificador válido: el que el formulario enviará de verdad.
RUT_A = '76.123.456-0'
RUT_B = '77.999.111-3'


class _Registro:
    """El alta por la ruta real, no por inserción directa en la base.

    Sin red: las verificaciones externas (SII, sitio web) se sustituyen por
    respuestas deterministas. Lo que se comprueba es la acreditación, no la
    disponibilidad del SII.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._web = main._verify_company_web
        cls._dom = main._verify_email_domain
        cls._get = main._requests.get
        main._verify_company_web = lambda *a, **k: {'valid': True}
        main._verify_email_domain = lambda *a, **k: {'valid': True}

        def _sin_red(*a, **k):
            raise RuntimeError('sin red en pruebas')
        main._requests.get = _sin_red

    @classmethod
    def tearDownClass(cls):
        main._verify_company_web = cls._web
        main._verify_email_domain = cls._dom
        main._requests.get = cls._get
        super().tearDownClass()

    def _alta(self, **extra):
        email = _uniq('rep') + '@empresa-ficticia.invalid'
        cuerpo = dict(self.CUERPO_BASE)
        cuerpo.update({'email': email, 'password': 'Clave-larga-1234',
                       'name': 'Representante Ficticio'})
        cuerpo.update(extra)
        r = self.client.post(self.RUTA_ALTA, json=cuerpo, headers=_ip())
        return r, email

    def _perfil_de(self, email):
        u = self.db.query(main.User).filter(
            main.func.lower(main.User.email) == email.lower()).first()
        self.db.expire_all()
        p = self.db.query(self.PERFIL).filter(
            self.PERFIL.user_id == u.id).first()
        return u, p

    def test_una_empresa_nace_pendiente_y_vinculada(self):
        r, email = self._alta(org_type='company', company_name='Delta SpA',
                              company_rut=RUT_A, country='CL',
                              cargo='Gerente', company_web='https://delta.cl')
        self.assertEqual(r.status_code, 200, r.text[:300])
        u, p = self._perfil_de(email)
        self.assertEqual(p.status, 'pending',
                         'el primer representante no se aprueba solo')
        self.assertFalse(p.is_supervisor,
                         'una organización no nace supervisora de sí misma')
        self.assertIsNotNone(p.company_id, 'con RUT válido queda vinculada')
        emp = self.db.query(main.Company).filter(
            main.Company.id == p.company_id).first()
        self.assertEqual(emp.tax_id_norm, main._norm_tax_id(RUT_A))
        self.assertEqual(emp.country, 'CL')
        self.assertTrue(emp.verified_tax_id)

    def test_dos_representantes_del_mismo_rut_comparten_empresa(self):
        _, e1 = self._alta(org_type='company', company_name='Épsilon SpA',
                           company_rut=RUT_B, country='CL', cargo='Gerente')
        _, e2 = self._alta(org_type='company', company_name='EPSILON S.P.A.',
                           company_rut=main._norm_tax_id(RUT_B), country='cl',
                           cargo='Subgerente')
        _, p1 = self._perfil_de(e1)
        _, p2 = self._perfil_de(e2)
        self.assertIsNotNone(p1.company_id)
        self.assertEqual(p1.company_id, p2.company_id,
                         'la identidad es el RUT, no cómo se escriba el nombre')
        self.assertEqual(p2.status, 'pending',
                         'el segundo tampoco se aprueba solo: lo autoriza un '
                         'supervisor acreditado de su misma empresa')

    def test_sin_identificacion_queda_pendiente_y_sin_vincular(self):
        r, email = self._alta(org_type='company', company_name='Sin RUT SpA',
                              company_rut='', country='CL', cargo='Gerente')
        self.assertEqual(r.status_code, 200, r.text[:300])
        _, p = self._perfil_de(email)
        self.assertEqual(p.status, 'pending')
        self.assertIsNone(p.company_id,
                          'sin identificación verificable no se inventa una '
                          'empresa: queda para revisión excepcional')

    def test_un_rut_invalido_no_se_marca_como_verificado(self):
        r, email = self._alta(org_type='company', company_name='Zeta SpA',
                              company_rut='76.123.456-9', country='CL',
                              cargo='Gerente')
        self.assertEqual(r.status_code, 200, r.text[:300])
        _, p = self._perfil_de(email)
        self.assertFalse(p.rut_verified)
        if p.company_id:
            emp = self.db.query(main.Company).filter(
                main.Company.id == p.company_id).first()
            self.assertFalse(emp.verified_tax_id,
                             'un dígito verificador que no cuadra no es una '
                             'identificación verificada')

    def test_una_empresa_pendiente_no_puede_operar(self):
        r, email = self._alta(org_type='company', company_name='Eta SpA',
                              company_rut=RUT_A, country='CL', cargo='Gerente')
        u, p = self._perfil_de(email)
        self.assertEqual(p.status, 'pending')
        bloqueada = self.OPERACION(self, u, email)
        self.assertEqual(bloqueada.status_code, 403,
                         f'una cuenta pendiente no opera: {bloqueada.text[:200]}')

    def test_la_solicitud_al_supervisor_se_crea_de_verdad(self):
        jefe = _uniq('jefe') + '@empresa-ficticia.invalid'
        r, email = self._alta(org_type='company', company_name='Theta SpA',
                              company_rut=RUT_B, country='CL', cargo='Analista',
                              is_supervisor=False, supervisor_email=jefe,
                              supervisor_name='Jefa Ficticia')
        self.assertEqual(r.status_code, 200, r.text[:300])
        u, _ = self._perfil_de(email)
        req = self.db.query(self.SOLICITUD).filter(
            self.SOLICITUD.employee_user_id == u.id).first()
        self.assertIsNotNone(req, 'la vía del supervisor tiene que crear la '
                                  'solicitud que el portal ahora ofrece')
        self.assertTrue(main._same_email(req.supervisor_email, jefe))
        self.assertEqual(req.status, 'pending')


class TestRegistroOrganizador(_Registro, Base):
    PERFIL = main.OrganizerProfile
    SOLICITUD = main.AuthorizationRequest
    RUTA_ALTA = '/organizer/register'
    CUERPO_BASE = {'phone': '+56900000000'}

    @staticmethod
    def OPERACION(self, u, email):
        return self.client.post(
            '/organizer/consultations',
            json={'title': _uniq('C'), 'context': 'Ficticia',
                  'options': ['A', 'B'], 'closes_at': '2027-06-30T23:59:59',
                  'creator_type': 'company', 'scope': 'country',
                  'scope_country': 'CL'},
            headers=self.auth(u.id, 'organizer'))

    def test_un_ciudadano_conserva_su_procedimiento(self):
        r, email = self._alta(org_type='person')
        self.assertEqual(r.status_code, 200, r.text[:300])
        _, p = self._perfil_de(email)
        self.assertEqual(p.status, 'approved',
                         'un ciudadano a título personal no necesita que '
                         'nadie lo acredite: se representa a sí mismo')
        self.assertTrue(p.is_supervisor)
        self.assertIsNone(p.company_id, 'una persona no es una empresa')


class TestRegistroAnunciante(_Registro, Base):
    PERFIL = main.MarketerProfile
    SOLICITUD = main.MarketerAuthorizationRequest
    RUTA_ALTA = '/marketer/register'
    CUERPO_BASE = {'phone': '+56900000000',
                   'business_category': 'retail_comercio'}

    @staticmethod
    def OPERACION(self, u, email):
        return self.client.post(
            '/payments/demo-credits', json={'credits': 100},
            headers=self.auth(u.id, 'marketer'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
