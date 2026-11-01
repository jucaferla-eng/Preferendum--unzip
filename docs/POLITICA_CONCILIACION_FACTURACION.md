# Política de conciliación de facturación — PROPUESTA

**Estado: PROPUESTA. No se ha cambiado ninguna regla comercial ni ningún
cargo histórico.** Este documento analiza las dos inconsistencias
detectadas, explica su causa y propone una política. Nada de lo que aquí se
recomienda está implementado.

Las cifras son medidas, no estimadas: salen de ejecutar el código real con
`COST_PER_VIEW = 20` y `USD_TO_CLP = 950`.

---

## 1. Los hechos

Hoy, **una sola impresión cobrada produce tres números distintos**:

| Representación | Dónde vive | Valor | De dónde sale |
|---|---|---|---|
| Registro de impresión | `ad_impression_logs.cost_clp` | **20 CLP** | `COST_PER_VIEW` |
| Espejo de gasto | `ad_campaigns.spent_clp` | **+20 CLP** | `int(round(creditos_PEDIDOS × 950))` |
| Ledger canónico | `ledger_entries.amount` | **0,02 créditos ≡ 19 CLP** | `round_amount(20/950)` |

El precio por impresión es `20/950 = 0,021052631…` créditos. El ledger lleva
los importes **al céntimo** (`ledger.round_amount`, 2 decimales), así que
postea `0,02`. Pierde `0,00105…` créditos por impresión.

**Desvío: 1,00 CLP por impresión, el 5,26 %.**

| Impresiones | Ledger (canónico) | `spent_clp` | Brecha |
|---|---|---|---|
| 1 | 19 CLP | 20 CLP | 1 CLP |
| 1.000.000 | 19.000.000 CLP | 20.000.000 CLP | **1.000.000 CLP** |

### 1.1 El espejo no es un espejo

Esto es más preciso —y más grave— de lo que informé primero.

`_ledger_spend` calcula el espejo así:

```python
cost_clp = int(round(float(cost_credits) * USD_TO_CLP))   # cost_credits = lo PEDIDO
```

Usa el importe **pedido** (`0,021052…`), no el **posteado** (`0,02`). Por eso
`spent_clp` suma 20 mientras el ledger reconoce 19. Su propio docstring dice
que «mirrors the CLP-equivalent cost», y no lo hace: refleja la petición, no
el asiento.

Consecuencias concretas:

- La puerta de entrega es `budget_clp > spent_clp`. Con el espejo inflado un
  5,26 %, **una campaña deja de entregarse antes de haber gastado su
  presupuesto** según el libro canónico.
- Cualquier factura construida sobre `spent_clp` cobraría un 5,26 % más de
  lo que el ledger reconoce.
- La conciliación exacta es imposible mientras las dos cifras se calculen
  de formas distintas.

### 1.2 El sistema ya lo detecta, pero no tiene política

`ledger.reconcile_campaign_spend` ya compara las cuatro representaciones con
una tolerancia de **1,0 CLP** — exactamente el error de una impresión. Con
dos o más impresiones la divergencia supera la tolerancia y se reporta en
`/admin/ledger/reconciliation`. No es un hueco de detección: es un hueco de
**decisión**.

---

## 2. Segunda inconsistencia: dos precios distintos

Conviven dos precios por impresión, calculados de formas incompatibles:

| Precio | Función | Con los datos de prueba | Cuándo se usa |
|---|---|---|---|
| Plano | `COST_PER_VIEW` | **20 CLP** | Al SERVIR: es lo que se cobra |
| Derivado de CPM | `_cost_per_impression_clp(campaña, db)` | **6 CLP** | Al ESTIMAR y al REPARAR |

`_cost_per_impression_clp` promedia `cpm_usd` de `commune_market_data` sobre
las comunas que la campaña segmenta, y divide por 1000. Es un precio
**vigente**, que cambia cuando cambian esos datos de mercado.

`POST /admin/campaigns/{id}/recompute-spend` recalcula el gasto como
`impresiones × _cost_per_impression_clp(...)`. Medido: **3 impresiones
cobradas a 20 CLP (60 CLP en el libro de impresiones) se recalculan a 18
CLP.**

Su docstring dice «from the campaign's REAL impression count — never
inferred or invented», y el **recuento** no se inventa; el **precio
aplicado** sí es otro. Dos consecuencias:

1. Reparar una campaña **mueve su gasto histórico a una base de precios que
   nunca se le aplicó**.
2. El resultado **depende de cuándo se ejecute la reparación**, porque
   `commune_market_data` cambia con los agentes de mercado.

La ruta ya se niega a actuar sobre una campaña `LEDGER_MANAGED` (409
verificado), así que hoy el daño está acotado a campañas legacy. Pero la
herramienta sigue siendo la única vía de reparación y su aritmética no
preserva lo cobrado.

---

## 3. Lo que una política tiene que garantizar

1. **Preservar los importes históricos efectivamente cobrados.** Lo que se
   cobró se cobró. Ninguna corrección puede reescribir un cargo pasado.
2. **Conciliación exacta** —no «dentro de una tolerancia»— entre
   impresiones, ledger y facturas.
3. **Independencia del momento**: recalcular dos veces el mismo periodo
   debe dar el mismo número, hoy y en seis meses.
4. **Una sola definición de precio** por cada propósito, sin dos funciones
   que respondan a la misma pregunta.

---

## 4. Propuesta

### 4.1 El importe cobrado se almacena, no se vuelve a derivar

**Regla: cada impresión guarda lo que se le cobró, y toda suma posterior
suma esas filas. Nunca se recalcula un precio para un periodo pasado.**

`ad_impression_logs` guarda hoy solo `cost_clp`. La propuesta añade columnas
(aditivas, sin tocar filas existentes) para que cada fila **se describa a sí
misma**:

| Columna nueva | Para qué |
|---|---|
| `cost_credits_posted` | El importe EXACTO que se asentó en el ledger |
| `ledger_transaction_id` | El asiento concreto: enlaza impresión ↔ ledger fila a fila |
| `price_basis` | `'flat_cost_per_view'`, `'cpm_commune'`, … |
| `price_version` | Versión de la política de precios aplicada |
| `fx_usd_to_clp` | El tipo de cambio usado ESE día |

`fx_usd_to_clp` importa: `USD_TO_CLP = 950` es hoy una constante del código.
El día que se mueva, toda conversión de un histórico cambiaría de valor
retroactivamente. Guardarlo por fila congela el pasado.

Las filas históricas quedan con las columnas nuevas en `NULL`, que significa
«desconocido», nunca un valor supuesto (R7). Para ellas la única cifra
defendible es la que ya tienen: `cost_clp`.

### 4.2 Facturar en una unidad entera, para que no haya redondeo

**Regla: el importe se postea en una unidad mínima ENTERA. Un entero no se
redondea.**

El problema de fondo es que el precio por impresión (0,021052… créditos) es
más fino que la unidad del ledger (el céntimo). Mientras se cobre impresión
a impresión redondeando cada una, hay residuo.

Tres opciones, de peor a mejor:

| Opción | Qué implica | Veredicto |
|---|---|---|
| **A.** Fijar el precio a un número exacto de céntimos (0,02 créditos = 19 CLP) | Exacto desde ya, sin cambios de esquema | **Cambia el precio** (−5,26 %). Es una decisión comercial, no técnica |
| **B.** Subir la precisión del ledger a 6 decimales | Reduce el residuo ×10.000 | Sigue siendo inexacto. Mueve el problema, no lo quita |
| **C.** Postear en micro-créditos enteros (1e-6) y convertir solo para mostrar | Exacto por construcción, sin residuo nunca | **Recomendada**. Es lo que hacen los sistemas de facturación |

**Recomendación: opción C.** `cost_credits` deja de ser un flotante y pasa a
ser un entero de micro-créditos. 20/950 son 21.052 micro-créditos exactos,
se asientan tal cual, y la suma de un millón de impresiones es exacta. La
conversión a créditos o a CLP ocurre **solo al presentar**, nunca al
asentar.

Si la opción C se considera demasiado cambio para este momento, la **A** es
aceptable y mucho mejor que seguir como estamos — pero hay que decir en voz
alta que baja el precio efectivo un 5,26 %.

Lo que **no** es aceptable es dejarlo como está: hoy el precio efectivo ya
es el de la opción A (19 CLP es lo que el ledger reconoce), solo que sin
haberlo decidido y con `spent_clp` diciendo otra cosa.

### 4.3 El espejo refleja el asiento, no la petición

**Regla: `spent_clp` se calcula a partir del importe POSTEADO.**

```python
# en lugar de  int(round(cost_credits   * USD_TO_CLP))   ← lo PEDIDO
#              int(round(monto_posteado * USD_TO_CLP))   ← lo ASENTADO
```

Es una corrección de un defecto, independiente de qué opción de precio se
elija: el espejo debe reflejar lo que hay en el libro. **Solo hacia
adelante**: no toca ningún `spent_clp` histórico.

### 4.4 La herramienta de reparación suma, no re-tarifica

**Regla: `recompute-spend` pasa a ser `SUM(ad_impression_logs.cost_clp)`.**

Deja de llamar a `_cost_per_impression_clp`. Así el recálculo es exacto,
idéntico hoy y en seis meses, y preserva por definición lo cobrado.

`_cost_per_impression_clp` se queda donde le corresponde: **estimación
previa a la venta** (`/marketer/estimate`, optimización de presupuesto).
Pronosticar con el CPM vigente es correcto; contabilizar con él, no.

Conviene renombrarla a algo que impida el malentendido —
`_estimated_cost_per_impression_clp`— y documentar que no debe aparecer en
ninguna ruta contable.

### 4.5 La factura es una vista derivada y congelada

Hoy **no existe ningún concepto de factura** en el código: no hay tabla, ni
ruta, ni periodo de facturación. Cualquier factura que se emitiera saldría
de `spent_clp`, que es la cifra inflada.

Cuando se implemente, debe cumplir:

- Una factura cubre un **periodo cerrado** y referencia las impresiones
  concretas que la componen (sus ids, o un rango por fecha más un recuento).
- Su total es **la suma de los importes almacenados** en esas impresiones.
  No se re-tarifica.
- Una vez emitida es **inmutable**. Un error se corrige con una nota de
  crédito que también se asienta, nunca editando la factura.
- Lleva el `fx_usd_to_clp` del periodo, para que su conversión no cambie
  después.

### 4.6 La identidad que la conciliación debe comprobar

Para cada campaña, y para cada periodo de facturación:

```
SUM(impresiones.cost_credits_posted)  ==  gasto reconocido en el ledger
SUM(impresiones.cost_clp)             ==  spent_clp
SUM(facturas del periodo)             ==  SUM(impresiones del periodo)
```

Con **igualdad exacta, sin tolerancia**. La tolerancia de 1,0 CLP que hoy
usa `reconcile_campaign_spend` existe precisamente porque el redondeo la
hacía necesaria; con la opción C deja de hacer falta y debe bajar a cero.
Una tolerancia es un sitio donde se esconde un defecto.

---

## 5. Lo que NO propone esta política

- **No reescribir ningún cargo histórico.** Las campañas y las impresiones
  ya cobradas se quedan con los importes que tienen. Si el precio efectivo
  pasado fue 19 CLP y el registro dice 20, eso se **documenta** como un
  periodo con desvío conocido del 5,26 %; no se corrige hacia atrás.
- **No decidir el precio.** Cuál de las opciones A/B/C se adopta, y si el
  precio por impresión debe ser 19, 20 o otro, es una decisión comercial.
- **No tocar los dos interruptores de política** que siguen declarados como
  no aprobados por negocio: `ledger.DEMO_POLICY_APPROVED_BY_BUSINESS` y
  `socioeconomic.THRESHOLDS_APPROVED_BY_BUSINESS`.

---

## 6. Orden de aplicación sugerido

Si se autoriza, este orden evita tocar nada histórico y deja cada paso
verificable por separado:

1. **Columnas nuevas en `ad_impression_logs`** (aditivo, históricas en
   `NULL`). No cambia ningún importe. Verificable sin riesgo.
2. **`spent_clp` refleja el asiento** (§4.3). Corrección de defecto, solo
   hacia adelante.
3. **`recompute-spend` pasa a sumar** (§4.4). Deja de poder mover un
   histórico a otra base de precios.
4. **Decisión comercial del precio** (§4.2). Es el único paso que necesita
   una decisión de negocio, y hasta que se tome los tres anteriores ya
   dejan el sistema conciliable y auditable.
5. **Facturas** (§4.5), cuando haya una decisión de precio estable.
6. **Bajar la tolerancia a cero** (§4.6), que es la prueba de que todo lo
   anterior funcionó.

---

## 7. Cómo verificar cada afirmación de este documento

Las dos inconsistencias están fijadas con pruebas que avisan si el
comportamiento cambia, para que nadie las dé por resueltas sin revisarlas:

- `test_e2e_commercial.TestD_EntregaYContabilidad.test_D6b_HALLAZGO_el_cargo_redondeado_no_iguala_el_precio_declarado`
- `test_e2e_commercial.TestD_EntregaYContabilidad.test_D22b_HALLAZGO_el_recalculo_usa_el_cpm_de_hoy_no_lo_cobrado`

Ambas fallan a propósito si las cifras dejan de divergir, obligando a
retirar la prueba y actualizar este documento en vez de dejarlo mintiendo.
