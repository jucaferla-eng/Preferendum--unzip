/**
 * prefy-content.js — Preferendum's contextual guide: canonical state list,
 * context registry, and translated copy.
 *
 * This file is PURE DATA + pure lookup functions. It never touches the DOM,
 * never reads localStorage, and never decides WHEN to show anything — that
 * is prefy.js's job. Same split as lang.js (pure resolveLanguage() vs
 * browser-only wiring) and as eligibility.py/socioeconomic.py vs main.py's
 * adapters: this module decides WHAT Prefy would say; prefy.js decides
 * WHETHER/WHEN to say it.
 *
 * Prefy explains what Preferendum's business logic already decided. It
 * never computes a tier, an income estimate, an eligibility result, a
 * fraud signal, or a balance itself — every number/state referenced here
 * is either generic methodology (no per-user values) or is handed in by
 * the caller from an already-computed, already-displayed value.
 *
 * Exported as CommonJS (for Node-based tests) AND attached to
 * `window.PrefyContent` in a browser — identical to lang.js's pattern.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.PrefyContent = factory();
  }
})(typeof window !== 'undefined' ? window : this, function () {
  'use strict';

  // ═══════════════════════════════════════════════════════════════════════
  // THE 15 CANONICAL VISUAL STATES (per the supplied Prefy concept sheet)
  // ═══════════════════════════════════════════════════════════════════════
  var STATES = [
    'WELCOME', 'EXPLAINING', 'PRESENTING', 'THINKING', 'IDEA', 'ATTENTION',
    'MISSING_INFORMATION', 'ERROR', 'POSSIBLE_FRAUD', 'HACKER_ALERT',
    'GOOD_JOB', 'SUCCESS', 'THANKS', 'HELP', 'GOODBYE',
  ];

  // These two MUST NEVER be reachable from an ordinary application event in
  // Phase 1 (single failed password, single selfie/document mismatch,
  // ordinary validation error, ordinary network error, a single 429).
  // prefy.js's setState()/setContext() consult this list and refuse to
  // apply either state unless the caller passes the explicit Phase-2
  // override token (which nothing in this phase's integration ever does —
  // see test_prefy.mjs's "cannot trigger" tests).
  var SECURITY_STATES = ['POSSIBLE_FRAUD', 'HACKER_ALERT'];

  // Safe fallback when a context key or state is unrecognized — never a
  // security state, never a silent no-op that could look broken.
  var DEFAULT_STATE = 'HELP';
  var UNKNOWN_CONTEXT_KEY = '_unknown';

  // ═══════════════════════════════════════════════════════════════════════
  // ASSET MAP — the 15 final Prefy images are NOT in this repository (per
  // the read-only audit's finding C). This documents the exact filenames/
  // dimensions the real art must ship as; prefy.js falls back to a neutral,
  // clearly-generic inline badge (see prefy.js's renderFallbackBadge) until
  // these exist. No screenshot from the concept sheet and no fabricated
  // character art is embedded anywhere in this codebase.
  //
  // Expected location once supplied: /prefy-assets/<filename> (served the
  // same way lang.js documents /lang.js — a plain file route in main.py).
  // SVG is preferred (crisp at any size, tiny payload); a @2x PNG fallback
  // is documented for whoever supplies raster-only art.
  var ASSET_WIDTH = 512;
  var ASSET_HEIGHT = 512;
  var ASSETS = {};
  STATES.forEach(function (s) {
    var kebab = s.toLowerCase().replace(/_/g, '-');
    ASSETS[s] = {
      svg: '/prefy-assets/prefy-' + kebab + '.svg',
      png2x: '/prefy-assets/prefy-' + kebab + '@2x.png',
      width: ASSET_WIDTH,
      height: ASSET_HEIGHT,
    };
  });

  // ═══════════════════════════════════════════════════════════════════════
  // TRANSLATED STRINGS — same shape/convention as voter_portal.html's own
  // UI_STRINGS + t(key). Fully authored for es/en (the two languages this
  // phase can produce and verify at real quality). The other 10 languages
  // PreferendumLang.SUPPORTED_LANGUAGES already lists (pt, fr, de, it, ja,
  // ko, zh, ar, ru, hi) are a DOCUMENTED, DISCLOSED gap for this phase —
  // str() below falls back to es for any key missing in the resolved
  // language, exactly like voter_portal.html's own t(), so a missing
  // translation degrades to Spanish text, never to a blank bubble, a raw
  // key, or a crash. See the Phase 1 report, section Y, for follow-up.
  var STRINGS = {
    es: {
      'chrome.minimize': 'Minimizar',
      'chrome.expand': 'Expandir',
      'chrome.close': 'Cerrar',
      'chrome.help': 'Ayuda',
      'chrome.reopen': 'Volver a explicar esta pantalla',
      'chrome.name': 'Prefy',
      'chrome.help.whereAmI': '¿Dónde estoy?',
      'chrome.help.whatCanIDo': '¿Qué puedo hacer aquí?',
      'chrome.help.why': '¿Por qué me piden esto?',
      'chrome.help.how': '¿Cómo funciona esta sección?',
      'chrome.unknown.title': 'Prefy',
      'chrome.unknown.body': 'Aún no tengo una explicación preparada para esta pantalla — pero el resto de Preferendum funciona igual.',

      'ctx.voter.welcome.title': '¡Bienvenido a Preferendum!',
      'ctx.voter.welcome.body': 'Soy Prefy, tu guía dentro de Preferendum. Te explico qué hace cada pantalla y por qué se te pide cada dato, a medida que avanzas. Puedes minimizarme en cualquier momento.',

      'ctx.voter.auth.login.title': 'Iniciar sesión',
      'ctx.voter.auth.login.body': 'Aquí ingresas con tu correo y contraseña ya registrados. Si es tu primera vez, usa la pestaña de registro.',

      'ctx.voter.register.country.title': 'País',
      'ctx.voter.register.country.body': 'Usamos tu país para tu contexto de cuenta y para saber a qué consultas eres elegible — muchas consultas están limitadas a un país o región específica.',

      'ctx.voter.register.commune.title': 'Comuna / localidad',
      'ctx.voter.register.commune.body': 'Tu comuna se usa para consultas de alcance local y, cuando corresponde, como parte del contexto socioeconómico de tu zona — nunca para identificarte ante otros usuarios.',

      'ctx.voter.register.dob.title': 'Fecha de nacimiento',
      'ctx.voter.register.dob.body': 'Tu edad determina a qué consultas eres elegible cuando tienen un rango etario configurado, y — cuando el sistema estima un rango de ingreso porque no hay una declaración explícita — es una de las señales que se usan para ese cálculo.',

      'ctx.voter.register.occupation.title': 'Ocupación',
      'ctx.voter.register.occupation.body': 'Tu ocupación se clasifica contra un catálogo estándar. Puede ser un criterio de segmentación para ciertas consultas o campañas, y contribuye a estimar un rango de ingreso cuando no lo declaras directamente.',
      'ctx.voter.register.occupation.why': 'Nunca mostramos ni compartimos tu ocupación exacta con otros usuarios — solo se usa internamente para elegibilidad y estimación.',

      'ctx.voter.register.company_size.title': 'Tamaño de la empresa',
      'ctx.voter.register.company_size.body': 'El tamaño de tu empresa da contexto económico adicional. Donde está implementado, contribuye a la estimación de ingreso y puede ser un criterio de segmentación — pero no todas las consultas ni campañas lo usan.',

      'ctx.voter.register.email.title': 'Correo electrónico',
      'ctx.voter.register.email.body': 'Tu correo se usa para el acceso a tu cuenta, para verificarte y para enviarte códigos de seguridad cuando corresponda.',

      'ctx.voter.register.phone.title': 'Teléfono',
      'ctx.voter.register.phone.body': 'Tu teléfono se usa para verificación por SMS y como capa adicional de seguridad de tu cuenta.',

      'ctx.voter.verify.selfie.title': 'Verificación con selfie',
      'ctx.voter.verify.selfie.body': 'Tu selfie confirma que eres una persona real y que coincide con tu documento. Prefy no recibe ni almacena tu foto — eso lo procesa el sistema de verificación directamente.',

      'ctx.voter.verify.document.title': 'Verificación de documento',
      'ctx.voter.verify.document.body': 'Tu documento de identidad se usa solo para confirmar quién eres. Prefy nunca lee ni muestra los datos de tu documento — ni aquí ni en ninguna otra pantalla.',

      'ctx.voter.consultations.title': 'Tus consultas',
      'ctx.voter.consultations.body': 'Aquí ves las consultas para las que Preferendum determinó que eres elegible, según los criterios configurados en cada una. No todas usan los mismos criterios.',

      'ctx.voter.consultation.detail.title': 'Detalle de la consulta',
      'ctx.voter.consultation.detail.body': 'Esta pantalla tiene la pregunta, el contexto, las opiniones de otros participantes y — cuando corresponde — los resultados. Usa las pestañas de abajo para moverte entre secciones.',

      'ctx.voter.opinion.title': 'Comparte tu perspectiva',
      'ctx.voter.opinion.body': 'Antes de votar, puedes leer y compartir opiniones sobre el tema. En algunas consultas esto es un paso obligatorio antes de poder votar.',

      'ctx.voter.voting_section.title': 'Sección de votación',
      'ctx.voter.voting_section.body': 'Aquí emites tu voto para esta consulta. Tu respuesta queda registrada de forma verificable.',

      'ctx.voter.vote.before_submit.title': 'Estás por enviar tu voto',
      'ctx.voter.vote.before_submit.body': 'Tu voto es privado y neutral: nadie más ve por quién votaste. Una vez enviado, no se puede votar de nuevo en esta misma consulta. Puedes verificar después que se registró exactamente como lo emitiste.',

      'ctx.voter.vote.success.title': '¡Voto registrado!',
      'ctx.voter.vote.success.body': 'Tu voto quedó registrado de forma verificable. Guarda tu código de verificación — te permite confirmar más adelante que tu voto se contó correctamente.',

      'ctx.voter.results.title': 'Resultados',
      'ctx.voter.results.body': 'Aquí ves cómo va (o cómo terminó) la consulta. Los resultados se calculan solo a partir de votos verificados.',

      'ctx.voter.profile.title': 'Tu perfil',
      'ctx.voter.profile.body': 'Aquí ves el estado de tu verificación y tu historial de participación. Puedes revisar qué falta verificar en tu cuenta desde aquí.',

      'ctx.voter.logout.title': '¡Hasta pronto!',
      'ctx.voter.logout.body': 'Gracias por participar en Preferendum. Tu sesión se cerrará en un momento.',

      'ctx.voter.missing_field.title': 'Falta un dato',
      'ctx.voter.missing_field.body': 'Revisa el campo marcado — es necesario para continuar.',

      'ctx.voter.error.generic.title': 'Algo no funcionó',
      'ctx.voter.error.generic.body': 'Hubo un problema al procesar esta acción. Puedes intentarlo de nuevo en un momento.',

      'ctx.voter.income_estimate_explainer.title': 'Cómo se estima un rango de ingreso',
      'ctx.voter.income_estimate_explainer.body': 'Cuando no declaras un ingreso explícito, Preferendum puede usar señales como ocupación, edad, tamaño de empresa y el contexto económico de tu zona para estimar un rango. No mostramos ese número exacto ni los coeficientes usados, y nunca es información visible para otros usuarios.',

      'ctx.organizer.home.title': 'Panel del organizador',
      'ctx.organizer.home.body': 'Desde aquí administras tus consultas: creación, seguimiento y resultados.',

      'ctx.organizer.create.title': 'Nueva consulta',
      'ctx.organizer.create.body': 'Define la pregunta, el contexto y las opciones. Esta información es lo primero que verán los participantes. Tu consulta pasa por un proceso de revisión antes de quedar disponible para votar.',

      'ctx.organizer.create.targeting.title': 'A quién llega esta consulta',
      'ctx.organizer.create.targeting.body': 'Estos campos (país, comuna, edad, tramo socioeconómico) configuran los criterios de elegibilidad. Preferendum los aplica automáticamente para decidir quién puede ver y votar tu consulta — no es obligatorio usar todos.',

      'ctx.organizer.missing_field.title': 'Falta un dato',
      'ctx.organizer.missing_field.body': 'Revisa el campo marcado — es necesario para publicar esta consulta.',

      'ctx.organizer.logout.title': '¡Hasta pronto!',
      'ctx.organizer.logout.body': 'Gracias por usar Preferendum. Tu sesión se cerrará en un momento.',

      'ctx.marketer.panel.overview.title': 'Resumen de tu cuenta',
      'ctx.marketer.panel.overview.body': 'Aquí ves un resumen de tus campañas y tu saldo disponible.',

      'ctx.marketer.panel.credits.title': 'Créditos REAL y DEMO',
      'ctx.marketer.panel.credits.body': 'Preferendum separa el dinero real (REAL) de los créditos de prueba (DEMO): son dos saldos completamente independientes. Los créditos DEMO sirven para probar el sistema de punta a punta y nunca se pueden usar como dinero real ni convertirse en él.',

      'ctx.marketer.panel.campaigns.title': 'Tus campañas',
      'ctx.marketer.panel.campaigns.body': 'Aquí ves el estado y los resultados de tus campañas activas y pasadas.',

      'ctx.marketer.panel.new_campaign.title': 'Crear campaña',
      'ctx.marketer.panel.new_campaign.body': 'Define tu campaña y sus criterios de segmentación (por ejemplo comuna, ingreso o demografía). Preferendum solo entrega tu anuncio a usuarios que cumplen los criterios que configuraste — y solo se factura contra saldo ya asignado a la campaña.',

      'ctx.marketer.missing_field.title': 'Falta un dato',
      'ctx.marketer.missing_field.body': 'Revisa el campo marcado — es necesario para crear la campaña.',

      'ctx.marketer.logout.title': '¡Hasta pronto!',
      'ctx.marketer.logout.body': 'Gracias por usar Preferendum. Tu sesión se cerrará en un momento.',
    },

    en: {
      'chrome.minimize': 'Minimize',
      'chrome.expand': 'Expand',
      'chrome.close': 'Close',
      'chrome.help': 'Help',
      'chrome.reopen': 'Explain this screen again',
      'chrome.name': 'Prefy',
      'chrome.help.whereAmI': 'Where am I?',
      'chrome.help.whatCanIDo': 'What can I do here?',
      'chrome.help.why': 'Why are you asking me this?',
      'chrome.help.how': 'How does this section work?',
      'chrome.unknown.title': 'Prefy',
      'chrome.unknown.body': "I don't have an explanation ready for this screen yet — but the rest of Preferendum works the same either way.",

      'ctx.voter.welcome.title': 'Welcome to Preferendum!',
      'ctx.voter.welcome.body': "I'm Prefy, your guide inside Preferendum. I'll explain what each screen does and why certain data is requested, as you go. You can minimize me any time.",

      'ctx.voter.auth.login.title': 'Log in',
      'ctx.voter.auth.login.body': 'Sign in here with your existing email and password. First time? Use the register tab instead.',

      'ctx.voter.register.country.title': 'Country',
      'ctx.voter.register.country.body': "We use your country for your account context and to determine which consultations you're eligible for — many consultations are limited to a specific country or region.",

      'ctx.voter.register.commune.title': 'Commune / locality',
      'ctx.voter.register.commune.body': 'Your commune is used for local-scope consultations and, where applicable, as part of your area’s economic context — never to identify you to other users.',

      'ctx.voter.register.dob.title': 'Date of birth',
      'ctx.voter.register.dob.body': 'Your age determines which consultations you’re eligible for when they have an age range configured, and — when the system estimates an income range because no explicit income was declared — it is one of the signals used for that estimate.',

      'ctx.voter.register.occupation.title': 'Occupation',
      'ctx.voter.register.occupation.body': 'Your occupation is matched against a standard classification. It can be a targeting criterion for some consultations or campaigns, and contributes to an estimated income range when you don’t declare one directly.',
      'ctx.voter.register.occupation.why': 'We never show or share your exact occupation with other users — it’s only used internally for eligibility and estimation.',

      'ctx.voter.register.company_size.title': 'Company size',
      'ctx.voter.register.company_size.body': 'Your company’s size adds economic context. Where implemented, it contributes to income estimation and can be a targeting criterion — but not every consultation or campaign uses it.',

      'ctx.voter.register.email.title': 'Email',
      'ctx.voter.register.email.body': 'Your email is used to access your account, to verify you, and to send you security codes when needed.',

      'ctx.voter.register.phone.title': 'Phone',
      'ctx.voter.register.phone.body': 'Your phone number is used for SMS verification and as an extra layer of account security.',

      'ctx.voter.verify.selfie.title': 'Selfie verification',
      'ctx.voter.verify.selfie.body': "Your selfie confirms you're a real person and that it matches your ID. Prefy never receives or stores your photo — the verification system handles that directly.",

      'ctx.voter.verify.document.title': 'Document verification',
      'ctx.voter.verify.document.body': 'Your ID document is used only to confirm who you are. Prefy never reads or displays your document’s details — here or anywhere else.',

      'ctx.voter.consultations.title': 'Your consultations',
      'ctx.voter.consultations.body': "Here you see the consultations Preferendum determined you're eligible for, based on each one's configured criteria. Not every consultation uses the same criteria.",

      'ctx.voter.consultation.detail.title': 'Consultation detail',
      'ctx.voter.consultation.detail.body': 'This screen has the question, context, other participants’ opinions, and — where available — results. Use the tabs below to move between sections.',

      'ctx.voter.opinion.title': 'Share your perspective',
      'ctx.voter.opinion.body': 'Before voting, you can read and share opinions on the topic. In some consultations this is a required step before you can vote.',

      'ctx.voter.voting_section.title': 'Voting section',
      'ctx.voter.voting_section.body': 'This is where you cast your vote for this consultation. Your response is recorded in a verifiable way.',

      'ctx.voter.vote.before_submit.title': "You're about to submit your vote",
      'ctx.voter.vote.before_submit.body': "Your vote is private and neutral — no one else sees who you voted for. Once submitted, you can't vote again on this same consultation. You'll be able to verify afterward that it was recorded exactly as you cast it.",

      'ctx.voter.vote.success.title': 'Vote recorded!',
      'ctx.voter.vote.success.body': 'Your vote was recorded in a verifiable way. Save your verification code — it lets you confirm later that your vote was counted correctly.',

      'ctx.voter.results.title': 'Results',
      'ctx.voter.results.body': 'Here you see how the consultation is going (or how it ended). Results are calculated only from verified votes.',

      'ctx.voter.profile.title': 'Your profile',
      'ctx.voter.profile.body': "Here you see your verification status and participation history. You can check what's still missing on your account from here.",

      'ctx.voter.logout.title': 'See you soon!',
      'ctx.voter.logout.body': "Thanks for participating in Preferendum. You'll be signed out in a moment.",

      'ctx.voter.missing_field.title': "Something's missing",
      'ctx.voter.missing_field.body': "Check the highlighted field — it's required to continue.",

      'ctx.voter.error.generic.title': "Something didn't work",
      'ctx.voter.error.generic.body': 'There was a problem processing this action. You can try again in a moment.',

      'ctx.voter.income_estimate_explainer.title': 'How an income range is estimated',
      'ctx.voter.income_estimate_explainer.body': "When you don't declare an explicit income, Preferendum may use signals like occupation, age, company size, and your area's economic context to estimate a range. We don't show that exact number or the coefficients used, and it's never visible to other users.",

      'ctx.organizer.home.title': 'Organizer panel',
      'ctx.organizer.home.body': 'From here you manage your consultations: creation, tracking, and results.',

      'ctx.organizer.create.title': 'New consultation',
      'ctx.organizer.create.body': "Define the question, context, and options. This is the first thing participants will see. Your consultation goes through a review process before it becomes available for voting.",

      'ctx.organizer.create.targeting.title': 'Who this consultation reaches',
      'ctx.organizer.create.targeting.body': "These fields (country, commune, age, socioeconomic tier) configure eligibility criteria. Preferendum applies them automatically to decide who can see and vote on your consultation — you don't have to use all of them.",

      'ctx.organizer.missing_field.title': "Something's missing",
      'ctx.organizer.missing_field.body': "Check the highlighted field — it's required to publish this consultation.",

      'ctx.organizer.logout.title': 'See you soon!',
      'ctx.organizer.logout.body': "Thanks for using Preferendum. You'll be signed out in a moment.",

      'ctx.marketer.panel.overview.title': 'Account overview',
      'ctx.marketer.panel.overview.body': "Here's a summary of your campaigns and available balance.",

      'ctx.marketer.panel.credits.title': 'REAL and DEMO credits',
      'ctx.marketer.panel.credits.body': "Preferendum keeps real money (REAL) completely separate from test credits (DEMO) — two independent balances. DEMO credits let you test the system end to end and can never be used as, or converted into, real money.",

      'ctx.marketer.panel.campaigns.title': 'Your campaigns',
      'ctx.marketer.panel.campaigns.body': "Here you see the status and results of your active and past campaigns.",

      'ctx.marketer.panel.new_campaign.title': 'Create a campaign',
      'ctx.marketer.panel.new_campaign.body': "Define your campaign and its targeting criteria (e.g. commune, income, or demographics). Preferendum only delivers your ad to users who match the criteria you set — and only bills against balance already allocated to the campaign.",

      'ctx.marketer.missing_field.title': "Something's missing",
      'ctx.marketer.missing_field.body': "Check the highlighted field — it's required to create the campaign.",

      'ctx.marketer.logout.title': 'See you soon!',
      'ctx.marketer.logout.body': "Thanks for using Preferendum. You'll be signed out in a moment.",
    },
  };

  function str(lang, key) {
    var table = STRINGS[lang] || STRINGS.es;
    return table[key] || STRINGS.es[key] || key;
  }

  // ═══════════════════════════════════════════════════════════════════════
  // CONTEXT REGISTRY — screen/action -> visual state + copy + behavior.
  // This is the ONE place explanatory prose is wired to a screen. Business
  // logic files (main.py, eligibility.py, socioeconomic.py, ledger.py)
  // never reference any of this, and this file never reimplements any of
  // their decisions.
  //
  // Shape per entry:
  //   state        — one of STATES (never a SECURITY_STATES member; see
  //                  prefy.js's own guard, which is the actual enforcement)
  //   titleKey/bodyKey — STRINGS keys
  //   whyKey       — optional extra "why we ask" STRINGS key (form fields)
  //   firstVisitAutoOpen — if true, prefy.js auto-expands the FIRST time
  //                  this context is seen by this browser, then only shows
  //                  the minimized bubble on subsequent visits
  //   surface      — 'voter' | 'organizer' | 'marketer', for test/coverage
  //                  bookkeeping only (never used to branch content logic)
  // ═══════════════════════════════════════════════════════════════════════
  var CONTEXTS = {
    'voter.welcome':                  { state: 'WELCOME',      titleKey: 'ctx.voter.welcome.title',                  bodyKey: 'ctx.voter.welcome.body',                  firstVisitAutoOpen: true,  surface: 'voter' },
    'voter.auth.login':               { state: 'EXPLAINING',   titleKey: 'ctx.voter.auth.login.title',               bodyKey: 'ctx.voter.auth.login.body',               firstVisitAutoOpen: true,  surface: 'voter' },
    'voter.register.country':         { state: 'EXPLAINING',   titleKey: 'ctx.voter.register.country.title',         bodyKey: 'ctx.voter.register.country.body',         firstVisitAutoOpen: true,  surface: 'voter' },
    'voter.register.commune':         { state: 'EXPLAINING',   titleKey: 'ctx.voter.register.commune.title',         bodyKey: 'ctx.voter.register.commune.body',         firstVisitAutoOpen: true,  surface: 'voter' },
    'voter.register.dob':             { state: 'EXPLAINING',   titleKey: 'ctx.voter.register.dob.title',             bodyKey: 'ctx.voter.register.dob.body',             firstVisitAutoOpen: true,  surface: 'voter' },
    'voter.register.occupation':      { state: 'EXPLAINING',   titleKey: 'ctx.voter.register.occupation.title',      bodyKey: 'ctx.voter.register.occupation.body',      whyKey: 'ctx.voter.register.occupation.why', firstVisitAutoOpen: true, surface: 'voter' },
    'voter.register.company_size':    { state: 'EXPLAINING',   titleKey: 'ctx.voter.register.company_size.title',    bodyKey: 'ctx.voter.register.company_size.body',    firstVisitAutoOpen: true,  surface: 'voter' },
    'voter.register.email':           { state: 'EXPLAINING',   titleKey: 'ctx.voter.register.email.title',           bodyKey: 'ctx.voter.register.email.body',           firstVisitAutoOpen: true,  surface: 'voter' },
    'voter.register.phone':           { state: 'EXPLAINING',   titleKey: 'ctx.voter.register.phone.title',           bodyKey: 'ctx.voter.register.phone.body',           firstVisitAutoOpen: true,  surface: 'voter' },
    'voter.verify.selfie':            { state: 'EXPLAINING',   titleKey: 'ctx.voter.verify.selfie.title',            bodyKey: 'ctx.voter.verify.selfie.body',            firstVisitAutoOpen: true,  surface: 'voter' },
    'voter.verify.document':          { state: 'EXPLAINING',   titleKey: 'ctx.voter.verify.document.title',          bodyKey: 'ctx.voter.verify.document.body',          firstVisitAutoOpen: true,  surface: 'voter' },
    'voter.consultations':            { state: 'PRESENTING',   titleKey: 'ctx.voter.consultations.title',            bodyKey: 'ctx.voter.consultations.body',            firstVisitAutoOpen: true,  surface: 'voter' },
    'voter.consultation.detail':      { state: 'PRESENTING',   titleKey: 'ctx.voter.consultation.detail.title',      bodyKey: 'ctx.voter.consultation.detail.body',      firstVisitAutoOpen: true,  surface: 'voter' },
    'voter.opinion':                  { state: 'EXPLAINING',   titleKey: 'ctx.voter.opinion.title',                  bodyKey: 'ctx.voter.opinion.body',                  firstVisitAutoOpen: true,  surface: 'voter' },
    'voter.voting_section':           { state: 'EXPLAINING',   titleKey: 'ctx.voter.voting_section.title',           bodyKey: 'ctx.voter.voting_section.body',           firstVisitAutoOpen: true,  surface: 'voter' },
    'voter.vote.before_submit':       { state: 'ATTENTION',    titleKey: 'ctx.voter.vote.before_submit.title',       bodyKey: 'ctx.voter.vote.before_submit.body',       firstVisitAutoOpen: true,  surface: 'voter' },
    'voter.vote.success':             { state: 'SUCCESS',      titleKey: 'ctx.voter.vote.success.title',             bodyKey: 'ctx.voter.vote.success.body',             firstVisitAutoOpen: true,  surface: 'voter' },
    'voter.results':                  { state: 'PRESENTING',   titleKey: 'ctx.voter.results.title',                  bodyKey: 'ctx.voter.results.body',                  firstVisitAutoOpen: true,  surface: 'voter' },
    'voter.profile':                  { state: 'EXPLAINING',   titleKey: 'ctx.voter.profile.title',                  bodyKey: 'ctx.voter.profile.body',                  firstVisitAutoOpen: true,  surface: 'voter' },
    'voter.logout':                   { state: 'GOODBYE',      titleKey: 'ctx.voter.logout.title',                   bodyKey: 'ctx.voter.logout.body',                   firstVisitAutoOpen: true,  surface: 'voter' },
    'voter.missing_field':            { state: 'MISSING_INFORMATION', titleKey: 'ctx.voter.missing_field.title',     bodyKey: 'ctx.voter.missing_field.body',            firstVisitAutoOpen: true,  surface: 'voter' },
    'voter.error.generic':            { state: 'ERROR',        titleKey: 'ctx.voter.error.generic.title',            bodyKey: 'ctx.voter.error.generic.body',            firstVisitAutoOpen: true,  surface: 'voter' },
    'voter.income_estimate_explainer':{ state: 'EXPLAINING',   titleKey: 'ctx.voter.income_estimate_explainer.title',bodyKey: 'ctx.voter.income_estimate_explainer.body',firstVisitAutoOpen: true,  surface: 'voter' },

    'organizer.home':                 { state: 'PRESENTING',   titleKey: 'ctx.organizer.home.title',                 bodyKey: 'ctx.organizer.home.body',                 firstVisitAutoOpen: true,  surface: 'organizer' },
    'organizer.create':               { state: 'EXPLAINING',   titleKey: 'ctx.organizer.create.title',               bodyKey: 'ctx.organizer.create.body',               firstVisitAutoOpen: true,  surface: 'organizer' },
    'organizer.create.targeting':     { state: 'EXPLAINING',   titleKey: 'ctx.organizer.create.targeting.title',     bodyKey: 'ctx.organizer.create.targeting.body',     firstVisitAutoOpen: true,  surface: 'organizer' },
    'organizer.missing_field':        { state: 'MISSING_INFORMATION', titleKey: 'ctx.organizer.missing_field.title', bodyKey: 'ctx.organizer.missing_field.body',        firstVisitAutoOpen: true,  surface: 'organizer' },
    'organizer.logout':               { state: 'GOODBYE',      titleKey: 'ctx.organizer.logout.title',               bodyKey: 'ctx.organizer.logout.body',               firstVisitAutoOpen: true,  surface: 'organizer' },

    'marketer.panel.overview':        { state: 'PRESENTING',   titleKey: 'ctx.marketer.panel.overview.title',        bodyKey: 'ctx.marketer.panel.overview.body',        firstVisitAutoOpen: true,  surface: 'marketer' },
    'marketer.panel.credits':         { state: 'EXPLAINING',   titleKey: 'ctx.marketer.panel.credits.title',         bodyKey: 'ctx.marketer.panel.credits.body',         firstVisitAutoOpen: true,  surface: 'marketer' },
    'marketer.panel.campaigns':       { state: 'PRESENTING',   titleKey: 'ctx.marketer.panel.campaigns.title',       bodyKey: 'ctx.marketer.panel.campaigns.body',       firstVisitAutoOpen: true,  surface: 'marketer' },
    'marketer.panel.new_campaign':    { state: 'EXPLAINING',   titleKey: 'ctx.marketer.panel.new_campaign.title',    bodyKey: 'ctx.marketer.panel.new_campaign.body',    firstVisitAutoOpen: true,  surface: 'marketer' },
    'marketer.missing_field':         { state: 'MISSING_INFORMATION', titleKey: 'ctx.marketer.missing_field.title', bodyKey: 'ctx.marketer.missing_field.body',         firstVisitAutoOpen: true,  surface: 'marketer' },
    'marketer.logout':                { state: 'GOODBYE',      titleKey: 'ctx.marketer.logout.title',                bodyKey: 'ctx.marketer.logout.body',                firstVisitAutoOpen: true,  surface: 'marketer' },

    // Safe fallback for any setContext(key) call with an unregistered key —
    // never a security state, never a hard failure.
    '_unknown':                       { state: 'HELP',         titleKey: 'chrome.unknown.title',                     bodyKey: 'chrome.unknown.body',                     firstVisitAutoOpen: false, surface: null },
  };

  function getContext(key) {
    return CONTEXTS[key] || null;
  }

  function resolveContext(key) {
    return CONTEXTS[key] || CONTEXTS[UNKNOWN_CONTEXT_KEY];
  }

  function listContextKeys() {
    return Object.keys(CONTEXTS);
  }

  function isValidState(s) {
    return STATES.indexOf(s) !== -1;
  }

  function isSecurityState(s) {
    return SECURITY_STATES.indexOf(s) !== -1;
  }

  // Renders {title, body, why?} for a context key in a given language —
  // the one function portals/tests need, so nobody has to know the
  // titleKey/bodyKey indirection exists.
  function render(key, lang) {
    var ctx = resolveContext(key);
    var out = {
      key: CONTEXTS[key] ? key : UNKNOWN_CONTEXT_KEY,
      state: ctx.state,
      title: str(lang, ctx.titleKey),
      body: str(lang, ctx.bodyKey),
      firstVisitAutoOpen: !!ctx.firstVisitAutoOpen,
      surface: ctx.surface || null,
    };
    if (ctx.whyKey) out.why = str(lang, ctx.whyKey);
    return out;
  }

  return {
    STATES: STATES,
    SECURITY_STATES: SECURITY_STATES,
    DEFAULT_STATE: DEFAULT_STATE,
    UNKNOWN_CONTEXT_KEY: UNKNOWN_CONTEXT_KEY,
    ASSET_WIDTH: ASSET_WIDTH,
    ASSET_HEIGHT: ASSET_HEIGHT,
    ASSETS: ASSETS,
    STRINGS: STRINGS,
    CONTEXTS: CONTEXTS,
    str: str,
    getContext: getContext,
    resolveContext: resolveContext,
    listContextKeys: listContextKeys,
    isValidState: isValidState,
    isSecurityState: isSecurityState,
    render: render,
  };
});
