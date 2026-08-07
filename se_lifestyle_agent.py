"""
se_lifestyle_agent.py — Agente de Consultas por Estrato Socioeconómico
======================================================================
Misión: generar debates aspiracionales y de estilo de vida segmentados
por nivel socioeconómico (SE-A, SE-B, SE-C, SE-D).

El debate actúa como IMÁN y FILTRO simultáneo:
- Atrae al usuario que vive o aspira ese estilo de vida
- La respuesta revela preferencias reales de personas verificadas
- Las marcas patrocinadoras obtienen market research de alto valor

Cada debate se crea con target_se_tiers para que el motor de ads
solo lo muestre al estrato correcto — silenciosamente.

En memoria del Socio Fundador José Ignacio Fernández (1989–2024)
"""

import os, json, hashlib, re
from datetime import datetime, timedelta
import requests as _requests

BACKEND_URL  = os.getenv('BACKEND_URL', 'https://preferendum-unzip.onrender.com')
ADMIN_SECRET = os.getenv('ADMIN_SECRET')

# ── META AD LIBRARY ───────────────────────────────────────────────────────────
# API pública de Meta — todos los anuncios activos de cualquier marca son públicos
# por ley desde 2019 (post Cambridge Analytica).
# Token: crear en developers.facebook.com → App → Access Token (sin permisos especiales)
# Guardar como META_AD_LIBRARY_TOKEN en Render env vars.
META_AD_LIBRARY_TOKEN = os.getenv('META_AD_LIBRARY_TOKEN', '')
META_AD_LIBRARY_URL   = 'https://graph.facebook.com/v20.0/ads_archive'

# Marcas de lujo a monitorear por tier
LUXURY_BRANDS_BY_TIER = {
    'A': [
        'Porsche', 'Ferrari', 'Lamborghini', 'Bentley', 'Rolls-Royce', 'Aston Martin',
        'Rolex', 'Patek Philippe', 'Audemars Piguet', 'Richard Mille',
        'Louis Vuitton', 'Hermès', 'Chanel', 'Gucci', 'Loro Piana',
        'NetJets', 'VistaJet',
        'Sotheby\'s', 'Christie\'s',
        'Four Seasons', 'Aman Resorts', 'Rosewood Hotels',
    ],
    'B': [
        'Audi', 'BMW', 'Mercedes-Benz', 'Volvo', 'Lexus', 'Jaguar',
        'Apple', 'Samsung', 'Sony', 'Bang & Olufsen',
        'Marriott Bonvoy', 'Hilton Honors', 'Emirates', 'Singapore Airlines',
        'American Express Platinum', 'HSBC Premier',
    ],
    'C': [
        'Hyundai', 'Kia', 'Chevrolet', 'Toyota',
        'Samsung Galaxy', 'Xiaomi',
        'LATAM Airlines', 'Booking.com', 'Airbnb',
        'Falabella', 'Ripley',
    ],
}


def fetch_meta_ad_library(brand: str, countries: list = None) -> list:
    """
    Consulta la Meta Ad Library API para ver los anuncios activos de una marca.
    Retorna lista de dicts con el texto de los anuncios activos.
    Requiere META_AD_LIBRARY_TOKEN en env vars.
    """
    if not META_AD_LIBRARY_TOKEN:
        return []
    try:
        params = {
            'access_token':       META_AD_LIBRARY_TOKEN,
            'ad_type':            'ALL',
            'search_terms':       brand,
            'ad_reached_countries': json.dumps(countries or ['US', 'GB', 'DE', 'FR', 'CL', 'AR', 'MX']),
            'ad_active_status':   'ACTIVE',
            'fields':             'page_name,ad_creative_bodies,ad_creative_link_titles,impressions,spend,currency',
            'limit':              10,
        }
        r = _requests.get(META_AD_LIBRARY_URL, params=params, timeout=15)
        if not r.ok:
            print(f'[AdLibrary] {brand}: {r.status_code} {r.text[:80]}')
            return []
        ads = r.json().get('data', [])
        results = []
        for ad in ads:
            bodies = ad.get('ad_creative_bodies') or []
            titles = ad.get('ad_creative_link_titles') or []
            text   = ' | '.join(filter(None, bodies[:2] + titles[:1]))
            if text:
                results.append({
                    'brand':     brand,
                    'page':      ad.get('page_name', brand),
                    'text':      text[:300],
                    'spend':     ad.get('spend', {}),
                    'currency':  ad.get('currency', 'USD'),
                })
        print(f'[AdLibrary] {brand}: {len(results)} active ads found')
        return results
    except Exception as e:
        print(f'[AdLibrary] Error fetching {brand}: {e}')
        return []


def get_active_luxury_campaigns(se_tier: str, max_brands: int = 5) -> list:
    """
    Obtiene anuncios activos de marcas de lujo para el tier dado.
    Retorna lista de campañas activas con su copy para informar al agente.
    """
    brands = LUXURY_BRANDS_BY_TIER.get(se_tier, [])[:max_brands]
    campaigns = []
    for brand in brands:
        ads = fetch_meta_ad_library(brand)
        if ads:
            campaigns.extend(ads[:2])  # máx 2 ads por marca
    return campaigns

def _get_api_key() -> str:
    key = os.getenv('ANTHROPIC_API_KEY', '').strip()
    if not key:
        for path in ['/etc/secrets/ANTHROPIC_API_KEY', './ANTHROPIC_API_KEY']:
            try:
                with open(path) as f:
                    key = f.read().strip()
                if key:
                    break
            except Exception:
                pass
    return key

_created_this_run: set = set()

# ══════════════════════════════════════════════════════════════
# BANCO DE TEMAS POR ESTRATO — evergreen, no requieren noticias
# ══════════════════════════════════════════════════════════════

SE_TOPICS = {

    # ── TIER A — Ultra alto ingreso ──────────────────────────────────────────
    # Porsche, Rolex, Louis Vuitton, viajes privados, yates, arte
    'A': [
        # Automóviles de lujo
        {
            'topic': 'luxury_cars',
            'prompt': (
                'Si pudieras elegir cualquier auto de alta gama, ¿cuál sería tu elección y por qué? '
                'Opciones: Porsche 911, Mercedes-Benz S-Class, BMW Serie 7, Bentley Continental, Ferrari Roma. '
                'Genera una consulta aspiracional sobre autos de lujo, en tono de preferencia personal.'
            ),
        },
        {
            'topic': 'luxury_cars_suv',
            'prompt': (
                'Entre los SUV de lujo más exclusivos del mercado, ¿cuál elegiría alguien que valora '
                'tanto el rendimiento como el confort? '
                'Opciones: Porsche Cayenne, Range Rover SVAutobiography, Bentley Bentayga, Lamborghini Urus, Mercedes GLS.'
            ),
        },
        # Relojes finos
        {
            'topic': 'fine_watches',
            'prompt': (
                'Entre los relojes más icónicos del mundo, ¿cuál representa mejor el éxito y el gusto personal? '
                'Opciones: Rolex Daytona, Patek Philippe Nautilus, Audemars Piguet Royal Oak, Richard Mille RM 11, IWC Portugieser.'
            ),
        },
        # Viajes privados — Croacia
        {
            'topic': 'croatia_sailing',
            'prompt': (
                'La costa de Croacia — Hvar, Split, Supetar, Dubrovnik — es uno de los destinos más exclusivos de Europa. '
                '¿Cuál sería tu forma ideal de explorarla? '
                'Opciones: catamarán privado con tripulación, velero clásico con skipper, yate a motor de lujo, villa privada en Hvar con excursiones en lancha.'
            ),
        },
        # Viajes privados — Mediterráneo
        {
            'topic': 'mediterranean_luxury',
            'prompt': (
                'El Mediterráneo ofrece destinos únicos para quienes buscan exclusividad. '
                '¿Cuál elegiría para sus próximas vacaciones de lujo? '
                'Opciones: Santorini y Mykonos en yate privado, Costa Amalfitana con villa y barco, Ibiza exclusiva con acceso VIP, Portofino y la Riviera Italiana.'
            ),
        },
        # Viajes — Aviación privada
        {
            'topic': 'private_aviation',
            'prompt': (
                'Cuando el tiempo es el activo más valioso, viajar en jet privado es la elección natural. '
                '¿Cuál sería su modelo preferido para viajes de negocios y placer? '
                'Opciones: Gulfstream G700, Bombardier Global 7500, Dassault Falcon 10X, fractional ownership con NetJets, charter on-demand.'
            ),
        },
        # Moda de lujo
        {
            'topic': 'luxury_fashion',
            'prompt': (
                'En el mundo de la moda de lujo, cada marca tiene una identidad única. '
                '¿Cuál representa mejor su estilo personal? '
                'Opciones: Hermès (artesanía y tradición), Louis Vuitton (icónico y cosmopolita), Chanel (elegancia atemporal), Loro Piana (discreción y calidad suprema).'
            ),
        },
        # Real estate de lujo
        {
            'topic': 'luxury_real_estate',
            'prompt': (
                'Si pudiera tener una segunda residencia en cualquier lugar del mundo, ¿dónde la elegiría? '
                'Opciones: penthouse en Manhattan con vista al Central Park, villa en la Toscana con viñedo propio, '
                'chalet en los Alpes suizos, mansión frente al mar en la Costa Azul francesa, finca en Mallorca.'
            ),
        },
        # Gastronomía fine dining
        {
            'topic': 'fine_dining',
            'prompt': (
                'La alta gastronomía es una experiencia que va más allá de comer. '
                '¿Qué tipo de experiencia culinaria de lujo prefiere? '
                'Opciones: cena en restaurante con 3 estrellas Michelin, mesa del chef con maridaje privado, '
                'cena privada preparada por chef reconocido en su casa, experiencia de cocina molecular de vanguardia.'
            ),
        },
        # Arte y coleccionismo
        {
            'topic': 'art_collecting',
            'prompt': (
                'Coleccionar arte es una de las formas más sofisticadas de inversión y expresión personal. '
                '¿Qué tipo de arte le atrae como coleccionista? '
                'Opciones: arte contemporáneo emergente, obras de maestros del siglo XX, arte latinoamericano moderno, fotografía de autor en ediciones limitadas, esculturas para espacios privados.'
            ),
        },
        # Golf y deportes exclusivos
        {
            'topic': 'exclusive_sports',
            'prompt': (
                'Los deportes de élite combinan pasión, disciplina y un estilo de vida único. '
                '¿Cuál es su actividad deportiva de lujo preferida? '
                'Opciones: golf en campos privados icónicos, polo internacional, vela oceánica de competencia, esquí en Aspen o Courchevel, tenis en clubes exclusivos.'
            ),
        },
        # Vinos y espirituosos
        {
            'topic': 'fine_wine',
            'prompt': (
                'Los grandes vinos y destilados son una pasión que combina cultura, historia y placer sensorial. '
                '¿Cuál es su preferencia en una colección de alta gama? '
                'Opciones: Burdeos Grands Crus Classés (Pétrus, Lafite), Borgoña Premier Cru (Romanée-Conti), '
                'whisky single malt de añadas raras, champagne de prestige (Dom Pérignon, Krug), vinos latinoamericanos de autor.'
            ),
        },
        # Educación elite
        {
            'topic': 'elite_education',
            'prompt': (
                'La educación de los hijos es la inversión más importante. '
                '¿Qué modelo educativo elegiría para sus hijos si los recursos no fueran una limitación? '
                'Opciones: internado en Suiza o Reino Unido, colegio privado bilingüe de élite local, '
                'educación internacional con IB en diferentes países, universidad Ivy League desde el pregrado.'
            ),
        },
    ],

    # ── TIER B — Medio-alto ──────────────────────────────────────────────────
    # Audi, BMW 3-series, viajes business class, tecnología premium
    'B': [
        {
            'topic': 'premium_cars',
            'prompt': (
                'Al renovar el auto, la relación entre calidad, tecnología y precio es clave. '
                '¿Cuál sería su elección en el segmento premium? '
                'Opciones: Audi A6, BMW Serie 5, Mercedes-Benz Clase C, Volvo S90, Lexus ES.'
            ),
        },
        {
            'topic': 'business_travel',
            'prompt': (
                'Viajar en business class cambia completamente la experiencia. '
                '¿Cuál aerolínea ofrece la mejor experiencia business class para vuelos internacionales? '
                'Opciones: Emirates, Singapore Airlines, Qatar Airways, Lufthansa, LATAM Premium Business.'
            ),
        },
        {
            'topic': 'premium_tech',
            'prompt': (
                'La tecnología premium mejora la productividad y el estilo de vida. '
                '¿Cuál es la inversión tecnológica que más impacto tiene en su vida diaria? '
                'Opciones: smartphone de gama alta (iPhone 16 Pro, Samsung S25 Ultra), laptop profesional (MacBook Pro, Dell XPS), '
                'audífonos premium (Sony XM5, Bose QC), smartwatch con GPS y salud avanzada, smart home integrado.'
            ),
        },
        {
            'topic': 'wellness',
            'prompt': (
                'El bienestar personal es una prioridad para quienes pueden invertir en él. '
                '¿Cuál sería su inversión principal en salud y bienestar? '
                'Opciones: membresía en gym premium con entrenador personal, retiro de bienestar anual en spa exclusivo, '
                'nutricionista y plan alimenticio personalizado, meditación y mindfulness con coach certificado, '
                'chequeo médico preventivo completo anual.'
            ),
        },
        {
            'topic': 'premium_travel',
            'prompt': (
                'Las vacaciones perfectas combinan descanso, cultura y experiencias únicas. '
                '¿Cuál destino elegiría para sus próximas vacaciones de nivel premium? '
                'Opciones: Nueva York y Hamptons en verano, Japón con guía privado, '
                'safari en Kenia con lodge exclusivo, Patagonia con expedición privada, Ámsterdam y Bélgica en profundidad.'
            ),
        },
        {
            'topic': 'home_renovation',
            'prompt': (
                'Transformar el hogar es una de las inversiones con mayor retorno en calidad de vida. '
                '¿En qué área de su hogar invertiría primero si tuviera un presupuesto generoso? '
                'Opciones: cocina integral de diseño europeo, baño principal tipo spa, jardín con paisajismo profesional, '
                'terraza o rooftop habilitado, sistema de domótica y smart home completo.'
            ),
        },
        {
            'topic': 'mba_education',
            'prompt': (
                'Invertir en educación ejecutiva puede transformar una carrera. '
                '¿Qué formato de formación ejecutiva elegiría? '
                'Opciones: MBA full-time en escuela top (Wharton, INSEAD, IE), '
                'Executive MBA mientras trabaja, certificaciones especializadas (CFA, PMP, AWS), '
                'cursos online de élite (Harvard Business School Online), coaching ejecutivo con mentor.'
            ),
        },
        {
            'topic': 'wine_culture',
            'prompt': (
                'El vino es cultura, gastronomía y placer. '
                '¿Cómo prefiere disfrutar y aprender sobre vinos? '
                'Opciones: visita a viñas premium con cata privada, sommelier personal para su cava en casa, '
                'club de vinos curado mensualmente, curso de sommelier certificado, '
                'viaje enológico a la Rioja, Mendoza o Valle del Maipo.'
            ),
        },
    ],

    # ── TIER C — Medio ──────────────────────────────────────────────────────
    # Primeras experiencias premium, movilidad, consumo aspiracional
    'C': [
        {
            'topic': 'first_car',
            'prompt': (
                'Comprar el primer auto propio o renovar el actual es una decisión importante. '
                '¿Qué priorizaría en su próxima compra de vehículo? '
                'Opciones: economía en combustible (eléctrico o híbrido), precio y cuotas accesibles, '
                'marca reconocida con garantía, espacio para la familia, tecnología y conectividad.'
            ),
        },
        {
            'topic': 'vacation_local',
            'prompt': (
                'Organizar vacaciones con presupuesto medido requiere inteligencia y creatividad. '
                '¿Cuál es su estrategia preferida para unas vacaciones memorables? '
                'Opciones: reservar con mucha anticipación para aprovechar precios, viajar en temporada baja, '
                'destinos locales o regionales poco explorados, paquetes turísticos todo incluido, '
                'Airbnb y turismo independiente.'
            ),
        },
        {
            'topic': 'online_courses',
            'prompt': (
                'Aprender nuevas habilidades online puede abrir puertas profesionales. '
                '¿En qué área invertiría en capacitación digital? '
                'Opciones: programación y tecnología (Python, IA, apps), marketing digital y redes sociales, '
                'idiomas (inglés, mandarín, portugués), finanzas personales e inversiones, diseño gráfico o UX/UI.'
            ),
        },
        {
            'topic': 'streaming',
            'prompt': (
                'El entretenimiento en casa ha cambiado radicalmente. '
                '¿Cuántos servicios de streaming considera que justifican el gasto mensual? '
                'Opciones: solo uno (el que más uso), dos o tres bien elegidos, '
                'cuatro o más si hay contenido variado, prefiero compartir cuentas con familia, '
                'prefiero no pagar y usar solo lo gratuito.'
            ),
        },
    ],

    # ── TIER D — Popular ────────────────────────────────────────────────────
    # Temas cotidianos, servicios públicos, consumo básico
    'D': [
        {
            'topic': 'public_transport',
            'prompt': (
                'El transporte público afecta la calidad de vida diaria de millones de personas. '
                '¿Cuál es el problema más urgente del transporte público en su ciudad? '
                'Opciones: frecuencia y puntualidad, seguridad en el transporte, '
                'precio del pasaje, cobertura de rutas, comodidad y mantenimiento.'
            ),
        },
        {
            'topic': 'basic_consumption',
            'prompt': (
                'La canasta básica de alimentos se ha encarecido en los últimos años. '
                '¿Cuál es el cambio de hábito que más ha adoptado para ajustarse al presupuesto familiar? '
                'Opciones: comprar en supermercados de descuento o ferias libres, '
                'reducir productos de marca y comprar genéricos, cocinar más en casa, '
                'comprar al por mayor con vecinos o familia, eliminar gastos no esenciales.'
            ),
        },
        {
            'topic': 'digital_access',
            'prompt': (
                'El acceso a internet se ha vuelto indispensable para el trabajo y la educación. '
                '¿Cómo califica el acceso a internet en su hogar? '
                'Opciones: bueno y suficiente para todo lo que necesito, '
                'aceptable pero con cortes frecuentes, solo con datos móviles del celular, '
                'deficiente para trabajar o estudiar desde casa, no tengo acceso en casa.'
            ),
        },
    ],
}


# ══════════════════════════════════════════════════════════════
# GENERACIÓN DE DEBATES
# ══════════════════════════════════════════════════════════════

def _generate_se_debate(topic_entry: dict, se_tier: str) -> dict | None:
    """Llama a Claude para generar un debate aspiracional para el tier dado."""
    api_key = _get_api_key()
    if not api_key:
        return None

    tier_context = {
        'A': 'personas de muy alto nivel socioeconómico (ejecutivos senior, empresarios, profesionales de élite)',
        'B': 'personas de nivel socioeconómico medio-alto (profesionales, gerentes, emprendedores exitosos)',
        'C': 'personas de nivel socioeconómico medio (trabajadores calificados, profesionales jóvenes)',
        'D': 'personas de nivel socioeconómico popular (trabajadores, estudiantes, familias de ingresos bajos)',
    }

    prompt = f"""Eres el agente de lifestyle de Preferendum. Tu misión es crear consultas de preferencias personales
para {tier_context[se_tier]}.

Tema a trabajar: {topic_entry['prompt']}

Reglas:
- La pregunta debe ser directa, sin juicios de valor, en tono aspiracional y respetuoso
- Máximo 120 caracteres en la pregunta
- El contexto explica el tema en 2-3 frases, sin mencionar el estrato socioeconómico
- Entre 3 y 4 opciones, mutuamente excluyentes, que representen gustos y estilos de vida reales
- Las opciones deben ser concretas y reconocibles para el público objetivo
- Responde en español

Responde ÚNICAMENTE con este JSON exacto (sin texto adicional):
{{
  "question": "¿[pregunta clara, máx 120 caracteres]?",
  "context": "[2-3 frases de contexto que sitúan el tema]",
  "options": ["Opción A", "Opción B", "Opción C", "Opción D"]
}}"""

    try:
        resp = _requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key':         api_key,
                'anthropic-version': '2023-06-01',
                'content-type':      'application/json',
            },
            json={
                'model':      'claude-haiku-4-5-20251001',
                'max_tokens': 500,
                'messages':   [{'role': 'user', 'content': prompt}],
            },
            timeout=25,
        )
        if not resp.ok:
            print(f'[SEAgent] API error {resp.status_code}')
            return None
        content = resp.json().get('content', [])
        text = next((c['text'] for c in content if c.get('type') == 'text'), '')
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if not match:
            return None
        return json.loads(match.group())
    except Exception as e:
        print(f'[SEAgent] Generation error: {e}')
        return None


def _create_se_debate_via_api(debate_data: dict, se_tier: str) -> bool:
    """Crea el debate en el backend con target_se_tiers configurado."""
    question = debate_data.get('question', '')
    q_hash = hashlib.sha256(question.encode()).hexdigest()[:16]
    if q_hash in _created_this_run:
        return False

    # Dedup: verificar contra debates existentes
    try:
        r = _requests.get(f'{BACKEND_URL}/debates?limit=100', timeout=10)
        if r.ok:
            existing = r.json().get('debates', [])
            stop_words = {'el','la','los','las','un','una','de','del','en','que','qué',
                          'y','o','a','al','se','su','por','para','con','es','son','cuál','cuáles'}
            def kw(t): return {w for w in re.findall(r'\b\w{4,}\b', t.lower()) if w not in stop_words}
            q_kw = kw(question)
            for d in existing:
                if d.get('status') == 'live' and len(q_kw & kw(d.get('title', ''))) >= 3:
                    print(f'[SEAgent] Duplicate skipped — similar to #{d["id"]}: {d["title"][:50]}')
                    return False
    except Exception:
        pass

    closes_at = (datetime.utcnow() + timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%S')
    payload = {
        'title':            question,
        'context':          debate_data.get('context', ''),
        'options':          debate_data.get('options', []),
        'creator_type':     'agent',
        'inst_name':        'Preferendum Lifestyle',
        'debate_type':      'citizen',
        'scope':            'global',
        'scope_country':    'GL',
        'closes_at':        closes_at,
        'verify_days':      30,
        'target_se_tiers':  se_tier,   # ← solo llega al estrato correcto
    }
    try:
        r = _requests.post(
            f'{BACKEND_URL}/debates',
            json=payload,
            headers={'X-Agent-Secret': ADMIN_SECRET},
            timeout=15,
        )
        if r.ok:
            debate_id = r.json().get('debate', {}).get('id', '?')
            print(f'[SEAgent] Created SE-{se_tier} debate #{debate_id}: {question[:60]}')
            _created_this_run.add(q_hash)
            return True
        else:
            print(f'[SEAgent] Failed: {r.status_code} {r.text[:80]}')
            return False
    except Exception as e:
        print(f'[SEAgent] Create error: {e}')
        return False


# ══════════════════════════════════════════════════════════════
# FUNCIÓN PRINCIPAL
# ══════════════════════════════════════════════════════════════

def _generate_se_debate_from_campaign(campaign: dict, se_tier: str) -> dict | None:
    """
    Genera un debate inspirado en un anuncio activo real de una marca de lujo.
    El debate es oportuno — refleja lo que la marca está comunicando HOY.
    """
    api_key = _get_api_key()
    if not api_key:
        return None

    prompt = f"""Eres el agente de lifestyle de Preferendum. Una marca de lujo tiene una campaña activa ahora mismo
y quieres crear un debate que sea relevante para personas que conocen esa marca.

Marca: {campaign['brand']}
Texto del anuncio activo: {campaign['text']}

Crea una consulta de preferencias personales sobre esta marca o su categoría de producto,
dirigida a personas de alto poder adquisitivo. NO menciones que es un anuncio ni que viene de una campaña.
La pregunta debe sentirse natural, como si surgiera del interés genuino de la comunidad.

Reglas:
- Pregunta directa, aspiracional, máx 120 caracteres
- Contexto: 2-3 frases que sitúan el tema en el mundo del lujo
- 3 a 4 opciones concretas y reconocibles
- En español

Responde ÚNICAMENTE con JSON:
{{
  "question": "¿[pregunta]?",
  "context": "[contexto]",
  "options": ["Opción A", "Opción B", "Opción C"]
}}"""

    try:
        resp = _requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={'x-api-key': api_key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'},
            json={'model': 'claude-haiku-4-5-20251001', 'max_tokens': 500,
                  'messages': [{'role': 'user', 'content': prompt}]},
            timeout=25,
        )
        if not resp.ok:
            return None
        text = next((c['text'] for c in resp.json().get('content', []) if c.get('type') == 'text'), '')
        match = re.search(r'\{.*\}', text, re.DOTALL)
        return json.loads(match.group()) if match else None
    except Exception as e:
        print(f'[SEAgent] Campaign debate error: {e}')
        return None


def run_se_lifestyle_debates(max_per_tier: int = 3) -> dict:
    """
    Genera debates aspiracionales para cada tier socioeconómico.
    Fuente 1: campañas activas en Meta Ad Library (si META_AD_LIBRARY_TOKEN está configurado)
    Fuente 2: banco de temas evergreen (siempre disponible)
    Corre semanalmente — los temas son evergreen, no requieren noticias.
    """
    global _created_this_run
    _created_this_run = set()

    total_created = 0
    total_skipped = 0
    summary = []

    for tier, topics in SE_TOPICS.items():
        created_for_tier = 0
        print(f'[SEAgent] === TIER {tier} ===')

        # Fuente 1: campañas activas en Meta Ad Library
        if META_AD_LIBRARY_TOKEN and tier in ('A', 'B'):
            print(f'[SEAgent] Checking Meta Ad Library for tier {tier} brands...')
            campaigns = get_active_luxury_campaigns(tier, max_brands=4)
            for campaign in campaigns:
                if created_for_tier >= max_per_tier:
                    break
                print(f'[SEAgent] Campaign debate: {campaign["brand"]} — "{campaign["text"][:50]}..."')
                debate = _generate_se_debate_from_campaign(campaign, tier)
                if debate and _create_se_debate_via_api(debate, tier):
                    created_for_tier += 1
                    total_created += 1
                    summary.append({
                        'tier': tier, 'source': 'meta_ad_library',
                        'brand': campaign['brand'],
                        'question': debate['question'][:80],
                    })
                else:
                    total_skipped += 1

        # Fuente 2: banco de temas evergreen (completa hasta max_per_tier)
        for topic_entry in topics:
            if created_for_tier >= max_per_tier:
                break
            print(f'[SEAgent] Evergreen SE-{tier} / {topic_entry["topic"]}...')
            debate = _generate_se_debate(topic_entry, tier)
            if not debate or not debate.get('question'):
                total_skipped += 1
                continue
            if _create_se_debate_via_api(debate, tier):
                created_for_tier += 1
                total_created += 1
                summary.append({
                    'tier': tier, 'source': 'evergreen',
                    'topic': topic_entry['topic'],
                    'question': debate['question'][:80],
                })
            else:
                total_skipped += 1

        print(f'[SEAgent] Tier {tier}: created {created_for_tier}')

    print(f'[SEAgent] Done — created {total_created}, skipped {total_skipped}')
    return {
        'debates_created': total_created,
        'debates_skipped': total_skipped,
        'summary':         summary,
        'run_at':          datetime.utcnow().isoformat(),
    }
