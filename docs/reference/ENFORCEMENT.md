# ENFORCEMENT — что реально стоит на страже

**Файл СГЕНЕРИРОВАН** `scripts/check_artifacts.py`. Руками не править:
правка будет затёрта, а расхождение с кодом — это и есть то, что файл ловит.

Столбец «заявлено» берётся из `CLAUDE.md`, столбец «код знает» — из
упоминаний `§N` в `scripts/`. Расхождение означает, что свод говорит о себе
неправду. Совпадение НЕ означает, что механизм хорош: он ловит отсутствие
носителя, а не его качество (§24).

| § | правило | заявлено | код знает |
|---|---|---|---|
| §1 | Единица наблюдения — партия в период участия в правительстве. | MANUAL | check_artifacts.py |
| §2 | Партия и её фигуры считаются раздельно. | MANUAL | — |
| §3 | Критерии отбора фиксируются ДО первого взгляда на результаты. | LIVE | build_lineage_candidates.py, check_criteria_order.py, post-receive.template, pre-commit, scan_bills.py |
| §4 | Карточка обязана нести отчёт о поиске опровержения. | MANUAL | check_artifacts.py, post-receive.template, pre-commit |
| §5 | Минимум два прочтения, и не все ослабляющие. | MANUAL | — |
| §6 | Уровень уверенности обязателен и несёт названную причину. | MANUAL | — |
| §7 | Ноль периодов правления ⇒ нет карточки-вердикта. | MANUAL | check_artifacts.py |
| §8 | Интерпретация проверяется на отложенном периоде. | MANUAL | — |
| §9 | Голосования только из `knesset.gov.il/OdataV4/ParliamentInfo`. | MANUAL | guarded_fetch.py, pre-commit |
| §10 | Смысл «за» не предполагается, а читается. | MANUAL | — |
| §11 | Единый срез. | MANUAL | probe_phase0.py |
| §12 | Ивритский оригинал хранится рядом с переводом. | MANUAL | post-receive.template, pre-commit |
| §13 | В публикации нет суммарного балла, рейтинга и оценочных ярлыков. | MANUAL | build_lineage_rule.py |
| §14 | Всё опубликованное воспроизводимо из репозитория. | MANUAL | — |
| §15 | Исправление публикуется, а не заменяет тихо. | MANUAL | check_artifacts.py |
| §16 | Доступно, но не продвигается. Массовость — триггер, а не разрешённое с | MANUAL | — |
| §17 | Рамка объявлена на первом экране. | MANUAL | — |
| §18 | Секреты вне репозитория. | MANUAL | pre-commit |
| §19 | Пишет только MacBook, canonical — Studio. | MANUAL | pre-commit |
| §20 | Не называть сделанным то, у чего нет краснеющего механизма. | MANUAL | post-receive.template, pre-commit, verify_names_wikidata.py |
| §21 | Риск → исполняемая проверка, а не строка в плане. | MANUAL | — |
| §22 | Правило прогоняется по изменению, которое его вводит, и сверяется со с | MANUAL | pre-commit |
| §23 | Ожидаемый объём получается ДРУГИМ путём и сверяется до использования д | LIVE | check_artifacts.py, check_knesset_120.py, guarded_fetch.py, probe_faction_join.py, probe_odata_shapes.py, probe_phase0.py, probe_phase0_odata.py, scan_bills.py, verify_names_wikidata.py |
| §24 | У каждого правила есть артефакт, отсутствие которого само является нар | LIVE | check_artifacts.py, post-receive.template, pre-commit |

Всего правил: 24 · заявлено LIVE: 3 · упомянуто в коде: 15
