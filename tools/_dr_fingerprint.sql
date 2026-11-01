-- tools/_dr_fingerprint.sql — huella de integridad para el ensayo de
-- recuperación ante desastre (tools/verify_backup_restore.sh).
--
-- Devuelve UNA línea que resume el CONTENIDO, no solo el recuento. Dos
-- bases con el mismo número de filas pueden tener datos distintos; esta
-- huella cambia si cambia cualquier valor que importe.
--
-- Se compara antes del desastre y después de la restauración. Si difiere,
-- la restauración no es válida aunque pg_restore haya terminado sin error.
--
-- NOTA IMPORTANTE SOBRE EL MODELO DE DATOS
-- `debate_votes.voter_id` está SIEMPRE en NULL a propósito: es la
-- separación entre identidad y voto. Por eso la unicidad "una persona, un
-- voto" NO se puede comprobar sobre esa columna —agrupar por ella juntaría
-- todas las papeletas en un solo grupo—. El vínculo identidad→voto vive en
-- `debate_has_voted` (debate_id, user_id, verify_code), y es ahí donde se
-- comprueba.
--
-- md5 sobre una cadena ORDENADA: el orden de las filas que devuelve
-- PostgreSQL no está garantizado, y sin ORDER BY la huella cambiaría sola.

SELECT
  'votos='      || (SELECT count(*) FROM debate_votes)
  || ' md5votos=' || (SELECT coalesce(md5(string_agg(x, '|' ORDER BY x)), 'vacio')
                        FROM (SELECT debate_id::text || ':' || option_index::text || ':' ||
                                     coalesce(verify_code, '') AS x
                                FROM debate_votes) v)
  || ' yavoto='   || (SELECT count(*) FROM debate_has_voted)
  || ' md5puente='|| (SELECT coalesce(md5(string_agg(x, '|' ORDER BY x)), 'vacio')
                        FROM (SELECT debate_id::text || ':' || user_id::text || ':' ||
                                     coalesce(verify_code, '') AS x
                                FROM debate_has_voted) h)
  || ' docvoto='  || (SELECT count(*) FROM national_id_vote_log)
  || ' usuarios=' || (SELECT count(*) FROM users)
  || ' docs='     || (SELECT count(DISTINCT national_id) FROM users
                       WHERE national_id IS NOT NULL AND national_id <> '')
  || ' consultas='|| (SELECT count(*) FROM debates)
  || ' md5cont='  || (SELECT coalesce(md5(string_agg(x, '|' ORDER BY x)), 'vacio')
                        FROM (SELECT d.id::text || ':' || coalesce(d.total_votes, 0)::text || ':' ||
                                     (SELECT count(*) FROM debate_votes v WHERE v.debate_id = d.id)::text AS x
                                FROM debates d) c)
  || ' asientos=' || (SELECT count(*) FROM ledger_entries)
  || ' md5ledger='|| (SELECT coalesce(md5(string_agg(x, '|' ORDER BY x)), 'vacio')
                        FROM (SELECT account_id::text || ':' || round(sum(amount)::numeric, 6)::text AS x
                                FROM ledger_entries GROUP BY account_id) l)
  AS huella;
