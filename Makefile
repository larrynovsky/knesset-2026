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

.PHONY: help check check-net fetch validate report stamp reproduce

help:
	@echo "check      — самопроверки без сети (валидатор карточки, генератор, §3, §24)"
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

validate:
	$(PY) scripts/validate_cards.py

report:
	$(PY) scripts/build_report.py

stamp:
	$(PY) scripts/build_report.py --stamp

# Две сборки подряд на одних данных обязаны совпасть побайтово. Расхождение
# означает, что в документ просочилось что-то, чего нет во входе, — время
# сборки, порядок обхода словаря, случайность. Такой отчёт нельзя ни
# проверить, ни сравнить с предыдущим.
reproduce: check fetch validate report
	$(SHA) site/index.html > .repro.sha
	$(PY) scripts/build_report.py
	@$(SHA) site/index.html | diff - .repro.sha > /dev/null \
	  && echo "§14: две сборки на одних данных совпали побайтово" \
	  || { echo "ОТКАЗ §14: сборка недетерминирована" >&2; exit 1; }
	@rm -f .repro.sha
