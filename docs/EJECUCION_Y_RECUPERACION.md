# Preferendum — ejecución, pruebas y recuperación

Documento operativo. Escrito para que un ingeniero que no conoce el proyecto
pueda clonarlo, ejecutar la suite completa y entender cómo recuperar el
servicio, sin preguntar a nadie.

---

## 1. Ejecutar las pruebas

```bash
git clone <repo> && cd Preferendum
make setup     # una sola vez — crea .venv-test con las versiones fijadas
make test      # ejecuta las 14 suites Python y las 9 de JavaScript
```

Nada de esto toca producción: la suite usa una base SQLite temporal y
secretos de prueba.

| Comando | Qué hace |
|---|---|
| `make setup` | Crea `.venv-test` desde `requirements-dev.txt` |
| `make test` | Toda la suite (Python + JS) |
| `make test-python` / `make test-js` | Solo una mitad |
| `make audit` | Inventario de rutas, pruebas y señales de trabajo pendiente |

### Por qué `requirements-dev.txt` es imprescindible

`requirements.txt` fija lo que necesita producción, pero **no basta para
ejecutar la suite**. Tres pines son críticos:

- **`pydantic==1.10.13`** — `fastapi 0.95.2` exige pydantic 1.x. Con pydantic
  2.x, `import fastapi` falla con `cannot import name 'Undefined'` y se cae
  cualquier suite que importe `main.py`.
- **`httpx==0.24.1`** — `starlette 0.27` pasa `app=` a `httpx.Client`, y
  httpx ≥0.25 lo rechaza: `TestClient` deja de construirse.
- **`eth-utils==2.3.1`** — `web3 6.11.1` con eth-utils moderno arrastra
  pydantic 2 por dependencia transitiva y rompe el primer pin.

`PYTHONNOUSERSITE=1` también es necesario: sin él, el `site-packages` del
usuario puede tener prioridad sobre el del entorno y reaparece pydantic 2.x.
`make test` y la CI ya lo aplican.

### Antecedente que explica la existencia de todo esto

Entre el **2026-09-29** y el **2026-10-31**, **467 pruebas no pudieron
ejecutarse en ningún entorno** y nadie lo detectó, porque no había
integración continua. El índice de `geo_units` declaraba su clase de
operador de PostgreSQL dentro de `text('… varchar_pattern_ops')`, que
SQLAlchemy emite en todos los dialectos; SQLite lo rechaza, así que
`create_all()` reventaba al importar `main.py`. El fallo se veía como un
`ImportError` sin relación aparente.

Entre esas 467 estaban las **105 pruebas del cableado del ledger** (núcleo
financiero) y las **106 de integración HTTP**. Corregido en `a327f35c`
declarando la clase de operador vía `postgresql_ops`, que es consciente del
dialecto; el DDL de PostgreSQL quedó byte por byte idéntico.

**Lección operativa: sin CI, una suite puede morir en silencio durante
semanas.** Por eso `.github/workflows/tests.yml` corre en cada push.

---

## 2. Estado conocido de la suite

Medido el 2026-10-31.

| | |
|---|---|
| Pruebas Python ejecutándose | **1.077** |
| En suites verdes | **1.077** |
| Suites con fallo | **ninguna** |
| Aserciones JS en verde | **15.936** |

```bash
make test          # las 15 suites Python + las 9 JS
```

### 2.1 Dos ensayos que NO entran en `make test`

Exigen PostgreSQL real y levantan su propia instancia temporal, así que van
aparte. **No basta con que `make test` esté verde: estos dos miden cosas que
SQLite no puede medir.**

```bash
make vote-drill                        # concurrencia del voto (9 pruebas)
make dr-drill                          # recuperación ante desastre
PREFY_DR_VOTES=50000 make dr-drill     # con volumen, para cronometrar
```

`make vote-drill` se **salta solo** si `DATABASE_URL` no es PostgreSQL. Eso
es deliberado y conviene entender por qué: SQLite serializa las escrituras
con un candado de fichero, así que una prueba de concurrencia ejecutada ahí
**daría verde sin haber probado nada**. Un verde engañoso es peor que un
rojo.

### 2.2 Qué cubre cada suite

| Suite | Qué mide |
|---|---|
| `test_e2e_commercial` | Recorrido comercial de punta a punta: registro e identidad, consultas y votación, campañas, **entrega efectiva de publicidad, consumo de presupuesto, ledger, métricas, informes del anunciante y administración**, integridad, monitoreo e integridad del escrutinio |
| `test_vote_concurrency_pg` | Voto único bajo concurrencia real (§5.3.1) |
| `test_production_readiness_fixes` | Guardas de regresión de las auditorías previas |
| `test_eligibility` / `test_socioeconomic*` | Elegibilidad y clasificación A/B/C/D |
| `test_ledger*` | Contabilidad de doble entrada |
| `test_integration_http` | Rutas reales sobre la app en memoria |
| `test_i18n*` / suites `.mjs` | Idiomas, portales y Prefy |

`test_e2e_commercial` declara además, en `TestLimitesConocidos`, **lo que no
puede validar y por qué**: Stripe real, Rekognition real, dispositivos
físicos y el anclaje real en Polygon. Están ahí para que «suite en verde» no
se lea como «todo comprobado».

### 2.3 Dos hallazgos comerciales fijados como pruebas

No son fallos de la suite: son inconsistencias reales que **se dejan
medidas** porque corregirlas es una decisión de negocio.

- `test_D6b` — el cargo redondeado no iguala el precio declarado.
- `test_D6c` — `spent_clp` refleja la petición, no el asiento del ledger
  (brecha de 1 CLP por impresión, 5,26 %).
- `test_D22b` — el recálculo administrativo usa el CPM de hoy, no lo cobrado.

Las tres **fallan a propósito si las cifras dejan de divergir**, para
obligar a retirarlas y actualizar
`docs/POLITICA_CONCILIACION_FACTURACION.md` en vez de dejarlo mintiendo.

---

## 3. Topología de producción

| Componente | Detalle |
|---|---|
| Servicio web | `preferendum-unzip` en Render — **es el que sirve el tráfico real** |
| Dominio | `preferendum-unzip-d2zd.onrender.com` (alias: `preferendum-unzip.onrender.com`) |
| Comando | `uvicorn main:app --host 0.0.0.0 --port $PORT` (sin `--workers`) |
| Base de datos | PostgreSQL gestionado por Render |
| Cron | `preferendum-daily-debates` (diario 07:00 UTC), `preferendum-income-data` (mensual) |
| Blockchain | Polygon mainnet, contrato `0xB7fCD1aD46eC0a3ABfaddf95961e435C991dfd36` |

> **Cuidado — hay un segundo servicio.** `render.yaml` describe un servicio
> llamado `preferendum-api`, que **no** es el que sirve el tráfico real.
> Cada uno administra sus propias variables de entorno de forma
> independiente. Una variable configurada en el servicio equivocado parece
> estar puesta y no tiene efecto. Verificar siempre el dominio del servicio,
> no su nombre.

### Comprobación de salud

```bash
curl -s https://preferendum-unzip-d2zd.onrender.com/health
# {"status":"ok","timestamp":"…","git_commit":"<sha>","db":"ok"}
```

`git_commit` es la forma fiable de saber qué versión está activa. Que Render
diga «Live» no garantiza que el proceso haya recargado una variable de
entorno nueva.

---

## 4. Despliegue

El patrón usado en este repositorio es **despliegue aislado**: nunca se
empuja la rama de trabajo completa, porque arrastra archivos ajenos.

```bash
git fetch origin main
git checkout -b <nombre>-deploy origin/main
git cherry-pick <sha> [<sha>…]
git diff origin/main HEAD --name-only     # confirmar SOLO los archivos esperados
make test                                  # suite completa en verde
git push origin <nombre>-deploy:main
# esperar a que /health reporte el sha nuevo
git checkout <rama-de-trabajo>
git branch -D <nombre>-deploy
```

Verificar **siempre** `git diff origin/main HEAD --name-only` antes de
empujar. En esta rama hay siete archivos de trabajo previo no desplegado
(`app.json`, `package.json`, `package-lock.json`, `prefy-video.css`,
`prefy-video.js`, `prefy_test_harness/*`) que se colarían en un push directo.

---

## 5. Recuperación

### 5.1 Reversión de un despliegue

```bash
git checkout -b revert-x origin/main
git checkout <sha-bueno> -- <archivos>
make test
git push origin revert-x:main
```

Preferir restaurar archivos a un estado conocido antes que `git revert`
cuando el cambio está acotado: es más fácil de verificar.

### 5.2 Respaldo y restauración de la base de datos

> **Estado: IMPLEMENTADO Y PROBADO.** El ciclo completo —respaldo, destrucción
> de la base y restauración— se ejecuta y se verifica contra PostgreSQL real.
> Lo que antes era un bloqueador de due diligence ahora es un procedimiento
> con cifras medidas.

**Respaldar**

```bash
DATABASE_URL=postgresql://... tools/backup_db.sh ./backups
```

Produce tres ficheros: el `.dump` (formato custom, comprimido), su
`.sha256` y un `.manifest.json` con el recuento de filas de las 14 tablas
críticas. El manifiesto es lo que hace el respaldo verificable: sin él, lo
único que se sabe es que `pg_dump` terminó sin error, y eso no prueba que el
contenido esté completo.

El script nunca imprime la URL de conexión ni ninguna credencial: solo el
nombre de la base y el host.

**Restaurar**

```bash
RESTORE_URL=postgresql://... tools/restore_db.sh ./backups/preferendum-<fecha>.dump
```

Verifica la suma de comprobación **antes** de borrar nada del destino, y al
terminar compara fila a fila contra el manifiesto. Si alguna tabla crítica no
coincide, sale con error: *«pg_restore terminó»* no es una prueba de
recuperación; *«las filas críticas coinciden»* sí.

Se niega a escribir sobre una base cuyo nombre sugiera producción
(`prod`, `production`, `live`) salvo que se pase
`--i-understand-this-overwrites`. Restaurar sobre producción destruye lo que
haya allí y no debe poder ocurrir por un error de copiar y pegar.

**Ensayar (lo que convierte el procedimiento en una prueba)**

```bash
make dr-drill                          # 25 papeletas, comprueba que funciona
PREFY_DR_VOTES=50000 make dr-drill     # volumen realista, para medir el RTO
```

El ensayo levanta su propia instancia temporal de PostgreSQL (no toca ninguna
base existente), crea el esquema con las **mismas** funciones que usa la
aplicación al arrancar, siembra datos ficticios, respalda, **destruye la base
entera**, restaura y comprueba la integridad: huella md5 del contenido,
ausencia de dobles votos, que cada código de verificación siga resolviendo a
una papeleta real, y deriva cero entre el contador y las papeletas.

**Cifras del ENSAYO LOCAL** (macOS, PostgreSQL 16.15 en la misma máquina,
50.000 papeletas / 50.002 usuarios / 6,1 MB de respaldo):

| Fase | Tiempo |
|---|---|
| Respaldo | 1 s |
| Restauración | 1 s |
| Ciclo completo del ensayo | ~2 s |

> ### ⚠️ Esto NO es el RTO de producción
>
> **Los 2 segundos son el tiempo del ensayo local, y no deben presentarse
> como el objetivo de tiempo de recuperación de Preferendum.** Son dos cosas
> distintas, y confundirlas sería dar por buena una cifra que nadie ha
> medido.
>
> El ensayo mide una restauración de PostgreSQL a PostgreSQL **en la misma
> máquina, sobre socket local, con 6 MB de datos y sin red**. Un RTO real de
> producción tiene que incluir además:
>
> - **Transferencia por red** del respaldo desde el almacenamiento externo
>   (que todavía no existe — ver más abajo).
> - **El volumen real de producción**, que no está medido. 50.000 papeletas
>   es una hipótesis de trabajo, no el tamaño de la base.
> - **Aprovisionar la instancia de PostgreSQL** en Render y reconfigurar
>   `DATABASE_URL`, que es trabajo manual no cronometrado.
> - **Detección y decisión**: el reloj del RTO empieza cuando ocurre el
>   incidente, no cuando alguien ejecuta `pg_restore`. Hoy no hay monitoreo
>   de base de datos que avise, así que ese tramo es **desconocido**.
> - **Verificación posterior** antes de volver a dar servicio.
>
> **Lo que el ensayo sí demuestra**, y es lo que antes no existía: que el
> respaldo es restaurable, que el procedimiento está escrito y automatizado,
> y que los datos vuelven íntegros y verificados. Eso es la diferencia entre
> «tenemos respaldos» y «hemos probado que funcionan».
>
> Para dar una cifra de RTO defendible hace falta un ensayo **de extremo a
> extremo contra la topología de producción**, con el volumen real y el
> respaldo viniendo de donde vendría de verdad. No está hecho.

**Lo que todavía falta**, dicho sin adornos:

- **Programar el respaldo.** Hoy se ejecuta a mano. Un respaldo que depende
  de que alguien se acuerde no es un respaldo.
- **Almacenamiento externo fuera de Render.** Un respaldo que vive en la
  misma infraestructura que la base no protege contra perderla.
- **Un ensayo contra la topología de producción** para poder declarar un RTO
  real (ver el aviso de arriba).

El procedimiento y su verificación ya existen; lo que falta es que se
ejecute solo, que el resultado salga de la casa, y que se cronometre donde
importa.

### 5.3 Monitoreo

> **Estado: PARCIAL.** Sigue sin haber Sentry, Rollbar, Datadog ni
> OpenTelemetry —cada uno exige cuenta, credencial y una dependencia nueva—,
> pero un error 500 ya **no** pasa desapercibido.

**Eventos de error estructurados.** Cada excepción no controlada de una ruta
se emite como **una sola línea** con un prefijo fijo y cuerpo JSON:

```
[ERROR_EVENT] {"at":"main.py:9148","commit":"...","exc":"IntegrityError", ...
```

Una línea con prefijo fijo es alertable desde los propios logs de Render, o
desde cualquier recolector posterior, **sin volver a tocar el código**.

**Qué lleva y qué no.** Un evento de error es un sitio clásico por donde se
escapan datos personales y secretos, así que se emite solo: la *plantilla* de
la ruta (`/admin/dev-otp/{phone}`, nunca la ruta concreta con el teléfono
dentro), el método, el tipo de excepción, el último marco de la traza
(`fichero:línea`), el hash de la IP y el commit. **Nunca** la cadena de
consulta (lleva `secret=`), ni el cuerpo, ni las cabeceras, ni el correo, ni
el documento, ni el mensaje de la excepción, que puede arrastrar valores de
una fila. Hay pruebas que lo verifican (`TestF_Monitoreo`).

**Webhook opcional.** Si se configura `ERROR_WEBHOOK_URL`, cada evento se
envía además por POST a esa dirección. Sin la variable no se intenta ninguna
salida de red: la función queda inerte.

**No cambia ninguna respuesta HTTP.** El middleware observa y vuelve a lanzar
la excepción tal cual, así que el comportamiento visible es el de antes.

**Orden en la pila** (comprobado ejecutándolo, no supuesto): Starlette inserta
cada middleware en el índice 0, así que el último declarado queda el más
externo. Orden real: `security_shield` → `error_observability` → CORS →
rutas. Es decir, se ven los errores de las rutas, pero **no** los del propio
escudo de seguridad, que queda por fuera.

Sí existen además alertas **de seguridad** por correo (`_sec_alert`), que
dependen de `RESEND_API_KEY`.

### 5.3.1 Integridad del voto y del escrutinio

#### Un voto por persona y consulta — garantizado por la base de datos

`CHANGE-004`. Hasta esta corrección, el doble voto se impedía con cinco
`SELECT` previos y **ninguna restricción detrás**: dos peticiones
simultáneas de la misma persona ejecutaban sus comprobaciones antes de que
ninguna hubiera insertado, las dos pasaban y las dos insertaban. Medido
sobre PostgreSQL real: **16 procesos simultáneos insertaban 16 filas para la
misma identidad**.

La restricción NO va en `debate_votes`: su `voter_id` es siempre `NULL` a
propósito —la separación entre identidad y preferencia— y añadir el votante
a la papeleta para poder restringirla destruiría justo eso. Va en las cinco
tablas de deduplicación, que sí tienen la identidad (hasheada) y **no**
tienen la opción votada:

| Índice único | Garantiza |
|---|---|
| `ux_vote_once_national_id` *(debate_id, national_id_hash)* | Una **persona**, aunque abra varias cuentas |
| `ux_vote_once_account` *(debate_id, user_id)* | Una **cuenta**, aplicable siempre |
| `ux_vote_once_sim` | Un teléfono |
| `ux_vote_once_device` | Un aparato |
| `ux_vote_once_doc_serial` | Una serie de documento |

Las dos primeras son las que garantizan el principio; las otras tres ya eran
política vigente en los `SELECT` y solo se hacen resistentes a la
concurrencia.

**Si en producción ya existen duplicados**, la migración **no borra nada**:
lo detecta, deja el índice sin crear y lo publica en
`/admin/tally/reconciliation` bajo `garantia_voto_unico`. Corregir un
duplicado histórico es una decisión sobre votos reales de personas reales.
**Comprobar ese campo después de desplegar es obligatorio**: si alguna
dimensión no dice `ACTIVO`, la garantía no está puesta para ella.

Ensayo de concurrencia:

```bash
make vote-drill        # levanta su propio PostgreSQL temporal
```

No se ejecuta en SQLite y se salta solo si `DATABASE_URL` no es PostgreSQL:
SQLite serializa las escrituras con un candado de fichero, así que una
prueba de concurrencia ahí daría verde **sin haber probado nada**. Cubre 16
procesos reales simultáneos, 8 peticiones simultáneas de la misma cuenta, la
misma persona desde dos cuentas, reintentos, y un fallo transaccional
inyectado en el commit (tras el cual la persona **sí** puede votar: un fallo
del sistema no consume su derecho a voto).

#### El escrutinio se cuenta sobre las papeletas

`CHANGE-005`. Al medir la concurrencia apareció un segundo defecto, peor que
el primero: **la concurrencia no solo permitía votar dos veces, también
descartaba votos válidos del resultado publicado**.

Ningún resultado mostrado a un usuario salía de contar papeletas:
`format_debate` leía `debates.total_votes` y `debates.vote_counts`, que el
voto mantenía con un leer-modificar-escribir en Python. Medido con **12
personas distintas votando a la vez: 12 papeletas en la base y el contador
en 1**. Once votos legítimos desaparecidos, en silencio.

Ahora el recuento se deriva de `debate_votes` con un `GROUP BY` por
`option_index` (`_derived_tally`), que es la única fuente que no puede
desincronizarse de sí misma. Se usa en `format_debate`, en la página pública
`/r/{id}` y en el panel de marca `/pilot/{id}/live` —que era internamente
inconsistente: el total contaba papeletas mientras el desglose leía el
JSON—. `total_votes` se suma además con un `UPDATE` atómico.

Agregar por `option_index` y no por el texto de la opción elimina de paso la
clase de defecto de las claves huérfanas: un texto editado ya no puede
esconder votos.

No se toca ninguna papeleta, ningún código de verificación ni la consulta
819: solo cambia **de dónde se lee** el resultado. Es una agregación, así
que nunca expone la opción de una persona concreta.

`vote_counts` se sigue escribiendo pero deja de ser la verdad, y **no se
corrige automáticamente a propósito**: en las consultas sembradas contiene
los votos reales sumados dentro de cubos ficticios, y sobrescribirla
destruiría ese registro histórico.

#### Conciliación

```bash
GET /admin/tally/reconciliation?secret=...
```

Conciliación de **solo lectura** del escrutinio contra las papeletas, el
equivalente para los votos de `/admin/ledger/reconciliation`. No existía:
hasta ahora no había forma de preguntarle al sistema si el resultado que
publica coincide con las papeletas que tiene.

Compara, por consulta, las papeletas reales contra las columnas heredadas, y
separa **dos clases** de hallazgo — una distinción que importa:

| Clase | Qué significa |
|---|---|
| `desviaciones` | Problemas **reales** de lo publicado. Papeletas sin puente identidad→voto (esos votantes no pueden verificar su voto), o más registros de puente que papeletas |
| `informativas` | Desajustes de las columnas heredadas de caché, que **ya no alimentan ningún resultado mostrado** |

También publica `garantia_voto_unico`, con el estado real de las cinco
restricciones de CHANGE-004. **Ese campo es lo primero que hay que mirar
después de un despliegue**: si alguna no dice `ACTIVO`, la garantía no está
puesta para esa dimensión, y la respuesta dice por qué.

Y declara en `origen_del_resultado` de dónde sale el número que se publica,
para que nadie tenga que deducirlo leyendo el código.

**No repara nada, a propósito.** La desviación mayor conocida —37.928 votos
fabricados por `seed_demo_data` en las consultas 1-3— no se puede corregir sin
exponer las preferencias individuales de las 3 personas que sí votaron en
ellas, porque sus votos quedaron sumados dentro de los mismos cubos ficticios.
Cualquier corrección es una decisión con consecuencias de privacidad.

Desde CHANGE-005 esa desviación **ya no miente a nadie**: el resultado
publicado se cuenta sobre las papeletas, así que un contador inflado queda
reducido a una caché desajustada. Se informa, pero no se publica.

### 5.4 Scheduler

Los trabajos programados viven en el proceso web (APScheduler), no en
procesos aparte. Consecuencias:

- Si el proceso web se reinicia, el scheduler se reinicia con él.
- **Nunca ejecutar `import main` en una consola de Render:** arrancaría un
  **segundo** scheduler dentro del mismo contenedor, duplicando los
  trabajos. Para inspeccionar la base desde la consola, conectarse con
  SQLAlchemy usando `DATABASE_URL`, sin importar `main`.

Para diagnósticos de solo lectura, abrir siempre la transacción como
`START TRANSACTION READ ONLY`: así es PostgreSQL quien rechaza cualquier
escritura, y no depende de la disciplina de quien escribió el script.

---

## 6. Secretos

Nunca se escriben en informes, pruebas ni CI. La integración continua usa
exclusivamente valores de prueba y una base temporal: **no necesita acceso a
producción para nada**.

Variables que gobiernan funcionalidad (sin valores, solo el efecto de su
ausencia):

| Variable | Si falta |
|---|---|
| `JWT_SECRET` | Todo login y token falla — falla cerrado, a propósito |
| `ADMIN_SECRET` | Las ~162 rutas `/admin/*` quedan inaccesibles |
| `DATABASE_URL` | Cae a SQLite local |
| `RESEND_API_KEY` / `GMAIL_APP_PASSWORD` | Sin canal de correo: OTP y alertas no salen |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Sin reconocimiento facial |
| `PREFERENDUM_WALLET_KEY` | Blockchain en modo simulado (`live=False`) |
| `SEED_DEMO_DATA` | Sin ella NO se siembran datos ficticios — es lo correcto en producción |
| `PREFY_SERVE_480P` | Prefy sirve los videos originales en vez de los comprimidos |

---

## 7. Lo que este documento NO cubre todavía

- **RTO real de producción: NO medido.** El ensayo local da ~2 s con 6 MB en
  la misma máquina; eso no es un RTO (§5.2). Falta un ensayo contra la
  topología de producción, con el volumen real y el respaldo llegando por
  red.
- **Respaldo programado y fuera de Render: no existe.** El procedimiento está
  probado; la periodicidad y el almacenamiento externo, no.
- **Volumen real de la base de producción: no medido.** Las 50.000 papeletas
  del ensayo son una hipótesis de trabajo.
- Pruebas de carga y cifras de escalabilidad: **no medidas**.
- Monitoreo: **parcial** (§5.3). Hay eventos de error estructurados y
  alertables y un webhook opcional; **no** hay servicio de observabilidad
  externo, ni monitoreo de la base de datos, ni alerta de que la base haya
  caído — y por eso el tramo «detección y decisión» del RTO es desconocido.
- Conciliación **exacta** entre impresiones, ledger y facturas: **no**. Hay
  dos inconsistencias medidas y una política propuesta, sin aprobar ni
  implementar — ver `docs/POLITICA_CONCILIACION_FACTURACION.md`. Y **no
  existe ningún concepto de factura** en el código.
- **Aplicaciones móviles: AMBAS EXISTEN y están distribuidas.** Corrección
  de un error mío anterior: afirmé que «Android no tiene proyecto nativo»
  porque no hay carpeta `android/` en el repositorio. Eso es **normal** con
  EAS Build: el proyecto nativo se genera en la nube a partir de `app.json`
  y `eas.json`, y no se versiona. La carpeta `ios/` existe solo porque
  alguien ejecutó un prebuild local.
  `eas.json` tiene perfil de producción para las dos plataformas (Android
  como `app-bundle`) y configuración de envío a Google Play (pista interna)
  y App Store. Las dos apps son un **envoltorio WebView** sobre la URL de
  producción, así que comprobar los flujos web comprueba casi todo de
  ambas.
  Lo que **no** está comprobado: el comportamiento en un dispositivo real
  (no tengo acceso a uno). Eso queda como NO COMPROBADO, no como
  inexistente.
- Arquitectura de voto secreto y verificable de extremo a extremo (el
  documento «Voto Único, Secreto y Verificable»): **sin empezar**. CHANGE-004
  garantiza un voto por persona; la verificabilidad criptográfica es otra
  cosa y sigue pendiente.
