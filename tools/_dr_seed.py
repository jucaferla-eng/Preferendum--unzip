"""tools/_dr_seed.py — semilla del ensayo de recuperación ante desastre.

Auxiliar de tools/verify_backup_restore.sh. No se ejecuta por sí solo en
producción y no sirve para nada más.

Crea el esquema con las MISMAS funciones que usa la aplicación al arrancar
(Base.metadata.create_all y _migrate), nunca con un CREATE TABLE escrito a
mano: si el esquema real cambia, el ensayo sigue probando el esquema real.

Luego siembra datos ficticios representativos de todo lo que una
recuperación tiene que devolver intacto: identidad, papeletas con su código
de verificación, los registros que impiden el doble voto, y la contabilidad
de una campaña con impresiones y asientos del ledger.

Todos los datos son ficticios: dominio .invalid, documentos del rango
99.xxx.xxx y dinero de clase DEMO.
"""
import os
import sys
import uuid

if not os.getenv('DATABASE_URL'):
    sys.exit('DATABASE_URL es obligatoria.')

import bcrypt                                     # noqa: E402
import main                                       # noqa: E402

# Volumen del ensayo. 25 basta para probar que la recuperación FUNCIONA;
# para que el tiempo medido (RTO) signifique algo hay que ensayar con un
# volumen parecido al de producción:
#   PREFY_DR_VOTES=50000 tools/verify_backup_restore.sh
N_VOTANTES = int(os.getenv('PREFY_DR_VOTES', '25'))
LOTE = 500          # filas por commit al sembrar volumen


def _uniq(p):
    return f'{p}-{uuid.uuid4().hex[:10]}'


def main_seed():
    main.Base.metadata.create_all(bind=main.engine)
    try:
        main._migrate()
    except Exception as e:
        # El ensayo debe seguir: lo que importa es que el esquema que se
        # respalde sea el que la aplicación produce de verdad, incluidos
        # los fallos de migración que ya existan.
        print(f'[dr-seed] _migrate avisó: {type(e).__name__}')

    db = main.SessionLocal()
    clave = bcrypt.hashpw(b'dr-local', bcrypt.gensalt()).decode()

    # ── comuna de referencia ──────────────────────────────────────────
    db.add(main.CommuneMarketData(country='CL', commune='Las Condes', se_tier='A',
                                  income_index=95.0, price_m2_avg=95.0, cpm_usd=6.0))
    db.commit()

    # ── organizador y consulta ────────────────────────────────────────
    org = main.User(name='Organizador DR', email=_uniq('org') + '@test.invalid',
                    password=clave, country='CL', role='organizer',
                    email_verified=True)
    db.add(org); db.commit(); db.refresh(org)

    consulta = main.Debate(
        title='Consulta ficticia del ensayo de recuperación',
        context='Datos ficticios. No es una consulta real.',
        options='["Opción A", "Opción B"]',
        creator_id=org.id, creator_type='organizer',
        scope='country', scope_country='CL', status='open',
        target_gender='all', target_age_min=18, target_age_max=99,
        target_se_tiers='A,B,C,D', total_votes=0)
    db.add(consulta); db.commit(); db.refresh(consulta)

    # ── votantes y papeletas ─────────────────────────────────────────
    # Una clave bcrypt se reutiliza para todos: calcular 50.000 hashes
    # tardaría más que todo el ensayo y no prueba nada sobre la
    # recuperación. El dato que importa es el VOLUMEN de filas.
    emitidos = 0
    for i in range(N_VOTANTES):
        doc = f'99{i:06d}-9'
        u = main.User(name=f'Votante DR {i}', email=_uniq('v') + '@test.invalid',
                      password=clave, country='CL', county='Las Condes',
                      dob='1990-05-05', gender='M' if i % 2 else 'F',
                      profession='Ingeniero Industrial', national_id=doc,
                      email_verified=True)
        db.add(u); db.flush()

        opcion = i % 2
        codigo = f'DR{uuid.uuid4().hex[:10].upper()}'
        # voter_id se deja en None A PROPÓSITO: es el diseño real de
        # Preferendum (separación entre identidad y voto), no un olvido de
        # esta semilla. El puente identidad→voto vive en debate_has_voted
        # a través de verify_code, y es justo eso lo que una recuperación
        # tiene que devolver intacto.
        voto = main.DebateVote(
            debate_id=consulta.id, voter_id=None, option_index=opcion,
            option_text=['Opción A', 'Opción B'][opcion],
            verify_code=codigo, vote_hash=uuid.uuid4().hex,
            gender=u.gender, age_group='35-44', commune='Las Condes',
            country='CL')
        db.add(voto)
        # Los registros que impiden votar dos veces forman parte de lo que
        # una recuperación tiene que devolver: sin ellos, restaurar
        # reabriría la puerta al doble voto.
        db.add(main.HasVotedLog(debate_id=consulta.id, user_id=u.id,
                                verify_code=codigo))
        db.add(main.NationalIdVoteLog(
            debate_id=consulta.id,
            national_id_hash=main.hashlib.sha256(doc.encode()).hexdigest()))
        emitidos += 1
        if emitidos % LOTE == 0:
            db.commit()
            print(f'[dr-seed] {emitidos}/{N_VOTANTES} papeletas', flush=True)
    db.commit()

    consulta.total_votes = emitidos
    db.commit()

    # ── anunciante, campaña, impresiones y ledger ────────────────────
    anunciante = main.User(name='Anunciante DR', email=_uniq('mk') + '@test.invalid',
                           password=clave, country='CL', role='marketer',
                           email_verified=True)
    db.add(anunciante); db.commit(); db.refresh(anunciante)

    campana = main.AdCampaign(
        advertiser_email=anunciante.email, advertiser_name='Marca Ficticia DR',
        title='Campaña ficticia DR', budget_clp=100000, is_active=True,
        target_country='CL', target_communes='Las Condes', target_gender='all',
        target_se_tiers='A,B,C,D', target_age_min=18, target_age_max=99,
        ad_copy='Anuncio ficticio', link_url='https://example.invalid',
        value_class=main._ledger.DEMO)
    db.add(campana); db.commit(); db.refresh(campana)

    main._ledger_fund(db, main._ledger.DEMO, anunciante.id, 50.0,
                      method='dr_demo', idempotency_key=_uniq('fund'),
                      description='Fondeo ficticio del ensayo DR')
    main._ledger_reserve(db, campana, anunciante.id, 50.0,
                         idempotency_key=_uniq('res'))

    for _ in range(5):
        log = main.AdImpressionLog(
            campaign_id=campana.id, debate_id=consulta.id, user_id=anunciante.id,
            cost_clp=main.COST_PER_VIEW, gender='M', age_group='35-44',
            county='Las Condes', country='CL')
        db.add(log); db.flush()
        main._ledger_spend(db, campana, main.COST_PER_VIEW / main.USD_TO_CLP,
                           idempotency_key=_uniq('spend'), source='dr_seed',
                           reference=str(log.id), description='Impresión ficticia DR')
    db.commit()

    print(f'[dr-seed] consulta={consulta.id} votos={emitidos} '
          f'campaña={campana.id} ledger={campana.ledger_status}')
    db.close()


if __name__ == '__main__':
    main_seed()
