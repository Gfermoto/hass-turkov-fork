# Turkov (Fork by Gfermoto)

> ⚡️ Это форк оригинальной интеграции [alryaz/hass-turkov](https://github.com/alryaz/hass-turkov)
> 
> Репозиторий форка: [https://github.com/Gfermoto/hass-turkov-fork](https://github.com/Gfermoto/hass-turkov-fork)
> 
> Для обсуждения и поддержки: [t.me/DIYIoT_Zone](https://t.me/DIYIoT_Zone)

А управление через modbus [находится тут](https://github.com/malexmnt/turkov-modbus)

# _Turkov_ для Home Assistant
> Облачное и локальное управление вентиляционными устройствами фирмы Turkov.
>
> [![hacs_badge](https://img.shields.io/badge/HACS-Default-41BDF5.svg?style=for-the-badge)](https://github.com/Gfermoto/hass-turkov-fork)

> 💬 **Техническая поддержка и обсуждение:**  [t.me/DIYIoT_Zone](https://t.me/DIYIoT_Zone)

> 💵 **Пожертвование на развитие проекта**  
> [![Пожертвование Тинькофф](https://img.shields.io/badge/Tinkoff-F8D81C.svg?style=for-the-badge)](https://www.tinkoff.ru/cf/3g8f1RTkf5G)
> [![Пожертвование Cбербанк](https://img.shields.io/badge/Сбербанк-green.svg?style=for-the-badge)](https://www.sberbank.com/ru/person/dl/jc?linkname=3pDgknI7FY3z7tJnN)

> 📚 **Документация API Turkov**  
> [![Документация API Turkov](https://img.shields.io/badge/Turkov-Wiki-111111.svg?style=for-the-badge)](https://wiki.turkov.ru/ru/equipment/wifi/pool)

## Установка
### Посредством HACS

[![Открыть Ваш Home Assistant и открыть репозиторий внутри Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Gfermoto&repository=hass-turkov-fork&category=integration)

1. Откройте HACS (через `Extensions` в боковой панели)
1. Добавьте новый произвольный репозиторий:
   1. Выберите `Integration` (`Интеграция`) в качестве типа репозитория
   1. Введите ссылку на репозиторий: `https://github.com/Gfermoto/hass-turkov-fork`
   1. Нажмите кнопку `Add` (`Добавить`)
   1. Дождитесь добавления репозитория (занимает до 10 секунд)
   1. Теперь вы должны видеть доступную интеграцию `Turkov` в списке новых интеграций.
1. Нажмите кнопку `Install` чтобы увидеть доступные версии
1. Установите последнюю версию нажатием кнопки `Install`
1. Перезапустите Home Assistant

## Настройка

[![Открыть Ваш Home Assistant и начать настройку интеграции.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=turkov)

Нажмите на кнопку выше, или следуйте следующим инструкциям:
1. Откройте `Настройки` -> `Интеграции`
1. Нажмите внизу справа страницы кнопку с плюсом
1. Введите в поле поиска `Turkov`  
   - Если интеграция не была найдена на данном этапе, перезапустите Home Assistant и очистите кеш браузера.
1. Выберите первый результат из списка
2. Следуйте инструкциям, описываемым на экране.
1. После завершения настройки начнётся обновление состояний объектов.

## Взаимодействие

Компонент создаёт два типа объектов:
- `climate.<имя устройства>`
- `sensor.<имя устройства>_<тип сенсора>` - сенсоры для значений, не используемых в объекте climate.
