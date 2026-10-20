# Как выложить сайт на Hetzner и проверить выкладку

Адрес сайта и хост выкладки в репозиторий не входят (§16, §18): на Studio они лежат в
`~/.knesset_secrets/site_url` и `~/.knesset_secrets/deploy_host` (вид `пользователь@хост`).
Сервер — Hetzner, Caddy, корень /var/www/knesset. Решение владельца 2026-10-20: вариант А (рядом с другим проектом владельца, бесплатно, адрес sslip.io).

## Выложить (на Studio, после зелёного `make report`)
    cd ~/knesset && rsync -rlt -c --delete -e "ssh -i ~/.ssh/knesset_deploy -o BatchMode=yes" \
      site/ "$(cat ~/.knesset_secrets/deploy_host)":/var/www/knesset/

Ключ `~/.ssh/knesset_deploy` — только на Studio, вне репозитория (§18). Пользователь выкладки без sudo,
ключ с `restrict`. rrsync не используется: openrsync на Studio с ним несовместим.

## Проверить (на Studio)
    make hosted-check

Успех — «нарушений: 0», EXIT 0. Выкладка по rsync сама по себе не доказывает, что сервер отдаёт то же самое.

## Откатить Caddy
Резервная копия: /etc/caddy/Caddyfile.bak-2026-10-20 (root на сервере). `caddy validate` до `systemctl reload caddy`;
после reload проверить, что соседний сайт жив: `curl` его корня → 200 (адрес — в `~/.infrastructure.md`).

## Чего нет
Автовыкладки из post-receive нет: выкладка ручная, после каждой пересборки сайта.
