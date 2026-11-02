"""pruebas_voto_facial.py — andamiaje para la verificación facial del voto.

Desde que votar EXIGE una verificación facial válida (y de un solo uso),
cualquier prueba que vote por la API necesita una. No se puede hacer
reconocimiento facial real en una prueba, así que aquí se crea exactamente
el rastro que deja `/debates/{id}/face-token` tras una comparación real:
la fila de un solo uso en `otp_codes` y el token firmado que la acompaña.

POR QUÉ AQUÍ Y NO EN CADA SUITE. Son seis suites y veintitantas llamadas a
votar, con variables distintas en cada sitio. Un ayudante por archivo
multiplica las ocasiones de equivocarse; esto está en un solo lugar y se
explica una sola vez. Cada suite que vota lo activa con una línea:

    import pruebas_voto_facial  # noqa: F401  (rellena el token facial)

No es un conftest.py porque `tools/run_all_tests.sh` ejecuta las suites con
`python -m unittest`, que ignora los conftest. Me pasó: individualmente
pasaban y en la batería fallaban las mismas siete.

LO QUE ESTO NO HACE, A PROPÓSITO: no desactiva el control. Solo rellena el
`face_token` cuando la prueba no trae ninguno, igual que el portal lo
rellena pidiendo la cámara. `test_voto_verificacion_facial.py` —la suite
que comprueba el control en sí— NO importa este módulo: ahí las peticiones
salen tal cual se escriben, para que lo que se mide sea el servidor.
"""
import re
from datetime import datetime, timedelta

_RUTA_VOTO = re.compile(r'/debates/(\d+)/vote$')


def _token_facial(main, user_id: int, debate_id: int) -> str:
    import uuid
    import jwt
    jti = uuid.uuid4().hex
    db = main.SessionLocal()
    try:
        db.add(main.OTPCode(user_id=user_id, email='', code=jti,
                            channel='face_vote', used=False,
                            expires_at=datetime.utcnow() + timedelta(minutes=5)))
        db.commit()
    finally:
        db.close()
    return jwt.encode({'sub': user_id, 'debate_id': debate_id,
                       'type': 'face_vote', 'jti': jti,
                       'exp': datetime.utcnow() + timedelta(minutes=5)},
                      main.SECRET, algorithm='HS256')


def _usuario_de(main, cabeceras) -> int:
    import jwt
    aut = ''
    for k, v in (cabeceras or {}).items():
        if k.lower() == 'authorization':
            aut = v or ''
    if not aut.lower().startswith('bearer '):
        return 0
    try:
        return int(jwt.decode(aut.split(' ', 1)[1], main.SECRET,
                              algorithms=['HS256'])['sub'])
    except Exception:
        return 0


def token(main, user_id: int, debate_id: int) -> str:
    """Token facial valido, para las pruebas que llaman a
    `_cast_vote_inner` directamente y no pasan por el cliente HTTP."""
    return _token_facial(main, user_id, debate_id)


def _activar():
    """Rellena el face_token de las peticiones de voto que no traigan uno.

    No desactiva el control: solo hace lo que hace el portal al pedir la
    cámara. Si la prueba MENCIONA `face_token` -aunque sea vacío- se
    respeta lo que diga, porque entonces la prueba es sobre el control.
    """
    import sys
    main = sys.modules.get('main')
    if main is None:
        import main                                  # noqa: F811
    from starlette.testclient import TestClient
    if getattr(TestClient.post, '_prefy_facial', False):
        return
    original = TestClient.post

    def post(self, url, *a, **kw):
        m = _RUTA_VOTO.search(str(url).split('?')[0])
        cuerpo = kw.get('json')
        if m and isinstance(cuerpo, dict) and 'face_token' not in cuerpo:
            uid = _usuario_de(main, kw.get('headers'))
            if uid:
                cuerpo = dict(cuerpo)
                cuerpo['face_token'] = _token_facial(main, uid, int(m.group(1)))
                kw['json'] = cuerpo
        return original(self, url, *a, **kw)

    post._prefy_facial = True
    TestClient.post = post


_activar()
