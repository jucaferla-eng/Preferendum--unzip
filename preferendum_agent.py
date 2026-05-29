"""
preferendum_agent.py — Agente Central de Preferendum
=====================================================
Gerente de operaciones impulsado por Claude.

Tres responsabilidades:
1. MODERACIÓN — revisa registros de votantes, organizadores, marketers y ads
2. OPERACIONES — dispara Apify, monitorea el sistema, actualiza datos de comunas
3. SOPORTE — responde preguntas, explica el sistema, ayuda con problemas

Usa Claude con tool use para acceder a la BD y APIs internas.

En memoria de José Ignacio Fernández (1989–2024)
"""

import os, json
import requests as _requests
from datetime import datetime

ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
BACKEND_URL       = os.getenv('BACKEND_URL', 'https://preferendum-unzip.onrender.com')
ADMIN_SECRET      = os.getenv('ADMIN_SECRET', 'preferendum-admin-2024')

# ══════════════════════════════════════════════════════════════
# SYSTEM PROMPT — identidad y conocimiento del agente
# ══════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """Eres el Agente de Preferendum — el gerente de operaciones de la plataforma.

QUIÉN ERES:
Preferendum es una plataforma de decisiones verificadas. Organizaciones (empresas, asociaciones,
municipios, universidades) hacen consultas a sus miembros. Los resultados se anclan en blockchain
y tienen un Legitimacy Score público. No es una encuesta — es una decisión verificada.

ARQUITECTURA DE PRIVACIDAD (MUY IMPORTANTE — explica esto siempre):
- El voto es completamente anónimo. En la urna NO aparece el nombre del votante.
- Bridge destruction: el voter_id se elimina inmediatamente después de votar.
  La identidad NUNCA queda vinculada al voto en la base de datos.
- AES-256: cada voto va cifrado.
- Código XXXX-XXXX-XXXX: el votante puede verificar que su voto fue contado correctamente,
  pero nadie — ni Preferendum — puede saber cómo votó.
- Blockchain Polygon: resultado inmutable, auditable públicamente.
- Legitimacy Score: % de votantes que verificaron su voto.

VERIFICACIÓN DE IDENTIDAD (5 capas):
1. Email OTP
2. SMS al chip del teléfono
3. Foto del carné/DNI
4. Selfie con carné bajo el mentón (cámara frontal obligatoria) → Amazon Rekognition
5. IMEI del aparato

TRES TIPOS DE USUARIOS:
- VOTANTES: personas naturales que votan en consultas
- ORGANIZADORES: empresas o personas que crean consultas (requieren aprobación)
- MARKETERS: empresas que ponen publicidad entre las opiniones

MODELO DE PUBLICIDAD:
- Ads aparecen cada 5 opiniones en el debate
- Targeting por nivel de ingreso de la comuna (AAA/AAB/ABB/BBB/BBC/BCC)
  basado en precio de arriendo m² (60%) + avalúo fiscal SII (40%) para Chile
- Sin datos personales — solo geografía + proxy de ingreso
- El marketer ve: personas alcanzadas, costo por contacto, distribución por tier

TUS RESPONSABILIDADES:
1. Moderar contenido (consultas, ads, registros)
2. Aprobar o rechazar organizadores
3. Monitorear el sistema
4. Responder preguntas de usuarios

REGLAS DE MODERACIÓN:
- RECHAZAR: contenido obsceno, ataques a personas, propaganda disfrazada, preguntas estúpidas o sin sentido
- REVISAR: contenido político sensible, preguntas tendenciosas
- APROBAR: consultas legítimas de decisión colectiva con opciones equilibradas

Responde siempre en el idioma en que te hablan. Sé directo, claro y breve.
"""

# ══════════════════════════════════════════════════════════════
# TOOLS — el agente puede llamar estos para acceder al sistema
# ══════════════════════════════════════════════════════════════

TOOLS = [
    {
        "name": "moderate_content",
        "description": "Analiza contenido y devuelve score 0-100 + decisión (approved/review/rejected)",
        "input_schema": {
            "type": "object",
            "properties": {
                "content_type": {"type": "string", "enum": ["consultation", "ad", "organizer_profile", "voter_doc"]},
                "title":        {"type": "string"},
                "body":         {"type": "string"},
                "options":      {"type": "array", "items": {"type": "string"}},
            },
            "required": ["content_type", "body"]
        }
    },
    {
        "name": "get_system_status",
        "description": "Obtiene el estado actual del sistema: debates activos, usuarios, campañas",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "approve_organizer",
        "description": "Aprueba o rechaza un organizador pendiente",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id":  {"type": "integer"},
                "action":   {"type": "string", "enum": ["approved", "rejected", "suspended"]},
                "reason":   {"type": "string"},
            },
            "required": ["user_id", "action"]
        }
    },
    {
        "name": "trigger_apify_daily",
        "description": "Dispara el agente Apify para actualizar datos de comunas del día",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "get_pending_reviews",
        "description": "Lista organizadores pendientes de aprobación y consultas en revisión",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "get_commune_data",
        "description": "Obtiene la tabla de comunas con índice de ingreso y CPM",
        "input_schema": {
            "type": "object",
            "properties": {
                "country": {"type": "string"},
            }
        }
    }
]


# ══════════════════════════════════════════════════════════════
# TOOL EXECUTION
# ══════════════════════════════════════════════════════════════

def execute_tool(tool_name: str, tool_input: dict) -> str:
    """Ejecuta un tool y devuelve el resultado como string."""

    if tool_name == "moderate_content":
        content_type = tool_input.get("content_type", "")
        body         = tool_input.get("body", "")
        title        = tool_input.get("title", "")
        options      = tool_input.get("options", [])

        if content_type == "consultation":
            bad_words = ["obscen", "porno", "imbécil", "idiota", "matar", "destruir"]
            political_words = ["vota por", "apoya a", "candidato", "partido político"]
            score = 100
            reason = "Consulta válida"
            if any(w in body.lower() for w in bad_words):
                score = 10; reason = "Contenido inapropiado detectado"
            elif any(w in body.lower() for w in political_words):
                score = 55; reason = "Posible propaganda política — requiere revisión"
            elif len(body) < 20:
                score = 30; reason = "Consulta demasiado vaga o sin contexto"
            elif len(options) < 2:
                score = 40; reason = "Se requieren al menos 2 opciones"
            decision = "approved" if score >= 80 else "review" if score >= 50 else "rejected"
            return json.dumps({"score": score, "decision": decision, "reason": reason})

        elif content_type == "ad":
            bad_ad = ["adulto", "18+", "apuesta", "casino", "porno"]
            score  = 90
            reason = "Ad válido"
            if any(w in body.lower() for w in bad_ad):
                score = 20; reason = "Categoría de publicidad no permitida"
            decision = "approved" if score >= 80 else "review" if score >= 50 else "rejected"
            return json.dumps({"score": score, "decision": decision, "reason": reason})

        return json.dumps({"score": 70, "decision": "review", "reason": "Revisión manual recomendada"})

    elif tool_name == "get_system_status":
        try:
            resp = _requests.get(f'{BACKEND_URL}/admin/db-info', timeout=10)
            return json.dumps(resp.json() if resp.ok else {"error": "Backend no responde"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    elif tool_name == "approve_organizer":
        user_id = tool_input.get("user_id")
        action  = tool_input.get("action")
        reason  = tool_input.get("reason", "")
        try:
            resp = _requests.post(
                f'{BACKEND_URL}/admin/organizer/{user_id}/status',
                params={"secret": ADMIN_SECRET},
                json={"status": action, "reason": reason},
                timeout=10
            )
            return json.dumps({"ok": resp.ok, "status": action, "user_id": user_id})
        except Exception as e:
            return json.dumps({"error": str(e)})

    elif tool_name == "trigger_apify_daily":
        try:
            resp = _requests.post(
                f'{BACKEND_URL}/admin/run-market-agent/daily',
                params={"secret": ADMIN_SECRET},
                timeout=30
            )
            return json.dumps(resp.json() if resp.ok else {"error": f"Status {resp.status_code}"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    elif tool_name == "get_pending_reviews":
        try:
            resp = _requests.get(
                f'{BACKEND_URL}/admin/pending-reviews',
                params={"secret": ADMIN_SECRET},
                timeout=10
            )
            return json.dumps(resp.json() if resp.ok else {"organizers": [], "consultations": []})
        except Exception as e:
            return json.dumps({"organizers": [], "consultations": [], "error": str(e)})

    elif tool_name == "get_commune_data":
        country = tool_input.get("country", "CL")
        try:
            resp = _requests.get(f'{BACKEND_URL}/communes', params={"country": country}, timeout=10)
            data = resp.json() if resp.ok else {}
            communes = data.get("communes", [])[:10]
            return json.dumps({"top_10": communes, "total": len(data.get("communes", []))})
        except Exception as e:
            return json.dumps({"error": str(e)})

    return json.dumps({"error": f"Tool {tool_name} desconocido"})


# ══════════════════════════════════════════════════════════════
# AGENTE PRINCIPAL
# ══════════════════════════════════════════════════════════════

def run_agent(user_message: str, conversation_history: list = None) -> dict:
    """
    Corre el agente con una consulta del usuario.
    Retorna {"response": str, "tool_calls": list, "history": list}
    """
    if not ANTHROPIC_API_KEY:
        return {
            "response": "El agente no está configurado. Agrega ANTHROPIC_API_KEY en Render.",
            "tool_calls": [],
            "history": []
        }

    messages = conversation_history or []
    messages.append({"role": "user", "content": user_message})

    tool_calls_log = []

    # Agentic loop — el agente puede usar múltiples tools antes de responder
    for _ in range(5):  # máximo 5 iteraciones de tools
        resp = _requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":      "claude-haiku-4-5-20251001",
                "max_tokens": 1024,
                "system":     SYSTEM_PROMPT,
                "tools":      TOOLS,
                "messages":   messages,
            },
            timeout=30,
        )

        if not resp.ok:
            return {"response": f"Error del agente: {resp.status_code}", "tool_calls": tool_calls_log, "history": messages}

        data        = resp.json()
        stop_reason = data.get("stop_reason")
        content     = data.get("content", [])

        # Agregar respuesta del asistente al historial
        messages.append({"role": "assistant", "content": content})

        if stop_reason == "end_turn":
            # Respuesta final
            text = next((c["text"] for c in content if c.get("type") == "text"), "")
            return {"response": text, "tool_calls": tool_calls_log, "history": messages}

        if stop_reason == "tool_use":
            # El agente quiere usar un tool
            tool_results = []
            for block in content:
                if block.get("type") == "tool_use":
                    tool_name   = block["name"]
                    tool_input  = block["input"]
                    tool_use_id = block["id"]
                    result      = execute_tool(tool_name, tool_input)
                    tool_calls_log.append({"tool": tool_name, "input": tool_input, "result": result})
                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": tool_use_id,
                        "content":     result,
                    })
            messages.append({"role": "user", "content": tool_results})

    return {"response": "El agente no pudo completar la tarea.", "tool_calls": tool_calls_log, "history": messages}


# ══════════════════════════════════════════════════════════════
# TAREAS PROGRAMADAS — el agente corre estas por sí solo
# ══════════════════════════════════════════════════════════════

SCHEDULED_TASKS = [
    {
        "name":     "daily_apify",
        "schedule": "0 6 * * *",      # 6am UTC todos los días
        "prompt":   "Ejecuta el agente Apify para actualizar los datos de comunas del día. Confirma qué país se procesó.",
    },
    {
        "name":     "daily_review",
        "schedule": "0 9 * * *",      # 9am UTC todos los días
        "prompt":   "Revisa los organizadores pendientes de aprobación y las consultas en revisión. Dame un resumen de lo que encontraste.",
    },
    {
        "name":     "weekly_summary",
        "schedule": "0 8 * * 1",      # Lunes 8am UTC
        "prompt":   "Dame un resumen semanal del sistema: nuevos usuarios, consultas publicadas, campañas activas, cualquier anomalía.",
    },
]


def run_scheduled_task(task_name: str) -> dict:
    """Ejecuta una tarea programada por nombre."""
    task = next((t for t in SCHEDULED_TASKS if t["name"] == task_name), None)
    if not task:
        return {"error": f"Tarea {task_name} no encontrada"}
    print(f'[Agent] Ejecutando tarea: {task_name} — {datetime.utcnow().isoformat()}')
    result = run_agent(task["prompt"])
    print(f'[Agent] {task_name} completado: {result["response"][:100]}')
    return result


# ══════════════════════════════════════════════════════════════
# RESPUESTAS DE SOPORTE PRE-DEFINIDAS
# (para preguntas frecuentes sin llamar a la API)
# ══════════════════════════════════════════════════════════════

FAQ = {
    "anónimo":      "Tu voto es completamente anónimo. Cuando votas, tu identidad se destruye inmediatamente (bridge destruction). En la urna NO aparece tu nombre, solo un voto cifrado. Ni Preferendum puede saber cómo votaste.",
    "verificacion": "Verificamos tu identidad con 5 capas: email, SMS al chip de tu teléfono, foto de tu carné, selfie con carné bajo el mentón, y el IMEI de tu aparato. Esto evita votos dobles pero nunca vincula tu identidad a tu voto.",
    "resultado":    "Los resultados son públicos y están anclados en blockchain. Cada resultado tiene un hash criptográfico inmutable. El Legitimacy Score muestra qué % de votantes verificaron que su voto fue contado correctamente.",
    "codigo":       "Tu código XXXX-XXXX-XXXX te permite verificar que tu voto fue contado sin revelar cómo votaste. Es tuyo solo — no lo compartas.",
    "publicidad":   "Los ads aparecen cada 5 opiniones. Se asignan según la comuna donde vives (proxy de nivel de ingreso), sin usar datos personales. Nunca sabemos tu nombre ni dirección exacta — solo tu comuna.",
}


def quick_faq_response(message: str) -> str:
    """Respuesta rápida para preguntas frecuentes sin llamar a la API."""
    msg_lower = message.lower()
    for keyword, response in FAQ.items():
        if keyword in msg_lower:
            return response
    return None


if __name__ == "__main__":
    print("=" * 60)
    print("PREFERENDUM AGENT — Test")
    print("=" * 60)
    questions = [
        "¿Es realmente anónimo el voto?",
        "¿Cómo sé que mi voto fue contado?",
        "Revisa los organizadores pendientes",
    ]
    for q in questions:
        print(f"\n→ {q}")
        fast = quick_faq_response(q)
        if fast:
            print(f"  [FAQ] {fast[:100]}...")
        else:
            result = run_agent(q)
            print(f"  [Agent] {result['response'][:150]}...")
            if result['tool_calls']:
                print(f"  [Tools usados] {[t['tool'] for t in result['tool_calls']]}")
