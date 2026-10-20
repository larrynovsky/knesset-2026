# Как выложить сайт на Hetzner и проверить выкладку

Адрес: https://knesset.SITE_HOST/ — сервер bias-tester (проект Hetzner «bias»), Caddy, корень /var/www/knesset.
Решение владельца 2026-10-20: вариант А (рядом с bias, бесплатно, адрес sslip.io).

## Выложить (на Studio, после зелёного `make report`)
    cd ~/knesset && rsync -rlt -c --delete -e "ssh -i ~/.ssh/knesset_deploy -o BatchMode=yes" \
      site/ knesset-deploy@HETZNER_HOST:/var/www/knesset/

Ключ `~/.ssh/knesset_deploy` — только на Studio, вне репозитория (§18). Пользователь knesset-deploy без sudo,
ключ с `restrict`. rrsync не используется: openrsync на Studio с ним несовместим.

## Проверить (на Studio)
    make hosted-check

Успех — «нарушений: 0», EXIT 0. Выкладка по rsync сама по себе не доказывает, что сервер отдаёт то же самое.

## Откатить Caddy
Резервная копия: /etc/caddy/Caddyfile.bak-2026-10-20 (root на bias-tester). `caddy validate` до `systemctl reload caddy`;
после reload проверить, что bias жив: `curl -s -o /dev/null -w '%{http_code}' https://SITE_HOST/` → 200.

## Чего нет
Автовыкладки из post-receive нет: выкладка ручная, после каждой пересборки сайта.
