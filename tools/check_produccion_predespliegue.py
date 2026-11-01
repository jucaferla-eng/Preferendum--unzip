"""tools/check_produccion_predespliegue.py — comprobación PREVIA al despliegue.

SOLO LECTURA. Cero escrituras. Responde a dos preguntas sobre la base de
PRODUCCIÓN antes de incorporar CHANGE-004 y CHANGE-005:

  2. ¿Hay duplicados históricos que impidan activar la protección de voto
     único?  (CHANGE-004)
  3. ¿Qué consultas cambiarían su resultado publicado?  (CHANGE-005)

CÓMO SE EJECUTA — en la Render Shell del servicio preferendum-unzip:

    python tools/check_produccion_predespliegue.py

Si el fichero no está en el contenedor, pegar su contenido en
`python - <<'EOF' … EOF`.

TRES PRECAUCIONES DELIBERADAS EN SU DISEÑO

1. NO IMPORTA `main`. Importarlo ejecutaría `create_all()` y `_migrate()`
   —que hacen DDL— y arrancaría un SEGUNDO scheduler dentro del contenedor,
   duplicando los trabajos programados. Aquí solo se usa SQLAlchemy a pelo.

2. Abre `START TRANSACTION READ ONLY`, así que es **PostgreSQL** quien
   rechaza cualquier escritura. No depende de la disciplina de quien escribió
   el script.

3. Cada consulta va en su propio SAVEPOINT: una tabla ausente no aborta el
   resto (en PostgreSQL un error aborta la transacción completa).

QUÉ NO IMPRIME, A PROPÓSITO
  · Ninguna credencial, ni la URL de conexión.
  · Ningún dato personal: ni correos, ni documentos, ni hashes de identidad.
  · Ninguna preferencia individual: no se consulta `option_index` ni
    `option_text` de ninguna papeleta.
  · Ningún título de consulta: para una consulta restringida el título es
    contenido protegido. Solo identificadores y recuentos agregados.
"""
import os
import sys

URL = os.getenv('DATABASE_URL', '')
if not URL:
    sys.exit('DATABASE_URL no está definida en este entorno.')
if 'postgresql' not in URL:
    sys.exit('Esto es para la base PostgreSQL de producción.')

from sqlalchemy import create_engine, text

engine = create_engine(URL)
conn = engine.connect()
conn.execute(text('ROLLBACK'))
conn.execute(text('START TRANSACTION READ ONLY'))


def q(sql, **params):
    """Una consulta aislada en su propio SAVEPOINT. Devuelve None si falla."""
    conn.execute(text('SAVEPOINT sp'))
    try:
        filas = conn.execute(text(sql), params).fetchall()
        conn.execute(text('RELEASE SAVEPOINT sp'))
        return filas
    except Exception as e:
        conn.execute(text('ROLLBACK TO SAVEPOINT sp'))
        print(f'    (consulta no disponible: {type(e).__name__})')
        return None


def uno(sql, **params):
    f = q(sql, **params)
    return f[0][0] if f else None


print()
print('=' * 72)
print(' COMPROBACIÓN PREVIA AL DESPLIEGUE — SOLO LECTURA')
print('=' * 72)
srv = uno('SELECT current_database()')
print(f' base: {srv}')
print(f' lectura forzada por el motor: START TRANSACTION READ ONLY')

# ════════════════════════════════════════════════════════════════════
# 2. DUPLICADOS HISTÓRICOS  (CHANGE-004)
# ════════════════════════════════════════════════════════════════════
print()
print('-' * 72)
print(' 2. DUPLICADOS HISTÓRICOS — ¿se puede activar el voto único?')
print('-' * 72)
print()
print('    Un duplicado preexistente impide crear ese índice único. La')
print('    migración NO borra nada: lo detecta y deja la protección')
print('    inactiva para esa dimensión. Esto dice si eso va a pasar.')
print()

DIMENSIONES = [
    ('ux_vote_once_account',     'debate_has_voted',     'debate_id, user_id'),
    ('ux_vote_once_national_id', 'national_id_vote_log', 'debate_id, national_id_hash'),
    ('ux_vote_once_sim',         'sim_vote_log',         'debate_id, phone_hash'),
    ('ux_vote_once_device',      'imei_vote_log',        'debate_id, imei_hash'),
    ('ux_vote_once_doc_serial',  'doc_serial_vote_log',  'debate_id, serial_hash'),
]

def existe(tabla):
    """Se pregunta ANTES de consultar la tabla: así una tabla que todavía no
    existe no imprime un aviso de error que parecería un problema."""
    n = uno("SELECT count(*) FROM information_schema.tables "
            " WHERE table_schema='public' AND table_name=:t", t=tabla)
    return bool(n)


bloqueantes = []
for indice, tabla, cols in DIMENSIONES:
    if not existe(tabla):
        print(f'    {indice:28} tabla {tabla} no existe aún -> se creará vacía')
        continue
    total = uno(f'SELECT count(*) FROM {tabla}')
    grupos = uno(
        f'SELECT count(*) FROM (SELECT 1 FROM {tabla} '
        f' GROUP BY {cols} HAVING count(*) > 1) d')
    exceso = uno(
        f'SELECT coalesce(sum(c),0) FROM (SELECT count(*) - 1 AS c FROM {tabla} '
        f' GROUP BY {cols} HAVING count(*) > 1) d')
    estado = 'SE ACTIVARÁ' if not grupos else f'BLOQUEADO ({grupos} grupos)'
    print(f'    {indice:28} filas={total:<9} duplicados={grupos or 0:<5} '
          f'filas sobrantes={exceso or 0:<5} -> {estado}')
    if grupos:
        bloqueantes.append((indice, tabla, cols, grupos, exceso))

print()
if not bloqueantes:
    print('    RESULTADO: sin duplicados. Las cinco protecciones se activarán.')
else:
    print(f'    RESULTADO: {len(bloqueantes)} dimensión(es) con duplicados.')
    print('    Esas protecciones quedarán INACTIVAS hasta decidir qué hacer')
    print('    con esos registros. Las demás sí se activan. El arranque NO')
    print('    falla y no se borra nada.')
    print()
    print('    Reparto por consulta de los duplicados (solo recuentos):')
    for indice, tabla, cols, _, _ in bloqueantes:
        filas = q(f'SELECT debate_id, count(*) AS grupos FROM '
                  f' (SELECT {cols} FROM {tabla} GROUP BY {cols} '
                  f'  HAVING count(*) > 1) d GROUP BY debate_id '
                  f' ORDER BY grupos DESC LIMIT 20')
        if filas:
            detalle = ', '.join(f'consulta {r[0]}: {r[1]}' for r in filas)
            print(f'      {tabla}: {detalle}')

# ════════════════════════════════════════════════════════════════════
# 3. IMPACTO DE CHANGE-005
# ════════════════════════════════════════════════════════════════════
print()
print('-' * 72)
print(' 3. IMPACTO DE CHANGE-005 — qué consultas cambian su resultado')
print('-' * 72)
print()
print('    CHANGE-005 publica el recuento de las PAPELETAS en vez del')
print('    contador almacenado. Cambia el número publicado solo donde los')
print('    dos difieren hoy. Se muestran identificadores y totales; nunca')
print('    títulos, ni desglose por opción, ni preferencias individuales.')
print()

consultas = uno('SELECT count(*) FROM debates')
divergentes = uno("""
    SELECT count(*) FROM debates d
     WHERE coalesce(d.total_votes, 0) <>
           (SELECT count(*) FROM debate_votes v WHERE v.debate_id = d.id)
""")
deriva = uno("""
    SELECT coalesce(sum(abs(coalesce(d.total_votes,0) -
          (SELECT count(*) FROM debate_votes v WHERE v.debate_id = d.id))), 0)
      FROM debates d
""")
print(f'    consultas en total              : {consultas}')
print(f'    consultas que CAMBIAN de número : {divergentes}')
print(f'    desviación total de votos       : {deriva}')
print()

filas = q("""
    SELECT d.id,
           coalesce(d.total_votes, 0) AS declarado,
           (SELECT count(*) FROM debate_votes v WHERE v.debate_id = d.id) AS papeletas
      FROM debates d
     WHERE coalesce(d.total_votes, 0) <>
           (SELECT count(*) FROM debate_votes v WHERE v.debate_id = d.id)
     ORDER BY abs(coalesce(d.total_votes,0) -
                 (SELECT count(*) FROM debate_votes v WHERE v.debate_id = d.id)) DESC
     LIMIT 40
""")
if filas:
    print('    Las que cambian (mayor desviación primero):')
    print(f'      {"consulta":>9}  {"publica hoy":>12}  {"publicará":>10}  {"diferencia":>11}')
    for cid, declarado, papeletas in filas:
        print(f'      {cid:>9}  {declarado:>12}  {papeletas:>10}  '
              f'{papeletas - declarado:>+11}')
else:
    print('    Ninguna consulta cambia de número.')

# ── la 819 y las sembradas, con atención especial ───────────────────
print()
print('    ATENCIÓN ESPECIAL:')
for etiqueta, cid in [('consulta 819 (fijada)', 819),
                      ('demo sembrada 1', 1),
                      ('demo sembrada 2', 2),
                      ('demo sembrada 3', 3)]:
    f = q("""
        SELECT coalesce(d.total_votes,0),
               (SELECT count(*) FROM debate_votes v WHERE v.debate_id = d.id)
          FROM debates d WHERE d.id = :cid
    """, cid=cid)
    if not f:
        continue
    if not len(f):
        print(f'      {etiqueta:24} no existe en esta base')
        continue
    declarado, papeletas = f[0]
    if declarado == papeletas:
        print(f'      {etiqueta:24} publica {declarado} -> SIN CAMBIO')
    else:
        print(f'      {etiqueta:24} publica {declarado} -> publicará {papeletas} '
              f'({papeletas - declarado:+})')

# ── CHANGE-006: estado de la columna y de los importes ──────────────
print()
print('-' * 72)
print(' EXTRA — CHANGE-006: importes históricos')
print('-' * 72)
col = uno("""
    SELECT count(*) FROM information_schema.columns
     WHERE table_name = 'ad_impression_logs'
       AND column_name = 'cost_credits_posted'
""")
print(f'    columna cost_credits_posted ya existe: {"sí" if col else "no (se añadirá vacía)"}')
imp = uno('SELECT count(*) FROM ad_impression_logs')
suma = uno('SELECT coalesce(sum(cost_clp),0) FROM ad_impression_logs')
gasto = uno('SELECT coalesce(sum(spent_clp),0) FROM ad_campaigns')
print(f'    impresiones registradas             : {imp}')
print(f'    suma de cost_clp (CLP)              : {suma}')
print(f'    suma de spent_clp de campañas (CLP) : {gasto}')
print()
print('    Estas tres cifras deben ser IDÉNTICAS después del despliegue:')
print('    CHANGE-006 solo añade una columna vacía y no toca ningún importe.')
print('    Anótalas ahora y vuelve a ejecutar este script después.')

conn.execute(text('ROLLBACK'))
conn.close()
print()
print('=' * 72)
print(' FIN — no se escribió nada en la base.')
print('=' * 72)
print()
