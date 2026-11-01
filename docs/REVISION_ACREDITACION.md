# Revisión de acreditaciones empresariales

Procedimiento único, compartido por **CREAR CONSULTA** y **CAMPAÑAS**.

## Qué identifica a una empresa

`(país, identificación tributaria normalizada)`. Nada más.

No el nombre: dos empresas distintas pueden llamarse igual, y una razón social
es texto que cualquiera escribe en un formulario. No el dominio del correo:
`@gmail.com` no acredita nada, y un dominio propio tampoco demuestra un cargo.

La normalización quita puntos, guiones y espacios y pasa a mayúsculas, así que
`76.123.456-7`, `76123456-7` y `761234567` son la misma empresa. El mismo
número en otro país es **otra** empresa.

Sin identificación normalizable el perfil queda **sin vincular** y pasa a
revisión excepcional. No se inventa una empresa a partir del nombre.

La tabla `companies` lleva un índice único `(country, tax_id_norm)`:
la unicidad la garantiza la base de datos, no el código.

## Estados

| Quién | Estado inicial | Puede operar |
|---|---|---|
| Ciudadano a título personal | `approved` | sí, igual que siempre |
| Primer representante de una empresa u organismo | `pending` | no |
| Representante adicional | `pending` hasta que lo autorice un supervisor acreditado de su misma empresa | no |

Mientras está `pending`: no puede publicar consultas, ni crear o activar
campañas, ni obtener saldo. El servidor lo rechaza con 403 aunque alguien
intente saltarse la interfaz, y ahora los dos portales lo dicen en pantalla en
vez de dejar que el botón falle sin explicación.

## El panel de revisión

El secreto administrativo viaja **por cabecera**, nunca en la URL: estas rutas
devuelven documentos de identidad y de cargo, y una URL queda en el historial
del navegador, en los registros del proxy y en el `Referer` de cualquier
recurso externo.

Es el mismo `ADMIN_SECRET` de siempre. No hay un mecanismo de autenticación
nuevo; lo único que cambia es por dónde viaja.

### Ver lo pendiente

```bash
curl -s -H "X-Admin-Secret: $ADMIN_SECRET" \
  https://preferendum-unzip.onrender.com/admin/accreditation/pending | python3 -m json.tool
```

Solo lectura. Devuelve lo necesario para decidir: tipo de perfil, `user_id`,
`company_id`, país, identificación, si la identificación está verificada, qué
verificaciones pasaron y si hay documento de cargo. **No** devuelve el
documento, ni el correo, ni el teléfono, ni el RUT personal del solicitante.

### Ver el documento de uno

```bash
curl -s -H "X-Admin-Secret: $ADMIN_SECRET" \
  "https://preferendum-unzip.onrender.com/admin/accreditation/document?tipo=organizador&user_id=123"
```

`tipo` es `organizador` o `anunciante`. Devuelve el `sha256` y el contenido en
base64, de uno en uno. El documento nunca se publica en un enlace abierto ni
se adjunta a un correo.

### Decidir

```bash
curl -s -X POST -H "X-Admin-Secret: $ADMIN_SECRET" \
     -H 'Content-Type: application/json' \
     -d '{"tipo":"organizador","user_id":123,"decision":"approved","decidido_por":"JC"}' \
  https://preferendum-unzip.onrender.com/admin/accreditation/decide
```

`decision` es `approved`, `rejected` o `more_info`. `motivo` se guarda y es lo
que verá el solicitante. Cada decisión deja registrado quién decidió, cuándo y
con qué resultado.

No se puede aprobar una organización **sin empresa identificada**: devuelve 409.
Aprobar sin identificación sería volver a acreditar por nombre. Si tras revisar
los antecedentes la empresa es la que dice ser, se vincula en la misma llamada:

```json
{"tipo":"organizador","user_id":123,"decision":"approved",
 "decidido_por":"JC","vincular_company_id":7}
```

### Completar los antecedentes de una solicitud antigua

Las solicitudes anteriores a este procedimiento se registraron con los
formularios que no enviaban la identificación tributaria, así que no hay
ninguna empresa a la que vincularlas. Tras comprobar los antecedentes, se
escriben en la misma decisión:

```json
{"tipo":"anunciante","user_id":321,"decision":"approved","decidido_por":"JC",
 "crear_empresa":{"country":"CL","tax_id":"76.123.456-7","name":"Empresa SpA"}}
```

Se resuelve con la misma función que usa el registro, así que si esa empresa
ya está registrada **se reutiliza**, no se duplica. La respuesta dice si se
creó o se reutilizó, la identificación normalizada y si quedó verificada
—para Chile se comprueba el dígito verificador; fuera de Chile no hay
validador y queda sin verificar, igual que en el registro—.

Escribir esos datos **no aprueba a nadie**. Lo único que decide es
`decision`: con `more_info` la empresa queda identificada y la cuenta sigue
pendiente. Un perfil ya vinculado a otra empresa no se reasigna desde aquí
(409): mover a un representante entre empresas con una errata sería crear
justo la autorización cruzada que el procedimiento impide.

Esa es también la vía para los **21 perfiles empresariales históricos**: la
migración no vinculó ninguno y no cambió ningún permiso. Siguen aprobados y
siguen operando. Lo único que no pueden hacer mientras estén sin vincular es
acreditar empleados, porque «misma empresa» no se puede comprobar sobre un
perfil que no está asociado a ninguna. Se vinculan uno a uno, a mano, cuando
haga falta.

## Autorización por un supervisor

Un supervisor acreditado puede autorizar a un empleado desde el enlace que le
llega por correo. El servidor comprueba **cuatro** cosas que antes no
comprobaba:

1. **Nadie se aprueba a sí mismo.**
2. **Quien aprueba es el supervisor designado en la solicitud.** Poseer el
   token ya no basta.
3. **Su perfil está vinculado a una empresa.** Un perfil sin vincular no
   acredita a nadie.
4. **El solicitante es de esa misma empresa**, por `company_id`, no por nombre
   ni por dominio.

Y sigue exigiendo, como antes, que el supervisor esté `approved`, sea
supervisor y tenga su propia identidad verificada con selfie.

Un token ya resuelto no vuelve a servir: la consulta filtra por
`status='pending'`, así que un segundo intento devuelve 404.

## Lo que este cambio NO hace

- No vincula ningún perfil histórico automáticamente.
- No cambia los permisos de ninguna cuenta existente.
- No interrumpe ninguna campaña activa.
- No toca votos, resultados, códigos de verificación, blockchain ni cargos
  históricos.
- No añade un segundo sistema de identificación: reutiliza la verificación de
  RUT, de dominio, de sitio web y de documento que ya existían y que los
  formularios no estaban enviando.
