"""test_vote_concurrency_pg.py — concurrencia del voto sobre PostgreSQL REAL.

EXIGE PostgreSQL. No se ejecuta contra SQLite a propósito, y se salta sola
si DATABASE_URL no apunta a PostgreSQL: SQLite serializa las escrituras con
un candado de fichero, así que la carrera que de verdad existe en producción
—varios procesos y posiblemente varias instancias contra el mismo
PostgreSQL— no se puede reproducir ahí. Una prueba de concurrencia en
SQLite daría verde sin haber probado nada.

Se lanza con:
    tools/verify_vote_concurrency.sh

que levanta su propia instancia temporal de PostgreSQL. No toca ninguna
base existente ni ningún voto histórico: todos los datos son ficticios
(dominio .invalid, documentos del rango 99.xxx.xxx).

QUÉ COMPRUEBA
  A. La restricción en sí, con PROCESOS reales simultáneos contra sus
     propias conexiones: 16 intentos de insertar la misma identidad →
     exactamente 1 sobrevive.
  B. El endpoint de voto con peticiones simultáneas de la misma cuenta →
     exactamente 1 papeleta, 1 registro de deduplicación, contador en 1.
  C. La misma PERSONA (mismo documento) desde DOS cuentas distintas,
     simultáneas → exactamente 1 papeleta.
  D. Reintentos secuenciales → 409 y nada duplicado.
  E. Un fallo transaccional a mitad de camino → no queda ni media
     escritura, y la persona puede votar después.
  F. La migración NO borra duplicados preexistentes: los detecta, deja la
     restricción sin crear y lo informa.
"""
import hashlib
import json
import os
import multiprocessing as mp
import threading
import unittest
import uuid

_URL = os.environ.get('DATABASE_URL', '')
_ES_PG = 'postgresql' in _URL

if _ES_PG:
    import bcrypt
    from fastapi.testclient import TestClient
    import main


def _ip():
    _ip.n = getattr(_ip, 'n', 0) + 1
    return {'X-Forwarded-For': f'198.51.100.{_ip.n % 250 + 1}'}


def _uniq(p):
    return f'{p}-{uuid.uuid4().hex[:10]}'


# ═══════════════════════════════════════════════════════════════════════
# A. La restricción, con PROCESOS reales
# ═══════════════════════════════════════════════════════════════════════
#
# Esta función corre en un proceso APARTE, así que no puede depender de
# nada del proceso padre: abre su propia conexión con psycopg2 directo (sin
# SQLAlchemy ni `main`, para que arrancar no cueste un import de 20.000
# líneas) y espera en una barrera para que los N intentos salgan a la vez.

def _intento_insertar(args):
    dsn, debate_id, user_id, barrera = args
    import psycopg2
    conn = psycopg2.connect(dsn)
    try:
        cur = conn.cursor()
        barrera.wait()          # todos a la vez: la carrera es real
        try:
            cur.execute(
                'INSERT INTO debate_has_voted (debate_id, user_id, verify_code) '
                'VALUES (%s, %s, %s)',
                (debate_id, user_id, uuid.uuid4().hex[:12].upper()))
            conn.commit()
            return 'OK'
        except Exception as e:
            conn.rollback()
            return type(e).__name__
    finally:
        conn.close()


@unittest.skipUnless(_ES_PG, 'exige PostgreSQL real; ver tools/verify_vote_concurrency.sh')
class TestA_LaRestriccionBajoProcesosSimultaneos(unittest.TestCase):

    N = 16

    @classmethod
    def setUpClass(cls):
        cls.db = main.SessionLocal()
        # DSN para psycopg2: sin el sufijo de driver de SQLAlchemy.
        cls.dsn = _URL.replace('postgresql+psycopg2://', 'postgresql://')

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_A1_la_garantia_esta_realmente_activa(self):
        """Antes de medir nada: comprobar que los índices EXISTEN en la base.
        Si no estuvieran, el resto de esta clase pasaría por la razón
        equivocada."""
        filas = self.db.execute(main.text(
            "SELECT indexname FROM pg_indexes WHERE indexname LIKE 'ux_vote_once%'"
        )).fetchall()
        nombres = {f[0] for f in filas}
        esperados = {n for n, _, _ in main.VOTE_UNIQUENESS_INDEXES}
        self.assertEqual(nombres, esperados,
                         f'faltan restricciones en la base: {esperados - nombres}')
        for nombre, estado in main.VOTE_UNIQUENESS_STATUS.items():
            self.assertEqual(estado, 'ACTIVO',
                             f'{nombre} no está activa: {estado}')

    def test_A2_dieciseis_procesos_simultaneos_dejan_exactamente_uno(self):
        """La carrera, de verdad: 16 procesos independientes, con sus propias
        conexiones, intentando registrar la MISMA identidad en la MISMA
        consulta en el mismo instante."""
        debate_id = 900000 + (uuid.uuid4().int % 1000)
        user_id = 900000 + (uuid.uuid4().int % 1000)
        with mp.Manager() as gestor:
            barrera = gestor.Barrier(self.N)
            with mp.Pool(self.N) as pool:
                resultados = pool.map(
                    _intento_insertar,
                    [(self.dsn, debate_id, user_id, barrera)] * self.N)

        exitos = [r for r in resultados if r == 'OK']
        self.db.rollback()      # ver lo que los otros procesos confirmaron
        filas = self.db.execute(main.text(
            'SELECT count(*) FROM debate_has_voted WHERE debate_id=:d AND user_id=:u'
        ), {'d': debate_id, 'u': user_id}).scalar()

        self.assertEqual(len(exitos), 1,
                         f'{len(exitos)} de {self.N} procesos lograron insertar; '
                         f'resultados: {resultados}')
        self.assertEqual(filas, 1,
                         f'quedaron {filas} filas para la misma identidad')
        # y los 15 restantes fallaron por la RESTRICCIÓN, no por otra cosa
        fallos = [r for r in resultados if r != 'OK']
        self.assertTrue(all('Unique' in r or 'Integrity' in r for r in fallos),
                        f'algún fallo no fue por la restricción: {set(fallos)}')


# ═══════════════════════════════════════════════════════════════════════
# B-E. El endpoint de voto
# ═══════════════════════════════════════════════════════════════════════

@unittest.skipUnless(_ES_PG, 'exige PostgreSQL real; ver tools/verify_vote_concurrency.sh')
class TestVotoConcurrente(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db = main.SessionLocal()
        cls.db.add(main.CommuneMarketData(
            country='CL', commune='Las Condes', se_tier='A',
            income_index=95.0, price_m2_avg=95.0, cpm_usd=6.0))
        cls.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    # ── utilidades ───────────────────────────────────────────────────

    def _consulta(self):
        org = main.User(name='Org C', email=_uniq('orgc') + '@test.invalid',
                        password=bcrypt.hashpw(b'x', bcrypt.gensalt()).decode(),
                        country='CL', role='organizer', email_verified=True)
        self.db.add(org); self.db.commit(); self.db.refresh(org)
        d = main.Debate(
            title=_uniq('Consulta concurrencia'), context='Ficticia',
            options=json.dumps(['Opción A', 'Opción B']),
            creator_id=org.id, creator_type='organizer', scope='country',
            scope_country='CL', status='open', target_gender='all',
            target_age_min=18, target_age_max=99, target_se_tiers='A,B,C,D',
            total_votes=0, vote_counts=json.dumps({'Opción A': 0, 'Opción B': 0}))
        self.db.add(d); self.db.commit(); self.db.refresh(d)
        return d

    def _votante(self, documento=None):
        u = main.User(
            name='Votante C', email=_uniq('vc') + '@test.invalid',
            password=bcrypt.hashpw(b'x', bcrypt.gensalt()).decode(),
            country='CL', county='Las Condes', dob='1990-05-05', gender='M',
            profession='Ingeniero Industrial',
            national_id=documento or f'99{uuid.uuid4().int % 10**6:06d}-9',
            email_verified=True, selfie_verified=False)
        self.db.add(u); self.db.commit(); self.db.refresh(u)
        return u

    def _votar_simultaneo(self, debate_id, tokens, opcion=0):
        """Lanza una petición por hilo, todas liberadas por una barrera.

        Un TestClient por hilo: compartir uno solo entre hilos no es seguro.
        El GIL no impide la carrera porque la sección crítica es E/S de base
        de datos, que lo libera; y cada petición recibe su propia sesión y su
        propia conexión por la dependencia get_db.
        """
        barrera = threading.Barrier(len(tokens))
        resultados = [None] * len(tokens)

        def _uno(i, token):
            cliente = TestClient(main.app)
            cabeceras = _ip()
            cabeceras['Authorization'] = f'Bearer {token}'
            barrera.wait()
            r = cliente.post(f'/debates/{debate_id}/vote',
                             json={'option_index': opcion},
                             headers=cabeceras)
            # Texto COMPLETO: truncarlo rompía el json.loads de D2, y un
            # cuerpo cortado haría ilegible cualquier diagnóstico.
            resultados[i] = (r.status_code, r.text)

        hilos = [threading.Thread(target=_uno, args=(i, t))
                 for i, t in enumerate(tokens)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(timeout=60)
        return resultados

    def _estado(self, d):
        self.db.rollback()
        papeletas = self.db.execute(main.text(
            'SELECT count(*) FROM debate_votes WHERE debate_id=:d'),
            {'d': d.id}).scalar()
        puente = self.db.execute(main.text(
            'SELECT count(*) FROM debate_has_voted WHERE debate_id=:d'),
            {'d': d.id}).scalar()
        docs = self.db.execute(main.text(
            'SELECT count(*) FROM national_id_vote_log WHERE debate_id=:d'),
            {'d': d.id}).scalar()
        fila = self.db.execute(main.text(
            'SELECT total_votes, vote_counts FROM debates WHERE id=:d'),
            {'d': d.id}).fetchone()
        contador = int(fila[0] or 0)
        try:
            cache = sum(int(v or 0) for v in (json.loads(fila[1] or '{}')).values())
        except Exception:
            cache = None
        # CHANGE-005 — el RESULTADO PUBLICADO, que es lo que de verdad
        # importa: se cuenta sobre las papeletas. `cache_opciones` es el
        # JSON heredado `vote_counts`, que ya no alimenta ningún resultado
        # mostrado y se deja intacto a propósito (sobrescribirlo destruiría
        # el registro histórico de las consultas sembradas).
        debate_orm = self.db.query(main.Debate).filter(main.Debate.id == d.id).first()
        publicado = main.format_debate(debate_orm, reveal_demo_counts=True)
        return {'papeletas': papeletas, 'puente': puente, 'docs': docs,
                'contador': contador, 'cache_opciones': cache,
                'publicado_total': publicado['total_votes'],
                'publicado_suma': sum(r['count'] or 0 for r in publicado['results'])}

    # ── B. misma cuenta, peticiones simultáneas ──────────────────────

    def test_B1_ocho_peticiones_simultaneas_de_la_misma_cuenta(self):
        d = self._consulta()
        u = self._votante()
        token = main.make_token(u.id, 'voter')
        res = self._votar_simultaneo(d.id, [token] * 8)

        aceptadas = [r for r in res if r and r[0] == 200]
        rechazadas = [r for r in res if r and r[0] == 409]
        est = self._estado(d)

        self.assertEqual(len(aceptadas), 1,
                         f'{len(aceptadas)} peticiones fueron aceptadas: {res}')
        self.assertEqual(len(rechazadas), 7,
                         f'los rechazos no fueron 409: {[r[0] for r in res]}')
        self.assertEqual(est['papeletas'], 1, f'estado final: {est}')
        self.assertEqual(est['puente'], 1, f'estado final: {est}')
        self.assertEqual(est['contador'], 1,
                         f'el contador se infló con la carrera: {est}')
        self.assertEqual(est['publicado_total'], 1,
                         f'el resultado publicado se infló: {est}')
        self.assertEqual(est['publicado_suma'], 1,
                         f'el recuento publicado por opción se infló: {est}')

    def test_B2_el_escrutinio_cuadra_con_muchos_votantes_a_la_vez(self):
        """12 personas DISTINTAS votando a la vez: las 12 deben entrar, y el
        escrutinio debe cuadrar exactamente. La restricción no debe rechazar
        votos legítimos."""
        d = self._consulta()
        tokens = [main.make_token(self._votante().id, 'voter') for _ in range(12)]
        res = self._votar_simultaneo(d.id, tokens)
        aceptadas = [r for r in res if r and r[0] == 200]
        est = self._estado(d)
        self.assertEqual(len(aceptadas), 12,
                         f'se rechazaron votos legítimos: {[r[0] for r in res]}')
        self.assertEqual(est['papeletas'], 12, f'estado final: {est}')
        # El contador: sumado con un UPDATE atómico, ya no pierde ninguno.
        # Antes de CHANGE-005 esto medía 1 con 12 papeletas en la base.
        self.assertEqual(est['contador'], 12,
                         f'se perdieron votos del contador: {est}')
        # Y el RESULTADO PUBLICADO, que se cuenta sobre las papeletas.
        self.assertEqual(est['publicado_total'], 12, f'estado final: {est}')
        self.assertEqual(est['publicado_suma'], 12, f'estado final: {est}')

    # ── C. misma persona, dos cuentas ────────────────────────────────

    def test_C1_la_misma_persona_con_dos_cuentas_simultaneas_vota_una_vez(self):
        """El caso que la restricción por cuenta NO cubre: dos cuentas, el
        mismo documento. Lo cierra ux_vote_once_national_id, que es la
        identidad de elegibilidad."""
        d = self._consulta()
        documento = f'99{uuid.uuid4().int % 10**6:06d}-9'
        u1 = self._votante(documento=documento)
        # La segunda cuenta se crea directamente en la base: el registro
        # rechazaría el documento repetido (y hace bien), pero el escenario
        # que hay que cerrar es que por cualquier vía existan dos cuentas con
        # el mismo documento.
        u2 = main.User(
            name='Votante C2', email=_uniq('vc2') + '@test.invalid',
            password=bcrypt.hashpw(b'x', bcrypt.gensalt()).decode(),
            country='CL', county='Las Condes', dob='1990-05-05', gender='M',
            profession='Ingeniero Industrial', national_id=documento,
            email_verified=True, selfie_verified=False)
        self.db.add(u2); self.db.commit(); self.db.refresh(u2)

        res = self._votar_simultaneo(
            d.id, [main.make_token(u1.id, 'voter'), main.make_token(u2.id, 'voter')])
        aceptadas = [r for r in res if r and r[0] == 200]
        est = self._estado(d)
        self.assertEqual(len(aceptadas), 1,
                         f'la misma persona votó dos veces con dos cuentas: {res}')
        self.assertEqual(est['papeletas'], 1, f'estado final: {est}')
        self.assertEqual(est['docs'], 1, f'estado final: {est}')
        self.assertEqual(est['contador'], 1, f'estado final: {est}')
        self.assertEqual(est['publicado_total'], 1, f'estado final: {est}')

    # ── D. reintentos ────────────────────────────────────────────────

    def test_D1_un_reintento_secuencial_devuelve_409_y_no_duplica(self):
        d = self._consulta()
        u = self._votante()
        cab = _ip(); cab['Authorization'] = f'Bearer {main.make_token(u.id, "voter")}'
        cliente = TestClient(main.app)
        r1 = cliente.post(f'/debates/{d.id}/vote', json={'option_index': 0}, headers=cab)
        self.assertEqual(r1.status_code, 200, r1.text[:300])
        for _ in range(3):
            cab2 = _ip(); cab2['Authorization'] = cab['Authorization']
            r2 = cliente.post(f'/debates/{d.id}/vote', json={'option_index': 1},
                              headers=cab2)
            self.assertEqual(r2.status_code, 409, r2.text[:300])
        est = self._estado(d)
        self.assertEqual(est['papeletas'], 1, f'estado final: {est}')
        self.assertEqual(est['contador'], 1, f'estado final: {est}')

    def test_D2_el_codigo_de_verificacion_del_voto_aceptado_sigue_sirviendo(self):
        """Tras la carrera, el votante que sí votó debe poder verificar su
        voto: la restricción no puede dejar el código huérfano."""
        d = self._consulta()
        u = self._votante()
        token = main.make_token(u.id, 'voter')
        res = self._votar_simultaneo(d.id, [token] * 6)
        aceptada = [r for r in res if r and r[0] == 200]
        self.assertEqual(len(aceptada), 1, f'{res}')
        codigo = (json.loads(aceptada[0][1]) or {}).get('verify_code')
        self.assertTrue(codigo, 'el voto aceptado no dejó código de verificación')
        # y el puente identidad->voto guarda EL MISMO código
        self.db.rollback()
        codigo_puente = self.db.execute(main.text(
            'SELECT verify_code FROM debate_has_voted WHERE debate_id=:d'),
            {'d': d.id}).scalar()
        self.assertEqual(codigo_puente, codigo,
                         'el código del puente no es el del voto aceptado')
        self.db.rollback()
        papeleta = self.db.execute(main.text(
            'SELECT count(*) FROM debate_votes WHERE verify_code=:c'),
            {'c': codigo}).scalar()
        self.assertEqual(papeleta, 1,
                         'el código del voto aceptado no resuelve a su papeleta')

    # ── E. fallo transaccional a mitad ───────────────────────────────

    def test_E1_un_fallo_a_mitad_no_deja_ni_media_escritura(self):
        """Si algo falla después de insertar la papeleta, no debe quedar ni
        papeleta, ni registro de deduplicación, ni contador sumado. Y la
        persona debe poder votar después: un fallo del sistema no puede
        consumir su derecho a voto.

        El fallo se inyecta en el commit, que es el punto donde una caída de
        la base dejaría todo a medias."""
        d = self._consulta()
        u = self._votante()
        antes = self._estado(d)

        original = main.SessionLocal
        class _SesionQueFallaAlConfirmar(main.SessionLocal().__class__):
            pass

        # Se envuelve Session.commit solo durante esta petición.
        import sqlalchemy.orm as _orm
        commit_real = _orm.Session.commit
        fallos = {'n': 0}

        def _commit_que_falla(self, *a, **kw):
            # Solo el primer commit de la petición de voto falla.
            if fallos['n'] == 0:
                fallos['n'] = 1
                raise RuntimeError('fallo inyectado en el commit')
            return commit_real(self, *a, **kw)

        cab = _ip(); cab['Authorization'] = f'Bearer {main.make_token(u.id, "voter")}'
        cliente = TestClient(main.app)
        _orm.Session.commit = _commit_que_falla
        try:
            r = cliente.post(f'/debates/{d.id}/vote', json={'option_index': 0},
                             headers=cab, )
        finally:
            _orm.Session.commit = commit_real
        self.assertEqual(r.status_code, 500, r.text[:300])

        despues = self._estado(d)
        self.assertEqual(despues['papeletas'], antes['papeletas'],
                         f'quedó una papeleta de una transacción fallida: {despues}')
        self.assertEqual(despues['puente'], antes['puente'],
                         f'quedó un registro de deduplicación huérfano: {despues}')
        self.assertEqual(despues['contador'], antes['contador'],
                         f'el contador se sumó sin papeleta: {despues}')

        # y la persona puede votar ahora
        cab2 = _ip(); cab2['Authorization'] = cab['Authorization']
        r2 = cliente.post(f'/debates/{d.id}/vote', json={'option_index': 0},
                          headers=cab2)
        self.assertEqual(r2.status_code, 200,
                         f'un fallo del sistema consumió el derecho a voto: '
                         f'{r2.text[:300]}')
        final = self._estado(d)
        self.assertEqual(final['papeletas'], antes['papeletas'] + 1, f'{final}')
        self.assertEqual(final['contador'], antes['contador'] + 1, f'{final}')


# ═══════════════════════════════════════════════════════════════════════
# F. La migración ante duplicados preexistentes
# ═══════════════════════════════════════════════════════════════════════

@unittest.skipUnless(_ES_PG, 'exige PostgreSQL real; ver tools/verify_vote_concurrency.sh')
class TestF_MigracionConDuplicadosPreexistentes(unittest.TestCase):
    """Producción puede tener ya duplicados de una carrera pasada. La
    migración NO debe borrarlos —son votos reales de personas reales— ni
    caerse, ni fingir que la garantía existe."""

    def test_F1_no_borra_detecta_e_informa(self):
        db = main.SessionLocal()
        try:
            # Tabla espejo con dos filas duplicadas, para no tocar la real.
            db.execute(main.text('DROP TABLE IF EXISTS dup_probe_vote_log'))
            db.execute(main.text(
                'CREATE TABLE dup_probe_vote_log ('
                ' id SERIAL PRIMARY KEY, debate_id INT NOT NULL,'
                ' user_id INT NOT NULL)'))
            db.execute(main.text(
                'INSERT INTO dup_probe_vote_log (debate_id, user_id) '
                'VALUES (1,1),(1,1),(2,2)'))
            db.commit()

            from sqlalchemy import inspect as _inspect
            estado_previo = dict(main.VOTE_UNIQUENESS_STATUS)
            original = main.VOTE_UNIQUENESS_INDEXES
            main.VOTE_UNIQUENESS_INDEXES = (
                ('ux_probe_dup', 'dup_probe_vote_log', ('debate_id', 'user_id')),)
            try:
                conn = main.engine.connect()
                main._migrate_vote_uniqueness(conn, _inspect(main.engine), main.text)
                conn.close()
            finally:
                main.VOTE_UNIQUENESS_INDEXES = original

            self.assertEqual(main.VOTE_UNIQUENESS_STATUS.get('ux_probe_dup'),
                             'DUPLICADOS:1',
                             'no informó el duplicado preexistente')
            # NO borró nada
            n = db.execute(main.text(
                'SELECT count(*) FROM dup_probe_vote_log')).scalar()
            self.assertEqual(n, 3, 'la migración borró filas: no debe hacerlo')
            # y no creó el índice
            idx = db.execute(main.text(
                "SELECT count(*) FROM pg_indexes WHERE indexname='ux_probe_dup'"
            )).scalar()
            self.assertEqual(idx, 0, 'creó un índice único sobre datos duplicados')

            main.VOTE_UNIQUENESS_STATUS.clear()
            main.VOTE_UNIQUENESS_STATUS.update(estado_previo)
        finally:
            db.execute(main.text('DROP TABLE IF EXISTS dup_probe_vote_log'))
            db.commit()
            db.close()


if __name__ == '__main__':
    unittest.main()
