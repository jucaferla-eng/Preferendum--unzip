"""test_experiencia_movil.py — las correcciones vistas en las capturas.

Cada clase corresponde a un problema real fotografiado en Android, y cada
prueba falla si vuelve la causa concreta, no si cambia un texto.
"""
import json
import os
import re
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta

_TMP = tempfile.mkdtemp(prefix='prefy_movil_')
os.environ['DATABASE_URL'] = f'sqlite:///{os.path.join(_TMP, "m.db")}'
os.environ.setdefault('ADMIN_SECRET', 'movil-solo-local')
os.environ.setdefault('JWT_SECRET', 'movil-solo-local')
os.environ.pop('ADMIN_SECRET_CANARY', None)

CUENTA = 'prueba.movil@test.invalid'
os.environ['PREFY_TEST_VOTE_ACCOUNTS'] = CUENTA

import bcrypt                                    # noqa: E402
from fastapi.testclient import TestClient        # noqa: E402

import main                                      # noqa: E402

PORTAL = open('voter_portal.html', encoding='utf-8').read()
APP = open('App.js', encoding='utf-8').read()


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

    def _usuario(self, email=None, selfie=True):
        u = main.User(name='Votante Ficticio', email=email or (_uniq('v') + '@test.invalid'),
                      password=bcrypt.hashpw(b'x', bcrypt.gensalt()).decode(),
                      country='CL', county='Vitacura', gender='M', dob='1980-01-01',
                      se_tier='B', role='voter', phone='+56900000000',
                      email_verified=True, phone_verified=True,
                      selfie_verified=selfie, verify_level=3, is_verified=True)
        self.db.add(u); self.db.commit(); self.db.refresh(u)
        h = _ip()
        h['Authorization'] = 'Bearer ' + main.make_token(u.id, 'voter')
        return u, h


# ══════════════════════════════════════════════════════════════════
# PUNTO 1 — SAFE AREAS
# ══════════════════════════════════════════════════════════════════

class TestSafeAreas(Base):
    """La cabecera se dibujaba bajo el reloj y la bateria."""

    def test_el_viewport_llega_a_los_bordes(self):
        """Sin viewport-fit=cover, env(safe-area-inset-*) devuelve 0 y
        cualquier margen calculado con ella no hace nada."""
        self.assertIn('viewport-fit=cover', PORTAL)

    def test_la_cabecera_respeta_la_barra_de_estado(self):
        i = PORTAL.index('.topbar{')
        bloque = PORTAL[i:i + 700]
        self.assertIn('env(safe-area-inset-top', bloque,
                      'la cabecera no respeta la barra de estado')
        self.assertIn('env(safe-area-inset-left', bloque)
        self.assertIn('env(safe-area-inset-right', bloque)

    def test_no_se_usan_margenes_fijos_para_la_barra_de_estado(self):
        """Un valor fijo solo acierta en un modelo de telefono."""
        i = PORTAL.index('.topbar{')
        bloque = PORTAL[i:i + 700]
        self.assertNotRegex(bloque, r'padding-top:\s*\d+px\s*;.*safe-area',
                            'margen fijo para la barra de estado')

    def test_hay_valor_de_respaldo_para_escritorio(self):
        """Un navegador que no define esas variables no debe romperse."""
        for m in re.findall(r'env\(safe-area-inset-\w+[^)]*\)', PORTAL):
            self.assertIn(',', m, f'{m} no tiene valor de respaldo')

    def test_la_barra_inferior_respeta_la_zona_de_gestos(self):
        i = PORTAL.index('.bottomnav{')
        self.assertIn('env(safe-area-inset-bottom', PORTAL[i:i + 400])

    def test_el_contenido_no_queda_bajo_la_barra_inferior(self):
        self.assertIn('padding-bottom:calc(72px + env(safe-area-inset-bottom', PORTAL)


# ══════════════════════════════════════════════════════════════════
# PUNTO 2 — EL SELECTOR DE IDIOMA
# ══════════════════════════════════════════════════════════════════

class TestSelectorDeIdioma(Base):
    """Flotaba sobre el contenido y tapaba el autor y las alternativas."""

    def test_ya_no_flota_sobre_el_contenido(self):
        i = PORTAL.index('#gt-float{')
        bloque = PORTAL[i:i + 300]
        self.assertNotIn('position:fixed', bloque,
                         'el selector sigue flotando sobre el contenido')
        self.assertNotIn('z-index:99999', bloque)

    def test_vive_dentro_de_la_cabecera(self):
        cab = PORTAL.index('<div class="topbar">')
        fin = PORTAL.index('</div>', PORTAL.index('<!-- BOTTOM NAV', cab)) \
            if '<!-- BOTTOM NAV' in PORTAL[cab:cab + 4000] else cab + 4000
        self.assertIn('id="gt-float"', PORTAL[cab:fin],
                      'el selector tiene que estar en la cabecera')

    def test_no_quedan_coordenadas_fijas_por_ancho(self):
        self.assertNotIn('#gt-float{top:10px;right:240px;}', PORTAL)

    def test_sigue_estando_el_motor_de_traduccion_propio(self):
        """No se rompe el sistema multilingue de Preferendum."""
        self.assertIn('data-pref-lang-selector', PORTAL)
        self.assertIn('id="gt-widget"', PORTAL)


# ══════════════════════════════════════════════════════════════════
# PUNTO 3 — LA BARRA DE TRADUCCION DE GOOGLE
# ══════════════════════════════════════════════════════════════════

class TestTraduccionDelNavegador(Base):
    """Chrome traducia la portada y convertia «preferendum» en
    «prefiero endum»."""

    def test_la_portada_no_pide_traduccion_automatica(self):
        r = self.client.get('/', headers=_ip())
        self.assertEqual(r.status_code, 200)
        self.assertIn('name="google" content="notranslate"', r.text)
        self.assertIn('translate="no"', r.text)

    def test_el_portal_del_votante_tampoco(self):
        self.assertIn('name="google" content="notranslate"', PORTAL)

    def test_la_marca_queda_protegida_en_la_cabecera(self):
        self.assertIn('class="topbar-brand" translate="no"', PORTAL,
                      'la marca puede volver a traducirse')

    def test_la_portada_conserva_su_sistema_de_idiomas(self):
        r = self.client.get('/', headers=_ip())
        self.assertIn('/lang.js', r.text)
        self.assertIn('/translate.js', r.text)


# ══════════════════════════════════════════════════════════════════
# PUNTO 4 — EL BOTON Y EL GESTO ATRAS (contenedor Android)
# ══════════════════════════════════════════════════════════════════

class TestBotonAtras(Base):
    """Atras cerraba la aplicacion en vez de volver atras."""

    def test_existe_un_manejador_del_boton_atras(self):
        self.assertIn('BackHandler', APP,
                      'sin manejador, Android cierra la aplicacion')
        self.assertIn("addEventListener('hardwareBackPress'", APP)

    def test_retrocede_en_el_webview_antes_de_salir(self):
        i = APP.index("addEventListener('hardwareBackPress'")
        bloque = APP[max(0, i - 700):i]
        self.assertIn('goBack()', bloque)
        self.assertIn('return true', bloque,
                      'hay que consumir el evento o la aplicacion se cierra igual')
        self.assertIn('return false', bloque,
                      'en la pantalla principal debe salir con el '
                      'comportamiento normal del sistema')

    def test_sabe_si_hay_historial_detras(self):
        self.assertIn('onNavigationStateChange', APP)
        self.assertIn('nav.canGoBack', APP)

    def test_se_desengancha_al_desmontar(self):
        """Un manejador que se acumula produce comportamientos duplicados."""
        i = APP.index("addEventListener('hardwareBackPress'")
        self.assertIn('sub.remove()', APP[i:i + 300])

    def test_solo_en_android(self):
        i = APP.index("addEventListener('hardwareBackPress'")
        self.assertIn("Platform.OS !== 'android'", APP[max(0, i - 700):i])


# ══════════════════════════════════════════════════════════════════
# PUNTO 5 — PRESENTACION
# ══════════════════════════════════════════════════════════════════

class TestPresentacion(Base):

    def test_sin_desplazamiento_horizontal_accidental(self):
        self.assertIn('overflow-x:hidden', PORTAL)

    def test_el_nombre_largo_no_desborda_la_cabecera(self):
        self.assertIn('text-overflow:ellipsis', PORTAL)
        self.assertIn('max-width:38vw', PORTAL)


# ══════════════════════════════════════════════════════════════════
# PUNTO 6 — CONTADORES COHERENTES
# ══════════════════════════════════════════════════════════════════

class TestContadoresCoherentes(Base):
    """«⬡ 0 votos» arriba y «Participación: 2 votos» abajo, en la misma
    pantalla y la misma consulta."""

    def _consulta(self):
        d = main.Debate(
            title=_uniq('Consulta'), context='Ficticia',
            options=json.dumps(['A', 'B']), status='live', creator_id=1,
            closes_at=datetime.utcnow() + timedelta(days=30),
            scope='country', scope_country='CL', target_gender='all',
            target_age_min=18, target_age_max=99, target_se_tiers='A,B,C,D',
            results_visibility='public')
        self.db.add(d); self.db.commit(); self.db.refresh(d)
        return d

    def test_la_cabecera_usa_la_participacion_no_el_escrutinio(self):
        """La cifra de la cabecera no puede depender de si se tiene
        acceso al reparto por alternativa."""
        i = PORTAL.index('function renderDebate(')
        bloque = PORTAL[i:i + 9000]
        self.assertIn('⬡ ${participacion}', bloque,
                      'la cabecera volveria a mostrar 0 sin escrutinio')
        self.assertNotIn('⬡ ${total}', bloque)

    def test_el_aviso_ya_no_repite_la_cifra(self):
        """Dos sitios con la misma cifra es como se produjo la
        contradiccion."""
        i = PORTAL.index('const motivoSinEscrutinio')
        bloque = PORTAL[i:i + 900]
        self.assertNotIn('Participación hasta ahora', bloque)

    def test_el_servidor_informa_la_participacion_real(self):
        d = self._consulta()
        u, cab = self._usuario()
        r = self.client.get(f'/debates/{d.id}', headers=cab)
        self.assertEqual(r.status_code, 200, r.text[:200])
        self.assertEqual(r.json()['total_votes'], 0)

    def test_un_voto_simulado_no_mueve_la_participacion(self):
        d = self._consulta()
        # Una designada propia de esta clase: el correo es unico en la
        # tabla, asi que no se puede reutilizar el de la otra.
        correo = _uniq('designada') + '@test.invalid'
        previo = os.environ['PREFY_TEST_VOTE_ACCOUNTS']
        os.environ['PREFY_TEST_VOTE_ACCOUNTS'] = correo
        self.addCleanup(os.environ.__setitem__,
                        'PREFY_TEST_VOTE_ACCOUNTS', previo)
        u, cab = self._usuario(email=correo)
        antes = self.client.get(f'/debates/{d.id}', headers=cab).json()['total_votes']
        v = self.client.post(f'/debates/{d.id}/vote',
                             json={'option_index': 0, 'vote_chain': [],
                                   'face_token': ''}, headers=cab)
        self.assertEqual(v.status_code, 200, v.text[:200])
        self.assertTrue(v.json()['voto_de_prueba'])
        despues = self.client.get(f'/debates/{d.id}', headers=cab).json()['total_votes']
        self.assertEqual(antes, despues,
                         'un voto simulado movio la participacion')

    def test_un_comentario_no_mueve_la_participacion(self):
        d = self._consulta()
        u, cab = self._usuario()
        antes = self.client.get(f'/debates/{d.id}', headers=cab).json()['total_votes']
        self.client.post(f'/debates/{d.id}/opinions',
                         json={'text': 'Una opinion ficticia con mas de veinte '
                                       'caracteres para pasar el minimo.'},
                         headers=cab)
        despues = self.client.get(f'/debates/{d.id}', headers=cab).json()['total_votes']
        self.assertEqual(antes, despues)


# ══════════════════════════════════════════════════════════════════
# PUNTO 7 — VOTO SIMULADO SIN CAMARA, DESDE LA PANTALLA
# ══════════════════════════════════════════════════════════════════

class TestVotoSimuladoSinCamara(Base):
    """Ya entraba sin camara, pero al VOTAR el portal se la pedia igual:
    se la pedia a todo el mundo, asi que no llegaba al servidor que la
    exime. El mismo fallo que el del ingreso, un endpoint mas abajo."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # El correo es unico en la tabla: la cuenta designada se crea UNA
        # vez por clase. Crearla en cada prueba revienta la sesion entera.
        cls._designada = main.User(
            name='Designada', email=CUENTA,
            password=bcrypt.hashpw(b'x', bcrypt.gensalt()).decode(),
            country='CL', county='Vitacura', gender='M', dob='1980-01-01',
            se_tier='B', role='voter', phone='+56900000000',
            email_verified=True, phone_verified=True, selfie_verified=True,
            verify_level=3, is_verified=True)
        cls.db.add(cls._designada); cls.db.commit(); cls.db.refresh(cls._designada)

    def _cab_designada(self):
        h = _ip()
        h['Authorization'] = 'Bearer ' + main.make_token(self._designada.id, 'voter')
        return h

    def test_el_servidor_le_dice_al_portal_quien_esta_exento(self):
        cab = self._cab_designada()
        d = self.client.get('/auth/me', headers=cab).json()
        self.assertIs(d['voto_simulado'], True)

    def test_y_a_los_demas_les_dice_que_no(self):
        u, cab = self._usuario()
        d = self.client.get('/auth/me', headers=cab).json()
        self.assertIs(d['voto_simulado'], False)

    def test_el_portal_solo_pide_camara_a_quien_no_esta_exento(self):
        i = PORTAL.index('faceToken = await requestFaceToken(debateId)')
        bloque = PORTAL[max(0, i - 600):i]
        self.assertIn('if (!usuarioEnModoPrueba)', bloque,
                      'el portal sigue pidiendo la camara a todo el mundo')

    def test_la_bandera_viene_del_servidor_y_no_del_almacenamiento(self):
        """Un indicador persistido en el navegador fue justo lo que fallo
        antes con la camara del voto."""
        self.assertIn('usuarioEnModoPrueba = d.voto_simulado === true', PORTAL)
        self.assertNotIn("localStorage.getItem('pref_voto_simulado'", PORTAL)
        self.assertNotIn("localStorage.setItem('pref_voto_simulado'", PORTAL)

    def test_el_portal_avisa_de_que_la_sesion_es_de_prueba(self):
        self.assertIn('MODO DE PRUEBA — tus votos no se contabilizan', PORTAL)

    def test_en_modo_prueba_se_explica_por_que_no_ve_el_escrutinio(self):
        """Un voto simulado no abre los resultados, porque no es un voto.
        Decirlo asi evita creer que el voto conto o que hubo un fallo."""
        self.assertIn('Estás en modo de prueba: tus votos son simulados', PORTAL)
        self.assertIn('no abren el escrutinio', PORTAL)
        i = PORTAL.index('const motivoSinEscrutinio')
        self.assertIn('usuarioEnModoPrueba', PORTAL[i:i + 500],
                      'el aviso tiene que distinguir el modo prueba')

    def test_el_servidor_sigue_siendo_el_que_decide(self):
        """Saltarse la pantalla no sirve: sin estar designado y sin token
        facial, el voto se rechaza."""
        d = main.Debate(
            title=_uniq('C'), context='F', options=json.dumps(['A', 'B']),
            status='live', creator_id=1,
            closes_at=datetime.utcnow() + timedelta(days=30),
            scope='country', scope_country='CL', target_gender='all',
            target_age_min=18, target_age_max=99, target_se_tiers='A,B,C,D')
        self.db.add(d); self.db.commit(); self.db.refresh(d)
        u, cab = self._usuario()
        r = self.client.post(f'/debates/{d.id}/vote',
                             json={'option_index': 0, 'vote_chain': [],
                                   'face_token': ''}, headers=cab)
        self.assertEqual(r.status_code, 403, r.text[:200])


if __name__ == '__main__':
    unittest.main(verbosity=2)
