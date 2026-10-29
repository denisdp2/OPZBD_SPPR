/**
 * Illustrative catalogue for UI development only.
 * Example names and requirement codes are for interface preview only, not a normative catalogue.
 */
export const demoRequirements = [
  { id: "REQ-01", group: "Доступ", title: "Идентификация и аутентификация пользователей", source: "Пример требования", description: "Учётные записи и проверка подлинности пользователей." },
  { id: "REQ-02", group: "Доступ", title: "Разграничение прав доступа", source: "Пример требования", description: "Назначение прав в соответствии с рабочими задачами." },
  { id: "REQ-03", group: "Мониторинг", title: "Регистрация событий безопасности", source: "Пример требования", description: "Сбор событий и возможность их последующего анализа." },
  { id: "REQ-04", group: "Защита узлов", title: "Защита рабочих станций и серверов", source: "Пример требования", description: "Контроль и защита конечных устройств." },
  { id: "REQ-05", group: "Непрерывность", title: "Резервное копирование данных", source: "Пример требования", description: "Создание резервных копий и проверка восстановления." },
  { id: "REQ-06", group: "Инциденты", title: "Реагирование на события безопасности", source: "Пример требования", description: "Определённый порядок обработки инцидентов." },
  { id: "REQ-07", group: "Организация", title: "Регламентирование доступа к информации", source: "Пример требования", description: "Установленные правила согласования и пересмотра доступа." },
];

export const demoItems = [
  {
    id: "iam-suite", kind: "tool", name: "Управление учётными записями", vendor: "Пример позиции",
    description: "Централизованное управление пользователями и политиками доступа.",
    covers: ["REQ-01", "REQ-02"], fstec_certified: false, in_ru_software_registry: false,
  },
  {
    id: "endpoint-protection", kind: "tool", name: "Защита конечных устройств", vendor: "Пример позиции",
    description: "Контроль состояния рабочих станций и серверов.",
    covers: ["REQ-04", "REQ-06"], fstec_certified: false, in_ru_software_registry: false,
  },
  {
    id: "log-monitoring", kind: "tool", name: "Сбор и анализ событий", vendor: "Пример позиции",
    description: "Централизованный сбор журналов и поиск подозрительных событий.",
    covers: ["REQ-03", "REQ-06"], fstec_certified: false, in_ru_software_registry: false,
  },
  {
    id: "backup-system", kind: "tool", name: "Резервное копирование", vendor: "Пример позиции",
    description: "Планирование копирования и контроль восстановления данных.",
    covers: ["REQ-05"], fstec_certified: false, in_ru_software_registry: false,
  },
  {
    id: "access-regulation", kind: "org", name: "Регламент управления доступом", vendor: "Организационная мера",
    description: "Порядок выдачи, изменения и отзыва прав доступа.",
    covers: ["REQ-02", "REQ-07"], implement_days: 8,
  },
  {
    id: "incident-plan", kind: "org", name: "Порядок реагирования на инциденты", vendor: "Организационная мера",
    description: "Роли, порядок эскалации и фиксация результатов реагирования.",
    covers: ["REQ-06", "REQ-07"], implement_days: 5,
  },
  {
    id: "security-training", kind: "org", name: "Обучение сотрудников", vendor: "Организационная мера",
    description: "Инструктажи и регулярное напоминание о правилах работы с данными.",
    covers: ["REQ-01", "REQ-07"], implement_days: 3,
  },
];

export const demoProfiles = [
  {
    id: "baseline", name: "Базовый профиль",
    description: "Демонстрационный профиль: обязательные требования к доступу, журналированию и регламентам.",
    mandatory: ["REQ-01", "REQ-02", "REQ-03", "REQ-07"],
  },
  {
    id: "extended", name: "Расширенный профиль",
    description: "Демонстрационный профиль с дополнительными требованиями к защите узлов, резервированию и инцидентам.",
    mandatory: ["REQ-01", "REQ-02", "REQ-03", "REQ-04", "REQ-05", "REQ-06", "REQ-07"],
  },
  {
    id: "continuity", name: "Профиль непрерывности",
    description: "Пример профиля с акцентом на защиту конечных устройств, резервное копирование и реагирование.",
    mandatory: ["REQ-03", "REQ-04", "REQ-05", "REQ-06"],
  },
];

export const demoOptimizers = [
  { name: "demo-exact", title: "Точный алгоритм (пример)", exact: true, description: "Название демонстрационное. Список реальных алгоритмов должен прийти из API.", supports_pareto: true },
  { name: "demo-heuristic", title: "Приближённый алгоритм (пример)", exact: false, description: "Название демонстрационное. Конкретный алгоритм выбирается после реализации модуля оптимизации.", supports_pareto: true },
];
