
# Развёртка

## Структура
  
- configs - каталог с конфигурационными файлами для сервисов
  - envs - каталог с переменными окружения
    - dev.env - переменные окружения при разворачивании
  - grafana - содержит конфиги подключения метрик серверов и дашборд (только nodeexporter, TBD)
  - postgresql
    - init-pg-databases.sh - скрипт инициализации базы PostgreSQL. В нем создаются необходимые базы
  - prometheus
    - prometheus.yml - конфигурационный файл с параметрами, с каких сервисов собирать метрики
  - vector
    - token.sh - скрипт получения первичного токена openobserve, для хранения логов сервисов.
    - vector.toml - конфигурация куда писать и какие логи.

## Общая информация

 1. При старте некоторые контейнеры будут билдится, пока не будет выполнена полная инициализация зависимых контейнеров. Такое поведение нормально.

 2. При локальном тестировании 
    - необходимо задать переменные LOCALHOST_IP - который определит к какому адаптеру подключаться для взаимодействия с сервисами.
      при локальном тестирование рекомендуется установить в LOCALHOST_IP=127.0.0.1, но это не обязательно.
    - при открытии порта для PostgreSQL контейнера, данный порт может быть задан.
      поменять можно заданием POSTGRES_EXT_PORT=15432 (например)

## Для локального тестирования
 
 ```bash
./build.sh
```