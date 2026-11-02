"""test_voto_verificacion_facial.py — NO SE VOTA SIN VERIFICAR LA CARA.

El defecto, medido: el bloqueo era `if user.selfie_verified:`. Es decir, se
le exigia la verificacion facial a quien YA habia probado su cara y se le
perdonaba a quien NO. Reproducido sobre una copia de produccion con un clon
del perfil que voto en la consulta destacada (selfie_verified = false):
POST /debates/{id}/vote con face_token vacio devolvio 200 y registro el
voto con su codigo de comprobacion.

Aqui se fija lo contrario: se exige SIEMPRE, tiene que ser reciente, de
ESTE ciudadano, para ESTA consulta, y de UN SOLO USO.

La identidad y la preferencia siguen separadas: estas pruebas nunca leen
ni comparan la opcion elegida por una persona concreta.
"""
import json
import os
import tempfile
import unittest
import uuid

_TMP = tempfile.mkdtemp(prefix='prefy_face_')
os.environ['DATABASE_URL'] = f'sqlite:///{os.path.join(_TMP, "face.db")}'
os.environ.setdefault('ADMIN_SECRET', 'face-solo-local')
os.environ.setdefault('JWT_SECRET', 'face-solo-local')
os.environ.pop('ADMIN_SECRET_CANARY', None)

import bcrypt                                    # noqa: E402
import jwt as _jwt                                # noqa: E402
from fastapi.testclient import TestClient        # noqa: E402

import main                                      # noqa: E402

from datetime import datetime, timedelta         # noqa: E402


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

    def _votante(self, selfie=False):
        u = main.User(name='Votante', email=_uniq('v') + '@test.invalid',
                      password=bcrypt.hashpw(b'x', bcrypt.gensalt()).decode(),
                      country='CL', county='Vitacura', gender='M',
                      dob='1980-01-01', se_tier='B', role='voter',
                      email_verified=True, phone_verified=True,
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
            scope='country', scope_country='CL',
            target_gender='all', target_age_min=18, target_age_max=99,
            target_se_tiers='A,B,C,D', results_visibility='public')
        self.db.add(d); self.db.commit(); self.db.refresh(d)
        return d

    def _verificacion(self, user, debate, *, minutos=5, jti=None,
                      registrar=True):
        """Lo que deja /debates/{id}/face-token tras una comparacion real."""
        jti = jti or uuid.uuid4().hex
        if registrar:
            self.db.add(main.OTPCode(
                user_id=user.id, email=user.email, code=jti,
                channel='face_vote', used=False,
                expires_at=datetime.utcnow() + timedelta(minutes=minutos)))
            self.db.commit()
        return _jwt.encode({'sub': user.id, 'debate_id': debate.id,
                            'type': 'face_vote', 'jti': jti,
                            'exp': datetime.utcnow() + timedelta(minutes=minutos)},
                           main.SECRET, algorithm='HS256')

    def _votar(self, debate, cab, face=''):
        return self.client.post(
            f'/debates/{debate.id}/vote',
            json={'option_index': 0, 'vote_chain': [], 'device_fp': 'fp',
                  'face_token': face},
            headers=cab)

    def _papeletas(self, debate):
        return self.db.query(main.DebateVote).filter(
            main.DebateVote.debate_id == debate.id).count()


class TestNoSeVotaSinCara(Base):

    def test_sin_token_no_se_vota_aunque_no_haya_verificado_nunca(self):
        """EL defecto. Este era el caso que pasaba: selfie_verified=false."""
        u, cab = self._votante(selfie=False)
        d = self._consulta()
        r = self._votar(d, cab)
        self.assertEqual(r.status_code, 403, r.text[:200])
        self.assertIn('facial', r.json()['detail'].lower())
        self.assertEqual(self._papeletas(d), 0, 'se registro una papeleta')

    def test_sin_token_tampoco_con_selfie_verificada(self):
        u, cab = self._votante(selfie=True)
        d = self._consulta()
        r = self._votar(d, cab)
        self.assertEqual(r.status_code, 403, r.text[:200])
        self.assertEqual(self._papeletas(d), 0)

    def test_token_basura(self):
        u, cab = self._votante()
        d = self._consulta()
        r = self._votar(d, cab, 'esto-no-es-un-token')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self._papeletas(d), 0)

    def test_token_firmado_con_otra_clave(self):
        u, cab = self._votante()
        d = self._consulta()
        falso = _jwt.encode({'sub': u.id, 'debate_id': d.id,
                             'type': 'face_vote', 'jti': uuid.uuid4().hex,
                             'exp': datetime.utcnow() + timedelta(minutes=5)},
                            'otra-clave-cualquiera', algorithm='HS256')
        r = self._votar(d, cab, falso)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self._papeletas(d), 0)

    def test_token_bien_firmado_pero_SIN_verificacion_detras(self):
        """Firmar no es verificar: sin la fila que deja la comparacion
        facial, el token no vale."""
        u, cab = self._votante()
        d = self._consulta()
        tk = self._verificacion(u, d, registrar=False)
        r = self._votar(d, cab, tk)
        self.assertEqual(r.status_code, 403, r.text[:200])
        self.assertEqual(self._papeletas(d), 0)

    def test_token_de_OTRA_persona(self):
        u1, cab1 = self._votante()
        u2, _ = self._votante()
        d = self._consulta()
        tk = self._verificacion(u2, d)
        r = self._votar(d, cab1, tk)
        self.assertEqual(r.status_code, 403, r.text[:200])
        self.assertEqual(self._papeletas(d), 0)

    def test_token_de_OTRA_consulta(self):
        u, cab = self._votante()
        d1 = self._consulta()
        d2 = self._consulta()
        tk = self._verificacion(u, d2)
        r = self._votar(d1, cab, tk)
        self.assertEqual(r.status_code, 403, r.text[:200])
        self.assertEqual(self._papeletas(d1), 0)

    def test_token_expirado(self):
        u, cab = self._votante()
        d = self._consulta()
        tk = self._verificacion(u, d, minutos=-1)
        r = self._votar(d, cab, tk)
        self.assertEqual(r.status_code, 403, r.text[:200])
        self.assertIn('expir', r.json()['detail'].lower())
        self.assertEqual(self._papeletas(d), 0)

    def test_token_antiguo_sin_jti_no_se_acepta(self):
        """Los tokens emitidos antes de esta correccion eran reusables."""
        u, cab = self._votante()
        d = self._consulta()
        antiguo = _jwt.encode({'sub': u.id, 'debate_id': d.id,
                               'type': 'face_vote',
                               'exp': datetime.utcnow() + timedelta(minutes=5)},
                              main.SECRET, algorithm='HS256')
        r = self._votar(d, cab, antiguo)
        self.assertEqual(r.status_code, 403, r.text[:200])
        self.assertEqual(self._papeletas(d), 0)

    def test_tipo_de_token_equivocado(self):
        u, cab = self._votante()
        d = self._consulta()
        otro = _jwt.encode({'sub': u.id, 'debate_id': d.id,
                            'type': 'face_login', 'jti': uuid.uuid4().hex,
                            'exp': datetime.utcnow() + timedelta(minutes=5)},
                           main.SECRET, algorithm='HS256')
        r = self._votar(d, cab, otro)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self._papeletas(d), 0)


class TestUnaVerificacionUnVoto(Base):

    def test_con_verificacion_valida_si_se_vota(self):
        u, cab = self._votante()
        d = self._consulta()
        tk = self._verificacion(u, d)
        r = self._votar(d, cab, tk)
        self.assertEqual(r.status_code, 200, r.text[:300])
        self.assertTrue(r.json().get('verify_code'),
                        'falta el codigo de comprobacion del voto')
        self.assertEqual(self._papeletas(d), 1)

    def test_la_verificacion_se_CONSUME(self):
        u, cab = self._votante()
        d = self._consulta()
        jti = uuid.uuid4().hex
        tk = self._verificacion(u, d, jti=jti)
        self.assertEqual(self._votar(d, cab, tk).status_code, 200)
        fila = self.db.query(main.OTPCode).filter(
            main.OTPCode.code == jti).first()
        self.db.refresh(fila)
        self.assertTrue(fila.used, 'la verificacion no se marco usada')

    def test_la_misma_verificacion_no_sirve_en_otra_consulta(self):
        u, cab = self._votante()
        d1 = self._consulta()
        d2 = self._consulta()
        tk = self._verificacion(u, d1)
        self.assertEqual(self._votar(d1, cab, tk).status_code, 200)
        # El token esta ligado a d1; en d2 no vale ni reemitiendolo con el
        # mismo jti, porque ya se consumio.
        tk2 = _jwt.encode({'sub': u.id, 'debate_id': d2.id,
                           'type': 'face_vote',
                           'jti': _jwt.decode(tk, main.SECRET,
                                              algorithms=['HS256'])['jti'],
                           'exp': datetime.utcnow() + timedelta(minutes=5)},
                          main.SECRET, algorithm='HS256')
        r = self._votar(d2, cab, tk2)
        self.assertEqual(r.status_code, 403, r.text[:200])
        self.assertEqual(self._papeletas(d2), 0)

    def test_el_voto_no_queda_ligado_a_la_identidad(self):
        """La correccion no debe romper la separacion identidad/voto."""
        u, cab = self._votante()
        d = self._consulta()
        tk = self._verificacion(u, d)
        self.assertEqual(self._votar(d, cab, tk).status_code, 200)
        papeleta = self.db.query(main.DebateVote).filter(
            main.DebateVote.debate_id == d.id).first()
        self.assertIsNone(papeleta.voter_id,
                          'la papeleta no puede guardar quien voto')


class TestResultadosTrasVotar(Base):

    def test_quien_voto_ve_el_escrutinio_completo(self):
        u, cab = self._votante()
        d = self._consulta()
        tk = self._verificacion(u, d)
        self.assertEqual(self._votar(d, cab, tk).status_code, 200)
        r = self.client.get(f'/debates/{d.id}/results', headers=cab)
        self.assertEqual(r.status_code, 200, r.text[:200])
        deb = r.json()['debate']
        self.assertEqual(deb['total_votes'], 1)
        self.assertTrue(deb['results'], 'sin results no hay grafico posible')
        for fila in deb['results']:
            for campo in ('option', 'count', 'pct'):
                self.assertIn(campo, fila)
        self.assertEqual(sum(f['count'] for f in deb['results']), 1)

    def test_quien_no_voto_no_ve_el_escrutinio(self):
        u, cab = self._votante()
        d = self._consulta()
        r = self.client.get(f'/debates/{d.id}/results', headers=cab)
        self.assertEqual(r.status_code, 403, r.text[:200])

    def test_una_consulta_con_resultados_reservados_no_los_entrega(self):
        """Si la consulta reserva sus resultados, se respeta: el portal
        muestra el aviso, no el grafico. No se cambia la politica."""
        u, cab = self._votante()
        d = self._consulta()
        d.results_visibility = 'restricted'
        self.db.commit()
        tk = self._verificacion(u, d)
        self.assertEqual(self._votar(d, cab, tk).status_code, 200)
        r = self.client.get(f'/debates/{d.id}/results', headers=cab)
        self.assertEqual(r.status_code, 404,
                         'una consulta reservada no entrega resultados')


class TestElPortal(Base):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.portal = open('voter_portal.html', encoding='utf-8').read()

    def test_pide_la_camara_SIEMPRE_antes_de_votar(self):
        i = self.portal.index('faceToken = await requestFaceToken(debateId)')
        ventana = self.portal[max(0, i - 400):i]
        self.assertNotIn('if (userSelfieVerified)', ventana,
                         'la camara no puede depender de un indicador del '
                         'navegador')
        self.assertIn('let faceToken', ventana)

    def test_el_grafico_sale_de_la_respuesta_no_de_currentDebate(self):
        self.assertIn('const etiquetas = resultsList.map(r => r.option)',
                      self.portal)

    def test_los_resultados_no_fallan_en_silencio(self):
        self.assertIn('avisoResultados', self.portal)
        self.assertIn('resultados reservados', self.portal)
        self.assertIn('a quienes ya votaron', self.portal)

    def test_sigue_mostrando_el_codigo_de_comprobacion(self):
        self.assertIn('data.verify_code', self.portal)

    def test_a_quien_le_falta_la_verificacion_se_le_dice_donde_ir(self):
        self.assertIn('face-ir-verificar', self.portal)
        self.assertIn('showVerifyScreen()', self.portal)


if __name__ == '__main__':
    unittest.main(verbosity=2)
