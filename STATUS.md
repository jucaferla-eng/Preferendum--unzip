# PREFERENDUM — STATUS MAESTRO
*Última actualización: Mayo 2026*
*En memoria de José Ignacio Fernández (1989-2024)*

---

## BACKEND (https://preferendum-unzip.onrender.com)

### ✅ HECHO Y FUNCIONANDO EN PRODUCCIÓN
- FastAPI corriendo en Render
- Base de datos SQLite con modelos completos
- `POST /auth/register` — registro de usuarios
- `POST /auth/login` — login con JWT
- `GET /auth/me` — perfil del usuario
- `GET /debates` — lista de debates
- `GET /debates/feed` — feed por país
- `GET /debates/{id}` — detalle de debate
- `POST /debates/{id}/vote` — votar
- `GET /debates/{id}/opinions` — opiniones con ads cada 5
- `POST /debates/{id}/opinions` — publicar opinión
- `GET /debates/{id}/results` — resultados
- `POST /debates/{id}/verify` — verificar voto por código
- `POST /debates/{id}/verify/confirm` — confirmar/disputar voto
- `GET /privacy` — política de privacidad HTML
- Bridge destruction (voter_id = None después de votar)
- Legitimacy Score calculado en tiempo real
- Código XXXX-XXXX-XXXX generado por voto
- 3 debates demo pre-cargados (diputados, Las Condes, Nike)
- Ads pre-cargados (BancoEstado, Toyota, Samsung)
- CPM por tier de país (Premium/Mid/Volume — 30 países)

### ⚠️ IMPLEMENTADO PERO MOCK (no real)
- **Blockchain** — genera hash falso `0x` + 64 chars aleatorios. Smart contract Solidity escrito pero NO desplegado en Polygon.
- **AES-256** — usa base64 simple, no AES real (falta pycryptodome configurado)
- **Verificación de documento** — acepta cualquier imagen, no lee el documento real
- **Verificación de selfie** — acepta cualquier imagen, no compara con documento
- **IMEI** — hashea el IMEI enviado, no lo captura del dispositivo real
- **Geolocalización** — acepta cualquier coordenada, no verifica contra país del usuario
- **Wallet blockchain** — valida formato de dirección, no verifica propiedad real

### ❌ NO CONSTRUIDO
- Panel del organizador (interfaz web para crear consultas)
- Panel del anunciante (interfaz para subir ads y ver métricas)
- Sistema de pagos para anunciantes (Stripe/MercadoPago)
- Closed List feature (lista de votantes autorizados por ID)
- Proxy de ingreso por m² de vivienda (descrito, no implementado en backend)
- Facial recognition real (comparar selfie vs foto del documento)
- Blockchain Polygon real (smart contract escrito, falta desplegar)

---

## EMAIL Y SMS

### ✅ HECHO
- Twilio cuenta de PAGO activa (puede enviar a cualquier número del mundo)
- SMS OTP funciona — probado y confirmado
- Código OTP se genera correctamente en el backend
- Resend cuenta creada con API key en Render

### ❌ BLOQUEADO
- **Email no llega** — dominio preferendum.com en Cloudflare sin acceso configurado
- Resend requiere DNS verificado para enviar
- DNS de preferendum.com están en Cloudflare (cuenta original perdida — Walter puede tener acceso)
- SendGrid: HTTP 403 (rechaza la API key actual)
- Gmail SMTP: Error 535 (credenciales rechazadas)

---

## APP MÓVIL iOS

### ✅ HECHO
- React Native + Expo
- Build 16 en TestFlight funcionando
- Bundle ID: com.caip.preferendumapp
- Diseño completo ("Democratic Precision")
- Pantallas: launch, register, login, verify-identity, feed, debate, vote, results, verify, profile
- API_URL conectada al backend de Render
- Registro conectado a `/auth/register`
- Login conectado a `/auth/login`
- Feed conectado a `/debates/feed`
- SMS OTP funciona desde la app
- Ícono final elegido por Macarena (madre de José Ignacio)

### ❌ BLOQUEADO / PENDIENTE
- **Apple App Store submission bloqueada** — versión 1.0 rechazada, no se puede crear 1.0.1 desde iPad. Necesita Apple Support (1-800-633-2152)
- Email de verificación no llega (DNS pendiente)
- Debate room no conectado al backend real (usa datos locales)
- Panel del organizador no construido
- Flujo completo de votación desde la app no probado end-to-end

---

## APP MÓVIL ANDROID

### ✅ HECHO
- Bundle ID: com.caip.preferendum
- Build AAB subido a Google Play
- 12 testers configurados
- Privacy policy URL configurada
- Screenshots y ícono 512x512 subidos

### ❌ BLOQUEADO
- **Google Play ficha con error de idiomas** — bloquea la publicación
- Necesita revisión de screenshots por idioma

---

## BLOCKCHAIN

### ✅ ESCRITO (no desplegado)
- Smart contract `Preferendum.sol` completo en Solidity
- Funciones: `createDebate`, `anchorVote`, `confirmVote`, `getVoteByCode`, `getLegitimacyScore`
- `blockchain_integration.py` — integración Python con Web3
- Fallback automático a mock si no hay credenciales

### ❌ PENDIENTE
- Desplegar contrato en Polygon Mainnet (necesita wallet con ~1 MATIC)
- Configurar `POLYGON_RPC_URL`, `WALLET_PRIVATE_KEY`, `CONTRACT_ADDRESS` en Render
- Integrar `blockchain_integration.py` en `main.py` (reemplazar mock actual)

---

## INFRAESTRUCTURA

### ✅ CONFIGURADO
| Servicio | Estado | Notas |
|----------|--------|-------|
| Render | ✅ Live | Plan gratuito, se duerme sin actividad |
| GitHub | ✅ | github.com/jucaferla-eng/Preferendum-unzip |
| Apple Developer | ✅ | Team 94LF36AQDA, Transfer Telecomunicaciones S.A |
| Google Play | ✅ | Developer ID: 8581086136462079138 |
| Twilio | ✅ PAGO | +15075027781, puede enviar SMS mundial |
| EAS (Expo) | ✅ | @jifg749090/preferendum — límite de builds alcanzado |
| SendGrid | ⚠️ | API key 403, sender no verificado |
| Resend | ⚠️ | API key configurada, DNS pendiente |
| Cloudflare | ❌ | preferendum.com — sin acceso a la cuenta |

### Variables de entorno en Render
- `JWT_SECRET` ✅
- `TWILIO_ACCOUNT_SID` ✅
- `TWILIO_AUTH_TOKEN` ✅
- `TWILIO_PHONE_NUMBER` ✅
- `SENDGRID_API_KEY` ✅ (403 error)
- `GMAIL_APP_PASSWORD` ✅ (535 error)
- `RESEND_API_KEY` ✅ (DNS pendiente)
- `FROM_EMAIL` ✅

---

## PARA WALTER — PRIORIDADES

1. **DNS Cloudflare** — acceso a cuenta preferendum.com → agregar 3 registros Resend → email funcionando
2. **Apple App Store** — crear versión 1.0.1 y resubmitir con build 16
3. **Google Play** — resolver error de idiomas en la ficha
4. **Blockchain** — desplegar Preferendum.sol en Polygon con wallet MATIC
5. **Debate room** — conectar al backend real end-to-end
6. **SMS Gateway Android** — configurar el Samsung como gateway (reemplaza Twilio para pruebas locales)

---

## ESTIMACIÓN DE HORAS RESTANTES
| Tarea | Horas |
|-------|-------|
| DNS + email funcionando | 1-2h |
| Apple App Store aprobación | 2-4h + 1-3 días Apple |
| Google Play aprobación | 2-3h + 1-3 días Google |
| Blockchain real | 4-6h |
| Debate room conectado | 4-6h |
| Panel organizador básico | 8-12h |
| Panel anunciante básico | 8-12h |
| **TOTAL** | **~30-45h** |
