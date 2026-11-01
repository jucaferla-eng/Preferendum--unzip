# Despliegue controlado de las correcciones

**Estado: PREPARADO, NO EJECUTADO.** Nada de este documento se ha ejecutado.

Rama: `deploy-correcciones` · un solo commit sobre `origin/main`
Respaldo recuperable: `~/Downloads/2026-11-01T03-04Z.dir.tar.gz`
sha256 `297ba7a9d33d55974b1598b273102df10398470bf676c1cb1c4604665add1505`
(verificado restaurándolo en PostgreSQL 18.6 temporal; reproduce producción
exactamente)

---

## 0. Antes de empezar

| Comprobación | Estado |
|---|---|
| Respaldo descargado y **verificado restaurándolo** | ✅ |
| Migración ejecutada **sobre los datos reales** de producción, en PG 18 | ✅ |
| Duplicados históricos en las 5 dimensiones | ✅ cero |
| Consulta 819 | ✅ sin cambio (1 voto / 1 papeleta) |
| Las tres consultas de demostración | ✅ ocultas al público |
| Importes históricos | ✅ intactos |
| Suite completa | ✅ 1.171 en verde, ninguna suite con fallo |
| Concurrencia del voto y recuperación, en PostgreSQL 18 | ✅ |
| Los siete archivos ajenos | ✅ excluidos |

**Cifras de producción a anotar antes (del script de solo lectura):**

```
consultas     24.810      impresiones   430
819           1 / 1       cost_clp      0
duplicados    0 en las 5  spent_clp     3.366
```

---

## 1. Qué se despliega

**Cuatro ficheros de producción.** El resto son pruebas, herramientas y
documentación, que no se ejecutan en producción.

| Fichero | Qué cambia |
|---|---|
| `main.py` | P0.1 índice geo_units · P0.5 SOC/slug · P0.6 sesión aislada del clasificador · CHANGE-004 voto único · CHANGE-005 escrutinio derivado · CHANGE-006 conciliación · 13 rutas administrativas protegidas · monitoreo · un fallo de anclaje ya no pierde el voto |
| `blockchain.py` | La intermitencia del anclaje · el recibo decide · un hash simulado nunca es éxito |
| `marketer_portal.html` | CAMPAÑAS: alta de anunciante real · token en la creación de campaña · recuadro de verificación |
| `voter_portal.html` | Las cuatro afirmaciones corregidas |

**No cambia:** datos históricos, precios, tarifas, reglas comerciales, votos,
códigos de verificación, la consulta 819. No reancla ningún voto. Prefy igual.

---

## 2. Despliegue

```bash
cd <worktree>
git checkout deploy-correcciones
git fetch origin main
git log --oneline origin/main..HEAD        # debe mostrar UN commit
git diff --name-only origin/main HEAD | grep -E 'app\.json|package|prefy-video|prefy_test_harness'
# ^ no debe devolver nada

make test                                   # 1.171 en verde
git push origin deploy-correcciones:main
```

Render redespliega solo. Esperar a que `/health` reporte el commit nuevo:

```bash
curl -s https://preferendum-unzip-d2zd.onrender.com/health
```

**Momento:** la creación de los cinco índices únicos toma un bloqueo
exclusivo breve. Con 139 papeletas es instantáneo, pero conviene desplegar
en horario de baja actividad.

---

## 3. Comprobaciones posteriores, en orden

### 3.1 El servicio arrancó

```bash
curl -s https://preferendum-unzip-d2zd.onrender.com/health
```

Debe traer el `git_commit` nuevo y `"db":"ok"`.

### 3.2 Voto único — LO PRIMERO

```bash
curl -s 'https://preferendum-unzip-d2zd.onrender.com/admin/tally/reconciliation?secret=…' | python3 -m json.tool
```

En `garantia_voto_unico` las **cinco** deben decir `ACTIVO`. Si alguna dice
`DUPLICADOS:n`, la garantía no está puesta para esa dimensión: la migración
no borra nada y lo informa, así que hay que decidir qué hacer con esos
registros. No bloquea el resto.

En `desviaciones` no debe haber ninguna entrada nueva.

### 3.3 Resultados y consulta 819

```bash
curl -s https://preferendum-unzip-d2zd.onrender.com/debates/819/results
```

Debe publicar **1 voto**. Si publica otro número, revertir y avisar.

Las consultas 1, 2 y 3 deben seguir **sin cifras** en vista pública.

### 3.4 Importes históricos — no deben haberse movido

Volver a ejecutar el script de solo lectura y comparar con lo anotado:

```
impresiones 430   ·   cost_clp 0   ·   spent_clp 3.366
```

Si alguna cambió, revertir.

### 3.5 Registro

Dar de alta un votante de prueba con una dirección propia y comprobar que
llega el código. Confirmarlo y verificar que el usuario queda verificado.
Borrar la cuenta después con `/admin/purge-user`.

### 3.6 CAMPAÑAS — las dos correcciones

En `/marketer-portal`:

1. **Alta**: crear una cuenta de anunciante de prueba. El formulario ahora
   pide **categoría de empresa**. Debe quedar con rol de anunciante.
2. **Crear campaña**: debe completarse. Antes devolvía 403.
3. Editar, pausar y ver métricas de esa campaña.
4. Borrar la campaña y la cuenta de prueba al terminar.

**Sin ejecutar pagos reales**: no comprar paquetes ni usar Stripe.

### 3.7 Estado del blockchain

```bash
curl -s 'https://preferendum-unzip-d2zd.onrender.com/admin/blockchain-status?secret=…'
```

Anotar si `live` es `true`. A partir de ahora, cada voto nuevo guarda en
`blockchain_anchored` si se ancló **de verdad**: `true` solo con recibo
confirmado, `false` si no. Los 113 votos históricos con hash simulado
siguen con `NULL` (desconocido) y **no se reanclan**.

---

## 4. Reversión

**Sin reescribir el historial.** El commit de despliegue se revierte y se
sube como un commit más:

```bash
git checkout -b revertir-correcciones origin/main
git revert --no-edit <sha-del-commit-de-despliegue>
git push origin revertir-correcciones:main
```

Esperar a que `/health` reporte el commit de reversión.

**La base de datos no hay que tocarla.** Todo lo que la migración añade es
**aditivo** y la versión anterior lo ignora:

| Lo que se añadió | Qué pasa al revertir el código |
|---|---|
| 5 índices únicos de voto | Quedan. Siguen impidiendo el doble voto; el código viejo no los conoce pero tampoco los viola |
| `ix_debate_votes_debate_option` | Queda. Solo acelera un `GROUP BY` que el código viejo no hace |
| Columna `cost_credits_posted` | Queda vacía. El código viejo no la lee |

**El único efecto visible de revertir** es que las consultas 1, 2 y 3
volverían a tener su contador inflado como fuente del resultado — y siguen
suprimidas en vista pública, así que no cambia nada para el usuario.

Si además hiciera falta volver a los datos del respaldo (no previsto, porque
el despliegue no modifica datos):

```bash
RESTORE_URL='<URL de una base NUEVA, nunca producción>' \
  tools/restore_db.sh ~/Downloads/2026-11-01T03-04Z.dir.tar.gz
```

El script se niega a escribir sobre una base cuyo nombre sugiera producción
salvo que se le pase `--i-understand-this-overwrites`.

---

## 5. Lo que este despliegue NO resuelve

Declarado para que no se confunda con lo corregido:

- **Verificación independiente en la cadena: no existe.** El código de
  verificación se resuelve contra nuestra base de datos.
- **113 votos históricos** tienen hash simulado y `blockchain_anchored` en
  `NULL`. No se reanclan.
- **Facturas: no implementadas.**
- **Cobro real de Stripe o cripto: no comprobado** (sin credenciales).
- **Reconocimiento facial: no comprobado** (exige AWS; falla cerrado).
- **Respaldo programado y fuera de Render: no existe.** El procedimiento
  está probado; la periodicidad, no.
- **RTO real de producción: no medido.**
