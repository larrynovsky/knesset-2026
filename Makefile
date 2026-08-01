# knesset — воспроизводимость (§14) одной командой.
#
# §14 говорит: любая цифра в отчёте получается прогоном скриптов репозитория
# из чистого клона. До сегодняшнего дня это не проверялось ни разу — здесь
# оно становится командой, которая краснеет.
#
# Что `reproduce` НЕ доказывает, и это надо знать заранее:
#   * он зависит от доступности obudget. Источник лёг — цель красная, хотя
#     репозиторий цел. Это не ложное срабатывание: невоспроизводимо сегодня
#     значит невоспроизводимо сегодня;
#   * он не перепрогоняет OCR соглашений. Цитаты хранятся в карточке как
#     данные, а §14 разрешает ручной шаг, записанный как данные. Числа —
#     единственное, что берётся из выгрузки, и они здесь и проверяются;
#   * он доказывает, что документ СОБИРАЕТСЯ и повторяется, а не что выводы
#     в нём осмысленны. Осмысленность машиной неотличима (§24).
#
# На Studio ssh не видит Homebrew:
#   make PY=/opt/homebrew/bin/python3.11 reproduce

PY ?= python3
SHA := shasum -a 256

.PHONY: help check check-net fetch fetch-report validate report stamp reproduce layout selftest

help:
	@echo "check      — самопроверки без сети (валидатор карточки, генератор, §3, §24)"
	@echo "layout     — вёрстка отчёта: канон, прокрутка, маскировка (нужен Chromium)"
	@echo "selftest   — поднести бумажку к каждому датчику: все ли проверки живы"
	@echo "check-net  — самопроверки, которым нужна сеть (§23, выгрузка, оракул 120)"
	@echo "fetch      — выгрузка бюджета (сеть, минуты)"
	@echo "validate   — контракт карточки на реальных данных"
	@echo "report     — собрать site/"
	@echo "stamp      — пересчитать отпечатки карточек (осознанное действие)"
	@echo "reproduce  — §14: выгрузка -> проверки -> две сборки -> сверка"

check:
	$(PY) scripts/validate_cards.py --selftest
	$(PY) scripts/build_report.py --selftest
	$(PY) scripts/check_criteria_order.py
	$(PY) scripts/check_artifacts.py

check-net:
	$(PY) scripts/guarded_fetch.py
	$(PY) scripts/fetch_budget.py --selftest
	$(PY) scripts/check_knesset_120.py

fetch:
	$(PY) scripts/fetch_budget.py

fetch-report:
	$(PY) scripts/fetch_budget.py --only takanot

validate:
	$(PY) scripts/validate_cards.py

report:
	$(PY) scripts/build_report.py

stamp:
	$(PY) scripts/build_report.py --stamp

# Вёрстка отчёта. Обе проверки объявляют, сколько объектов осмотрели:
# «осмотрено 0» — красный, а не зелёный (§23, применённый к проверкам).
layout:
	$(PY) scripts/check_report_canon.py site
	$(PY) scripts/check_layout.py site

# Поднести бумажку к каждому датчику. Проверка, не покрасневшая на собственном
# подложенном нарушении, мертва — узнать это иначе нельзя: работающая и мёртвая
# проверки печатают одинаковое зелёное.
#
# Это КОМАНДА, а не хук: механизм, срабатывающий лишь при вызове, защищает
# вызов (§24). В post-receive не вставлена намеренно — check_layout поднимает
# браузер. Названо вслух, чтобы не считалось сторожем.
selftest:
	$(PY) scripts/validate_cards.py --selftest
	$(PY) scripts/build_report.py --selftest
	$(PY) scripts/check_report_canon.py site --selftest
	$(PY) scripts/check_layout.py site --selftest

# Две сборки подряд на одних данных обязаны совпасть побайтово. Расхождение
# означает, что в документ просочилось что-то, чего нет во входе, — время
# сборки, порядок обхода словаря, случайность. Такой отчёт нельзя ни
# проверить, ни сравнить с предыдущим.
# Перевыгружается ТОЛЬКО raw_budget: отчёт читает его и ничего больше.
# Тянуть сюда budget_changes значило бы поставить воспроизводимость
# документа в зависимость от источника, которого в документе нет, — 31.07
# obudget перестал отвечать на count(1) по этой таблице, и §23 отказал.
reproduce: check fetch-report validate report
	$(SHA) site/index.html > .repro.sha
	$(PY) scripts/build_report.py
	@$(SHA) site/index.html | diff - .repro.sha > /dev/null \
	  && echo "§14: две сборки на одних данных совпали побайтово" \
	  || { echo "ОТКАЗ §14: сборка недетерминирована" >&2; exit 1; }
	@rm -f .repro.sha
