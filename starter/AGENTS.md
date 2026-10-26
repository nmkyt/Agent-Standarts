# AGENTS.md — {{PROJECT_NAME}}

{{PROJECT_DESCRIPTION}}

## Стандарты агента

Прочитай `.agent-rules/workflow.md` перед началом работы. Это общая процедура, она доставлена
из центрального репозитория стандартов; файлы в `.agent-rules/` вручную не правь.

## Проект

- Стек: {{STACK}}
- Структура: {{STRUCTURE}}

## Проверки

Единая точка входа: `bash .agent-rules/tools/check.sh`.
Проверки самого проекта (lint, тесты, сборка) запускает `ci/gate.sh`.

## Локальные правила

{{LOCAL_RULES}}
