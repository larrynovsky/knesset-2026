# ENFORCEMENT — заявления свода и упоминания в коде

**Файл СГЕНЕРИРОВАН** `scripts/check_artifacts.py`. Руками не править:
правка будет затёрта, а расхождение с кодом — это и есть то, что файл ловит.

Столбец «заявлено» берётся из `CLAUDE.md`, «файлы с упоминанием» — из
текстового поиска `§N` в `scripts/`, включая комментарии и ссылки на чужие своды.
Упоминание не механизм (инвариант `mention_is_not_mechanism` в
`subsystem_intent.yaml`): оно не доказывает ни наличие проверки, ни её работу.
MANUAL с упоминаниями допустим; оснований повышать Enforcement здесь нет.
Проверка (A) блокирует LIVE без упоминаний, но их наличие не подтверждает LIVE.

| § | правило | заявлено | файлы с упоминанием |
|---|---|---|---|
| §1 | Единица наблюдения — партия в период участия в правительстве. | PARTIAL | build_periods.py, check_artifacts.py, probe_shas_periods.py, slice_party_theme.py, validate_cards.py |
| §2 | Партия и её фигуры считаются раздельно. | PARTIAL | validate_cards.py |
| §3 | Критерии отбора фиксируются ДО первого взгляда на результаты. | LIVE | build_blind_reading.py, build_lineage_candidates.py, build_periods.py, build_report.py, check_artifacts.py, check_criteria_order.py, commit-msg, direction_confidence.py, fetch_votes.py, map_commitments.py, post-receive.template, pre-commit, scan_bills.py, select_pilot.py, select_structdiff_pilot.py |
| §4 | Карточка обязана нести отчёт о поиске опровержения. | PARTIAL | check_artifacts.py, classify_direction.py, post-receive.template, pre-commit, validate_cards.py |
| §5 | Минимум два прочтения, и не все ослабляющие. | PARTIAL | validate_cards.py |
| §6 | Уровень уверенности обязателен и несёт названную причину. | PARTIAL | direction_confidence.py, probe_bill_texts.py, select_structdiff_pilot.py, validate_cards.py |
| §7 | Ноль периодов правления ⇒ матрица экспозиции, а не базовая ставка. | PARTIAL | check_artifacts.py, coverage_matrix.py, direction_confidence.py, fetch_votes.py, guarded_fetch.py, render_overview.py, validate_cards.py |
| §8 | Интерпретация проверяется на отложенном периоде. | PARTIAL | select_pilot.py, validate_cards.py |
| §9 | Голосования только из `knesset.gov.il/OdataV4/ParliamentInfo`. | PARTIAL | build_report.py, fetch_votes.py, guarded_fetch.py, pre-commit, render_overview.py |
| §10 | Смысл «за» не предполагается, а читается. | PARTIAL | build_report.py, direction_confidence.py, fetch_votes.py, render_card_page.py, render_overview.py, slice_party_theme.py, validate_cards.py |
| §11 | Единый срез. | PARTIAL | build_line_cards.py, build_report.py, check_report_canon.py, fetch_budget.py, map_commitments.py, probe_phase0.py, validate_cards.py |
| §12 | Ивритский оригинал хранится рядом с переводом. | PARTIAL | build_report.py, classify_direction.py, fetch_agreements.py, map_commitments.py, ocr_agreements.py, post-receive.template, pre-commit, render_card_page.py, render_mapping_review.py, render_overview.py, validate_cards.py |
| §13 | В публикации нет суммарного балла, рейтинга и оценочных ярлыков. | PARTIAL | build_lineage_rule.py, build_report.py, render_axes.py, render_card_page.py, render_mapping_review.py, render_overview.py, validate_cards.py |
| §14 | Воспроизводимость публикации требует сохранённых входов; локальная про | PARTIAL | build_report.py, check_report_canon.py, classify_direction.py, coverage_matrix.py, direction_confidence.py, extract_institutions.py, fetch_agreements.py, fetch_budget.py, ocr_agreements.py, probe_bill_texts.py, select_pilot.py, select_structdiff_pilot.py, validate_cards.py |
| §15 | Исправление публикуется, а не заменяет тихо. | PARTIAL | build_report.py, check_artifacts.py, probe_placebo.py, validate_cards.py |
| §16 | Доступно, но не продвигается. Массовость — триггер, а не разрешённое с | LIVE | build_report.py, check_report_canon.py, render_axes.py, render_card_page.py, render_overview.py |
| §17 | Рамка объявлена на первом экране. | LIVE | build_report.py, render_axes.py, render_card_page.py, render_overview.py |
| §18 | Секреты вне репозитория. | PARTIAL | classify_direction.py, pre-commit |
| §19 | Пишет только MacBook, canonical — Studio. | PARTIAL | build_line_cards.py, build_report.py, fetch_budget.py, guarded_fetch.py, map_commitments.py, pre-commit, resolve_law_ref.py |
| §20 | Не называть сделанным то, у чего нет краснеющего механизма. | PARTIAL | check_artifacts.py, check_criteria_order.py, check_knesset_120.py, classify_direction.py, direction_confidence.py, map_commitments.py, post-receive.template, pre-commit, select_pilot.py, validate_cards.py, verify_names_wikidata.py |
| §21 | Риск → исполняемая проверка, а не строка в плане. | PARTIAL | build_report.py, check_layout.py, render_pilot_review.py, resolve_law_ref.py, select_structdiff_pilot.py |
| §22 | Правило прогоняется по изменению, которое его вводит, и сверяется со с | MANUAL | check_artifacts.py, pre-commit, select_pilot.py |
| §23 | Ожидаемый объём получается ДРУГИМ путём и сверяется до использования д | LIVE | build_periods.py, check_artifacts.py, check_knesset_120.py, check_report_canon.py, classify_direction.py, commit-msg, direction_confidence.py, extract_institutions.py, fetch_agreements.py, fetch_bill_dates.py, fetch_bill_texts.py, fetch_budget.py, fetch_law_texts.py, fetch_votes.py, guarded_fetch.py, map_commitments.py, ocr_agreements.py, pre-commit, probe_bill_texts.py, probe_faction_join.py, probe_mk_bridge.py, probe_odata_shapes.py, probe_phase0.py, probe_phase0_odata.py, probe_placebo.py, probe_shas_periods.py, probe_vote_links.py, probe_vote_publicity.py, probe_votes_join.py, probe_votes_shape.py, probe_wikisource.py, scan_bills.py, select_pilot.py, validate_cards.py, verify_names_wikidata.py |
| §24 | У каждого правила есть артефакт, отсутствие которого само является нар | LIVE | build_report.py, check_artifacts.py, check_criteria_order.py, check_knesset_120.py, check_report_canon.py, classify_direction.py, coverage_matrix.py, fetch_bill_texts.py, guarded_fetch.py, post-receive.template, pre-commit, render_axes.py, render_overview.py, validate_cards.py |
| §26 | Утверждение о том, как документ читается, проверяется чтением вслепую, | MANUAL | render_overview.py |

Всего правил: 25 · заявлено LIVE: 5 · упомянуто в коде: 26
