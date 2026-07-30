# ENFORCEMENT — что реально стоит на страже

**Файл СГЕНЕРИРОВАН** `scripts/check_artifacts.py`. Руками не править:
правка будет затёрта, а расхождение с кодом — это и есть то, что файл ловит.

Столбец «заявлено» берётся из `CLAUDE.md`, столбец «код знает» — из
упоминаний `§N` в `scripts/`. Расхождение означает, что свод говорит о себе
неправду. Совпадение НЕ означает, что механизм хорош: он ловит отсутствие
носителя, а не его качество (§24).

| § | правило | заявлено | код знает |
|---|---|---|---|
| §1 | Единица наблюдения — партия в период участия в правительстве. | MANUAL | build_periods.py, check_artifacts.py, probe_shas_periods.py, slice_party_theme.py |
| §2 | Партия и её фигуры считаются раздельно. | MANUAL | — |
| §3 | Критерии отбора фиксируются ДО первого взгляда на результаты. | LIVE | build_lineage_candidates.py, build_periods.py, check_artifacts.py, check_criteria_order.py, commit-msg, post-receive.template, pre-commit, scan_bills.py, select_pilot.py |
| §4 | Карточка обязана нести отчёт о поиске опровержения. | MANUAL | check_artifacts.py, classify_direction.py, post-receive.template, pre-commit |
| §5 | Минимум два прочтения, и не все ослабляющие. | MANUAL | — |
| §6 | Уровень уверенности обязателен и несёт названную причину. | MANUAL | probe_bill_texts.py |
| §7 | Ноль периодов правления ⇒ нет карточки-вердикта. | MANUAL | check_artifacts.py |
| §8 | Интерпретация проверяется на отложенном периоде. | MANUAL | select_pilot.py |
| §9 | Голосования только из `knesset.gov.il/OdataV4/ParliamentInfo`. | MANUAL | fetch_votes.py, guarded_fetch.py, pre-commit |
| §10 | Смысл «за» не предполагается, а читается. | MANUAL | fetch_votes.py, slice_party_theme.py |
| §11 | Единый срез. | MANUAL | probe_phase0.py |
| §12 | Ивритский оригинал хранится рядом с переводом. | MANUAL | classify_direction.py, fetch_agreements.py, ocr_agreements.py, post-receive.template, pre-commit |
| §13 | В публикации нет суммарного балла, рейтинга и оценочных ярлыков. | MANUAL | build_lineage_rule.py |
| §14 | Всё опубликованное воспроизводимо из репозитория. | MANUAL | extract_institutions.py, fetch_agreements.py, ocr_agreements.py, probe_bill_texts.py, select_pilot.py |
| §15 | Исправление публикуется, а не заменяет тихо. | MANUAL | check_artifacts.py |
| §16 | Доступно, но не продвигается. Массовость — триггер, а не разрешённое с | MANUAL | — |
| §17 | Рамка объявлена на первом экране. | MANUAL | — |
| §18 | Секреты вне репозитория. | MANUAL | classify_direction.py, pre-commit |
| §19 | Пишет только MacBook, canonical — Studio. | MANUAL | pre-commit |
| §20 | Не называть сделанным то, у чего нет краснеющего механизма. | MANUAL | check_artifacts.py, check_criteria_order.py, classify_direction.py, post-receive.template, pre-commit, select_pilot.py, verify_names_wikidata.py |
| §21 | Риск → исполняемая проверка, а не строка в плане. | MANUAL | — |
| §22 | Правило прогоняется по изменению, которое его вводит, и сверяется со с | MANUAL | pre-commit, select_pilot.py |
| §23 | Ожидаемый объём получается ДРУГИМ путём и сверяется до использования д | LIVE | build_periods.py, check_artifacts.py, check_knesset_120.py, classify_direction.py, commit-msg, extract_institutions.py, fetch_agreements.py, fetch_bill_texts.py, fetch_votes.py, guarded_fetch.py, ocr_agreements.py, probe_bill_texts.py, probe_faction_join.py, probe_mk_bridge.py, probe_odata_shapes.py, probe_phase0.py, probe_phase0_odata.py, probe_shas_periods.py, probe_votes_join.py, probe_votes_shape.py, scan_bills.py, select_pilot.py, verify_names_wikidata.py |
| §24 | У каждого правила есть артефакт, отсутствие которого само является нар | LIVE | check_artifacts.py, check_criteria_order.py, fetch_bill_texts.py, guarded_fetch.py, post-receive.template, pre-commit |

Всего правил: 24 · заявлено LIVE: 3 · упомянуто в коде: 20
