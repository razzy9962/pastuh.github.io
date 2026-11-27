## Как включить ежедневные копии Neon

Настроить это один раз нужно **в GitHub**, не в Render. Если автоматические копии пока не нужны, бот работает и без этих настроек.

1. Добавьте в репозиторий файл **`.github/workflows/neon-backup.yml`** из архива. Если интерфейс загрузки не переносит скрытую папку `.github`, используйте **Add file → Create new file**, укажите полное имя `.github/workflows/neon-backup.yml` и вставьте содержимое файла. Сохраните в основной ветке.
2. В Neon → **Connect** отключите **Connection pooling** и скопируйте прямой `postgresql://…` URI той же базы (с параметрами SSL). В GitHub → **Settings → Secrets and variables → Actions → Secrets → New repository secret** создайте **`NEON_BACKUP_URL`** с этой строкой. Не меняйте `DATABASE_URL` на Render. Не помещайте строку в код, переменную Variables или скриншот.
3. На своём компьютере установите [age](https://github.com/FiloSottile/age#installation) и выполните `age-keygen -o neon-backup.key`. **Файл `neon-backup.key` — приватный ключ**, держите его вне репозитория и сделайте отдельную защищённую копию. В GitHub → **Settings → Secrets and variables → Actions → Variables → New repository variable** создайте **`NEON_AGE_RECIPIENT`**. Вставьте туда только публичную строку `age1…`, выведенную `age-keygen`, без надписи `Public key:`. Не вставляйте приватный ключ: он нужен только вам при восстановлении.
4. В GitHub откройте **Actions → Encrypted Neon backup → Run workflow**. Дождитесь зелёного статуса. Внизу страницы запуска **Artifacts** скачайте архив, распакуйте `.dump.age` и проверочно расшифруйте его:

   ```bash
   age --decrypt -i neon-backup.key -o restore.dump neon-YYYY-MM-DD.dump.age
   pg_restore --list restore.dump
   ```

   Вместо `neon-YYYY-MM-DD.dump.age` подставьте имя скачанного файла. Для восстановления используйте новую пустую PostgreSQL-базу и `pg_restore --no-owner --no-acl` или pgAdmin. Сначала проверьте записи и только потом меняйте `DATABASE_URL` в Render; не накатывайте резервную копию поверх действующей базы. Расшифрованную копию храните только в защищённом месте.
5. Задание запланировано **раз в сутки, в 02:17 UTC**. GitHub может запускать расписание с задержкой; проверьте историю запусков и лимиты Actions в приватном репозитории. Зашифрованные файлы находятся вне Neon, в **Artifacts** GitHub; настройка хранения — 30 дней, если лимит репозитория не ниже. Периодически скачивайте экземпляр отдельно. Без ключа из шага 3 расшифровать копию нельзя.

