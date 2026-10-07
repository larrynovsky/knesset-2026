# §14: детерминированность локальной сборки, не восстановление источников.
PY ?= python3

.PHONY: help check check-net fetch fetch-report validate report stamp reproduce layout selftest repro-selftest

help:
	@echo "check      — самопроверки без сети (валидатор карточки, генератор, §3, §24)"
	@echo "layout     — вёрстка отчёта: канон, прокрутка, маскировка (нужен Chromium)"
	@echo "selftest   — поднести бумажку к каждому датчику: все ли проверки живы"
	@echo "check-net  — самопроверки, которым нужна сеть (§23, выгрузка, оракул 120)"
	@echo "fetch      — выгрузка бюджета (сеть, минуты)"
	@echo "validate   — контракт карточки на реальных данных"
	@echo "report     — собрать site/"
	@echo "stamp      — пересчитать отпечатки карточек (осознанное действие)"
	@echo "reproduce  — §14: локальный снимок -> две сборки render_overview -> сверка всех файлов"

check:
	$(PY) scripts/validate_cards.py --selftest
	$(PY) scripts/render_overview.py --selftest
	$(PY) scripts/check_report_canon.py --selftest-reproduce
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
	$(PY) scripts/check_report_canon.py --build

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
	$(PY) scripts/render_overview.py --selftest
	$(PY) scripts/check_report_canon.py --selftest-reproduce
	$(PY) scripts/check_report_canon.py site --selftest
	$(PY) scripts/check_layout.py site --selftest

# Никакой сети и записи в data/. Входы копируются один раз; это не архив публикации.
# Последовательные вызовы внутри скрипта безопасны и при make -j.
reproduce:
	$(PY) scripts/check_report_canon.py --reproduce

repro-selftest:
	$(PY) scripts/check_report_canon.py --selftest-reproduce
