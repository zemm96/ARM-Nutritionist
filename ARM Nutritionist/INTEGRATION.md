# Инструкция по интеграции плана питания

## Новые файлы (добавить в проект)

| Файл | Описание |
|------|----------|
| `mealplangenerator.h / .cpp` | Логика: запускает парсер → формирует промпт → вызывает DeepSeek |
| `mealplanwidget.h / .cpp`   | Qt-виджет: UI экрана «Генерация плана питания» |
| `chizhik_bridge.py`          | Python-мост: принимает параметры от Qt, возвращает JSON в stdout |

---

## 1. .pro файл — добавить

```
QT += network

HEADERS += mealplangenerator.h mealplanwidget.h
SOURCES += mealplangenerator.cpp mealplanwidget.cpp
```

---

## 2. myqtclass.h — изменения

```cpp
// Добавить include
#include "mealplanwidget.h"

// В private секцию класса добавить:
MealPlanWidget *m_planWidget = nullptr;
int             m_planWidgetIndex = -1;
```

---

## 3. myqtclass.cpp — конструктор

```cpp
myqtclass::myqtclass(QWidget *parent)
    : QMainWindow(parent)
    , ui(new Ui::myqtclass)
    , m_db("users.db")
{
    ui->setupUi(this);
    m_db.init();

    // ── Новый экран плана питания ──────────────────────────────────
    m_planWidget = new MealPlanWidget(this);
    m_planWidgetIndex = ui->stackedWidget->addWidget(m_planWidget);

    // Кнопка «Назад» в виджете возвращает на экран результата КБЖУ (индекс 5)
    connect(m_planWidget, &MealPlanWidget::backRequested, this, [this]() {
        ui->stackedWidget->setCurrentIndex(5);
    });
}
```

---

## 4. Добавить кнопку «Создать план питания» на экран результата (индекс 5)

В UI-редакторе (или через код) добавьте `QPushButton` с objectName `mealPlanBtn`
на страницу 5 (страница с `cal_label` и `PercentLabel`).

Затем в `myqtclass.cpp`:

```cpp
void myqtclass::on_mealPlanBtn_clicked()
{
    // Передаём КБЖУ-данные пользователя в виджет плана
    // proteinPct/fatPct/carbPct вычисляются из aim
    double prot = 25, fat = 30, carb = 45;
    if      (aim == -300) { prot = 30; fat = 30; carb = 40; }
    else if (aim ==  300) { prot = 20; fat = 25; carb = 55; }

    m_planWidget->setUserCalories(totalCalorieIntake, prot, fat, carb);
    ui->stackedWidget->setCurrentIndex(m_planWidgetIndex);
}
```

Не забудьте добавить слот в заголовочный файл:
```cpp
void on_mealPlanBtn_clicked();
```

---

## 5. chizhik_bridge.py — размещение

Положите `chizhik_bridge.py` рядом с `chi94.py` (в папку запуска приложения).

По умолчанию `MealPlanGenerator` ищет Python как `python3`.
Если нужен другой путь — вызовите в конструкторе myqtclass:
```cpp
m_planWidget->... // доступ к генератору можно добавить через метод setPythonPath
```

Или задайте путь напрямую через публичный метод (при необходимости добавить accessor):
```cpp
// Можно добавить в MealPlanWidget:
void setPythonPath(const QString &p) { m_generator->setPythonPath(p); }
void setBridgePath(const QString &p) { m_generator->setBridgePath(p); }
```

---

## Как это работает (поток данных)

```
Кнопка «Сгенерировать»
        │
        ▼
MealPlanGenerator::generate()
        │
        ├─► QProcess → python3 chizhik_bridge.py "продукты питания" <budget> 80
        │                              │
        │                    chi94.py (async парсинг Чижика)
        │                    Сортировка: сначала полное КБЖУ + высокий рейтинг
        │                              │ JSON в stdout
        │                              ▼
        ├─◄ onParserFinished() → parseJsonProducts()
        │
        ├─► buildDeepSeekPrompt()  ← топ-50 товаров по рейтингу
        │
        ├─► POST https://api.deepseek.com/v1/chat/completions
        │
        └─► onDeepSeekReply() → emit planReady(text)
                                        │
                                        ▼
                              MealPlanWidget::onPlanReady()
                              Отображает план, активирует кнопку «Сохранить»
```

---

## Зависимости

- Qt: `QtWidgets`, `QtNetwork`
- Python 3.8+ с установленными зависимостями chi94.py (`aiohttp`, `chizhik_api`)
- Интернет-соединение во время генерации
